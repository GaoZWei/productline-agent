"""M5.6 五订单动态路径、有限重试和固定Workflow基线回归。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.models import AgentStepType
from app.schemas import (
    AgentAction,
    AgentTerminationReason,
    BlockingStage,
    OrderDiagnosisState,
    PageContext,
    PermissionScope,
    SpecificationQaResult,
    SpecificationQaStatus,
)
from app.schemas.business import BusinessIdentity
from app.settings import Settings
from app.tools import ToolContext, create_read_tool_registry
from app.workflows import (
    ActionDecider,
    AgentExecutionLimits,
    DynamicDiagnosisWorkflow,
    OrderDiagnosisWorkflow,
    WorkflowStepRecorder,
)
from app.workflows.action_prompt import ActionDecisionPrompt

# 控制测试中模型的动作顺序
class SequenceActionModel:
    """按测试声明顺序返回动作并记录实际模型调用次数。"""

    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)
        self.call_count = 0

    async def generate(self, prompt: ActionDecisionPrompt) -> object:
        del prompt
        self.call_count += 1
        return next(self._outputs)


class StubSpecificationWorkflow:
    """返回不冒充规范结论的安全结果并记录调用。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ainvoke(
        self,
        question: str,
        *,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> SpecificationQaResult:
        del effective_at, permission_scope, page_context
        self.calls.append(question)
        return SpecificationQaResult(
            status=SpecificationQaStatus.INSUFFICIENT_CONTEXT,
            question=question,
            rewritten_query=question,
            answer="未检索到足够的当前有效规范依据, 无法给出规范结论。",
            citations=(),
        )


class NoopStepRecorder(WorkflowStepRecorder):
    """固定Workflow基线只验证结果, 不在测试中持久化Step。"""

    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None,
    ) -> None:
        del step_id, run_id, sequence_number, step_type, step_name, input_summary

    async def mark_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
    ) -> None:
        del step_id, output_summary

    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
    ) -> None:
        del step_id, error_code, output_summary


def _settings() -> Settings:
    return Settings(
        environment="test",
        business_service_url=AnyHttpUrl("http://business.test"),
    )


def _context(order_id: str, *, workflow_type: str) -> ToolContext:
    suffix = order_id.removeprefix("ORDER-")
    return ToolContext(
        identity=BusinessIdentity(user_id=f"{workflow_type}-user", role="REVIEWER"),
        permissions=frozenset(
            {
                "ORDER_READ",
                "TASK_READ",
                "QUALITY_ISSUE_READ",
                "REVIEW_READ",
                "DELIVERY_READ",
            }
        ),
        trace_id=f"trace-{workflow_type}-{suffix}",
        run_id=f"run-{workflow_type}-{suffix}",
    )


def _success(data: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-Trace-Id": "trace-dynamic-path"},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": data,
            "trace_id": "trace-dynamic-path",
            "retryable": False,
        },
    )


def _scenario_responses(order_id: str) -> dict[str, object]:
    suffix = order_id.removeprefix("ORDER-")
    task_id = f"TASK-{suffix}"
    statuses = {
        "001": ("PRODUCING", "RUNNING", "RUNNING", "NOT_READY"),
        "002": ("BLOCKED", "FAILED", "FAILED", "NOT_READY"),
        "003": ("QUALITY_CHECKING", "COMPLETED", "COMPLETED", "BLOCKED"),
        "004": ("REVIEWING", "COMPLETED", "COMPLETED", "BLOCKED"),
        "005": ("READY_FOR_DELIVERY", "COMPLETED", "COMPLETED", "READY"),
    }
    order_status, task_status, step_status, delivery_status = statuses[suffix]
    issues: list[dict[str, object]] = []
    reviews: list[dict[str, object]] = []
    if suffix in {"003", "004", "005"}:
        issue_number = {"003": "001", "004": "002", "005": "003"}[suffix]
        issue_status = {"003": "OPEN", "004": "RESOLVED", "005": "CLOSED"}[suffix]
        review_status = {"003": "PENDING", "004": "PENDING", "005": "APPROVED"}[suffix]
        issues = [
            {
                "issueId": f"ISSUE-{issue_number}",
                "taskId": task_id,
                "issueType": "COORDINATE_SYSTEM",
                "status": issue_status,
                "description": "固定坐标系问题",
            }
        ]
        reviews = [
            {
                "reviewId": f"REVIEW-{suffix}",
                "issueId": f"ISSUE-{issue_number}",
                "status": review_status,
                "reviewComment": None,
            }
        ]
    return {
        f"/api/orders/{order_id}": {
            "orderId": order_id,
            "productType": "DOM",
            "status": order_status,
        },
        f"/api/orders/{order_id}/tasks": {
            "orderId": order_id,
            "tasks": [
                {
                    "taskId": task_id,
                    "orderId": order_id,
                    "status": task_status,
                    "version": 0,
                }
            ],
        },
        f"/api/tasks/{task_id}/progress": {
            "taskId": task_id,
            "steps": [
                {
                    "stepId": f"STEP-{suffix}-01",
                    "taskId": task_id,
                    "stepName": "固定生产步骤",
                    "sequenceNumber": 1,
                    "status": step_status,
                }
            ],
        },
        f"/api/tasks/{task_id}/quality-issues": {
            "taskId": task_id,
            "issues": issues,
        },
        f"/api/tasks/{task_id}/review": {
            "taskId": task_id,
            "reviews": reviews,
        },
        f"/api/orders/{order_id}/delivery-status": {
            "orderId": order_id,
            "records": [
                {
                    "deliveryId": f"DELIVERY-{suffix}",
                    "orderId": order_id,
                    "status": delivery_status,
                }
            ],
        },
    }


