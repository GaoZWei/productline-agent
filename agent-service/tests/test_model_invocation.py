"""M7.6-A模型调用与LLM Step观测接线测试。"""

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.clients import ChatMessage, ModelClientError, ModelErrorCode, StructuredModelResult
from app.models import AgentStepType
from app.schemas.run_observability import LLMStepObservation, RunTokenUsage
from app.services.model_invocation import ObservedModelInvoker


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str


class RecordingStepRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def start_step(self, **values: Any) -> None:
        self.calls.append(("start", values))

    async def mark_llm_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
        observation: LLMStepObservation,
    ) -> None:
        self.calls.append(
            (
                "succeeded",
                {
                    "step_id": step_id,
                    "output_summary": output_summary,
                    "observation": observation,
                },
            )
        )

    async def mark_llm_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
        observation: LLMStepObservation | None,
    ) -> None:
        self.calls.append(
            (
                "failed",
                {
                    "step_id": step_id,
                    "error_code": error_code,
                    "output_summary": output_summary,
                    "observation": observation,
                },
            )
        )


class SuccessfulClient:
    model_name = "configured-model"

    async def complete_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        assert messages[0].content == "question"
        return StructuredModelResult(
            output=output_schema.model_validate({"answer": "sensitive-model-answer"}),
            model_name="actual-model-version",
            token_usage=RunTokenUsage.from_counts(input_tokens=21, output_tokens=5),
            duration_ms=14,
            retry_count=1,
        )


class FailingClient:
    model_name = "configured-model"

    async def complete_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        raise ModelClientError(
            code=ModelErrorCode.RATE_LIMITED,
            message="structured model provider rate limited the request",
            retryable=True,
            retry_count=2,
            status_code=429,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_observed_invoker_records_success_metrics_without_prompt_or_output() -> None:
    recorder = RecordingStepRecorder()
    invoker = ObservedModelInvoker(SuccessfulClient(), recorder)

    result = await invoker.complete_structured(
        (ChatMessage(role="user", content="question"),),
        StructuredAnswer,
        step_id="step-llm-success",
        run_id="run-llm-success",
        sequence_number=3,
        step_name="route_intent",
        input_summary="message_length=8",
    )

    assert result.output.answer == "sensitive-model-answer"
    assert recorder.calls[0] == (
        "start",
        {
            "step_id": "step-llm-success",
            "run_id": "run-llm-success",
            "sequence_number": 3,
            "step_type": AgentStepType.LLM,
            "step_name": "route_intent",
            "input_summary": "message_length=8",
        },
    )
    observation = recorder.calls[1][1]["observation"]
    assert observation == LLMStepObservation(
        model_name="actual-model-version",
        token_usage=RunTokenUsage.from_counts(input_tokens=21, output_tokens=5),
        retry_count=1,
    )
    assert "question" not in repr(recorder.calls[1])
    assert "sensitive-model-answer" not in repr(recorder.calls[1])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_observed_invoker_records_stable_failure_and_actual_retries() -> None:
    recorder = RecordingStepRecorder()
    invoker = ObservedModelInvoker(FailingClient(), recorder)

    with pytest.raises(ModelClientError, match="rate limited"):
        await invoker.complete_structured(
            (ChatMessage(role="user", content="question"),),
            StructuredAnswer,
            step_id="step-llm-failed",
            run_id="run-llm-failed",
            sequence_number=1,
            step_name="route_intent",
            input_summary="message_length=8",
        )

    failure = recorder.calls[1]
    assert failure[0] == "failed"
    assert failure[1]["error_code"] == "MODEL_RATE_LIMITED"
    assert failure[1]["output_summary"] == "retryable=true"
    assert failure[1]["observation"] == LLMStepObservation(
        model_name="configured-model",
        token_usage=RunTokenUsage(),
        retry_count=2,
    )
