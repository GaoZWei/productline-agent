"""M2.4 Workflow状态和结构化诊断Schema测试。"""

from typing import get_args, get_type_hints

import pytest
from pydantic import ValidationError

from app.errors import ToolErrorCode
from app.schemas import (
    BlockingStage,
    DiagnosisResult,
    Evidence,
    OrderDiagnosisState,
    ReadToolName,
    RootCause,
    RuleDecision,
    StepError,
    Suggestion,
)
from app.schemas.tools import (
    DeliveryStatus,
    OrderDetail,
    ProgressResult,
    QualityIssue,
    ReviewResult,
    TaskDetail,
)
from app.tools.readonly import READ_TOOL_NAMES


def _golden_diagnosis() -> DiagnosisResult:
    return DiagnosisResult(
        order_id="ORDER-003",
        blocking_stage=BlockingStage.QUALITY_REVIEW,
        summary="订单阻塞在质量复核环节。",
        root_causes=[
            RootCause(
                code="OPEN_COORDINATE_SYSTEM_ISSUE",
                description="关联任务存在未关闭的坐标系质量问题",
            ),
            RootCause(
                code="REVIEW_PENDING",
                description="质检复核尚未完成",
            ),
        ],
        evidence=[
            Evidence(
                source_type="TOOL",
                tool_name="get_quality_issues",
                field_path="issues[0].status",
                value="OPEN",
                description="ISSUE-001尚未关闭",
            ),
            Evidence(
                source_type="TOOL",
                tool_name="get_delivery_status",
                field_path="records[0].status",
                value="BLOCKED",
                description="ORDER-003交付状态为BLOCKED",
            ),
        ],
        suggestions=[
            Suggestion(
                action_type="CREATE_COORDINATE_SYSTEM_REWORK",
                description="创建坐标系处理返工任务",
            ),
            Suggestion(
                action_type="RESUBMIT_REVIEW",
                description="问题处理完成后重新提交复核",
            ),
        ],
        confidence=1.0,
    )


@pytest.mark.unit
def test_diagnosis_result_accepts_structured_order_003_golden_result() -> None:
    diagnosis = _golden_diagnosis()

    assert diagnosis.order_id == "ORDER-003"
    assert diagnosis.blocking_stage == "QUALITY_REVIEW"
    assert diagnosis.summary == "订单阻塞在质量复核环节。"
    assert diagnosis.root_causes[0].code == "OPEN_COORDINATE_SYSTEM_ISSUE"
    assert diagnosis.evidence[0].tool_name == "get_quality_issues"
    assert diagnosis.evidence[0].field_path == "issues[0].status"
    assert diagnosis.suggestions[0].action_type == "CREATE_COORDINATE_SYSTEM_REWORK"
    assert diagnosis.model_dump(mode="json")["confidence"] == 1.0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("order_id", "TASK-003"),
        ("blocking_stage", "quality-review"),
        ("blocking_stage", "UNKNOWN_STAGE"),
        ("summary", " "),
        ("root_causes", []),
        ("evidence", []),
        ("suggestions", []),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("confidence", "1.0"),
    ],
)
def test_diagnosis_result_rejects_invalid_top_level_contract(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _golden_diagnosis().model_dump()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        DiagnosisResult.model_validate(payload)


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_evidence",
    [
        {
            "source_type": "MODEL",
            "tool_name": "get_quality_issues",
            "field_path": "issues[0].status",
            "value": "OPEN",
            "description": "模型不能充当业务事实来源",
        },
        {
            "source_type": "TOOL",
            "tool_name": "unknown_tool",
            "field_path": "issues[0].status",
            "value": "OPEN",
            "description": "未知Tool不能作为证据来源",
        },
        {
            "source_type": "TOOL",
            "tool_name": "get_quality_issues",
            "field_path": "issues 0 status",
            "value": "OPEN",
            "description": "字段路径必须可定位",
        },
        {
            "source_type": "TOOL",
            "tool_name": "get_quality_issues",
            "field_path": "issues[0]",
            "value": {"status": "OPEN"},
            "description": "证据值必须是单个字段的标量",
        },
    ],
)
def test_evidence_rejects_untraceable_or_composite_business_facts(
    invalid_evidence: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(invalid_evidence)


@pytest.mark.unit
def test_nested_diagnosis_schemas_are_strict_and_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RootCause.model_validate(
            {
                "code": "OPEN_ISSUE",
                "description": "存在未关闭问题",
                "unsupported": True,
            }
        )
    with pytest.raises(ValidationError):
        Suggestion(action_type="create rework", description="创建返工任务")
    with pytest.raises(ValidationError):
        Suggestion(action_type="CREATE_REWORK", description=" ")


@pytest.mark.unit
def test_diagnosis_result_does_not_allow_root_causes_for_no_blocker() -> None:
    payload = _golden_diagnosis().model_dump()
    payload["blocking_stage"] = BlockingStage.NONE

    with pytest.raises(ValidationError):
        DiagnosisResult.model_validate(payload)

    payload["root_causes"] = []
    diagnosis = DiagnosisResult.model_validate(payload)
    assert diagnosis.blocking_stage is BlockingStage.NONE
    assert diagnosis.root_causes == []


@pytest.mark.unit
def test_step_error_preserves_machine_branch_fields_without_raw_payload() -> None:
    error = StepError(
        step_name="get_quality_issues",
        code=ToolErrorCode.TOOL_TIMEOUT,
        message="Java业务服务请求超时",
        retryable=True,
        trace_id="trace-m2-4",
    )

    assert error.code is ToolErrorCode.TOOL_TIMEOUT
    assert error.model_dump(mode="json") == {
        "step_name": "get_quality_issues",
        "code": "TOOL_TIMEOUT",
        "message": "Java业务服务请求超时",
        "retryable": True,
        "trace_id": "trace-m2-4",
    }
    with pytest.raises(ValidationError):
        StepError.model_validate(
            {
                **error.model_dump(),
                "raw_response": {"authorization": "Bearer secret"},
            }
        )


@pytest.mark.unit
def test_order_diagnosis_state_exposes_required_workflow_channels() -> None:
    hints = get_type_hints(OrderDiagnosisState)

    assert hints == {
        "run_id": str,
        "order_id": str,
        "order": OrderDetail | None,
        "tasks": list[TaskDetail],
        "progress": dict[str, ProgressResult],
        "quality_issues": dict[str, list[QualityIssue]],
        "reviews": dict[str, ReviewResult | None],
        "delivery": DeliveryStatus | None,
        "rule_decision": RuleDecision | None,
        "diagnosis": DiagnosisResult | None,
        "errors": list[StepError],
    }
    assert OrderDiagnosisState.__required_keys__ == frozenset(hints)


@pytest.mark.unit
def test_evidence_tool_name_contract_matches_registered_read_tools() -> None:
    assert frozenset(get_args(ReadToolName)) == READ_TOOL_NAMES
