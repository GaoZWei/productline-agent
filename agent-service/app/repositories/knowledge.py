"""知识文档、分块和Embedding当前索引的异步持久化。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import EmbeddingGeneration, ProcessedDocument, build_search_document
from app.models import KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import EMBEDDING_DIMENSION, DocumentLifecycle


class KnowledgeIndexValidationError(ValueError):
    """处理结果、向量或索引身份不满足原子入库契约。"""


@dataclass(frozen=True, slots=True)
class StoredKnowledgeDocumentIndex:
    """一份已存文档的Chunk数量和可空索引身份。"""

    document_id: str
    chunk_count: int
    embedding_provider: str | None
    embedding_model: str | None
    embedding_dimension: int | None
    index_version: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeIndexState:
    """能力检查所需的全部文档级索引状态。"""

    documents: tuple[StoredKnowledgeDocumentIndex, ...]

    @property
    def chunk_count(self) -> int:
        """汇总当前数据库中的Chunk数量。"""

        return sum(document.chunk_count for document in self.documents)


# 把“本次处理得到的文档、Chunk和Embedding”完整同步到数据库, 旧索引存在时进行整体替换
class KnowledgeIndexRepository:
    """不隐式提交事务的知识索引查询和全量文档替换。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_content_hash_owners(self) -> dict[str, str]:
        """返回供Loader在模型调用前去重的内容哈希与文档ID。"""

        rows = await self._session.execute(
            select(KnowledgeDocument.content_hash, KnowledgeDocument.document_id)
        )
        return {content_hash: document_id for content_hash, document_id in rows}
    # 删除已经不在当前 catalog.json 中的旧文档
    async def prune_documents_not_in(self, document_ids: Sequence[str]) -> int:
        """全量目录入库时删除不再属于目录的文档, 由同一事务保证可回滚。"""

        normalized_ids = tuple(document_ids)
        if not normalized_ids or len(normalized_ids) != len(set(normalized_ids)):
            raise KnowledgeIndexValidationError("catalog document ids must be non-empty and unique")
        removed_count = await self._session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.document_id.not_in(normalized_ids))
        )
        await self._session.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.document_id.not_in(normalized_ids))
        )
        await self._session.flush()
        return int(removed_count or 0)

    async def get_index_state(self) -> KnowledgeIndexState:
        """按文档返回Chunk数量和索引身份, 不读取正文或向量。"""

        rows = (
            await self._session.execute(
                select(
                    KnowledgeDocument.document_id,
                    func.count(KnowledgeChunk.chunk_id),
                    KnowledgeDocument.embedding_provider,
                    KnowledgeDocument.embedding_model,
                    KnowledgeDocument.embedding_dimension,
                    KnowledgeDocument.index_version,
                )
                .outerjoin(
                    KnowledgeChunk,
                    KnowledgeChunk.document_id == KnowledgeDocument.document_id,
                )
                .group_by(
                    KnowledgeDocument.document_id,
                    KnowledgeDocument.embedding_provider,
                    KnowledgeDocument.embedding_model,
                    KnowledgeDocument.embedding_dimension,
                    KnowledgeDocument.index_version,
                )
                .order_by(KnowledgeDocument.document_id)
            )
        ).all()
        return KnowledgeIndexState(
            documents=tuple(
                StoredKnowledgeDocumentIndex(
                    document_id=document_id,
                    chunk_count=chunk_count,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    embedding_dimension=embedding_dimension,
                    index_version=index_version,
                )
                for (
                    document_id,
                    chunk_count,
                    embedding_provider,
                    embedding_model,
                    embedding_dimension,
                    index_version,
                ) in rows
            )
        )

    # 核心重新索引算法
    async def reindex_documents(
        self,
        documents: Sequence[ProcessedDocument],
        generation: EmbeddingGeneration,
    ) -> tuple[KnowledgeDocument, ...]:
        """替换目标文档全部Chunk并保存同一索引版本, 事务由调用方提交。"""

        normalized_documents = tuple(documents)
        # 第一步: 完整校验输入参数
        embeddings_by_id = self._validate_reindex_input(normalized_documents, generation)
        # 第二步: 先保存ACTIVE文档
        documents_by_lifecycle = sorted(
            normalized_documents,
            key=lambda item: item.metadata.lifecycle is DocumentLifecycle.HISTORICAL,
        )
        stored_by_id: dict[str, KnowledgeDocument] = {}
        for processed in documents_by_lifecycle:
            stored = await self._session.get(
                KnowledgeDocument,
                processed.metadata.document_id,
            )
            if stored is None:
                stored = KnowledgeDocument(document_id=processed.metadata.document_id)
                self._session.add(stored)
            # 第三步: 写文档信息和索引身份
            self._apply_document_fields(stored, processed, generation)
            stored_by_id[stored.document_id] = stored
            if processed.metadata.lifecycle is DocumentLifecycle.ACTIVE:
                await self._session.flush()

        document_ids = tuple(stored_by_id)
        # 第四步: 删除目标文档的全部旧Chunk
        await self._session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(document_ids))
        )
        await self._session.flush()
        for processed in normalized_documents:
            for chunk in processed.chunks:
                self._session.add(
                    # 第五步: 插入新Chunk和向量
                    KnowledgeChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        chunk_index=chunk.chunk_index,
                        section_path=list(chunk.section_path),
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        token_count=chunk.token_count,
                        search_document=build_search_document(
                            content=chunk.content,
                            section_path=chunk.section_path,
                        ),
                        embedding=list(embeddings_by_id[chunk.chunk_id]),
                    )
                )
        # 第六步: 由调用方提交事务
        await self._session.flush()
        return tuple(stored_by_id[item.metadata.document_id] for item in normalized_documents)

    @staticmethod
    def _apply_document_fields(
        stored: KnowledgeDocument,
        processed: ProcessedDocument,
        generation: EmbeddingGeneration,
    ) -> None:
        metadata = processed.metadata
        stored.title = metadata.title
        stored.file_path = metadata.file_path
        stored.content_hash = processed.content_hash
        stored.lifecycle = metadata.lifecycle
        stored.replaced_by = metadata.replaced_by
        stored.document_type = metadata.document_type
        stored.satellite_type = metadata.satellite_type
        stored.product_type = metadata.product_type
        stored.processing_level = metadata.processing_level
        stored.specification_version = metadata.specification_version
        stored.effective_date = metadata.effective_date
        stored.expiry_date = metadata.expiry_date
        stored.permission_scope = metadata.permission_scope
        stored.embedding_provider = generation.descriptor.provider
        stored.embedding_model = generation.descriptor.model
        stored.embedding_dimension = generation.descriptor.dimension
        stored.index_version = generation.descriptor.index_version
        stored.indexed_at = generation.generated_at

    @staticmethod
    def _validate_reindex_input(
        documents: tuple[ProcessedDocument, ...],
        generation: EmbeddingGeneration,
    ) -> dict[str, tuple[float, ...]]:
        if not documents:
            raise KnowledgeIndexValidationError("at least one processed document is required")
        if generation.descriptor.dimension != EMBEDDING_DIMENSION:
            raise KnowledgeIndexValidationError(
                "embedding dimension does not match database schema"
            )
        document_ids = [item.metadata.document_id for item in documents]
        if len(document_ids) != len(set(document_ids)):
            raise KnowledgeIndexValidationError("processed documents contain duplicate document_id")

        chunks = [chunk for document in documents for chunk in document.chunks]
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise KnowledgeIndexValidationError("processed documents contain duplicate chunk_id")
        for document in documents:
            if not document.chunks or any(
                chunk.document_id != document.metadata.document_id for chunk in document.chunks
            ):
                raise KnowledgeIndexValidationError("chunk ownership does not match document")
            if [chunk.chunk_index for chunk in document.chunks] != list(
                range(len(document.chunks))
            ):
                raise KnowledgeIndexValidationError("chunk indices must be contiguous")

        embeddings_by_id = {item.chunk_id: item.vector for item in generation.embeddings}
        if len(embeddings_by_id) != len(generation.embeddings) or set(embeddings_by_id) != set(
            chunk_ids
        ):
            raise KnowledgeIndexValidationError("embedding identities do not match document chunks")
        if any(
            len(vector) != EMBEDDING_DIMENSION
            or any(not math.isfinite(value) for value in vector)
            or not any(value != 0.0 for value in vector)
            for vector in embeddings_by_id.values()
        ):
            raise KnowledgeIndexValidationError("embedding vector is invalid")
        if generation.generated_at.tzinfo is None or generation.generated_at.utcoffset() is None:
            raise KnowledgeIndexValidationError("indexed_at must be timezone-aware")
        return embeddings_by_id
