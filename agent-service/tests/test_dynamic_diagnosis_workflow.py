"""M5.3-M5.4 动态诊断图、结果生成、异常结束和执行限制测试。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, cast

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode
from app.schemas import (
    ActionDecision,
    AgentAction,
    AgentTerminationReason,
    BlockingStage,
    PageContext,
    PageType,
    PermissionScope,
    SpecificationQaResult,
    SpecificationQaStatus,
    StepError,
)
from app.schemas.business import BusinessIdentity
from app.settings import Settings
from app.tools import ToolContext, create_read_tool_registry
from app.workflows import (
    ActionDecider,
    AgentExecutionLimits,
    DynamicDiagnosisState,
    DynamicDiagnosisWorkflow,
)
from app.workflows.action_prompt import ActionDecisionPrompt


class SequenceActionModel:
    """按测试声明的顺序返回动作。"""

    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)
        self.call_count = 0

    async def generate(self, prompt: ActionDecisionPrompt) -> object:
        del prompt
        self.call_count += 1
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


def _context(*, permissions: frozenset[str] | None = None) -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="dynamic-user", role="REVIEWER"),
        permissions=(
            permissions
            if permissions is not None
            else frozenset(
                {
                    "ORDER_READ",
                    "TASK_READ",
                    "QUALITY_ISSUE_READ",
                    "REVIEW_READ",
                    "DELIVERY_READ",
                }
            )
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
        limits=AgentExecutionLimits(max_decision_rounds=10),
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
    assert state["iteration_count"] == 8
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
    assert state["iteration_count"] == 1
    assert state["termination_reason"] is AgentTerminationReason.INSUFFICIENT_INFORMATION
    assert [gap.code for gap in state["information_gaps"]] == [
        "ORDER_REQUIRED",
        "RELATED_TASKS_REQUIRED",
        "DELIVERY_STATUS_REQUIRED",
    ]
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


@pytest.mark.unit
def test_agent_execution_limits_have_stable_defaults_and_reject_invalid_values() -> None:
    limits = AgentExecutionLimits()

    assert limits.max_decision_rounds == 6
    assert limits.max_tool_calls == 8
    assert limits.max_consecutive_no_new_information == 2
    with pytest.raises(ValueError):
        AgentExecutionLimits(max_decision_rounds=0)


@pytest.mark.asyncio
async def test_dynamic_graph_stops_infinite_planning_at_six_decision_rounds() -> None:
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
            _decision(AgentAction.FINISH, {}),
        ]
    )
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(model=model, registry=registry),
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

    assert model.call_count == 6
    assert state["iteration_count"] == 6
    assert len(state["tool_history"]) == 6
    assert state["termination_reason"] is AgentTerminationReason.MAX_ITERATIONS
    assert state["diagnosis"] is not None
    assert state["diagnosis"].blocking_stage is BlockingStage.INSUFFICIENT_INFORMATION
    assert [gap.code for gap in state["information_gaps"]] == ["SPECIFICATION_RESULT_REQUIRED"]


@pytest.mark.asyncio
async def test_dynamic_graph_stops_before_exceeding_tool_call_limit() -> None:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_golden_transport(calls))
    registry = create_read_tool_registry(client)
    model = SequenceActionModel(
        [
            _decision(AgentAction.QUERY_ORDER, {"order_id": "ORDER-003"}),
            _decision(AgentAction.QUERY_TASKS, {"order_id": "ORDER-003"}),
            _decision(AgentAction.QUERY_PROGRESS, {"task_id": "TASK-003"}),
        ]
    )
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(model=model, registry=registry),
        tool_registry=registry,
        tool_context=_context(),
        specification_workflow=StubSpecificationWorkflow(),
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
        limits=AgentExecutionLimits(max_decision_rounds=10, max_tool_calls=2),
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert model.call_count == 3
    assert state["iteration_count"] == 3
    assert len(state["tool_history"]) == 2
    assert len(calls) == 2
    assert state["termination_reason"] is AgentTerminationReason.MAX_TOOL_CALLS


@pytest.mark.asyncio
async def test_dynamic_graph_blocks_duplicate_logical_call_before_tool_execution() -> None:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_golden_transport(calls))
    registry = create_read_tool_registry(client)
    model = SequenceActionModel(
        [
            _decision(AgentAction.QUERY_ORDER, {"order_id": "ORDER-003"}),
            _decision(AgentAction.QUERY_ORDER, {"order_id": "ORDER-003"}),
        ]
    )
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(model=model, registry=registry),
        tool_registry=registry,
        tool_context=_context(),
        specification_workflow=StubSpecificationWorkflow(),
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
        limits=AgentExecutionLimits(max_decision_rounds=10),
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert model.call_count == 2
    assert calls == ["/api/orders/ORDER-003"]
    assert len(state["tool_history"]) == 1
    assert state["termination_reason"] is AgentTerminationReason.NO_NEW_INFORMATION


@pytest.mark.asyncio
async def test_dynamic_graph_stops_after_two_successes_without_new_information() -> None:
    class FixedSpecificationWorkflow(StubSpecificationWorkflow):
        async def ainvoke(
            self,
            question: str,
            *,
            effective_at: date,
            permission_scope: PermissionScope,
            page_context: PageContext | None = None,
        ) -> SpecificationQaResult:
            await super().ainvoke(
                question,
                effective_at=effective_at,
                permission_scope=permission_scope,
                page_context=page_context,
            )
            return SpecificationQaResult(
                status=SpecificationQaStatus.INSUFFICIENT_CONTEXT,
                question="固定规范问题",
                rewritten_query="固定规范问题",
                answer="没有足够规范依据。",
                citations=(),
            )

    client = BusinessHttpClient(_settings(), transport=_golden_transport([]))
    registry = create_read_tool_registry(client)
    specification = FixedSpecificationWorkflow()
    model = SequenceActionModel(
        [
            _decision(AgentAction.RETRIEVE_SPEC, {"question": "规范问题一"}),
            _decision(AgentAction.RETRIEVE_SPEC, {"question": "规范问题二"}),
            _decision(AgentAction.RETRIEVE_SPEC, {"question": "规范问题三"}),
            _decision(AgentAction.FINISH, {}),
        ]
    )
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(model=model, registry=registry),
        tool_registry=registry,
        tool_context=_context(),
        specification_workflow=specification,
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
        limits=AgentExecutionLimits(max_decision_rounds=10),
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert model.call_count == 3
    assert len(specification.calls) == 3
    assert [item.has_new_information for item in state["tool_history"]] == [
        True,
        False,
        False,
    ]
    assert state["termination_reason"] is AgentTerminationReason.NO_NEW_INFORMATION


@pytest.mark.asyncio
async def test_validate_action_rejects_write_unknown_and_missing_permission() -> None:
    client = BusinessHttpClient(_settings(), transport=_golden_transport([]))
    registry = create_read_tool_registry(client)
    workflow = DynamicDiagnosisWorkflow(
        action_decider=ActionDecider(
            model=SequenceActionModel([_decision(AgentAction.FINISH, {})]),
            registry=registry,
        ),
        tool_registry=registry,
        tool_context=_context(permissions=frozenset()),
        specification_workflow=StubSpecificationWorkflow(),
        effective_at=date(2026, 8, 22),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )
    initialized = cast(
        DynamicDiagnosisState,
        await workflow.initialize(
            cast(
                DynamicDiagnosisState,
                {
                    "run_id": "run-dynamic-003",
                    "order_id": "ORDER-003",
                    "page_context": PageContext(
                        current_system="production-system",
                        current_page=PageType.ORDER_DETAIL,
                        order_id="ORDER-003",
                        user_role="REVIEWER",
                    ),
                },
            )
        ),
    )

    try:
        forbidden_decisions = (
            (AgentAction.QUERY_ORDER, "delete_order", {"order_id": "ORDER-003"}),
            (AgentAction.QUERY_ORDER, "unknown_read_tool", {"order_id": "ORDER-003"}),
            (AgentAction.RETRIEVE_SPEC, "delete_order", {"question": "规范问题"}),
            (AgentAction.FINISH, "delete_order", {"order_id": "ORDER-003"}),
        )
        for action, forbidden_name, arguments in forbidden_decisions:
            forged = ActionDecision.model_construct(
                action=action,
                reason="绕过模型输出Schema后的防御测试。",
                tool_name=cast(Any, forbidden_name),
                tool_arguments=arguments,
            )
            rejected = await workflow.validate_action(
                cast(DynamicDiagnosisState, {**initialized, "current_decision": forged})
            )
            assert rejected["errors"]

        permission_decision = ActionDecision.model_validate(
            _decision(AgentAction.QUERY_ORDER, {"order_id": "ORDER-003"})
        )
        rejected_permission = await workflow.validate_action(
            cast(
                DynamicDiagnosisState,
                {**initialized, "current_decision": permission_decision},
            )
        )
        permission_errors = cast(list[StepError], rejected_permission["errors"])
        assert permission_errors
        assert permission_errors[0].code is ToolErrorCode.PERMISSION_DENIED
    finally:
        await client.aclose()
