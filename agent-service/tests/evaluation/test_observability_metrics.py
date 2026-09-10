"""M7.9异常观测三项指标口径和数据边界测试。"""

import pytest
from pydantic import ValidationError

from app.evaluation.observability import (
    ObservabilityEvaluationDataError,
    ObservabilityEvaluationOutcome,
    evaluate_observability_metrics,
)


def _outcome(case_id: str, **overrides: object) -> ObservabilityEvaluationOutcome:
    values: dict[str, object] = {
        "case_id": case_id,
        "expected_error_type": "JAVA_TIMEOUT",
    }
    values.update(overrides)
    return ObservabilityEvaluationOutcome.model_validate(values)


def test_observability_metrics_aggregate_location_type_and_even_median() -> None:
    report = evaluate_observability_metrics(
        (
            _outcome(
                "obs-001",
                observed_error_type="JAVA_TIMEOUT",
                expected_error_step="load_order",
                located_error_step="load_order",
                troubleshooting_duration_ms=10,
            ),
            _outcome(
                "obs-002",
                expected_error_type="MODEL_INVALID_REQUEST",
                observed_error_type="TOOL_INVALID_ARGUMENT",
                expected_error_step="decide_action",
                located_error_step="load_order",
                troubleshooting_duration_ms=20,
            ),
            _outcome(
                "obs-003",
                expected_error_type="SSE_INTERRUPTED",
                troubleshooting_duration_ms=30,
            ),
            _outcome(
                "obs-004",
                expected_error_type="APPROVAL_EXPIRED",
                observed_error_type="APPROVAL_EXPIRED",
                expected_error_step="wait_for_confirmation",
                troubleshooting_duration_ms=100,
            ),
        )
    )

    assert report.total_cases == 4
    assert report.step_location_evaluated_cases == 3
    assert report.correctly_located_steps == 1
    assert report.exception_step_locatable_rate == pytest.approx(1 / 3)
    assert report.correctly_identified_error_types == 2
    assert report.error_type_identification_accuracy == 0.5
    assert report.troubleshooting_timed_cases == 4
    assert report.median_troubleshooting_duration_ms == 25.0


def test_observability_metrics_return_zero_without_step_or_time_observations() -> None:
    report = evaluate_observability_metrics((_outcome("obs-001"),))

    assert report.step_location_evaluated_cases == 0
    assert report.exception_step_locatable_rate == 0.0
    assert report.correctly_identified_error_types == 0
    assert report.error_type_identification_accuracy == 0.0
    assert report.troubleshooting_timed_cases == 0
    assert report.median_troubleshooting_duration_ms == 0.0


def test_observability_metrics_reject_empty_or_duplicate_collections() -> None:
    with pytest.raises(ObservabilityEvaluationDataError, match="at least one"):
        evaluate_observability_metrics(())

    duplicate = _outcome("obs-001")
    with pytest.raises(ObservabilityEvaluationDataError, match="duplicate"):
        evaluate_observability_metrics((duplicate, duplicate))


@pytest.mark.parametrize(
    "values",
    [
        {
            "case_id": "obs-001",
            "expected_error_type": "lowercase-error",
        },
        {
            "case_id": "obs-001",
            "expected_error_type": "JAVA_TIMEOUT",
            "located_error_step": "load_order",
        },
        {
            "case_id": "obs-001",
            "expected_error_type": "JAVA_TIMEOUT",
            "raw_exception": "sensitive",
        },
    ],
)
def test_observability_outcome_rejects_invalid_or_extra_data(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ObservabilityEvaluationOutcome.model_validate(values)
