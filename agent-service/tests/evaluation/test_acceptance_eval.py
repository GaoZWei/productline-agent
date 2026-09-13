"""诊断与Approval验收结果的最小聚合契约测试。"""

from __future__ import annotations

import pytest

from app.evaluation.acceptance import (
    AcceptanceEvaluationDataError,
    AcceptanceEvaluationOutcome,
    evaluate_acceptance,
)


def test_aggregates_success_duration_and_safe_failures() -> None:
    report = evaluate_acceptance(
        (
            AcceptanceEvaluationOutcome(
                case_id="approval-001",
                succeeded=True,
                duration_ms=20,
            ),
            AcceptanceEvaluationOutcome(
                case_id="approval-002",
                succeeded=False,
                duration_ms=40,
                error_code="APPROVAL_EXPIRED",
            ),
            AcceptanceEvaluationOutcome(
                case_id="approval-003",
                succeeded=True,
            ),
        )
    )

    assert report.total_cases == 3
    assert report.successful_cases == 2
    assert report.success_rate == pytest.approx(2 / 3)
    assert report.timed_cases == 2
    assert report.total_duration_ms == 60
    assert report.average_duration_ms == 30.0
    assert report.failures[0].model_dump() == {
        "case_id": "approval-002",
        "error_code": "APPROVAL_EXPIRED",
    }


def test_rejects_inconsistent_empty_duplicate_and_sensitive_outcomes() -> None:
    with pytest.raises(ValueError, match="successful"):
        AcceptanceEvaluationOutcome(
            case_id="approval-001",
            succeeded=True,
            error_code="UNEXPECTED_ERROR",
        )
    with pytest.raises(ValueError, match="requires"):
        AcceptanceEvaluationOutcome(case_id="approval-001", succeeded=False)
    with pytest.raises(ValueError):
        AcceptanceEvaluationOutcome.model_validate(
            {
                "case_id": "approval-001",
                "succeeded": False,
                "error_code": "FAILED",
                "message": "sensitive body",
            }
        )
    with pytest.raises(AcceptanceEvaluationDataError, match="at least one"):
        evaluate_acceptance(())

    outcome = AcceptanceEvaluationOutcome(case_id="approval-001", succeeded=True)
    with pytest.raises(AcceptanceEvaluationDataError, match="duplicate"):
        evaluate_acceptance((outcome, outcome))
