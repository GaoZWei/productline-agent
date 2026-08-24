"""M5.3 动态诊断 LangGraph 的循环、结果生成和异常结束测试。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.schemas import (
    AgentAction,
    AgentTerminationReason,
    BlockingStage,
    PageContext,
    PermissionScope,
    SpecificationQaResult,
    SpecificationQaStatus,
)
from app.schemas.business import BusinessIdentity
from app.settings import Settings
from app.tools import ToolContext, create_read_tool_registry
from app.workflows import ActionDecider, DynamicDiagnosisWorkflow
from app.workflows.action_prompt import ActionDecisionPrompt


class SequenceActionModel:
    """按测试声明的顺序返回动作。"""

    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)

    async def generate(self, prompt: ActionDecisionPrompt) -> object:
        del prompt
        return next(self._outputs)


class StubSpecificationWorkflow:
    """记录动态图传入规范问答的显式安全边界。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, date, PermissionScope, PageContext | None]] = []

    async def ainvoke(
        self,
        question: str,
        *,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> SpecificationQaResult:
        self.calls.append((question, effective_at, permission_scope, page_context))
        return SpecificationQaResult(
            status=SpecificationQaStatus.INSUFFICIENT_CONTEXT,
            question=question,
            rewritten_query=question,
            answer="未检索到足够的当前有效规范依据, 无法给出规范结论。",
            citations=(),
        )


def _settings() -> Settings:
    return Settings(
        environment="test",
        business_service_url=AnyHttpUrl("http://business.test"),
    )


def _context() -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="dynamic-user", role="REVIEWER"),
        permissions=frozenset(
            {
                "ORDER_READ",
                "TASK_READ",
                "QUALITY_ISSUE_READ",
                "REVIEW_READ",
                "DELIVERY_READ",
            }
        ),
        trace_id="trace-dynamic-003",
        run_id="run-dynamic-003",
    )


def _success(data: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-Trace-Id": "trace-dynamic-003"},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": data,
            "trace_id": "trace-dynamic-003",
            "retryable": False,
        },
    )


