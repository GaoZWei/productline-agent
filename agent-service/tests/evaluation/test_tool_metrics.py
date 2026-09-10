"""M7.9 Tool五项指标的口径、计数和输入边界测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.evaluation.tools import (
    ToolEvaluationDataError,
    ToolEvaluationOutcome,
    evaluate_tool_metrics,
)


def _outcome(
    case_id: str,
    *,
    initial_validation_passed: bool,
    final_call_succeeded: bool,
    retry_count: int = 0,
    duplicate_call_detected: bool = False,
) -> ToolEvaluationOutcome:
    return ToolEvaluationOutcome(
        case_id=case_id,
        initial_validation_passed=initial_validation_passed,
        final_call_succeeded=final_call_succeeded,
        retry_count=retry_count,
        duplicate_call_detected=duplicate_call_detected,
    )


def test_calculates_all_five_tool_metrics_with_explicit_denominators() -> None:
    outcomes = (
        _outcome(
            "tool-001",
            initial_validation_passed=True,
            final_call_succeeded=True,
        ),
        _outcome(
            "tool-002",
            initial_validation_passed=False,
            final_call_succeeded=True,
        ),
        _outcome(
            "tool-003",
            initial_validation_passed=False,
            final_call_succeeded=False,
        ),
        _outcome(
            "tool-004",
            initial_validation_passed=True,
            final_call_succeeded=True,
            retry_count=1,
            duplicate_call_detected=True,
        ),
        _outcome(
            "tool-005",
            initial_validation_passed=True,
            final_call_succeeded=False,
            retry_count=2,
        ),
    )

    report = evaluate_tool_metrics(outcomes)

    assert report.total_cases == 5
    assert report.initial_validation_passed == 3
    assert report.initial_validation_pass_rate == 0.6
    assert report.initial_validation_failed == 2
    assert report.corrected_successes == 1
    assert report.correction_success_rate == 0.5
    assert report.final_call_successes == 3
    assert report.final_valid_call_success_rate == 0.6
    assert report.total_retries == 3
    assert report.average_retry_count == 0.6
    assert report.duplicate_call_cases == 1
    assert report.duplicate_call_rate == 0.2


def test_correction_rate_is_zero_when_no_case_needs_correction() -> None:
    report = evaluate_tool_metrics(
        (
            _outcome(
                "tool-001",
                initial_validation_passed=True,
                final_call_succeeded=True,
            ),
        )
    )

    assert report.initial_validation_failed == 0
    assert report.corrected_successes == 0
    assert report.correction_success_rate == 0.0


def test_rejects_empty_or_duplicate_outcomes_without_sensitive_payloads() -> None:
    with pytest.raises(ToolEvaluationDataError, match="at least one"):
        evaluate_tool_metrics(())

    outcome = _outcome(
        "tool-001",
        initial_validation_passed=True,
        final_call_succeeded=True,
    )
    with pytest.raises(ToolEvaluationDataError, match="duplicate ids") as captured:
        evaluate_tool_metrics((outcome, outcome))

    assert "input" not in str(captured.value)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "case_id": "tool-invalid",
            "initial_validation_passed": True,
            "final_call_succeeded": True,
        },
        {
            "case_id": "tool-001",
            "initial_validation_passed": True,
            "final_call_succeeded": True,
            "retry_count": -1,
        },
        {
            "case_id": "tool-001",
            "initial_validation_passed": True,
            "final_call_succeeded": True,
            "raw_input": "sensitive",
        },
    ],
)
def test_outcome_schema_rejects_invalid_or_sensitive_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ToolEvaluationOutcome.model_validate(payload)
