"""M7.9 Agent六项指标口径和数据边界测试。"""

import pytest
from pydantic import ValidationError

from app.evaluation.agents import (
    AgentEvaluationDataError,
    AgentEvaluationOutcome,
    evaluate_agent_metrics,
)
from app.schemas.workflow import BlockingStage


def _outcome(case_id: str, **overrides: object) -> AgentEvaluationOutcome:
    values: dict[str, object] = {
        "case_id": case_id,
        "e2e_succeeded": True,
        "executed_tool_calls": 0,
        "total_tool_call_attempts": 0,
    }
    values.update(overrides)
    return AgentEvaluationOutcome.model_validate(values)


def test_agent_metrics_aggregate_success_tool_duration_and_stage_quality() -> None:
    report = evaluate_agent_metrics(
        (
            _outcome(
                "agent-001",
                executed_tool_calls=2,
                total_tool_call_attempts=2,
                diagnosis_duration_ms=100,
                expected_blocking_stage=BlockingStage.QUALITY_REVIEW,
                actual_blocking_stage=BlockingStage.QUALITY_REVIEW,
            ),
            _outcome(
                "agent-002",
                executed_tool_calls=1,
                total_tool_call_attempts=2,
                invalid_tool_call_attempts=1,
                diagnosis_duration_ms=300,
                expected_blocking_stage=BlockingStage.DELIVERY,
                actual_blocking_stage=BlockingStage.QUALITY_REVIEW,
            ),
            _outcome(
                "agent-003",
                e2e_succeeded=False,
                executed_tool_calls=1,
                total_tool_call_attempts=2,
                duplicate_tool_call_attempts=1,
                expected_blocking_stage=BlockingStage.PRODUCTION_BLOCKED,
            ),
            _outcome("agent-004", e2e_succeeded=False),
        )
    )

    assert report.total_cases == 4
    assert report.e2e_successes == 2
    assert report.e2e_success_rate == 0.5
    assert report.total_executed_tool_calls == 4
    assert report.average_tool_call_count == 1.0
    assert report.total_tool_call_attempts == 6
    assert report.invalid_tool_call_attempts == 1
    assert report.invalid_tool_call_rate == pytest.approx(1 / 6)
    assert report.duplicate_tool_call_attempts == 1
    assert report.duplicate_tool_call_rate == pytest.approx(1 / 6)
    assert report.diagnosis_timed_cases == 2
    assert report.total_diagnosis_duration_ms == 400
    assert report.average_diagnosis_duration_ms == 200.0
    assert report.blocking_stage_evaluated_cases == 3
    assert report.blocking_stage_correct_cases == 1
    assert report.blocking_stage_accuracy == pytest.approx(1 / 3)


def test_agent_metrics_return_zero_for_unobserved_optional_denominators() -> None:
    report = evaluate_agent_metrics((_outcome("agent-001"),))

    assert report.invalid_tool_call_rate == 0.0
    assert report.duplicate_tool_call_rate == 0.0
    assert report.diagnosis_timed_cases == 0
    assert report.average_diagnosis_duration_ms == 0.0
    assert report.blocking_stage_evaluated_cases == 0
    assert report.blocking_stage_accuracy == 0.0


def test_agent_metrics_reject_empty_or_duplicate_collections() -> None:
    with pytest.raises(AgentEvaluationDataError, match="at least one"):
        evaluate_agent_metrics(())

    duplicate = _outcome("agent-001")
    with pytest.raises(AgentEvaluationDataError, match="duplicate"):
        evaluate_agent_metrics((duplicate, duplicate))


@pytest.mark.parametrize(
    "values",
    [
        {
            "case_id": "agent-001",
            "e2e_succeeded": True,
            "executed_tool_calls": 1,
            "total_tool_call_attempts": 0,
        },
        {
            "case_id": "agent-001",
            "e2e_succeeded": True,
            "unexpected_raw_result": "sensitive",
        },
        {
            "case_id": "agent-001",
            "e2e_succeeded": True,
            "actual_blocking_stage": BlockingStage.DELIVERY,
        },
    ],
)
def test_agent_outcome_rejects_inconsistent_or_extra_data(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AgentEvaluationOutcome.model_validate(values)
