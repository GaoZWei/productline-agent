"""只读捕获演示原件并核对旧索引，不写文件、数据库或调用模型。"""

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.pipeline import DuplicateDocumentDetector
from app.knowledge.search import build_search_document
from app.knowledge.storage import MAX_ORIGINAL_BYTES
from app.schemas.knowledge import (
    DocumentCatalog,
    DocumentLifecycle,
    DocumentMetadata,
    PermissionScope,
)
from app.schemas.knowledge_import import KnowledgeImportPreflight, KnowledgeImportVersionCheck
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity


@dataclass(frozen=True, slots=True)
class ImportSourceFile:
    """原始字节只在内存保留，为后续再次校验提供明确来源。"""

    metadata: DocumentMetadata
    raw: bytes
    parsed: ParsedKnowledgeRevision


@dataclass(frozen=True, slots=True)
class ImportFiles:
    """本次读取的catalog与全部规范，未复制到管理原件目录。"""

    catalog_hash: str
    files: tuple[ImportSourceFile, ...]


@dataclass(frozen=True, slots=True)
class LegacyImportDocument:
    """旧索引文档的元数据、正文哈希及完整索引身份。"""

    metadata: DocumentMetadata
    content_hash: str
    index: KnowledgePublicationIndexIdentity
    indexed_at: datetime


@dataclass(frozen=True, slots=True)
class LegacyImportChunk:
    """旧引用的原始分块和float32向量，不分配虚构管理批次身份。"""

    document_id: str
    chunk_id: str
    chunk_index: int
    section_path: tuple[str, ...]
    content: str
    content_hash: str
    token_count: int
    search_document: str
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class LegacyImportSnapshot:
    """同一只读SQL快照内的旧索引与目标库状态，不带Java业务数据。"""

    documents: tuple[LegacyImportDocument, ...]
    chunks: tuple[LegacyImportChunk, ...]
    document_count: int
    chunk_count: int
    source_mode: str
    library_release_revision: int
    source_catalog_hash: str | None
    target_conflict: bool


