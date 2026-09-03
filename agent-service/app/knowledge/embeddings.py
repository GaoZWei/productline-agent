"""Embedding Provider契约、OpenAI兼容适配器和有限批量生成。"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, Protocol

import httpx
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
)

from app.knowledge.chunking import DocumentChunk
from app.schemas.knowledge import EMBEDDING_DIMENSION

if TYPE_CHECKING:
    from app.settings import Settings

logger = logging.getLogger(__name__)
_Sleep = Callable[[float], Awaitable[None]]
_Now = Callable[[], datetime]

# 错误分为可重试和不可重试
class EmbeddingErrorCode(StrEnum):
    """Embedding调用可观察但不泄露供应商响应的稳定错误码。"""

    TIMEOUT = "EMBEDDING_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "EMBEDDING_UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "EMBEDDING_RATE_LIMITED"
    AUTHENTICATION = "EMBEDDING_AUTHENTICATION_ERROR"
    INVALID_REQUEST = "EMBEDDING_INVALID_REQUEST"
    INVALID_RESPONSE = "EMBEDDING_RESPONSE_VALIDATION_ERROR"


class EmbeddingProviderError(RuntimeError):
    """Provider标准错误, 原始响应和密钥不得进入安全文案。"""

    def __init__(
        self,
        *,
        code: EmbeddingErrorCode,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code

# EmbeddingConfig 把一次Embedding索引所需的配置集中到一个不可变对象中 
class EmbeddingConfig(BaseModel):
    """一套Provider、批量、重试、维度和索引版本的不可变配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: Literal["openai_compatible"]
    model: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")]
    base_url: AnyHttpUrl
    # SecretStr用于包装API Key, 使日志和对象打印结果不会直接暴露密钥。
    api_key: Annotated[SecretStr, Field(min_length=1)]
    dimension: Literal[1536] = EMBEDDING_DIMENSION  # 表示当前系统只允许1536维向量
    batch_size: Annotated[int, Field(ge=1, le=128)] = 32
    max_retries: Annotated[int, Field(ge=0, le=3)] = 2
    initial_backoff_seconds: Annotated[float, Field(gt=0, le=10)] = 0.2
    max_backoff_seconds: Annotated[float, Field(gt=0, le=30)] = 2.0
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 30.0
    index_version: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ]

    def model_post_init(self, context: object) -> None:
        """保证指数退避上限不小于首次等待。"""

        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must not be smaller than initial backoff")

    @classmethod
    def from_settings(cls, settings: Settings) -> EmbeddingConfig:
        """从进程配置构建调用契约, 缺少密钥时在实际启用处失败。"""

        if (
            settings.embedding_api_key is None
            or not settings.embedding_api_key.get_secret_value()
        ):
            raise ValueError("EMBEDDING_API_KEY is required to enable embedding generation")
        return cls(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            dimension=settings.embedding_dimension,
            batch_size=settings.embedding_batch_size,
            max_retries=settings.embedding_max_retries,
            initial_backoff_seconds=settings.embedding_initial_backoff_seconds,
            max_backoff_seconds=settings.embedding_max_backoff_seconds,
            timeout_seconds=settings.embedding_timeout_seconds,
            index_version=settings.embedding_index_version,
        )

# 向量空间的身份 这一批向量到底由谁、用什么模型、什么维度、哪个索引版本生成
@dataclass(frozen=True, slots=True)
class EmbeddingIndexDescriptor:
    """需要随知识文档保存的当前Embedding索引身份。"""

    provider: str
    model: str
    dimension: int
    index_version: str

    @classmethod
    def from_config(cls, config: EmbeddingConfig) -> EmbeddingIndexDescriptor:
        """从同一配置生成Provider与数据库共享的索引身份。"""

        return cls(
            provider=config.provider,
            model=config.model,
            dimension=config.dimension,
            index_version=config.index_version,
        )

# 隔离具体供应商的实现细节, 只暴露必要的接口
class EmbeddingProvider(Protocol):
    """批量Embedding生成器依赖的最小异步Provider协议。"""

    descriptor: EmbeddingIndexDescriptor

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """按输入逻辑顺序返回相同数量的固定维向量。"""

        ...


class _EmbeddingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["embedding"]
    index: Annotated[int, Field(ge=0)]
    embedding: tuple[float, ...]


class _EmbeddingUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"]
    data: tuple[_EmbeddingItem, ...]
    model: Annotated[str, Field(min_length=1)]
    usage: _EmbeddingUsage


