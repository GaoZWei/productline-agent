"""M2.6 确定性诊断规则的五订单、信息完整性和优先级测试。"""

from collections.abc import Callable

import pytest

from app.schemas import BlockingStage, OrderDiagnosisState
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
from app.workflows import evaluate_diagnosis_rules


def _state(
    *,
    order_id: str,
    order_status: str,
    task_status: str,
    step_status: str,
    issue_status: str | None,
    review_status: str | None,
    delivery_status: str,
) -> OrderDiagnosisState:
    task_id = f"TASK-{order_id.removeprefix('ORDER-')}"
    issues = (
        []
        if issue_status is None
        else [
            QualityIssue(
                issue_id=f"ISSUE-{order_id.removeprefix('ORDER-')}",
                task_id=task_id,
                issue_type="COORDINATE_SYSTEM",
                status=issue_status,  # type: ignore[arg-type]
                description="固定质检问题",
            )
        ]
    )
    reviews = (
        []
        if review_status is None
        else [
            ReviewRecord(
                review_id=f"REVIEW-{order_id.removeprefix('ORDER-')}",
                issue_id=issues[0].issue_id,
                status=review_status,  # type: ignore[arg-type]
                review_comment=None,
            )
        ]
    )
    return {
        "run_id": f"run-{order_id.lower()}",
        "order_id": order_id,
        "order": OrderDetail(
            order_id=order_id,
            product_type="DOM",
            status=order_status,  # type: ignore[arg-type]
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
                        step_id=f"STEP-{order_id.removeprefix('ORDER-')}-01",
                        task_id=task_id,
                        step_name="固定生产步骤",
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
                    delivery_id=f"DELIVERY-{order_id.removeprefix('ORDER-')}",
                    order_id=order_id,
                    status=delivery_status,  # type: ignore[arg-type]
                )
            ],
        ),
        "rule_decision": None,
        "diagnosis": None,
        "errors": [],
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "expected_stage"),
    [
        (
            _state(
                order_id="ORDER-001",
                order_status="PRODUCING",
                task_status="RUNNING",
                step_status="RUNNING",
                issue_status=None,
                review_status=None,
                delivery_status="NOT_READY",
            ),
            BlockingStage.PRODUCTION,
        ),
        (
            _state(
                order_id="ORDER-002",
                order_status="BLOCKED",
                task_status="FAILED",
                step_status="FAILED",
                issue_status=None,
                review_status=None,
                delivery_status="NOT_READY",
            ),
            BlockingStage.PRODUCTION_BLOCKED,
        ),
        (
            _state(
                order_id="ORDER-003",
                order_status="QUALITY_CHECKING",
                task_status="COMPLETED",
                step_status="COMPLETED",
                issue_status="OPEN",
                review_status="PENDING",
                delivery_status="BLOCKED",
            ),
            BlockingStage.QUALITY_REVIEW,
        ),
        (
            _state(
                order_id="ORDER-004",
                order_status="REVIEWING",
                task_status="COMPLETED",
                step_status="COMPLETED",
                issue_status="RESOLVED",
                review_status="PENDING",
                delivery_status="BLOCKED",
            ),
            BlockingStage.REVIEW,
        ),
        (
            _state(
                order_id="ORDER-005",
                order_status="READY_FOR_DELIVERY",
                task_status="COMPLETED",
                step_status="COMPLETED",
                issue_status="CLOSED",
                review_status="APPROVED",
                delivery_status="READY",
            ),
            BlockingStage.NONE,
        ),
    ],
)
def test_fixed_orders_match_declared_blocking_stage(
    state: OrderDiagnosisState,
    expected_stage: BlockingStage,
) -> None:
    decision = evaluate_diagnosis_rules(state)

    assert decision.order_id == state["order_id"]
    assert decision.blocking_stage is expected_stage


@pytest.mark.unit
@pytest.mark.parametrize(
    "remove_fact",
    [
        lambda state: state.__setitem__("order", None),
        lambda state: state.__setitem__("tasks", []),
        lambda state: state.__setitem__("progress", {}),
        lambda state: state.__setitem__("quality_issues", {}),
        lambda state: state.__setitem__("reviews", {}),
        lambda state: state.__setitem__("delivery", None),
    ],
)
def test_missing_required_fact_returns_insufficient_information(
    remove_fact: Callable[[OrderDiagnosisState], object],
) -> None:
    state = _state(
        order_id="ORDER-005",
        order_status="READY_FOR_DELIVERY",
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status="CLOSED",
        review_status="APPROVED",
        delivery_status="READY",
    )
    remove_fact(state)

    assert (
        evaluate_diagnosis_rules(state).blocking_stage
        is BlockingStage.INSUFFICIENT_INFORMATION
    )


@pytest.mark.unit
def test_rule_priority_uses_earliest_blocking_business_stage() -> None:
    state = _state(
        order_id="ORDER-003",
        order_status="BLOCKED",
        task_status="FAILED",
        step_status="FAILED",
        issue_status="OPEN",
        review_status="PENDING",
        delivery_status="BLOCKED",
    )

    assert (
        evaluate_diagnosis_rules(state).blocking_stage
        is BlockingStage.PRODUCTION_BLOCKED
    )


@pytest.mark.unit
def test_resolved_issue_without_approved_review_stays_in_review_stage() -> None:
    state = _state(
        order_id="ORDER-004",
        order_status="REVIEWING",
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status="RESOLVED",
        review_status=None,
        delivery_status="BLOCKED",
    )

    assert evaluate_diagnosis_rules(state).blocking_stage is BlockingStage.REVIEW


@pytest.mark.unit
def test_completed_upstream_with_failed_delivery_uses_delivery_stage() -> None:
    state = _state(
        order_id="ORDER-RULE-DELIVERY",
        order_status="BLOCKED",
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status=None,
        review_status=None,
        delivery_status="FAILED",
    )

    assert evaluate_diagnosis_rules(state).blocking_stage is BlockingStage.DELIVERY


@pytest.mark.unit
def test_empty_nested_fact_collection_is_not_treated_as_no_blocker() -> None:
    state = _state(
        order_id="ORDER-005",
        order_status="READY_FOR_DELIVERY",
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status="CLOSED",
        review_status="APPROVED",
        delivery_status="READY",
    )
    task_id = state["tasks"][0].task_id
    state["progress"][task_id] = ProgressResult(task_id=task_id, steps=[])

    assert (
        evaluate_diagnosis_rules(state).blocking_stage
        is BlockingStage.INSUFFICIENT_INFORMATION
    )
