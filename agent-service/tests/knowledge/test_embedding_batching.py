"""M4.4 Embedding批处理、有限重试和结果关联测试。"""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import pytest
from pydantic import AnyHttpUrl, SecretStr

from app.knowledge import (
    EMBEDDING_DIMENSION,
    DocumentChunk,
    EmbeddingBatchGenerator,
    EmbeddingConfig,
    EmbeddingErrorCode,
    EmbeddingIndexDescriptor,
    EmbeddingProviderError,
)


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


def _chunk(index: int) -> DocumentChunk:
    content = f"第{index}段正文"
    return DocumentChunk(
        chunk_id=f"KCH-{index:040d}",
        document_id="QUALITY-DEMO-001",
        chunk_index=index,
        section_path=("测试规范", f"章节{index}"),
        content=content,
        content_hash=f"{index:064d}",
        token_count=len(content),
    )


def _vectors(size: int, first_value: float) -> tuple[tuple[float, ...], ...]:
    return tuple(
        (first_value + index, *([0.0] * (EMBEDDING_DIMENSION - 1)))
        for index in range(size)
    )


class StubEmbeddingProvider:
    """按队列返回固定结果或异常的Provider测试替身。"""

    def __init__(
        self,
        config: EmbeddingConfig,
        responses: Sequence[tuple[tuple[float, ...], ...] | EmbeddingProviderError],
    ) -> None:
        self.descriptor = EmbeddingIndexDescriptor.from_config(config)
        self.responses = deque(responses)
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        response = self.responses.popleft()
        if isinstance(response, EmbeddingProviderError):
            raise response
        return response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generator_batches_chunks_and_preserves_chunk_identity() -> None:
    config = _config(batch_size=2, max_retries=0)
    provider = StubEmbeddingProvider(
        config,
        (_vectors(2, 1.0), _vectors(2, 3.0), _vectors(1, 5.0)),
    )
    generator = EmbeddingBatchGenerator(config, provider)

    generation = await generator.generate(tuple(_chunk(index) for index in range(5)))

    assert [len(call) for call in provider.calls] == [2, 2, 1]
    assert [item.chunk_id for item in generation.embeddings] == [
        f"KCH-{index:040d}" for index in range(5)
    ]
    assert [item.vector[0] for item in generation.embeddings] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert generation.descriptor.index_version == "demo-embedding-v1"
    assert generation.generated_at.tzinfo is UTC


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generator_retries_only_retryable_failure_with_bounded_backoff() -> None:
    config = _config(batch_size=2, max_retries=1)
    provider = StubEmbeddingProvider(
        config,
        (
            EmbeddingProviderError(
                code=EmbeddingErrorCode.RATE_LIMITED,
                message="embedding provider rate limited",
                retryable=True,
            ),
            _vectors(2, 1.0),
        ),
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    generation = await EmbeddingBatchGenerator(
        config,
        provider,
        sleep=record_sleep,
        now=lambda: datetime(2026, 8, 17, tzinfo=UTC),
    ).generate((_chunk(0), _chunk(1)))

    assert len(generation.embeddings) == 2
    assert len(provider.calls) == 2
    assert delays == [0.01]
    assert generation.generated_at == datetime(2026, 8, 17, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generator_does_not_retry_non_retryable_failure() -> None:
    config = _config(max_retries=2)
    provider = StubEmbeddingProvider(
        config,
        (
            EmbeddingProviderError(
                code=EmbeddingErrorCode.AUTHENTICATION,
                message="embedding authentication failed",
                retryable=False,
            ),
        ),
    )
    sleep: Callable[[float], Awaitable[None]]

    async def unexpected_sleep(delay: float) -> None:
        raise AssertionError("non-retryable failure must not sleep")

    sleep = unexpected_sleep
    with pytest.raises(EmbeddingProviderError) as caught:
        await EmbeddingBatchGenerator(config, provider, sleep=sleep).generate((_chunk(0),))

    assert caught.value.code is EmbeddingErrorCode.AUTHENTICATION
    assert len(provider.calls) == 1
