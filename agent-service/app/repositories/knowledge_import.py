"""首批纳管源的只读一致性快照，不改旧索引或管理记录。"""

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.knowledge.import_preflight import (
    LegacyImportChunk,
    LegacyImportDocument,
    LegacyImportSnapshot,
)
from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.managed_knowledge import ManagedKnowledgeLibrary, ManagedKnowledgeVersion
from app.schemas.knowledge import DocumentMetadata, PermissionScope
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity


class KnowledgeImportPreflightRepository:
    """旧表全量计数与授权范围内正文，在同一只读可重复读事务取出。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def read_source(self, document_ids: tuple[str, ...], scope: str) -> LegacyImportSnapshot:
        """只读SELECT，不在事务内授权、读文件或调用模型。"""

        try:
            PermissionScope(scope)
        except ValueError:
            raise KnowledgeManagementError("PERMISSION_DENIED") from None
        async with self.database.session() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            return await self.read_in_session(session, document_ids, scope)

    async def read_in_session(
        self, session: AsyncSession, document_ids: tuple[str, ...], scope: str
    ) -> LegacyImportSnapshot:
        """复用已持有源表锁的最终事务，源表不允许在比较与写入之间改变。"""

        document_count = await session.scalar(select(func.count()).select_from(KnowledgeDocument))
        chunk_count = await session.scalar(select(func.count()).select_from(KnowledgeChunk))
        library = await session.get(ManagedKnowledgeLibrary, "DEFAULT")
        if library is None:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        documents = tuple(
            await session.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.document_id.in_(document_ids),
                    KnowledgeDocument.permission_scope == scope,
                )
                .order_by(KnowledgeDocument.document_id)
            )
        )
        if (
            document_count != 16
            or len(documents) != 16
            or {item.document_id for item in documents} != set(document_ids)
        ):
            raise KnowledgeManagementError("IMPORT_LEGACY_INCOMPLETE")
        if chunk_count != 80:
            raise KnowledgeManagementError("IMPORT_LEGACY_CHUNKS_INVALID")
        conflict = await session.scalar(
            select(ManagedKnowledgeVersion.version_id)
            .where(
                or_(
                    ManagedKnowledgeVersion.citation_document_id.in_(document_ids),
                    ManagedKnowledgeVersion.source_document_id.in_(document_ids),
                )
            )
            .limit(1)
        )
        stored_documents: list[LegacyImportDocument] = []
        for document in documents:
            try:
                metadata = DocumentMetadata.model_validate(
                    {name: getattr(document, name) for name in DocumentMetadata.model_fields}
                )
            except ValueError:
                raise KnowledgeManagementError("IMPORT_LEGACY_DOCUMENT_MISMATCH") from None
            try:
                index = KnowledgePublicationIndexIdentity.model_validate(
                    {
                        "provider": document.embedding_provider,
                        "model": document.embedding_model,
                        "dimension": document.embedding_dimension,
                        "index_version": document.index_version,
                    }
                )
            except ValueError:
                raise KnowledgeManagementError("IMPORT_LEGACY_INDEX_INVALID") from None
            if document.indexed_at is None:
                raise KnowledgeManagementError("IMPORT_LEGACY_INDEX_INVALID")
            stored_documents.append(
                LegacyImportDocument(metadata, document.content_hash, index, document.indexed_at)
            )
        chunks = await session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id.in_(document_ids))
            .order_by(KnowledgeChunk.chunk_id)
        )
        stored_chunks: list[LegacyImportChunk] = []
        for chunk in chunks:
            if not isinstance(chunk.section_path, list) or any(
                not isinstance(part, str) for part in chunk.section_path
            ):
                raise KnowledgeManagementError("IMPORT_LEGACY_CHUNKS_INVALID")
            if chunk.embedding is None:
                raise KnowledgeManagementError("IMPORT_LEGACY_VECTOR_INVALID")
            stored_chunks.append(
                LegacyImportChunk(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    section_path=tuple(chunk.section_path),
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    token_count=chunk.token_count,
                    search_document=chunk.search_document,
                    embedding=tuple(float(value) for value in chunk.embedding),
                )
            )
        return LegacyImportSnapshot(
            documents=tuple(stored_documents),
            chunks=tuple(stored_chunks),
            document_count=document_count,
            chunk_count=chunk_count or 0,
            source_mode=library.source_mode,
            library_release_revision=library.release_revision,
            source_catalog_hash=library.source_catalog_hash,
            target_conflict=conflict is not None,
        )