def _transport(order_id: str, calls: list[str]) -> httpx.MockTransport:
    responses = _scenario_responses(order_id)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _success(responses[request.url.path])

    return httpx.MockTransport(handler)


def _decision(action: AgentAction, *, order_id: str) -> dict[str, object]:
    suffix = order_id.removeprefix("ORDER-")
    task_id = f"TASK-{suffix}"
    tool_names = {
        AgentAction.QUERY_ORDER: "get_order_detail",
        AgentAction.QUERY_TASKS: "get_related_tasks",
        AgentAction.QUERY_PROGRESS: "get_production_progress",
        AgentAction.QUERY_QUALITY: "get_quality_issues",
        AgentAction.QUERY_REVIEW: "get_review_result",
        AgentAction.QUERY_DELIVERY: "get_delivery_status",
        AgentAction.RETRIEVE_SPEC: "retrieve_spec",
        AgentAction.FINISH: None,
    }
    arguments: dict[str, object]
    if action in {
        AgentAction.QUERY_ORDER,
        AgentAction.QUERY_TASKS,
        AgentAction.QUERY_DELIVERY,
    }:
        arguments = {"order_id": order_id}
    elif action in {
        AgentAction.QUERY_PROGRESS,
        AgentAction.QUERY_QUALITY,
        AgentAction.QUERY_REVIEW,
    }:
        arguments = {"task_id": task_id}
    elif action is AgentAction.RETRIEVE_SPEC:
        arguments = {"question": "坐标系质量问题应如何处理"}
    else:
        arguments = {}
    return {
        "action": action.value,
        "reason": "执行固定订单动态路径回归。",
        "tool_name": tool_names[action],
        "tool_arguments": arguments,
    }


async def _run_dynamic(
    order_id: str,
    actions: tuple[AgentAction, ...],
) -> tuple[OrderDiagnosisState, list[str], StubSpecificationWorkflow]:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_transport(order_id, calls))
    registry = create_read_tool_registry(client)
    specification = StubSpecificationWorkflow()
    model = SequenceActionModel(
        [
            *(_decision(action, order_id=order_id) for action in actions),
            _decision(AgentAction.FINISH, order_id=order_id),
        ]
    )
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(model=model, registry=registry),
        tool_registry=registry,
        tool_context=_context(order_id, workflow_type="dynamic"),
        specification_workflow=specification,
        effective_at=date(2026, 8, 25),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
        limits=AgentExecutionLimits(max_decision_rounds=10),
    )
    try:
        state = await workflow.ainvoke(order_id)
    finally:
        await client.aclose()
    return state, calls, specification


