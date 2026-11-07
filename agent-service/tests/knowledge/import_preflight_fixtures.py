"""首批原件与假向量源快照，仅用于隔离测试，不调用外部Provider。"""

from datetime import UTC, datetime

from app.knowledge.import_preflight import (
    ImportFiles,
    LegacyImportChunk,
    LegacyImportDocument,
    LegacyImportSnapshot,
)
from app.knowledge.search import build_search_document
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity

INDEX = KnowledgePublicationIndexIdentity(
    provider="test-provider", model="test-model", index_version="test-index-v1"
)
INDEXED_AT = datetime(2026, 11, 1, tzinfo=UTC)


def source_snapshot(files: ImportFiles) -> LegacyImportSnapshot:
    """由固定语料构建期望分块，非零向量只是测试数据，不代表语义质量。"""

    return LegacyImportSnapshot(
        documents=tuple(
            LegacyImportDocument(item.metadata, item.parsed.normalized_hash, INDEX, INDEXED_AT)
            for item in files.files
        ),
        chunks=tuple(
            LegacyImportChunk(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                section_path=chunk.section_path,
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_count=chunk.token_count,
                search_document=build_search_document(
                    content=chunk.content, section_path=chunk.section_path
                ),
                embedding=(float(chunk.chunk_index + 1),) + (0.0,) * 1535,
            )
            for item in files.files
            for chunk in item.parsed.chunks
        ),
        document_count=16,
        chunk_count=80,
        source_mode="LEGACY",
        library_release_revision=0,
        source_catalog_hash=None,
        target_conflict=False,
    )