def _digest(payload: object) -> str:
    """规范JSON绑定文件、元数据和向量，不把摘要作为授权票据。"""

    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _read(directory: int, relative: str, limit: int) -> bytes:
    """逐级NOFOLLOW只读打开，拒绝特殊文件和读取中的原件变更。"""

    path = PurePosixPath(relative)
    if (
        not path.parts
        or path.is_absolute()
        or str(path) != relative
        or any(part in {".", "..", ""} or "\\" in part for part in path.parts)
    ):
        raise ValueError("invalid source relative path")
    parent = os.dup(directory)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(
            path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ValueError("invalid source file type or size")
            data = bytearray()
            while len(data) <= limit:
                block = os.read(descriptor, min(65536, limit + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
            after = os.fstat(descriptor)
            if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("source file changed during read")
            return bytes(data)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def capture_import_files(root: Path) -> ImportFiles:
    """首批固定为16版本/14当前/2历史/80块，复用相同规范化和稳定分块。"""

    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.absolute().parts[1:]:
            if part in {".", "..", ""}:
                raise ValueError("invalid knowledge root")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        catalog_raw = _read(directory, "catalog.json", 2 * 1024 * 1024)
        catalog = DocumentCatalog.model_validate_json(catalog_raw)
        active = [item for item in catalog.documents if item.lifecycle == DocumentLifecycle.ACTIVE]
        if len(catalog.documents) != 16 or len(active) != 14:
            raise KnowledgeManagementError("IMPORT_BATCH_SCOPE_INVALID")
        detector = DuplicateDocumentDetector()
        files: list[ImportSourceFile] = []
        groups: dict[str, set[str]] = {}
        for metadata in catalog.documents:
            raw = _read(directory, metadata.file_path, MAX_ORIGINAL_BYTES)
            if b"\x00" in raw:
                raise ValueError("source must be UTF-8 text")
            suffix = PurePosixPath(metadata.file_path).suffix.lower()
            file_format = {".md": "MD", ".txt": "TXT"}.get(suffix)
            if file_format is None:
                raise ValueError("unsupported source document format")
            parsed = parse_managed_revision(
                raw,
                citation_document_id=metadata.document_id,
                title=metadata.title,
                file_format=file_format,
            )
            detector.register(document_id=metadata.document_id, content_hash=parsed.normalized_hash)
            key = metadata.replaced_by or metadata.document_id
            versions = groups.setdefault(key, set())
            if metadata.specification_version in versions:
                raise ValueError("source logical document contains duplicate specification version")
            versions.add(metadata.specification_version)
            files.append(ImportSourceFile(metadata, raw, parsed))
        if len(groups) != 14 or sum(len(item.parsed.chunks) for item in files) != 80:
            raise KnowledgeManagementError("IMPORT_BATCH_SCOPE_INVALID")
        return ImportFiles(hashlib.sha256(catalog_raw).hexdigest(), tuple(files))
    except KnowledgeManagementError:
        raise
    except (OSError, ValueError):
        raise KnowledgeManagementError("IMPORT_SOURCE_FILES_INVALID") from None
    finally:
        os.close(directory)


def file_fingerprint(files: ImportFiles) -> str:
    """原字节变化即使规范化后相同也会改变源文件指纹。"""

    return _digest(
        {
            "catalog": files.catalog_hash,
            "files": [
                {"id": item.metadata.document_id, "raw_hash": hashlib.sha256(item.raw).hexdigest()}
                for item in sorted(files.files, key=lambda item: item.metadata.document_id)
            ],
        }
    )


def validate_import_source(
    files: ImportFiles,
    stored: LegacyImportSnapshot,
    *,
    actor: str,
    scope: str,
    expected_index: KnowledgePublicationIndexIdentity,
) -> KnowledgeImportPreflight:
    """完整比较源文件、旧索引和当前配置，不以行数或READY标签替代证据校验。"""

    if stored.source_mode != "LEGACY":
        raise KnowledgeManagementError("IMPORT_SOURCE_MODE_CONFLICT")
    if stored.source_catalog_hash is not None:
        raise KnowledgeManagementError(
            "IMPORT_ALREADY_PRESENT"
            if stored.source_catalog_hash == files.catalog_hash
            else "IMPORT_SOURCE_CONFLICT"
        )
    if stored.target_conflict:
        raise KnowledgeManagementError("IMPORT_TARGET_CONFLICT")
    expected_ids = {item.metadata.document_id for item in files.files}
    documents = {item.metadata.document_id: item for item in stored.documents}
    if stored.document_count != 16 or set(documents) != expected_ids or len(stored.documents) != 16:
        raise KnowledgeManagementError("IMPORT_LEGACY_INCOMPLETE")
    if (
        stored.chunk_count != 80
        or len(stored.chunks) != 80
        or len({item.chunk_id for item in stored.chunks}) != 80
    ):
        raise KnowledgeManagementError("IMPORT_LEGACY_CHUNKS_INVALID")
    by_id = {item.chunk_id: item for item in stored.chunks}
    entries: list[KnowledgeImportVersionCheck] = []
    source_rows: list[dict[str, object]] = []
    for source in sorted(files.files, key=lambda item: item.metadata.document_id):
        metadata = source.metadata
        if metadata.permission_scope.value != scope:
            raise KnowledgeManagementError("PERMISSION_DENIED")
        document = documents[metadata.document_id]
        if document.metadata != metadata or document.content_hash != source.parsed.normalized_hash:
            raise KnowledgeManagementError("IMPORT_LEGACY_DOCUMENT_MISMATCH")
        if document.index != expected_index:
            raise KnowledgeManagementError("IMPORT_INDEX_IDENTITY_MISMATCH")
        if document.indexed_at.tzinfo is None or document.indexed_at.utcoffset() is None:
            raise KnowledgeManagementError("IMPORT_LEGACY_INDEX_INVALID")
        for expected in source.parsed.chunks:
            chunk = by_id.get(expected.chunk_id)
            if chunk is None or (
                chunk.document_id,
                chunk.chunk_index,
                chunk.section_path,
                chunk.content,
                chunk.content_hash,
                chunk.token_count,
                chunk.search_document,
            ) != (
                expected.document_id,
                expected.chunk_index,
                expected.section_path,
                expected.content,
                expected.content_hash,
                expected.token_count,
                build_search_document(content=expected.content, section_path=expected.section_path),
            ):
                raise KnowledgeManagementError("IMPORT_LEGACY_CHUNKS_INVALID")
            if (
                len(chunk.embedding) != 1536
                or not any(chunk.embedding)
                or any(
                    not math.isfinite(value) or abs(value) > 3.4028234663852886e38
                    for value in chunk.embedding
                )
            ):
                raise KnowledgeManagementError("IMPORT_LEGACY_VECTOR_INVALID")
        raw_hash = hashlib.sha256(source.raw).hexdigest()
        metadata_hash = _digest(metadata.model_dump(mode="json"))
        entries.append(
            KnowledgeImportVersionCheck(
                source_document_id=metadata.document_id,
                logical_document_key=metadata.replaced_by or metadata.document_id,
                title=metadata.title,
                specification_version=metadata.specification_version,
                lifecycle=metadata.lifecycle,
                replaced_by=metadata.replaced_by,
                file_path=metadata.file_path,
                raw_hash=raw_hash,
                normalized_hash=source.parsed.normalized_hash,
                source_metadata_hash=metadata_hash,
                byte_size=len(source.raw),
                chunk_count=len(source.parsed.chunks),
            )
        )
        source_rows.append(
            {
                "metadata": metadata.model_dump(mode="json"),
                "raw_hash": raw_hash,
                "normalized_hash": document.content_hash,
                "indexed_at": document.indexed_at.isoformat(),
            }
        )
    fingerprint = _digest(
        {
            "contract": "knowledge-import-source-v1",
            "catalog_hash": files.catalog_hash,
            "index": expected_index.model_dump(mode="json"),
            "documents": source_rows,
            "chunks": [
                vars_for_chunk(item)
                for item in sorted(stored.chunks, key=lambda item: item.chunk_id)
            ],
        }
    )
    return KnowledgeImportPreflight(
        checked_by=actor,
        permission_scope=PermissionScope(scope),
        source_catalog_hash=files.catalog_hash,
        source_fingerprint=fingerprint,
        library_release_revision=stored.library_release_revision,
        index=expected_index,
        versions=tuple(entries),
    )


def vars_for_chunk(chunk: LegacyImportChunk) -> dict[str, object]:
    """显式列出引用与完整向量，避免只绑定元数据却漏掉向量变化。"""

    return {key: getattr(chunk, key) for key in LegacyImportChunk.__dataclass_fields__}
