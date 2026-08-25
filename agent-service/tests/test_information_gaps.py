"""M5.5 场景化信息缺口检测和动态规则测试。"""

from __future__ import annotations

from app.schemas import (
    BlockingStage,
    OrderDiagnosisState,
    SpecificationQaResult,
    SpecificationQaStatus,
)
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
from app.workflows import InformationGapDetector, evaluate_dynamic_diagnosis_rules


def _state(
    *,
    order_status: str = "QUALITY_CHECKING",
    task_status: str = "COMPLETED",
    delivery: bool = True,
) -> OrderDiagnosisState:
    order_id = "ORDER-003"
    task_id = "TASK-003"
    return {
        "run_id": "run-gap-003",
        "order_id": order_id,
        "page_context": None,
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
        "progress": {},
        "quality_issues": {},
        "reviews": {},
        "delivery": (
            DeliveryStatus(
                order_id=order_id,
                records=[
                    DeliveryRecord(
                        delivery_id="DELIVERY-003",
                        order_id=order_id,
                        status="BLOCKED",
                    )
                ],
            )
            if delivery
            else None
        ),
        "rule_decision": None,
        "diagnosis": None,
        "errors": [],
        "tool_history": [],
        "information_gaps": [],
        "iteration_count": 0,
        "termination_reason": None,
    }


def _gap_codes(
    detector: InformationGapDetector,
    state: OrderDiagnosisState,
    *,
    specification_result: SpecificationQaResult | None = None,
) -> list[str]:
    return [
        gap.code
        for gap in detector.detect(
            state,
            specification_result=specification_result,
        )
    ]


def _safe_specification_result() -> SpecificationQaResult:
    return SpecificationQaResult(
        status=SpecificationQaStatus.INSUFFICIENT_CONTEXT,
        question="坐标系问题应如何处理",
        rewritten_query="坐标系问题应如何处理",
        answer="当前没有足够的有效规范依据。",
        citations=(),
    )


def test_detector_reports_only_actionable_base_gaps_before_business_facts() -> None:
    state = _state(delivery=False)
    state["order"] = None
    state["tasks"] = []

    assert _gap_codes(InformationGapDetector(), state) == [
        "ORDER_REQUIRED",
        "RELATED_TASKS_REQUIRED",
        "DELIVERY_STATUS_REQUIRED",
    ]


def test_production_scenario_requires_valid_progress_for_active_task() -> None:
    detector = InformationGapDetector()
    state = _state(order_status="PRODUCING", task_status="RUNNING")

    assert _gap_codes(detector, state) == ["PRODUCTION_PROGRESS_REQUIRED"]

    state["progress"]["TASK-003"] = ProgressResult(
        task_id="TASK-003",
        steps=[
            ProductionStep(
                step_id="STEP-003-01",
                task_id="TASK-003",
                step_name="DOM生产",
                sequence_number=1,
                status="RUNNING",
            )
        ],
    )

    assert detector.detect(state) == []
    state["information_gaps"] = []
    assert evaluate_dynamic_diagnosis_rules(state).blocking_stage is BlockingStage.PRODUCTION


def test_quality_scenario_adds_review_and_specification_gaps_from_issues() -> None:
    detector = InformationGapDetector()
    state = _state()

    assert _gap_codes(detector, state) == ["QUALITY_ISSUES_REQUIRED"]

    state["quality_issues"]["TASK-003"] = [
        QualityIssue(
            issue_id="ISSUE-001",
            task_id="TASK-003",
            issue_type="COORDINATE_SYSTEM",
            status="OPEN",
            description="坐标系不一致",
        )
    ]

    assert _gap_codes(detector, state) == [
        "REVIEW_RESULT_REQUIRED",
        "SPECIFICATION_RESULT_REQUIRED",
    ]

    state["reviews"]["TASK-003"] = ReviewResult(
        task_id="TASK-003",
        reviews=[
            ReviewRecord(
                review_id="REVIEW-003",
                issue_id="ISSUE-001",
                status="PENDING",
                review_comment=None,
            )
        ],
    )
    specification_result = _safe_specification_result()

    assert (
        detector.detect(
            state,
            specification_result=specification_result,
        )
        == []
    )
    state["information_gaps"] = []
    assert evaluate_dynamic_diagnosis_rules(state).blocking_stage is BlockingStage.QUALITY_REVIEW


def test_review_scenario_requires_review_without_forcing_quality_query() -> None:
    detector = InformationGapDetector()
    state = _state(order_status="REVIEWING")

    assert _gap_codes(detector, state) == ["REVIEW_RESULT_REQUIRED"]

    state["reviews"]["TASK-003"] = ReviewResult(
        task_id="TASK-003",
        reviews=[
            ReviewRecord(
                review_id="REVIEW-004",
                issue_id="ISSUE-004",
                status="REJECTED",
                review_comment="需要返工",
            )
        ],
    )

    assert detector.detect(state) == []
    state["information_gaps"] = []
    assert evaluate_dynamic_diagnosis_rules(state).blocking_stage is BlockingStage.REVIEW


def test_delivery_scenario_accepts_completed_upstream_and_valid_delivery() -> None:
    detector = InformationGapDetector()
    state = _state(order_status="READY_FOR_DELIVERY")

    assert detector.detect(state) == []
    state["information_gaps"] = []
    assert evaluate_dynamic_diagnosis_rules(state).blocking_stage is BlockingStage.DELIVERY

    state["delivery"] = None
    assert _gap_codes(detector, state) == ["DELIVERY_STATUS_REQUIRED"]


def test_dynamic_rules_refuse_a_conclusion_while_any_gap_remains() -> None:
    state = _state(order_status="PRODUCING", task_status="RUNNING")
    state["information_gaps"] = InformationGapDetector().detect(state)

    assert (
        evaluate_dynamic_diagnosis_rules(state).blocking_stage
        is BlockingStage.INSUFFICIENT_INFORMATION
    )


def test_detector_rejects_mismatched_nested_business_resources() -> None:
    detector = InformationGapDetector()
    state = _state(order_status="PRODUCING", task_status="RUNNING")
    state["delivery"] = DeliveryStatus(
        order_id="ORDER-999",
        records=[
            DeliveryRecord(
                delivery_id="DELIVERY-999",
                order_id="ORDER-999",
                status="NOT_READY",
            )
        ],
    )
    state["progress"]["TASK-003"] = ProgressResult(
        task_id="TASK-999",
        steps=[
            ProductionStep(
                step_id="STEP-999-01",
                task_id="TASK-999",
                step_name="错误归属生产步骤",
                sequence_number=1,
                status="RUNNING",
            )
        ],
    )

    assert _gap_codes(detector, state) == [
        "DELIVERY_STATUS_REQUIRED",
        "PRODUCTION_PROGRESS_REQUIRED",
    ]