def _golden_transport(calls: list[str]) -> httpx.MockTransport:
    responses: dict[str, object] = {
        "/api/orders/ORDER-003": {
            "orderId": "ORDER-003",
            "productType": "DOM",
            "status": "QUALITY_CHECKING",
        },
        "/api/orders/ORDER-003/tasks": {
            "orderId": "ORDER-003",
            "tasks": [
                {
                    "taskId": "TASK-003",
                    "orderId": "ORDER-003",
                    "status": "COMPLETED",
                    "version": 0,
                }
            ],
        },
        "/api/tasks/TASK-003/progress": {
            "taskId": "TASK-003",
            "steps": [
                {
                    "stepId": "STEP-003-01",
                    "taskId": "TASK-003",
                    "stepName": "DOM production",
                    "sequenceNumber": 1,
                    "status": "COMPLETED",
                }
            ],
        },
        "/api/tasks/TASK-003/quality-issues": {
            "taskId": "TASK-003",
            "issues": [
                {
                    "issueId": "ISSUE-001",
                    "taskId": "TASK-003",
                    "issueType": "COORDINATE_SYSTEM",
                    "status": "OPEN",
                    "description": "coordinate system mismatch",
                }
            ],
        },
        "/api/tasks/TASK-003/review": {
            "taskId": "TASK-003",
            "reviews": [
                {
                    "reviewId": "REVIEW-003",
                    "issueId": "ISSUE-001",
                    "status": "PENDING",
                    "reviewComment": None,
                }
            ],
        },
        "/api/orders/ORDER-003/delivery-status": {
            "orderId": "ORDER-003",
            "records": [
                {
                    "deliveryId": "DELIVERY-003",
                    "orderId": "ORDER-003",
                    "status": "BLOCKED",
                }
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _success(responses[request.url.path])

    return httpx.MockTransport(handler)


def _decision(
    action: AgentAction,
    arguments: dict[str, object],
) -> dict[str, object]:
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
    return {
        "action": action.value,
        "reason": "测试动态诊断的下一步只读动作。",
        "tool_name": tool_names[action],
        "tool_arguments": arguments,
    }


@pytest.mark.asyncio
async def test_dynamic_graph_collects_facts_and_generates_order_003_diagnosis() -> None:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_golden_transport(calls))
    registry = create_read_tool_registry(client)
    model = SequenceActionModel(
        [
            _decision(AgentAction.QUERY_ORDER, {"order_id": "ORDER-003"}),
            _decision(AgentAction.QUERY_TASKS, {"order_id": "ORDER-003"}),
            _decision(AgentAction.QUERY_PROGRESS, {"task_id": "TASK-003"}),
            _decision(AgentAction.QUERY_QUALITY, {"task_id": "TASK-003"}),
            _decision(AgentAction.QUERY_REVIEW, {"task_id": "TASK-003"}),
            _decision(AgentAction.QUERY_DELIVERY, {"order_id": "ORDER-003"}),
            _decision(
                AgentAction.RETRIEVE_SPEC,
                {"question": "坐标系质量问题应如何处理"},
            ),
            _decision(AgentAction.FINISH, {}),
        ]
    )
    specification = StubSpecificationWorkflow()
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(model=model, registry=registry),
        tool_registry=registry,
        tool_context=_context(),
        specification_workflow=specification,
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert set(workflow.graph.get_graph().nodes) >= {
        "initialize",
        "plan_next_action",
        "validate_action",
        "execute_action",
        "save_observation",
        "check_completion",
        "generate_result",
        "exceptional_finish",
    }
    assert calls == [
        "/api/orders/ORDER-003",
        "/api/orders/ORDER-003/tasks",
        "/api/tasks/TASK-003/progress",
        "/api/tasks/TASK-003/quality-issues",
        "/api/tasks/TASK-003/review",
        "/api/orders/ORDER-003/delivery-status",
    ]
    assert [item.action for item in state["tool_history"]] == list(AgentAction)[:-1]
    assert len({item.call_fingerprint for item in state["tool_history"]}) == 7
    assert state["iteration_count"] == 7
    assert state["termination_reason"] is AgentTerminationReason.SUFFICIENT_INFORMATION
    assert state["specification_result"] is not None
    assert state["specification_result"].status is SpecificationQaStatus.INSUFFICIENT_CONTEXT
    assert specification.calls[0][:3] == (
        "坐标系质量问题应如何处理",
        date(2026, 8, 22),
        PermissionScope.INTERNAL_REVIEWER,
    )
    assert state["errors"] == []
    assert state["diagnosis"] is not None
    assert state["diagnosis"].blocking_stage is BlockingStage.QUALITY_REVIEW
    assert [item.code for item in state["diagnosis"].root_causes] == [
        "OPEN_COORDINATE_SYSTEM_ISSUE",
        "REVIEW_PENDING",
    ]


@pytest.mark.asyncio
async def test_dynamic_graph_finishes_safely_when_facts_are_insufficient() -> None:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_golden_transport(calls))
    registry = create_read_tool_registry(client)
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(
            model=SequenceActionModel([_decision(AgentAction.FINISH, {})]),
            registry=registry,
        ),
        tool_registry=registry,
        tool_context=_context(),
        specification_workflow=StubSpecificationWorkflow(),
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert calls == []
    assert state["tool_history"] == []
    assert state["iteration_count"] == 0
    assert state["termination_reason"] is AgentTerminationReason.INSUFFICIENT_INFORMATION
    assert state["diagnosis"] is not None
    assert state["diagnosis"].blocking_stage is BlockingStage.INSUFFICIENT_INFORMATION
    assert state["diagnosis"].evidence == []


@pytest.mark.asyncio
async def test_dynamic_graph_saves_failed_observation_and_ends_exceptionally() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"X-Trace-Id": "trace-upstream"},
            json={"message": "unavailable"},
        )

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    registry = create_read_tool_registry(client)
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(
            model=SequenceActionModel(
                [_decision(AgentAction.QUERY_ORDER, {"order_id": "ORDER-003"})]
            ),
            registry=registry,
        ),
        tool_registry=registry,
        tool_context=_context(),
        specification_workflow=StubSpecificationWorkflow(),
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert state["termination_reason"] is AgentTerminationReason.EXECUTION_ERROR
    assert state["iteration_count"] == 1
    assert len(state["tool_history"]) == 1
    assert state["tool_history"][0].success is False
    assert state["tool_history"][0].error == state["errors"][0]
    assert state["diagnosis"] is not None
    assert state["diagnosis"].blocking_stage is BlockingStage.INSUFFICIENT_INFORMATION
