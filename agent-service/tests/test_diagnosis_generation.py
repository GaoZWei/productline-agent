"""M2.7 规则文案、结构化模型改写和失败回退测试。"""

from collections.abc import Callable

import pytest

from app.schemas.tools import (
    DeliveryRecord,
    DeliveryStatus,
    OrderDetail,
    ProductionStep,
    ProgressResult,
    QualityIssue,
    ReviewRecord,
    ReviewResult,
    TaskDetail,
)
from app.schemas.workflow import BlockingStage, OrderDiagnosisState, RuleDecision
from app.workflows import (
    InvalidDiagnosisNarrativeError,
    apply_model_narrative,
    generate_rule_diagnosis,
)


def _state(
    *,
    stage: BlockingStage,
    task_status: str,
    step_status: str,
    issue_status: str | None,
    review_status: str | None,
    delivery_status: str,
) -> OrderDiagnosisState:
    order_id = "ORDER-003"
    task_id = "TASK-003"
    issues = (
        []
        if issue_status is None
        else [
            QualityIssue(
                issue_id="ISSUE-001",
                task_id=task_id,
                issue_type="COORDINATE_SYSTEM",
                status=issue_status,  # type: ignore[arg-type]
                description="coordinate system mismatch",
            )
        ]
    )
    reviews = (
        []
        if review_status is None
        else [
            ReviewRecord(
                review_id="REVIEW-003",
                issue_id="ISSUE-001",
                status=review_status,  # type: ignore[arg-type]
                review_comment=None,
            )
        ]
    )
    return {
        "run_id": "run-generation-003",
        "order_id": order_id,
        "order": OrderDetail(
            order_id=order_id,
            product_type="DOM",
            status="QUALITY_CHECKING",
        ),
        "tasks": [
            TaskDetail(
                task_id=task_id,
                order_id=order_id,
                status=task_status,  # type: ignore[arg-type]
                version=0,
            )
        ],
        "progress": {
            task_id: ProgressResult(
                task_id=task_id,
                steps=[
                    ProductionStep(
                        step_id="STEP-003-01",
                        task_id=task_id,
                        step_name="DOM production",
                        sequence_number=1,
                        status=step_status,  # type: ignore[arg-type]
                    )
                ],
            )
        },
        "quality_issues": {task_id: issues},
        "reviews": {task_id: ReviewResult(task_id=task_id, reviews=reviews)},
        "delivery": DeliveryStatus(
            order_id=order_id,
            records=[
                DeliveryRecord(
                    delivery_id="DELIVERY-003",
                    order_id=order_id,
                    status=delivery_status,  # type: ignore[arg-type]
                )
            ],
        ),
        "rule_decision": RuleDecision(order_id=order_id, blocking_stage=stage),
        "diagnosis": None,
        "errors": [],
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "expected_root_code", "expected_action"),
    [
        (
            _state(
                stage=BlockingStage.PRODUCTION,
                task_status="RUNNING",
                step_status="RUNNING",
                issue_status=None,
                review_status=None,
                delivery_status="NOT_READY",
            ),
            "PRODUCTION_IN_PROGRESS",
            "WAIT_FOR_PRODUCTION",
        ),
        (
            _state(
                stage=BlockingStage.PRODUCTION_BLOCKED,
                task_status="FAILED",
                step_status="FAILED",
                issue_status=None,
                review_status=None,
                delivery_status="NOT_READY",
            ),
            "PRODUCTION_EXECUTION_BLOCKED",
            "RETRY_PRODUCTION",
        ),
        (
            _state(
                stage=BlockingStage.QUALITY_REVIEW,
                task_status="COMPLETED",
                step_status="COMPLETED",
                issue_status="OPEN",
                review_status="PENDING",
                delivery_status="BLOCKED",
            ),
            "OPEN_COORDINATE_SYSTEM_ISSUE",
            "CREATE_COORDINATE_SYSTEM_REWORK",
        ),
        (
            _state(
                stage=BlockingStage.REVIEW,
                task_status="COMPLETED",
                step_status="COMPLETED",
                issue_status="RESOLVED",
                review_status="PENDING",
                delivery_status="BLOCKED",
            ),
            "REVIEW_NOT_APPROVED",
            "COMPLETE_REVIEW",
        ),
        (
            _state(
                stage=BlockingStage.DELIVERY,
                task_status="COMPLETED",
                step_status="COMPLETED",
                issue_status=None,
                review_status=None,
                delivery_status="FAILED",
            ),
            "DELIVERY_NOT_READY",
            "RESOLVE_DELIVERY_BLOCKER",
        ),
    ],
)
def test_rule_generation_covers_each_blocking_stage(
    state: OrderDiagnosisState,
    expected_root_code: str,
    expected_action: str,
) -> None:
    diagnosis = generate_rule_diagnosis(state)

    assert diagnosis.root_causes[0].code == expected_root_code
    assert diagnosis.suggestions[0].action_type == expected_action
    assert diagnosis.evidence[0].source_type == "TOOL"
    assert diagnosis.confidence == 1.0


