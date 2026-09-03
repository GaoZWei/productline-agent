"""显式串联知识目录校验、分块、Embedding和事务内全量重建。"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.knowledge import (
    DocumentChunk,
    DocumentProcessingPipeline,
    EmbeddingGeneration,
    ProcessedDocument,
)
from app.schemas.knowledge import DocumentCatalog
from app.schemas.knowledge_index import KnowledgeIndexIdentity, KnowledgeIngestionSummary

DEFAULT_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge-base"


class KnowledgeCatalogLoadError(ValueError):
    """目录文件缺失、越界、编码错误或不符合严格Schema。"""

# 要求目录文件位于知识库根目录内，防止路径越界
def load_document_catalog(
    knowledge_root: Path,
    catalog_path: Path | None = None,
) -> DocumentCatalog:
    """只允许读取知识库根目录内的UTF-8目录并执行完整关系校验。"""

    try:
        resolved_root = knowledge_root.resolve(strict=True)
        resolved_catalog = (catalog_path or knowledge_root / "catalog.json").resolve(strict=True)
        resolved_catalog.relative_to(resolved_root)
        content = resolved_catalog.read_bytes().decode("utf-8")
        catalog = DocumentCatalog.model_validate_json(content)
        if not catalog.documents:
            raise ValueError("knowledge catalog must contain at least one document")
        return catalog
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as error:
        raise KnowledgeCatalogLoadError("knowledge catalog is missing or invalid") from error


class KnowledgeIngestionRepository(Protocol):
    """全量入库服务需要的最小事务内Repository边界。"""

    def prune_documents_not_in(self, document_ids: Sequence[str]) -> Awaitable[int]: ...

    def reindex_documents(
        self,
        documents: Sequence[ProcessedDocument],
        generation: EmbeddingGeneration,
    ) -> Awaitable[object]: ...


class KnowledgeEmbeddingGenerator(Protocol):
    """全量入库只依赖批量Chunk Embedding生成能力。"""

    def generate(self, chunks: Sequence[DocumentChunk]) -> Awaitable[EmbeddingGeneration]: ...

# 知识入库应用服务
class KnowledgeIngestionService:
    """在外层事务中完成一次全量目录重建, Embedding成功前不写数据库。"""

    def __init__(
        self,
        *,
        repository: KnowledgeIngestionRepository,
        embedding_generator: KnowledgeEmbeddingGenerator,
        processing_pipeline: DocumentProcessingPipeline | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_generator = embedding_generator
        self._processing_pipeline = processing_pipeline or DocumentProcessingPipeline()
    # 先处理全部文档并生成全部向量，成功之后才开始修改数据库
    async def ingest_catalog(
        self,
        knowledge_root: Path,
        catalog_path: Path | None = None,
    ) -> KnowledgeIngestionSummary:
        """验证完整目录、生成全部向量, 再替换索引并清理目录外旧文档。"""

        catalog = load_document_catalog(knowledge_root, catalog_path)
        documents = self._processing_pipeline.process_catalog(knowledge_root, catalog)
        chunks = tuple(chunk for document in documents for chunk in document.chunks)
        generation = await self._embedding_generator.generate(chunks)

        document_ids = tuple(document.metadata.document_id for document in documents)
        removed_count = await self._repository.prune_documents_not_in(document_ids)
        await self._repository.reindex_documents(documents, generation)
        descriptor = generation.descriptor
        return KnowledgeIngestionSummary(
            document_count=len(documents),
            chunk_count=len(chunks),
            removed_document_count=removed_count,
            index=KnowledgeIndexIdentity(
                provider=descriptor.provider,
                model=descriptor.model,
                dimension=descriptor.dimension,
                index_version=descriptor.index_version,
            ),
        )


__all__ = [
    "DEFAULT_KNOWLEDGE_ROOT",
    "KnowledgeCatalogLoadError",
    "KnowledgeEmbeddingGenerator",
    "KnowledgeIngestionRepository",
    "KnowledgeIngestionService",
    "load_document_catalog",
]
