"""M7.6-A结构化Chat客户端、稳定错误和有限重试测试。"""

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from app.clients import (
    ChatMessage,
    ModelClientError,
    ModelErrorCode,
    OpenAICompatibleChatClient,
)
from app.settings import Settings


class DecisionOutput(BaseModel):
    """测试使用的最小严格结构化输出。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


def _settings() -> Settings:
    return Settings(
        environment="test",
        model_name="structured-test-model",
        model_base_url=AnyHttpUrl("https://models.example.test/v1"),
        model_api_key=SecretStr("test-model-secret"),
        model_timeout_seconds=1.0,
        model_max_retries=1,
        model_initial_backoff_seconds=0.01,
        model_max_backoff_seconds=0.02,
    )


def _success_response(
    *,
    content: str = '{"intent":"ORDER_STATUS","confidence":0.95}',
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test-001",
            "object": "chat.completion",
            "created": 1_788_134_400,
            "model": "structured-test-model-202608",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
        },
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_client_sends_json_schema_and_returns_validated_output_and_usage() -> None:
    requests: list[httpx.Request] = []
    clock_values = iter((10.0, 10.125))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_response()

    client = OpenAICompatibleChatClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        clock=lambda: next(clock_values),
    )
    try:
        result = await client.complete_structured(
            (ChatMessage(role="user", content="查询订单状态"),),
            DecisionOutput,
        )
    finally:
        await client.aclose()

    assert result.output == DecisionOutput(intent="ORDER_STATUS", confidence=0.95)
    assert result.model_name == "structured-test-model-202608"
    assert result.token_usage.total_tokens == 20
    assert result.duration_ms == 125
    assert result.retry_count == 0
    assert len(requests) == 1
    request = requests[0]
    assert request.url == "https://models.example.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-model-secret"
    body = json.loads(request.content)
    assert body["model"] == "structured-test-model"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unconfigured_chat_client_fails_without_creating_a_request() -> None:
    client = OpenAICompatibleChatClient(
        Settings(
            environment="test",
            model_name=None,
            model_base_url=None,
            model_api_key=None,
        )
    )

    with pytest.raises(ModelClientError) as captured:
        await client.complete_structured(
            (ChatMessage(role="user", content="query"),),
            DecisionOutput,
        )

    assert captured.value.code is ModelErrorCode.NOT_CONFIGURED
    assert captured.value.retryable is False
    assert captured.value.retry_count == 0
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transient_http_failure_retries_once_and_reports_actual_retry_count() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls == 1 else _success_response()

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    client = OpenAICompatibleChatClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
    )
    try:
        result = await client.complete_structured(
            (ChatMessage(role="user", content="query"),),
            DecisionOutput,
        )
    finally:
        await client.aclose()

    assert calls == 2
    assert delays == [0.01]
    assert result.retry_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (400, ModelErrorCode.INVALID_REQUEST, False),
        (401, ModelErrorCode.AUTHENTICATION, False),
        (418, ModelErrorCode.INVALID_RESPONSE, False),
        (429, ModelErrorCode.RATE_LIMITED, True),
    ],
)
async def test_http_failures_map_to_stable_errors_without_response_body_leakage(
    status_code: int,
    expected_code: ModelErrorCode,
    retryable: bool,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text="provider-secret-body")

    client = OpenAICompatibleChatClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )
    try:
        with pytest.raises(ModelClientError) as captured:
            await client.complete_structured(
                (ChatMessage(role="user", content="query"),),
                DecisionOutput,
            )
    finally:
        await client.aclose()

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert captured.value.retry_count == (1 if retryable else 0)
    assert calls == (2 if retryable else 1)
    assert "provider-secret-body" not in str(captured.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_is_retried_only_to_configured_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("upstream detail", request=request)

    client = OpenAICompatibleChatClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )
    try:
        with pytest.raises(ModelClientError) as captured:
            await client.complete_structured(
                (ChatMessage(role="user", content="query"),),
                DecisionOutput,
            )
    finally:
        await client.aclose()

    assert captured.value.code is ModelErrorCode.TIMEOUT
    assert captured.value.retryable is True
    assert captured.value.retry_count == 1
    assert calls == 2
    assert "upstream detail" not in str(captured.value)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_factory", "expected_code"),
    [
        (
            lambda: httpx.Response(200, json={"object": "chat.completion"}),
            ModelErrorCode.INVALID_RESPONSE,
        ),
        (lambda: _success_response(content="not-json"), ModelErrorCode.INVALID_OUTPUT),
        (
            lambda: _success_response(content='{"intent":"ORDER_STATUS","confidence":2}'),
            ModelErrorCode.INVALID_OUTPUT,
        ),
    ],
)
async def test_invalid_envelope_json_or_schema_is_not_retried(
    response_factory: Callable[[], httpx.Response],
    expected_code: ModelErrorCode,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response_factory()

    client = OpenAICompatibleChatClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )
    try:
        with pytest.raises(ModelClientError) as captured:
            await client.complete_structured(
                (ChatMessage(role="user", content="query"),),
                DecisionOutput,
            )
    finally:
        await client.aclose()

    assert captured.value.code is expected_code
    assert captured.value.retryable is False
    assert captured.value.retry_count == 0
    assert calls == 1


async def _no_sleep(_: float) -> None:
    return None