class OpenAICompatibleEmbeddingProvider:
    """调用官方Embeddings JSON契约兼容端点并严格校验向量。"""

    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.descriptor = EmbeddingIndexDescriptor.from_config(config)
        self._config = config
        # 创建共享HTTP客户端 客户端应该复用, 而不是每个批次创建一次
        self._client = httpx.AsyncClient(
            base_url=f"{str(config.base_url).rstrip('/')}/",
            headers={
                "Authorization": f"Bearer {config.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=config.timeout_seconds,
            transport=transport,
            trust_env=False,
        )

    async def aclose(self) -> None:
        """释放共享HTTP连接池。"""

        await self._client.aclose()

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """批量调用兼容端点, 按响应index恢复输入顺序。"""

        normalized_texts = tuple(texts)
        if not normalized_texts or any(not text.strip() for text in normalized_texts):
            raise ValueError("embedding input must contain non-empty text")
        try:  
            # 发送批量请求
            response = await self._client.post(
                "embeddings",
                json={
                    "input": list(normalized_texts),
                    "model": self._config.model,
                    "encoding_format": "float",
                    "dimensions": self._config.dimension,
                },
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderError(
                code=EmbeddingErrorCode.TIMEOUT,
                message="embedding provider request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise EmbeddingProviderError(
                code=EmbeddingErrorCode.UPSTREAM_UNAVAILABLE,
                message="embedding provider is unavailable",
                retryable=True,
            ) from exc

        self._raise_http_error(response)
        try:
            payload = _EmbeddingResponse.model_validate_json(response.content)
            return self._ordered_vectors(payload, expected_count=len(normalized_texts))
        except (ValidationError, ValueError) as exc:
            raise EmbeddingProviderError(
                code=EmbeddingErrorCode.INVALID_RESPONSE,
                message="embedding provider returned an invalid response",
                retryable=False,
                status_code=response.status_code,
            ) from exc

    @staticmethod
    def _raise_http_error(response: httpx.Response) -> None:
        status_code = response.status_code
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            code = EmbeddingErrorCode.AUTHENTICATION
            message = "embedding provider authentication failed"
            retryable = False
        elif status_code == 429:
            code = EmbeddingErrorCode.RATE_LIMITED
            message = "embedding provider rate limited the request"
            retryable = True
        elif status_code >= 500:
            code = EmbeddingErrorCode.UPSTREAM_UNAVAILABLE
            message = "embedding provider is unavailable"
            retryable = True
        elif status_code in {400, 404, 409, 413, 422}:
            code = EmbeddingErrorCode.INVALID_REQUEST
            message = "embedding provider rejected the request"
            retryable = False
        else:
            code = EmbeddingErrorCode.INVALID_RESPONSE
            message = "embedding provider returned an unexpected status"
            retryable = False
        raise EmbeddingProviderError(
            code=code,
            message=message,
            retryable=retryable,
            status_code=status_code,
        )
    # 根据index重新排序向量, 确保与输入顺序一致
    def _ordered_vectors(
        self,
        payload: _EmbeddingResponse,
        *,
        expected_count: int,
    ) -> tuple[tuple[float, ...], ...]:
        items_by_index = {item.index: item for item in payload.data}
        if len(payload.data) != expected_count or set(items_by_index) != set(range(expected_count)):
            raise ValueError("embedding response indices do not match inputs")
        vectors = tuple(items_by_index[index].embedding for index in range(expected_count))
        _validate_vectors(vectors, dimension=self._config.dimension, expected_count=expected_count)
        return vectors


@dataclass(frozen=True, slots=True)
class ChunkEmbedding:
    """一个稳定Chunk ID及其校验后的向量。"""

    chunk_id: str
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingGeneration:
    """一次完整批量生成的索引身份、时间和全部Chunk向量。"""

    descriptor: EmbeddingIndexDescriptor
    generated_at: datetime
    embeddings: tuple[ChunkEmbedding, ...]

# 不是单独保存一个向量, 而是查询向量和生成它的索引身份
@dataclass(frozen=True, slots=True)
class QueryEmbedding:
    """与文档索引身份一致的一次查询向量。"""

    descriptor: EmbeddingIndexDescriptor
    vector: tuple[float, ...]


# Embedding 批处理和有限重试机制 不会边生成边写库，而是先收集并校验所有批次的结果，只有所有批次都成功，结果才会交给 Repository
class EmbeddingBatchGenerator:
    """按配置分批生成全部Chunk向量, 只有限重试明确瞬时错误。"""

    def __init__(
        self,
        config: EmbeddingConfig,
        provider: EmbeddingProvider,
        *,
        sleep: _Sleep = asyncio.sleep,
        now: _Now | None = None,
    ) -> None:
        descriptor = EmbeddingIndexDescriptor.from_config(config)
        if provider.descriptor != descriptor:
            raise ValueError("embedding provider descriptor does not match config")
        self._config = config
        self._provider = provider
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    async def generate(self, chunks: Sequence[DocumentChunk]) -> EmbeddingGeneration:
        """先在内存生成全部向量, 不产生数据库部分写入。"""

        normalized_chunks = tuple(chunks)
        if not normalized_chunks:
            raise ValueError("at least one document chunk is required")
        chunk_ids = [chunk.chunk_id for chunk in normalized_chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("embedding chunks contain duplicate chunk_id")

        embeddings: list[ChunkEmbedding] = []
        # 分批处理, 每个批次大小为_batch_size
        for batch_number, start in enumerate(
            range(0, len(normalized_chunks), self._config.batch_size),
            start=1,
        ):
            batch = normalized_chunks[start : start + self._config.batch_size]
            vectors = await self._embed_with_retry(
                tuple(chunk.content for chunk in batch),
                batch_number=batch_number,
            )
            _validate_vectors(
                vectors,
                dimension=self._config.dimension,
                expected_count=len(batch),
            )
            # 返回结果不是单纯的向量列表, Chunk和向量绑定起来
            embeddings.extend(
                ChunkEmbedding(chunk_id=chunk.chunk_id, vector=vector)
                for chunk, vector in zip(batch, vectors, strict=True)
            )

        generated_at = self._now()
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("embedding generation time must be timezone-aware")
        # 先把全部结果收集到内存, 确保全部向量生成完成后才返回结果
        return EmbeddingGeneration(
            descriptor=self._provider.descriptor,
            generated_at=generated_at,
            embeddings=tuple(embeddings),
        )

    async def generate_query(self, query: str) -> QueryEmbedding:
        """复用同一Provider和重试策略生成单条检索Query向量。"""
        # 1.清理和限制输入长度
        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 8000:
            raise ValueError("embedding query must contain 1 to 8000 characters")
        # 2.复用文档Embedding策略生成查询向量
        vectors = await self._embed_with_retry((normalized_query,), batch_number=1)
        # 3. 校验结果
        _validate_vectors(vectors, dimension=self._config.dimension, expected_count=1)
        # 4. 返回完整索引身份
        return QueryEmbedding(
            descriptor=self._provider.descriptor,
            vector=vectors[0],
        )

    async def _embed_with_retry(
        self,
        texts: tuple[str, ...],
        *,
        batch_number: int,
    ) -> tuple[tuple[float, ...], ...]:
        retries_completed = 0
        while True:
            try:
                return await self._provider.embed(texts)
            except EmbeddingProviderError as exc:
                if not exc.retryable or retries_completed >= self._config.max_retries:
                    raise
                retries_completed += 1
                # 指数退避策略
                delay = min(
                    self._config.initial_backoff_seconds
                    * (2 ** (retries_completed - 1)),
                    self._config.max_backoff_seconds,
                )
                logger.warning(
                    "embedding_retry_scheduled",
                    extra={
                        "embedding_provider": self._provider.descriptor.provider,
                        "embedding_model": self._provider.descriptor.model,
                        "index_version": self._provider.descriptor.index_version,
                        "batch_number": batch_number,
                        "retry_number": retries_completed,
                        "retry_delay_ms": round(delay * 1000, 3),
                        "error_code": exc.code.value,
                    },
                )
                await self._sleep(delay)


def _validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    dimension: int,
    expected_count: int,
) -> None:
    """拒绝数量、维度或有限性不符合索引契约的向量。"""

    if len(vectors) != expected_count:
        raise ValueError("embedding vector count does not match inputs")
    for vector in vectors:
        if (
            len(vector) != dimension
            or any(not math.isfinite(value) for value in vector)
            or not any(value != 0.0 for value in vector)
        ):
            raise ValueError(
                "embedding vector has invalid dimension, non-finite value, or zero norm"
            )