async def _run_fixed(order_id: str) -> OrderDiagnosisState:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_transport(order_id, calls))
    workflow = OrderDiagnosisWorkflow(
        tool_registry=create_read_tool_registry(client),
        tool_context=_context(order_id, workflow_type="fixed"),
        step_recorder=NoopStepRecorder(),
    )
    try:
        return await workflow.ainvoke(order_id)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order_id", "actions", "expected_paths", "expected_stage"),
    [
        pytest.param(
            "ORDER-001",
            (
                AgentAction.QUERY_ORDER,
                AgentAction.QUERY_TASKS,
                AgentAction.QUERY_PROGRESS,
                AgentAction.QUERY_DELIVERY,
            ),
            (
                "/api/orders/ORDER-001",
                "/api/orders/ORDER-001/tasks",
                "/api/tasks/TASK-001/progress",
                "/api/orders/ORDER-001/delivery-status",
            ),
            BlockingStage.PRODUCTION,
            id="production",
        ),
        pytest.param(
            "ORDER-002",
            (
                AgentAction.QUERY_ORDER,
                AgentAction.QUERY_TASKS,
                AgentAction.QUERY_PROGRESS,
                AgentAction.QUERY_DELIVERY,
            ),
            (
                "/api/orders/ORDER-002",
                "/api/orders/ORDER-002/tasks",
                "/api/tasks/TASK-002/progress",
                "/api/orders/ORDER-002/delivery-status",
            ),
            BlockingStage.PRODUCTION_BLOCKED,
            id="production-blocked",
        ),
        pytest.param(
            "ORDER-003",
            (
                AgentAction.QUERY_ORDER,
                AgentAction.QUERY_TASKS,
                AgentAction.QUERY_QUALITY,
                AgentAction.QUERY_REVIEW,
                AgentAction.QUERY_DELIVERY,
                AgentAction.RETRIEVE_SPEC,
            ),
            (
                "/api/orders/ORDER-003",
                "/api/orders/ORDER-003/tasks",
                "/api/tasks/TASK-003/quality-issues",
                "/api/tasks/TASK-003/review",
                "/api/orders/ORDER-003/delivery-status",
            ),
            BlockingStage.QUALITY_REVIEW,
            id="quality-review",
        ),
        pytest.param(
            "ORDER-004",
            (
                AgentAction.QUERY_ORDER,
                AgentAction.QUERY_TASKS,
                AgentAction.QUERY_REVIEW,
                AgentAction.QUERY_DELIVERY,
            ),
            (
                "/api/orders/ORDER-004",
                "/api/orders/ORDER-004/tasks",
                "/api/tasks/TASK-004/review",
                "/api/orders/ORDER-004/delivery-status",
            ),
            BlockingStage.REVIEW,
            id="review",
        ),
        pytest.param(
            "ORDER-005",
            (
                AgentAction.QUERY_ORDER,
                AgentAction.QUERY_TASKS,
                AgentAction.QUERY_DELIVERY,
            ),
            (
                "/api/orders/ORDER-005",
                "/api/orders/ORDER-005/tasks",
                "/api/orders/ORDER-005/delivery-status",
            ),
            BlockingStage.NONE,
            id="ready-for-delivery",
        ),
    ],
)
async def test_dynamic_paths_match_fixed_workflow_baseline(
    order_id: str,
    actions: tuple[AgentAction, ...],
    expected_paths: tuple[str, ...],
    expected_stage: BlockingStage,
) -> None:
    dynamic_state, calls, specification = await _run_dynamic(order_id, actions)
    fixed_state = await _run_fixed(order_id)

    assert calls == list(expected_paths)
    assert [item.action for item in dynamic_state["tool_history"]] == list(actions)
    assert dynamic_state["information_gaps"] == []
    assert dynamic_state["termination_reason"] is AgentTerminationReason.SUFFICIENT_INFORMATION
    assert dynamic_state["diagnosis"] is not None
    assert fixed_state["diagnosis"] is not None
    assert dynamic_state["diagnosis"].blocking_stage is expected_stage
    assert dynamic_state["diagnosis"] == fixed_state["diagnosis"]
    assert len(specification.calls) == (1 if order_id == "ORDER-003" else 0)


@pytest.mark.asyncio
async def test_dynamic_read_tool_retries_one_timeout_then_succeeds() -> None:
    order_id = "ORDER-001"
    attempts = 0
    order_response = _scenario_responses(order_id)[f"/api/orders/{order_id}"]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return _success(order_response)

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    registry = create_read_tool_registry(client)
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(
            model=SequenceActionModel(
                [
                    _decision(AgentAction.QUERY_ORDER, order_id=order_id),
                    _decision(AgentAction.FINISH, order_id=order_id),
                ]
            ),
            registry=registry,
        ),
        tool_registry=registry,
        tool_context=_context(order_id, workflow_type="retry"),
        specification_workflow=StubSpecificationWorkflow(),
        effective_at=date(2026, 8, 25),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )
    try:
        state = await workflow.ainvoke(order_id)
    finally:
        await client.aclose()

    assert attempts == 2
    assert len(state["tool_history"]) == 1
    assert state["tool_history"][0].success is True
    assert state["errors"] == []
    assert state["termination_reason"] is AgentTerminationReason.INSUFFICIENT_INFORMATION
