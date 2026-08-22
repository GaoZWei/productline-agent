"""M5.1 动态诊断Agent状态契约与序列化测试。"""

from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from app.errors import ToolErrorCode
from app.schemas import (
    AgentAction,
    AgentObservation,
    AgentTerminationReason,
    InformationGap,
    OrderDiagnosisState,
    StepError,
)


@pytest.mark.unit
def test_agent_action_and_termination_reason_are_stable_machine_contracts() -> None:
    assert tuple(AgentAction) == (
        AgentAction.QUERY_ORDER,
        AgentAction.QUERY_TASKS,
        AgentAction.QUERY_PROGRESS,
        AgentAction.QUERY_QUALITY,
        AgentAction.QUERY_REVIEW,
        AgentAction.QUERY_DELIVERY,
        AgentAction.RETRIEVE_SPEC,
        AgentAction.FINISH,
    )
    assert tuple(AgentTerminationReason) == (
        AgentTerminationReason.SUFFICIENT_INFORMATION,
        AgentTerminationReason.MAX_ITERATIONS,
        AgentTerminationReason.MAX_TOOL_CALLS,
        AgentTerminationReason.NO_NEW_INFORMATION,
        AgentTerminationReason.TOOL_ERROR_LIMIT,
    )


@pytest.mark.unit
def test_agent_observation_round_trips_without_raw_tool_payload() -> None:
    observation = AgentObservation(
        action=AgentAction.QUERY_QUALITY,
        call_fingerprint="a" * 64,
        success=True,
        summary="发现1个未关闭的坐标系问题。",
        has_new_information=True,
    )

    restored = AgentObservation.model_validate_json(observation.model_dump_json())

    assert restored == observation
    assert restored.model_dump(mode="json") == {
        "action": "QUERY_QUALITY",
        "call_fingerprint": "a" * 64,
        "success": True,
        "summary": "发现1个未关闭的坐标系问题。",
        "has_new_information": True,
        "error": None,
    }
    with pytest.raises(ValidationError):
        AgentObservation.model_validate(
            {
                **observation.model_dump(),
                "raw_tool_result": {"status": "OPEN"},
            }
        )


@pytest.mark.unit
def test_agent_observation_enforces_execution_result_boundaries() -> None:
    error = StepError(
        step_name="get_quality_issues",
        code=ToolErrorCode.TOOL_TIMEOUT,
        message="业务服务请求超时",
        retryable=True,
    )

    with pytest.raises(ValidationError):
        AgentObservation(
            action=AgentAction.QUERY_QUALITY,
            call_fingerprint="not-a-sha256",
            success=True,
            summary="调用身份必须使用安全指纹。",
            has_new_information=False,
        )
    with pytest.raises(ValidationError):
        AgentObservation(
            action=AgentAction.QUERY_QUALITY,
            call_fingerprint="a" * 64,
            success=True,
            summary="不允许成功结果携带错误。",
            has_new_information=False,
            error=error,
        )
    with pytest.raises(ValidationError):
        AgentObservation(
            action=AgentAction.QUERY_QUALITY,
            call_fingerprint="a" * 64,
            success=False,
            summary="失败结果必须携带安全错误。",
            has_new_information=False,
        )
    with pytest.raises(ValidationError):
        AgentObservation(
            action=AgentAction.QUERY_QUALITY,
            call_fingerprint="a" * 64,
            success=False,
            summary="失败不能声称获得新事实。",
            has_new_information=True,
            error=error,
        )
    with pytest.raises(ValidationError):
        AgentObservation(
            action=AgentAction.FINISH,
            call_fingerprint="a" * 64,
            success=True,
            summary="FINISH只终止循环且不执行外部读取。",
            has_new_information=False,
        )


@pytest.mark.unit
def test_extended_agent_state_round_trips_with_history_and_gaps() -> None:
    state: OrderDiagnosisState = {
        "run_id": "run-m5-1",
        "order_id": "ORDER-003",
        "page_context": None,
        "order": None,
        "tasks": [],
        "progress": {},
        "quality_issues": {},
        "reviews": {},
        "delivery": None,
        "rule_decision": None,
        "diagnosis": None,
        "errors": [],
        "tool_history": [
            AgentObservation(
                action=AgentAction.QUERY_ORDER,
                call_fingerprint="b" * 64,
                success=True,
                summary="已读取订单基本状态。",
                has_new_information=True,
            )
        ],
        "information_gaps": [
            InformationGap(
                code="QUALITY_ISSUES_REQUIRED",
                description="尚未确认关联任务是否存在未关闭质检问题。",
            )
        ],
        "iteration_count": 1,
        "termination_reason": None,
    }
    adapter = TypeAdapter(OrderDiagnosisState)

    restored = adapter.validate_json(adapter.dump_json(state))

    assert restored == state
    assert restored["tool_history"][0].action is AgentAction.QUERY_ORDER
    assert restored["information_gaps"][0].code == "QUALITY_ISSUES_REQUIRED"
    assert restored["iteration_count"] == 1


@pytest.mark.unit
def test_extended_agent_state_channels_are_required_and_strict() -> None:
    hints = get_type_hints(OrderDiagnosisState)

    assert hints["tool_history"] == list[AgentObservation]
    assert hints["information_gaps"] == list[InformationGap]
    assert hints["iteration_count"] is int
    assert hints["termination_reason"] == AgentTerminationReason | None
    assert {
        "tool_history",
        "information_gaps",
        "iteration_count",
        "termination_reason",
    }.issubset(OrderDiagnosisState.__required_keys__)

    with pytest.raises(ValidationError):
        InformationGap(code="quality_issues_required", description="代码必须稳定。")
    with pytest.raises(ValidationError):
        TypeAdapter(OrderDiagnosisState).validate_python(
            {
                "run_id": "run-m5-1",
                "order_id": "ORDER-003",
                "page_context": None,
                "order": None,
                "tasks": [],
                "progress": {},
                "quality_issues": {},
                "reviews": {},
                "delivery": None,
                "rule_decision": None,
                "diagnosis": None,
                "errors": [],
                "tool_history": [],
                "information_gaps": [],
                "iteration_count": -1,
                "termination_reason": None,
            }
        )
