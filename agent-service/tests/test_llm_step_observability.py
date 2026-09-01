"""M7.6-A LLM Step独立指标生命周期测试。"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.models import AgentStep, AgentStepStatus, AgentStepType
from app.repositories import AgentRunRepository, AgentStepRepository
from app.schemas.run_observability import LLMStepObservation, RunTokenUsage
from app.services.step_lifecycle import StepLifecycleService, StepLifecycleValidationError


def _running_step(step_type: AgentStepType = AgentStepType.LLM) -> AgentStep:
    return AgentStep(
        step_id="step-llm-observation",
        run_id="run-llm-observation",
        sequence_number=1,
        step_type=step_type,
        step_name="route_intent",
        status=AgentStepStatus.RUNNING,
        started_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_step_success_persists_model_tokens_retries_and_duration() -> None:
    step = _running_step()
    step_repository = AsyncMock(spec=AgentStepRepository)
    step_repository.get_fresh.return_value = step

    async def transition(
        step_id: str,
        *,
        expected_status: AgentStepStatus,
        target_status: AgentStepStatus,
        changes: dict[str, Any],
    ) -> AgentStep:
        assert step_id == step.step_id
        assert expected_status is AgentStepStatus.RUNNING
        assert target_status is AgentStepStatus.SUCCEEDED
        for key, value in changes.items():
            setattr(step, key, value)
        step.status = target_status
        return step

    step_repository.transition_status.side_effect = transition
    service = StepLifecycleService(
        cast(AgentStepRepository, step_repository),
        cast(AgentRunRepository, AsyncMock(spec=AgentRunRepository)),
        now=lambda: datetime(2026, 8, 31, 1, 0, tzinfo=UTC) + timedelta(milliseconds=37),
    )

    completed = await service.mark_succeeded(
        step.step_id,
        output_summary="structured_output=validated",
        llm_observation=LLMStepObservation(
            model_name="actual-model-version",
            token_usage=RunTokenUsage.from_counts(input_tokens=31, output_tokens=7),
            retry_count=1,
        ),
    )

    assert completed.duration_ms == 37
    assert completed.llm_model_name == "actual-model-version"
    assert completed.llm_input_token_count == 31
    assert completed.llm_output_token_count == 7
    assert completed.llm_total_token_count == 38
    assert completed.llm_retry_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_observation_is_rejected_for_non_llm_step() -> None:
    step_repository = AsyncMock(spec=AgentStepRepository)
    step_repository.get_fresh.return_value = _running_step(AgentStepType.TOOL)
    service = StepLifecycleService(
        cast(AgentStepRepository, step_repository),
        cast(AgentRunRepository, AsyncMock(spec=AgentRunRepository)),
    )

    with pytest.raises(StepLifecycleValidationError, match="only allowed for an LLM step"):
        await service.mark_failed(
            "step-llm-observation",
            error_code="MODEL_TIMEOUT",
            llm_observation=LLMStepObservation(model_name="configured-model"),
        )

    step_repository.transition_status.assert_not_awaited()
