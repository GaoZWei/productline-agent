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


class FixedFailureClient:
    """为故障矩阵返回指定模型错误并保留实际重试次数。"""

    model_name = "configured-model"

    def __init__(self, error: ModelClientError) -> None:
        self.error = error

    async def complete_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        del messages, output_schema
        raise self.error


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


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "retryable", "retry_count"),
    [
        (ModelErrorCode.TIMEOUT, True, 1),
        (ModelErrorCode.INVALID_OUTPUT, False, 0),
        (ModelErrorCode.INVALID_RESPONSE, False, 0),
    ],
)
async def test_model_protocol_failures_leave_a_stable_failed_llm_step(
    error_code: ModelErrorCode,
    retryable: bool,
    retry_count: int,
) -> None:
    recorder = RecordingStepRecorder()
    invoker = ObservedModelInvoker(
        FixedFailureClient(
            ModelClientError(
                code=error_code,
                message="safe structured model failure",
                retryable=retryable,
                retry_count=retry_count,
            )
        ),
        recorder,
    )

    with pytest.raises(ModelClientError) as caught:
        await invoker.complete_structured(
            (ChatMessage(role="user", content="question"),),
            StructuredAnswer,
            step_id="step-m77-model-failure",
            run_id="run-m77-model-failure",
            sequence_number=1,
            step_name="route_intent",
            input_summary="message_length=8",
        )

    assert caught.value.code is error_code
    assert recorder.calls[0][0] == "start"
    assert recorder.calls[1] == (
        "failed",
        {
            "step_id": "step-m77-model-failure",
            "error_code": error_code.value,
            "output_summary": f"retryable={str(retryable).lower()}",
            "observation": LLMStepObservation(
                model_name="configured-model",
                token_usage=RunTokenUsage(),
                retry_count=retry_count,
            ),
        },
    )
