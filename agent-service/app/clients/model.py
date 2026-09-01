"""OpenAI兼容结构化对话模型的HTTP、错误、重试和用量契约。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.run_observability import RunTokenUsage
from app.settings import Settings

logger = logging.getLogger(__name__)

OutputT = TypeVar("OutputT", bound=BaseModel)
_Sleep = Callable[[float], Awaitable[None]]
_Clock = Callable[[], float]

# 错误定义
class ModelErrorCode(StrEnum):
    """不暴露供应商正文的稳定模型错误码。"""

    NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
    TIMEOUT = "MODEL_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "MODEL_UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "MODEL_RATE_LIMITED"
    AUTHENTICATION = "MODEL_AUTHENTICATION_ERROR"
    INVALID_REQUEST = "MODEL_INVALID_REQUEST"
    INVALID_RESPONSE = "MODEL_RESPONSE_VALIDATION_ERROR"
    INVALID_OUTPUT = "MODEL_OUTPUT_VALIDATION_ERROR"


class ModelClientError(RuntimeError):
    """模型调用的安全错误, 原始响应、请求正文和密钥不得进入异常文案。"""

    def __init__(
        self,
        *,
        code: ModelErrorCode,
        message: str,
        retryable: bool,
        retry_count: int = 0,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_count = retry_count
        self.status_code = status_code

    def after_retries(self, retry_count: int) -> ModelClientError:
        """返回带实际重试次数的同类安全错误。"""

        return ModelClientError(
            code=self.code,
            message=str(self),
            retryable=self.retryable,
            retry_count=retry_count,
            status_code=self.status_code,
        )


class ChatMessage(BaseModel):
    """一次Chat Completions请求中的最小文本消息。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: Literal["system", "user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=100_000)]


@dataclass(frozen=True, slots=True)
class StructuredModelResult[OutputT]:
    """已通过目标Schema校验的输出及本次调用观测数据。"""

    output: OutputT
    model_name: str
    token_usage: RunTokenUsage
    duration_ms: int
    retry_count: int


class _ChatResponseMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    role: Literal["assistant"]
    content: Annotated[str, Field(min_length=1)]


class _ChatChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    index: Literal[0]
    message: _ChatResponseMessage
    finish_reason: Annotated[str, Field(min_length=1)]


class _ChatUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    prompt_tokens: Annotated[int, Field(ge=0, le=2_147_483_647)]
    completion_tokens: Annotated[int, Field(ge=0, le=2_147_483_647)]
    total_tokens: Annotated[int, Field(ge=0, le=2_147_483_647)]

    @model_validator(mode="after")
    def require_exact_total(self) -> _ChatUsage:
        """拒绝互相矛盾的供应商Token统计。"""

        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("total_tokens must equal prompt_tokens plus completion_tokens")
        return self


class _ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: Annotated[str, Field(min_length=1)]
    object: Literal["chat.completion"]
    created: Annotated[int, Field(ge=0)]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    choices: Annotated[tuple[_ChatChoice, ...], Field(min_length=1, max_length=1)]
    usage: _ChatUsage


class OpenAICompatibleChatClient:
    """共享连接池调用Chat Completions, 并只有限重试明确瞬时失败。"""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: _Sleep = asyncio.sleep,
        clock: _Clock = time.monotonic,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._clock = clock
        self._client: httpx.AsyncClient | None = None
        if settings.model_configured:
            assert settings.model_base_url is not None
            headers = {"Content-Type": "application/json"}
            if settings.model_api_key is not None:
                headers["Authorization"] = f"Bearer {settings.model_api_key.get_secret_value()}"
            self._client = httpx.AsyncClient(
                base_url=f"{str(settings.model_base_url).rstrip('/')}/",
                headers=headers,
                timeout=settings.model_timeout_seconds,
                transport=transport,
                trust_env=False,
            )

    @property
    def model_name(self) -> str | None:
        """返回请求使用的配置模型名, 未配置时明确返回空。"""

        return self._settings.model_name

    async def aclose(self) -> None:
        """释放已启用客户端的共享连接池。"""

        if self._client is not None:
            await self._client.aclose()

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        """请求严格JSON Schema输出, 并返回校验结果与实际调用指标。"""
        # 检查模型是否已配置
        if self._client is None or self._settings.model_name is None:
            raise ModelClientError(
                code=ModelErrorCode.NOT_CONFIGURED,
                message="structured model is not configured",
                retryable=False,
            )
        normalized_messages = tuple(messages)
        if not normalized_messages:
            raise ValueError("at least one chat message is required")
        if not issubclass(output_schema, BaseModel):
            raise TypeError("output_schema must be a Pydantic BaseModel type")
        # 请求体构建
        request_body = {
            "model": self._settings.model_name,
            "messages": [message.model_dump(mode="json") for message in normalized_messages],
            "temperature": self._settings.model_temperature,
            "max_tokens": self._settings.model_max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_schema.__name__,
                    "strict": True,
                    "schema": output_schema.model_json_schema(),
                },
            },
        }
        started_at = self._clock()
        retry_count = 0
        while True:
            try:
                # 调用 /chat/completions 
                response = await self._client.post("chat/completions", json=request_body)
                # 校验HTTP响应外壳是否符合预期
                payload = self._parse_response(response)
                output = self._parse_output(payload, output_schema)
                duration_ms = max(0, int((self._clock() - started_at) * 1000))
                # 返回模型名、Token、耗时和重试次数
                return StructuredModelResult(
                    output=output,
                    model_name=payload.model,
                    token_usage=RunTokenUsage.from_counts(
                        input_tokens=payload.usage.prompt_tokens,
                        output_tokens=payload.usage.completion_tokens,
                    ),
                    duration_ms=duration_ms,
                    retry_count=retry_count,
                )
            # 只对超时、限流、5xx等瞬时错误有限重试
            except ModelClientError as exc:
                if not exc.retryable or retry_count >= self._settings.model_max_retries:
                    raise exc.after_retries(retry_count) from exc
                retry_count += 1
                delay = min(
                    self._settings.model_initial_backoff_seconds * (2 ** (retry_count - 1)),
                    self._settings.model_max_backoff_seconds,
                )
                logger.warning(
                    "model_retry_scheduled",
                    extra={
                        "model_provider": self._settings.model_provider,
                        "model_name": self._settings.model_name,
                        "retry_number": retry_count,
                        "retry_delay_ms": round(delay * 1000, 3),
                        "error_code": exc.code.value,
                    },
                )
                await self._sleep(delay)
            except httpx.TimeoutException as exc:
                error = ModelClientError(
                    code=ModelErrorCode.TIMEOUT,
                    message="structured model request timed out",
                    retryable=True,
                )
                if retry_count >= self._settings.model_max_retries:
                    raise error.after_retries(retry_count) from exc
                retry_count = await self._wait_before_retry(retry_count, error)
            except httpx.RequestError as exc:
                error = ModelClientError(
                    code=ModelErrorCode.UPSTREAM_UNAVAILABLE,
                    message="structured model provider is unavailable",
                    retryable=True,
                )
                if retry_count >= self._settings.model_max_retries:
                    raise error.after_retries(retry_count) from exc
                retry_count = await self._wait_before_retry(retry_count, error)

    async def _wait_before_retry(
        self,
        retry_count: int,
        error: ModelClientError,
    ) -> int:
        """为网络类瞬时错误执行同一套有限退避并返回新计数。"""

        next_retry_count = retry_count + 1
        delay = min(
            self._settings.model_initial_backoff_seconds * (2 ** (next_retry_count - 1)),
            self._settings.model_max_backoff_seconds,
        )
        logger.warning(
            "model_retry_scheduled",
            extra={
                "model_provider": self._settings.model_provider,
                "model_name": self._settings.model_name,
                "retry_number": next_retry_count,
                "retry_delay_ms": round(delay * 1000, 3),
                "error_code": error.code.value,
            },
        )
        await self._sleep(delay)
        return next_retry_count
    # 校验 Chat Completions 外壳是否符合预期
    @staticmethod
    def _parse_response(response: httpx.Response) -> _ChatCompletionResponse:
        """先映射HTTP失败, 再严格验证成功响应的必要外壳。"""

        OpenAICompatibleChatClient._raise_http_error(response)
        try:
            return _ChatCompletionResponse.model_validate_json(response.content)
        except ValidationError as exc:
            raise ModelClientError(
                code=ModelErrorCode.INVALID_RESPONSE,
                message="structured model provider returned an invalid response",
                retryable=False,
                status_code=response.status_code,
            ) from exc

    @staticmethod
    def _parse_output(
        payload: _ChatCompletionResponse,
        output_schema: type[OutputT],
    ) -> OutputT:
        """只接受选择零中的纯JSON正文, 并按调用方Schema校验。"""

        try:
            # 把模型正文交给业务 Schema 校验
            return output_schema.model_validate_json(payload.choices[0].message.content)
        except ValidationError as exc:
            raise ModelClientError(
                code=ModelErrorCode.INVALID_OUTPUT,
                message="structured model output failed schema validation",
                retryable=False,
            ) from exc

    @staticmethod
    def _raise_http_error(response: httpx.Response) -> None:
        status_code = response.status_code
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            code = ModelErrorCode.AUTHENTICATION
            message = "structured model provider authentication failed"
            retryable = False
        elif status_code == 429:
            code = ModelErrorCode.RATE_LIMITED
            message = "structured model provider rate limited the request"
            retryable = True
        elif status_code in {408, 425} or status_code >= 500:
            code = ModelErrorCode.UPSTREAM_UNAVAILABLE
            message = "structured model provider is unavailable"
            retryable = True
        elif status_code in {400, 404, 409, 413, 422}:
            code = ModelErrorCode.INVALID_REQUEST
            message = "structured model provider rejected the request"
            retryable = False
        else:
            code = ModelErrorCode.INVALID_RESPONSE
            message = "structured model provider returned an unexpected status"
            retryable = False
        raise ModelClientError(
            code=code,
            message=message,
            retryable=retryable,
            status_code=status_code,
        )