@pytest.mark.unit
def test_order_003_generation_preserves_golden_root_causes_evidence_and_suggestions() -> None:
    state = _state(
        stage=BlockingStage.QUALITY_REVIEW,
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status="OPEN",
        review_status="PENDING",
        delivery_status="BLOCKED",
    )

    diagnosis = generate_rule_diagnosis(state)

    assert diagnosis.summary == "订单阻塞在质量复核环节。"
    assert [cause.code for cause in diagnosis.root_causes] == [
        "OPEN_COORDINATE_SYSTEM_ISSUE",
        "REVIEW_PENDING",
    ]
    assert [(item.tool_name, item.field_path, item.value) for item in diagnosis.evidence] == [
        ("get_related_tasks", "tasks[0].status", "COMPLETED"),
        ("get_quality_issues", "issues[0].status", "OPEN"),
        ("get_review_result", "reviews[0].status", "PENDING"),
        ("get_delivery_status", "records[0].status", "BLOCKED"),
    ]
    assert [item.action_type for item in diagnosis.suggestions] == [
        "CREATE_COORDINATE_SYSTEM_REWORK",
        "RESUBMIT_REVIEW",
    ]


@pytest.mark.unit
def test_no_blocker_has_no_root_cause_and_keeps_delivery_evidence() -> None:
    state = _state(
        stage=BlockingStage.NONE,
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status="CLOSED",
        review_status="APPROVED",
        delivery_status="READY",
    )

    diagnosis = generate_rule_diagnosis(state)

    assert diagnosis.root_causes == []
    assert diagnosis.evidence[0].value == "READY"
    assert diagnosis.suggestions[0].action_type == "CONTINUE_DELIVERY"


@pytest.mark.unit
def test_insufficient_information_uses_loaded_fact_and_zero_confidence() -> None:
    state = _state(
        stage=BlockingStage.INSUFFICIENT_INFORMATION,
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status=None,
        review_status=None,
        delivery_status="READY",
    )
    state["tasks"] = []

    diagnosis = generate_rule_diagnosis(state)

    assert diagnosis.root_causes[0].code == "INSUFFICIENT_BUSINESS_FACTS"
    assert diagnosis.evidence[0].tool_name == "get_order_detail"
    assert diagnosis.confidence == 0.0


@pytest.mark.unit
def test_model_narrative_can_only_replace_descriptions() -> None:
    rule_result = generate_rule_diagnosis(
        _state(
            stage=BlockingStage.QUALITY_REVIEW,
            task_status="COMPLETED",
            step_status="COMPLETED",
            issue_status="OPEN",
            review_status="PENDING",
            delivery_status="BLOCKED",
        )
    )
    raw_output = {
        "summary": "质量问题尚未闭环。当前无法进入交付。",
        "root_causes": [
            {"code": cause.code, "description": f"模型整理: {cause.description}"}
            for cause in rule_result.root_causes
        ],
        "suggestions": [
            {
                "action_type": suggestion.action_type,
                "description": f"模型整理: {suggestion.description}",
            }
            for suggestion in rule_result.suggestions
        ],
    }

    refined = apply_model_narrative(rule_result, raw_output)

    assert refined.summary == raw_output["summary"]
    assert refined.order_id == rule_result.order_id
    assert refined.blocking_stage is rule_result.blocking_stage
    assert refined.evidence == rule_result.evidence
    assert refined.confidence == rule_result.confidence


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda output: output.__setitem__("blocking_stage", "NONE"),
        lambda output: output["root_causes"][0].__setitem__("code", "CHANGED_CODE"),
        lambda output: output.__setitem__("suggestions", []),
    ],
)
def test_model_narrative_rejects_extra_fields_changed_codes_and_empty_suggestions(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    rule_result = generate_rule_diagnosis(
        _state(
            stage=BlockingStage.QUALITY_REVIEW,
            task_status="COMPLETED",
            step_status="COMPLETED",
            issue_status="OPEN",
            review_status="PENDING",
            delivery_status="BLOCKED",
        )
    )
    raw_output: dict[str, object] = {
        "summary": rule_result.summary,
        "root_causes": [item.model_dump() for item in rule_result.root_causes],
        "suggestions": [item.model_dump() for item in rule_result.suggestions],
    }
    mutate(raw_output)

    with pytest.raises(InvalidDiagnosisNarrativeError):
        apply_model_narrative(rule_result, raw_output)
