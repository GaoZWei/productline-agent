"""PostgreSQL全文检索和pgvector余弦检索。"""

from __future__ import annotations

import math

from sqlalchemy import Float, desc, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import (
    EMBEDDING_DIMENSION,
    KeywordSearchHit,
    QueryEmbedding,
    VectorSearchHit,
    preprocess_keyword_query,
)
from app.models import KnowledgeChunk, KnowledgeDocument


class KnowledgeSearchValidationError(ValueError):
    """检索数量、阈值或Query Embedding不满足查询契约。"""


class KnowledgeSearchRepository:
    """在Agent自有知识表上执行确定性关键词和向量检索。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_keywords(
        self,
        query: str,
        *,
        top_k: int = 10,
    ) -> tuple[KeywordSearchHit, ...]:
        """使用中文双字预处理、GIN全文匹配和cover-density分数检索Chunk。"""
        # 第一步：校验TopK 1～100
        self._validate_top_k(top_k)
        # 第二步：查询预处理
        keyword_query = preprocess_keyword_query(query)
        # 第三步：构造安全tsquery 使用plainto_tsquery，它把输入当普通文本处理
        ts_query = func.plainto_tsquery(
            literal_column("'simple'::regconfig"),
            keyword_query.search_text,
        )
        # 第四步：计算关键词分数
        score = func.ts_rank_cd(KnowledgeChunk.search_vector, ts_query, 32).label(
            "keyword_score"
        )
        
        statement = (
            select(KnowledgeChunk, score)
            .where(KnowledgeChunk.search_vector.op("@@")(ts_query))  # 第五步：全文匹配
            .order_by(desc(score), KnowledgeChunk.chunk_id)  # 第六步：排序和TopK
            .limit(top_k)
        )
        rows = (await self._session.execute(statement)).all()
        # 第七步：返回结果
        return tuple( 
            KeywordSearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                section_path=tuple(chunk.section_path),
                content=chunk.content,
                content_hash=chunk.content_hash,
                keyword_score=float(keyword_score),
            )
            for chunk, keyword_score in rows
        )
    # 向量检索
    async def search_vectors(
        self,
        query_embedding: QueryEmbedding,
        *,
        top_k: int = 10,
        min_similarity: float = -1.0,
    ) -> tuple[VectorSearchHit, ...]:
        """仅在相同索引身份内按余弦相似度、阈值和TopK检索Chunk。"""
        # 第一步：校验输入
        self._validate_top_k(top_k)
        self._validate_query_embedding(query_embedding)
        if not math.isfinite(min_similarity) or not -1.0 <= min_similarity <= 1.0:
            raise KnowledgeSearchValidationError("min_similarity must be between -1 and 1")
        # 第二步：构造余弦距离
        distance = KnowledgeChunk.embedding.op("<=>", return_type=Float)(
            list(query_embedding.vector)
        )
        # 第三步：转换成相似度
        score = (1.0 - distance).label("vector_score")
        descriptor = query_embedding.descriptor
        statement = (
            select(KnowledgeChunk, score)
            .join(KnowledgeDocument, KnowledgeDocument.document_id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.embedding.is_not(None), # 四项全部一致，文档才参与比较
                KnowledgeDocument.embedding_provider == descriptor.provider,
                KnowledgeDocument.embedding_model == descriptor.model,
                KnowledgeDocument.embedding_dimension == descriptor.dimension,
                KnowledgeDocument.index_version == descriptor.index_version,
                distance <= 1.0 - min_similarity, # 过滤出相似度大于阈值的文档
            )
            .order_by(distance, KnowledgeChunk.chunk_id)
            .limit(top_k)
        )
        rows = (await self._session.execute(statement)).all()
        # 第四步：返回结果
        return tuple(
            VectorSearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                section_path=tuple(chunk.section_path),
                content=chunk.content,
                content_hash=chunk.content_hash,
                vector_score=float(vector_score),
            )
            for chunk, vector_score in rows
        )

    @staticmethod
    def _validate_top_k(top_k: int) -> None:
        if isinstance(top_k, bool) or not 1 <= top_k <= 100:
            raise KnowledgeSearchValidationError("top_k must be between 1 and 100")

    @staticmethod
    def _validate_query_embedding(query_embedding: QueryEmbedding) -> None:
        descriptor = query_embedding.descriptor
        if (
            descriptor.dimension != EMBEDDING_DIMENSION
            or not descriptor.provider
            or not descriptor.model
            or not descriptor.index_version
            or len(query_embedding.vector) != EMBEDDING_DIMENSION
            or any(not math.isfinite(value) for value in query_embedding.vector)
            or not any(value != 0.0 for value in query_embedding.vector)
        ):
            raise KnowledgeSearchValidationError("query embedding does not match index schema")
