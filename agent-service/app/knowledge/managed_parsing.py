"""复用单份正文规范化和稳定分块，不运行固定catalog的跨文档重复检测。"""

import hashlib
from dataclasses import dataclass

from app.knowledge.chunking import DocumentChunk, HeadingDocumentChunker
from app.knowledge.loaders import (
    DocumentFormat,
    DocumentLoadError,
    normalize_document_content,
    validate_markdown_title,
)


@dataclass(frozen=True, slots=True)
class ManagedChunkMetadata:
    """只提供分块真正需要的身份，不补造ACTIVE或失效日期。"""

    document_id: str
    title: str


@dataclass(frozen=True, slots=True)
class ManagedChunkSource:
    """管理修订的规范化正文，不依赖仓库文件路径。"""

    metadata: ManagedChunkMetadata
    document_format: DocumentFormat
    content: str


@dataclass(frozen=True, slots=True)
class ParsedKnowledgeRevision:
    """解析结果先在事务外构建，全部通过后再一次提交。"""

    body: str
    normalized_hash: str
    chunks: tuple[DocumentChunk, ...]


def parse_managed_revision(
    raw: bytes,
    *,
    citation_document_id: str,
    title: str,
    file_format: str,
) -> ParsedKnowledgeRevision:
    """处理单份MD/TXT，不生成Embedding，也不修改发布状态。"""

    body = normalize_document_content(raw.decode("utf-8"))
    if file_format == "MD":
        validate_markdown_title(body, title)
    elif file_format != "TXT":
        raise DocumentLoadError("unsupported managed document format")
    source = ManagedChunkSource(
        ManagedChunkMetadata(citation_document_id, title),
        DocumentFormat.MARKDOWN if file_format == "MD" else DocumentFormat.PLAIN_TEXT,
        body,
    )
    chunks = HeadingDocumentChunker().split(source)
    if not chunks:
        raise DocumentLoadError("managed document produced no chunks")
    return ParsedKnowledgeRevision(body, hashlib.sha256(body.encode()).hexdigest(), chunks)
