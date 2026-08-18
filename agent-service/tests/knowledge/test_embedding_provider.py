"""M4.4 Embedding配置和OpenAI兼容HTTP Provider契约测试。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr, ValidationError

from app.knowledge import (
    EMBEDDING_DIMENSION,
    EmbeddingConfig,
    EmbeddingErrorCode,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingProvider,
)
from app.settings import Settings


def _config(**updates: object) -> EmbeddingConfig:
    values: dict[str, object] = {
        "provider": "openai_compatible",
        "model": "text-embedding-3-small",
        "base_url": AnyHttpUrl("https://embedding.example/v1"),
        "api_key": SecretStr("embedding-secret"),
        "dimension": EMBEDDING_DIMENSION,
        "batch_size": 2,
        "max_retries": 1,
        "initial_backoff_seconds": 0.01,
        "max_backoff_seconds": 0.1,
        "timeout_seconds": 2.0,
        "index_version": "demo-embedding-v1",
    }
    values.update(updates)
    return EmbeddingConfig.model_validate(values)


def _vector(first_value: float) -> list[float]:
    return [first_value, *([0.0] * (EMBEDDING_DIMENSION - 1))]


@asynccontextmanager
async def _provider(
    handler: httpx.AsyncBaseTransport,
    *,
    config: EmbeddingConfig | None = None,
) -> AsyncIterator[OpenAICompatibleEmbeddingProvider]:
    provider = OpenAICompatibleEmbeddingProvider(config or _config(), transport=handler)
    try:
        yield provider
    finally:
        await provider.aclose()


@pytest.mark.unit
def test_embedding_config_rejects_missing_key_and_wrong_dimension() -> None:
    with pytest.raises(ValidationError):
        _config(api_key=SecretStr(""))
    with pytest.raises(ValidationError):
        _config(dimension=3)
    with pytest.raises(ValidationError):
        _config(index_version="contains spaces")


@pytest.mark.unit
def test_embedding_config_is_built_from_settings_without_exposing_secret() -> None:
    settings = Settings(
        environment="test",
        embedding_api_key=SecretStr("settings-secret"),
        embedding_batch_size=16,
        embedding_index_version="settings-v1",
    )

    config = EmbeddingConfig.from_settings(settings)

    assert config.batch_size == 16
    assert config.index_version == "settings-v1"
    assert "settings-secret" not in repr(config)
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY"):
        EmbeddingConfig.from_settings(
            Settings(environment="test", embedding_api_key=None)
        )
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY"):
        EmbeddingConfig.from_settings(
            Settings(environment="test", embedding_api_key=SecretStr(""))
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provider_sends_official_batch_contract_and_reorders_indices() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": _vector(2.0)},
                    {"object": "embedding", "index": 0, "embedding": _vector(1.0)},
                ],
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )

    async with _provider(httpx.MockTransport(handler)) as provider:
        vectors = await provider.embed(("第一段", "第二段"))

    assert captured_request is not None
    assert captured_request.url.path == "/v1/embeddings"
    assert captured_request.headers["Authorization"] == "Bearer embedding-secret"
    assert json.loads(captured_request.content) == {
        "input": ["第一段", "第二段"],
        "model": "text-embedding-3-small",
        "encoding_format": "float",
        "dimensions": EMBEDDING_DIMENSION,
    }
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, EmbeddingErrorCode.AUTHENTICATION, False),
        (429, EmbeddingErrorCode.RATE_LIMITED, True),
        (503, EmbeddingErrorCode.UPSTREAM_UNAVAILABLE, True),
    ],
)
async def test_provider_maps_http_failures_without_leaking_response(
    status_code: int,
    expected_code: EmbeddingErrorCode,
    retryable: bool,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"secret": "provider detail"})

    async with _provider(httpx.MockTransport(handler)) as provider:
        with pytest.raises(EmbeddingProviderError) as caught:
            await provider.embed(("正文",))

    assert caught.value.code is expected_code
    assert caught.value.retryable is retryable
    assert "provider detail" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provider_rejects_invalid_vector_dimension() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    async with _provider(httpx.MockTransport(handler)) as provider:
        with pytest.raises(EmbeddingProviderError) as caught:
            await provider.embed(("正文",))

    assert caught.value.code is EmbeddingErrorCode.INVALID_RESPONSE
    assert caught.value.retryable is False
