"""串联目录读取、格式Loader、分块和内容哈希重复检测。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.knowledge.chunking import DocumentChunk, HeadingDocumentChunker
from app.knowledge.loaders import (
    DocumentFormat,
    DocumentLoaderRegistry,
    DocumentLoadError,
)
from app.schemas.knowledge import DocumentCatalog, DocumentMetadata


class DuplicateDocumentError(ValueError):
    """两个不同文档ID对应规范化后完全相同的正文。"""

    def __init__(
        self,
        *,
        document_id: str,
        existing_document_id: str,
        content_hash: str,
    ) -> None:
        super().__init__(
            f"document {document_id} duplicates {existing_document_id} "
            f"with content hash {content_hash}"
        )
        self.document_id = document_id
        self.existing_document_id = existing_document_id
        self.content_hash = content_hash

# 重复文档检测器
class DuplicateDocumentDetector:
    """按规范化SHA-256跟踪批内或调用方提供的既有文档。"""

    def __init__(self, known_content_hashes: Mapping[str, str] | None = None) -> None:
        self._owners_by_hash = dict(known_content_hashes or {})

    def register(self, *, document_id: str, content_hash: str) -> None:
        """登记内容哈希, 不同ID复用同一正文时拒绝继续处理。"""

        existing_document_id = self._owners_by_hash.get(content_hash)
        if existing_document_id is not None and existing_document_id != document_id:
            raise DuplicateDocumentError(
                document_id=document_id,
                existing_document_id=existing_document_id,
                content_hash=content_hash,
            )
        self._owners_by_hash[content_hash] = document_id


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """一次确定性处理产生的文档级哈希和全部分块。"""

    metadata: DocumentMetadata
    document_format: DocumentFormat
    content_hash: str
    chunks: tuple[DocumentChunk, ...]


class DocumentProcessingPipeline:
    """处理完整目录但不执行数据库写入或Embedding调用。"""

    def __init__(
        self,
        *,
        loader_registry: DocumentLoaderRegistry | None = None,
        chunker: HeadingDocumentChunker | None = None,
    ) -> None:
        self._loader_registry = loader_registry or DocumentLoaderRegistry.default()
        self._chunker = chunker or HeadingDocumentChunker()
    # Pipeline串联全部步骤
    def process_catalog(
        self,
        knowledge_root: Path,
        catalog: DocumentCatalog,
        *,
        known_content_hashes: Mapping[str, str] | None = None,
    ) -> tuple[ProcessedDocument, ...]:
        """按目录顺序读取和分块, 并拒绝路径逃逸及重复正文。"""
        try:
            resolved_root = knowledge_root.resolve(strict=True)
        except OSError as exc:
            raise DocumentLoadError("knowledge root does not exist") from exc

        detector = DuplicateDocumentDetector(known_content_hashes)
        processed: list[ProcessedDocument] = []
        for metadata in catalog.documents:
            source_path = resolved_root.joinpath(*PurePosixPath(metadata.file_path).parts)
            try:
                # 第一步: 确保文件真实存在
                resolved_source = source_path.resolve(strict=True)
                # 第二步: 确保解析后的真实路径仍位于知识库根目录
                resolved_source.relative_to(resolved_root)
            except (OSError, ValueError) as exc:
                raise DocumentLoadError(
                    "knowledge document escapes or is missing from root"
                ) from exc
            # 第三步: 加载文档内容
            loaded = self._loader_registry.load(resolved_source, metadata)
            # 第四步: 登记内容哈希
            detector.register(
                document_id=metadata.document_id,
                content_hash=loaded.content_hash,
            )
            # 第五步: 分块文档内容
            chunks = self._chunker.split(loaded)
            if not chunks:
                raise DocumentLoadError("knowledge document produced no chunks")
            # 第六步: 收集处理结果文档
            processed.append(
                ProcessedDocument(
                    metadata=metadata,
                    document_format=loaded.document_format,
                    content_hash=loaded.content_hash,
                    chunks=chunks,
                )
            )
            # 第七步: 返回处理结果文档
        return tuple(processed)
