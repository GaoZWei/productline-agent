"""知识文档的统一读取协议、格式选择和UTF-8内容规范化。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.schemas.knowledge import DocumentMetadata


class DocumentFormat(StrEnum):
    """第一版Loader支持的确定性文本格式。"""

    MARKDOWN = "MARKDOWN"
    PLAIN_TEXT = "PLAIN_TEXT"


class DocumentLoadError(ValueError):
    """文档缺失、编码、内容或元数据与正文不一致。"""


class UnsupportedDocumentFormatError(DocumentLoadError):
    """文件扩展名没有对应的受控Loader。"""

# 规范化正文内容
def normalize_document_content(content: str) -> str:
    """统一BOM和换行符, 使内容哈希不受操作系统换行差异影响。"""

    normalized = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise DocumentLoadError("knowledge document is empty")
    return normalized

# 已经读入, 但还没有分块的文档
@dataclass(frozen=True, slots=True)
class LoadedDocument:
    """已读取但尚未分块的规范正文及其稳定内容哈希。"""

    metadata: DocumentMetadata  # 目录中的文档类型、版本、有效期、权限等信息
    document_format: DocumentFormat  # Markdown或纯文本格式
    content: str  # 规范化后的完整正文
    content_hash: str  # 稳定的内容哈希, 用于后续的相似度计算和检索

    @classmethod
    def from_content(
        cls,
        *,
        metadata: DocumentMetadata,
        document_format: DocumentFormat,
        content: str,
    ) -> LoadedDocument:
        """规范化内存文本并以SHA-256生成跨运行稳定哈希。"""
        # 正文内容规范化
        normalized = normalize_document_content(content)
        return cls(
            metadata=metadata,
            document_format=document_format,
            content=normalized,
            content_hash=sha256(normalized.encode("utf-8")).hexdigest(),
        )

# 统一DocumentLoader协议
# 所有Loader都必须声明支持的扩展名, 并按文件路径和已校验元数据返回LoadedDocument。
class DocumentLoader(Protocol):
    """不同文本格式必须实现的统一同步读取协议。"""

    @property
    def supported_suffixes(self) -> frozenset[str]:
        """返回包含点号的小写扩展名集合。"""

        ...

    def load(self, source_path: Path, metadata: DocumentMetadata) -> LoadedDocument:
        """按照已校验元数据读取一份文档。"""

        ...

# Markdown和纯文本Loader的内部基类
class _Utf8DocumentLoader:
    """共享文件存在性、UTF-8解码和元数据扩展名校验。"""

    document_format: DocumentFormat
    supported_suffixes: frozenset[str]

    def load(self, source_path: Path, metadata: DocumentMetadata) -> LoadedDocument:
        """读取并规范化文档, 子类可追加格式专属校验。"""

        suffix = source_path.suffix.lower()
        metadata_suffix = PurePosixPath(metadata.file_path).suffix.lower()
        # 文件扩展名与元数据不一致
        if suffix not in self.supported_suffixes or suffix != metadata_suffix:
            raise UnsupportedDocumentFormatError(
                f"document suffix {suffix or '<none>'} does not match loader metadata"
            )
        # 读取文件内容
        try:
            content = source_path.read_bytes().decode("utf-8")
        except FileNotFoundError as exc:  # 文件不存在
            raise DocumentLoadError("knowledge document does not exist") from exc
        except OSError as exc:  # 读取文件失败
            raise DocumentLoadError("knowledge document cannot be read") from exc
        except UnicodeDecodeError as exc:  # 编码错误
            raise DocumentLoadError("knowledge document must be valid UTF-8") from exc
        # 正文内容规范化
        loaded = LoadedDocument.from_content(
            metadata=metadata,
            document_format=self.document_format,
            content=content,
        )
        # 校验正文内容
        self._validate_content(loaded)
        return loaded

    def _validate_content(self, document: LoadedDocument) -> None:
        """允许具体格式在读取后验证正文契约。"""


class MarkdownDocumentLoader(_Utf8DocumentLoader):
    """读取带一级标题且标题与目录元数据一致的Markdown规范。"""
    # 格式支持markdown文件
    document_format = DocumentFormat.MARKDOWN
    # 后缀.md
    supported_suffixes = frozenset({".md"})

    def _validate_content(self, document: LoadedDocument) -> None:
        # 读取完成后, 它会取得第一个非空行作为标题行
        first_line = next(
            (line.strip() for line in document.content.splitlines() if line.strip()),
            "",
        )
        # 然后要求它必须是一级标题
        if not first_line.startswith("# ") or first_line.startswith("## "):
            raise DocumentLoadError("Markdown document requires a level-one title")
        title = first_line[2:].rstrip().rstrip("#").rstrip()
        # 标题必须等于DocumentMetadata.title
        if title != document.metadata.title:
            raise DocumentLoadError("Markdown title does not match document metadata title")

# 纯文本Loader
class PlainTextDocumentLoader(_Utf8DocumentLoader):
    """读取不解释标题语法的UTF-8纯文本规范。"""

    document_format = DocumentFormat.PLAIN_TEXT
    supported_suffixes = frozenset({".txt"})

# Loader注册表 负责格式选择
class DocumentLoaderRegistry:
    """按扩展名选择唯一Loader, 拒绝隐式猜测文件格式。"""

    def __init__(self, loaders: Iterable[DocumentLoader]) -> None:
        loaders_by_suffix: dict[str, DocumentLoader] = {}
        for loader in loaders:
            for suffix in loader.supported_suffixes:
                normalized_suffix = suffix.lower()
                if normalized_suffix in loaders_by_suffix:
                    raise ValueError(f"duplicate document loader suffix: {normalized_suffix}")
                loaders_by_suffix[normalized_suffix] = loader
        if not loaders_by_suffix:
            raise ValueError("at least one document loader is required")
        self._loaders_by_suffix = loaders_by_suffix
    # 默认注册表
    @classmethod
    def default(cls) -> DocumentLoaderRegistry:
        """建立第一版Markdown和纯文本Loader集合。"""

        return cls((MarkdownDocumentLoader(), PlainTextDocumentLoader()))

    def load(self, source_path: Path, metadata: DocumentMetadata) -> LoadedDocument:
        """使用源文件扩展名选择Loader并读取正文。"""

        suffix = source_path.suffix.lower()
        loader = self._loaders_by_suffix.get(suffix)
        # 如果是.pdf、.docx或没有扩展名, 会抛出异常
        if loader is None:
            raise UnsupportedDocumentFormatError(
                f"unsupported knowledge document format: {suffix or '<none>'}"
            )
        return loader.load(source_path, metadata)
