"""把Query Embedding、关键词/向量召回和RRF组合为统一检索入口。"""

from __future__ import annotations

import math
from collections.abc import Awaitable
from typing import Protocol

from app.knowledge.embeddings import QueryEmbedding
from app.knowledge.hybrid import RetrievalResult, fuse_hybrid_results
from app.knowledge.search import KeywordSearchHit, VectorSearchHit
from app.schemas.knowledge import KnowledgeSearchFilter


class QueryEmbeddingGenerator(Protocol):
    """规范问答只依赖生成单条Query向量的最小接口。"""

    def generate_query(self, query: str) -> Awaitable[QueryEmbedding]:
        """在与知识Chunk相同的索引空间生成查询向量。"""


class KnowledgeSearchChannels(Protocol):
    """关键词和向量Repository必须共享同一元数据过滤契约。"""

    def search_keywords(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
    ) -> Awaitable[tuple[KeywordSearchHit, ...]]:
        """返回已按关键词相关度排序的候选。"""

    def search_vectors(
        self,
        query_embedding: QueryEmbedding,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
        min_similarity: float = -1.0,
    ) -> Awaitable[tuple[VectorSearchHit, ...]]:
        """返回已按余弦相似度排序的候选。"""


class KnowledgeRetriever(Protocol):
    """Workflow依赖的完整混合检索接口。"""

    def retrieve(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
    ) -> Awaitable[tuple[RetrievalResult, ...]]:
        """使用同一过滤条件执行双路召回与确定性融合。"""

# 统一检索入口 （把关键词检索、向量检索和RRF融合封装成一个统一的“混合检索入口”）
# 只负责把用户问题转换成一批稳定、经过元数据过滤的RetrievalResult候选
class KnowledgeRetrievalPipeline:
    """串联Query Embedding、两路安全召回和M4.8 RRF融合。"""

    def __init__(
        self,
        *,
        repository: KnowledgeSearchChannels,
        embedding_generator: QueryEmbeddingGenerator,
        channel_top_k: int = 20,  # 每条检索通道最多返回多少候选
        hybrid_top_k: int = 10,  # RRF融合后最多保留多少条候选
        min_vector_similarity: float = -1.0, 
    ) -> None:
        _validate_top_k("channel_top_k", channel_top_k)
        _validate_top_k("hybrid_top_k", hybrid_top_k)
        if (
            not math.isfinite(min_vector_similarity)
            or not -1.0 <= min_vector_similarity <= 1.0
        ):
            raise ValueError("min_vector_similarity must be between -1 and 1")
        self._repository = repository
        self._embedding_generator = embedding_generator
        self._channel_top_k = channel_top_k
        self._hybrid_top_k = hybrid_top_k
        self._min_vector_similarity = min_vector_similarity

    async def retrieve(
        self,
        query: str,  # 经过规范化的检索问题
        *,
        filters: KnowledgeSearchFilter,  # 元数据过滤器(统一的元数据过滤条件)
    ) -> tuple[RetrievalResult, ...]:
        """对两条通道复用同一过滤器, 并返回带文档身份的混合结果。"""
        # 从关键词通道召回
        keyword_hits = await self._repository.search_keywords(
            query,
            filters=filters,
            top_k=self._channel_top_k,
        )
        # 生成Query Embedding 把自然语言查询转换成向量
        query_embedding = await self._embedding_generator.generate_query(query)
        # 从向量通道召回
        vector_hits = await self._repository.search_vectors(
            query_embedding,
            filters=filters,
            top_k=self._channel_top_k,
            min_similarity=self._min_vector_similarity,
        )
        # 融合结果
        return fuse_hybrid_results(
            keyword_hits,
            vector_hits,
            top_k=self._hybrid_top_k,
        )


def _validate_top_k(name: str, value: int) -> None:
    if isinstance(value, bool) or not 1 <= value <= 100:
        raise ValueError(f"{name} must be between 1 and 100")
