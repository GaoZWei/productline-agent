"""将结构化模型调用与LLM Step持久观测连接起来。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.clients.model import (
    ChatMessage,
    ModelClientError,
    StructuredModelResult,
)
from app.models import AgentStepType
from app.schemas.run_observability import LLMStepObservation, RunTokenUsage

OutputT = TypeVar("OutputT", bound=BaseModel)


class StructuredChatClient(Protocol):
    """观测层依赖的最小结构化模型客户端边界。"""

    @property
    def model_name(self) -> str | None:
        """返回配置的请求模型名。"""

        ...

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        """返回已校验输出和本次调用指标。"""

        ...


class ModelStepRecorder(Protocol):
    """模型调用所需的LLM Step记录能力。"""

    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None,
    ) -> None:
        """在HTTP调用前创建LLM Step。"""

        ...

    async def mark_llm_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
        observation: LLMStepObservation,
    ) -> None:
        """保存成功终态和调用指标。"""

        ...

    async def mark_llm_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
        observation: LLMStepObservation | None,
    ) -> None:
        """保存失败终态和实际可得调用指标。"""

        ...

# LLM Step 观测包装器 把 HTTP Client 和 Step 生命周期连接起来
class ObservedModelInvoker:
    """执行一次结构化模型请求并把安全指标写入对应LLM Step。"""

    def __init__(self, client: StructuredChatClient, recorder: ModelStepRecorder) -> None:
        self._client = client
        self._recorder = recorder

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_name: str,
        input_summary: str | None,
    ) -> StructuredModelResult[OutputT]:
        """不保存Prompt或模型正文, 只保存调用方白名单摘要和独立指标。"""

        if not messages:
            raise ValueError("at least one chat message is required")
        # 调用开始前创建 Step
        await self._recorder.start_step(
            step_id=step_id,
            run_id=run_id,
            sequence_number=sequence_number,
            step_type=AgentStepType.LLM,
            step_name=step_name,
            input_summary=input_summary,
        )
        try:
            result = await self._client.complete_structured(messages, output_schema)
        except ModelClientError as exc:
            # 模型失败
            observation = (
                LLMStepObservation(
                    model_name=self._client.model_name,
                    token_usage=RunTokenUsage(),
                    retry_count=exc.retry_count,
                )
                if self._client.model_name is not None
                else None
            )
            await self._recorder.mark_llm_failed(
                step_id,
                error_code=exc.code.value,
                output_summary=f"retryable={str(exc.retryable).lower()}",
                observation=observation,
            )
            raise
        # 模型成功后构造观测
        observation = LLMStepObservation(
            model_name=result.model_name,
            token_usage=result.token_usage,
            retry_count=result.retry_count,
        )
        # 通过 mark_llm_succeeded() 保存指标
        await self._recorder.mark_llm_succeeded(
            step_id,
            output_summary="structured_output=validated",
            observation=observation,
        )
        return result
