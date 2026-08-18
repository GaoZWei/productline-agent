"""按Markdown标题和字符上限生成确定性知识分块。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from app.knowledge.loaders import DocumentFormat, LoadedDocument

_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*|[^\s]"
)
_SPLIT_PUNCTUATION = frozenset({"。", "\uff01", "\uff1f", "\uff1b", ".", "!", "?", ";", "\n"})

# DocumentChunk结构定义 表示一个可入库分块
@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """可直接映射到KnowledgeChunk的稳定分块数据。"""

    chunk_id: str  # 分块稳定身份
    document_id: str  # 所属文档ID
    chunk_index: int  # 当前文档内展示顺序
    section_path: tuple[str, ...]  # 标题层级和引用位置
    content: str  # 分块正文
    content_hash: str  # 分块内容SHA-256
    token_count: int  # 当前确定性词元近似值

# Markdown标题分节算法
class HeadingDocumentChunker:
    """Markdown按标题分节, 纯文本按文档标题分节, 再切分超长内容。"""

    def __init__(
        self,
        *,
        max_chunk_characters: int = 1200,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        if max_chunk_characters < 32:
            raise ValueError("max_chunk_characters must be at least 32")
        self._max_chunk_characters = max_chunk_characters
        self._token_counter = token_counter or _count_lexical_tokens

    def split(self, document: LoadedDocument) -> tuple[DocumentChunk, ...]:
        """保持目录顺序生成Chunk, ID不依赖全局chunk_index。"""

        sections: tuple[tuple[tuple[str, ...], str], ...]
        if document.document_format is DocumentFormat.MARKDOWN:
            # Markdown文档按标题分节
            # 每个标题层级和引用位置都对应一个分块
            # 分块内容是该标题以下的所有文本
            # 类似: ("测试规范", "第一章", "子节")
            sections = _markdown_sections(document)
        else:
            sections = (((document.metadata.title,), document.content),)

        fragments: list[tuple[tuple[str, ...], str]] = []
        for section_path, section_content in sections:
            fragments.extend(
                (section_path, fragment)
                for fragment in _split_oversized_text(
                    section_content,
                    max_characters=self._max_chunk_characters,
                )
            )

        chunks: list[DocumentChunk] = []
        signature_occurrences: dict[tuple[tuple[str, ...], str], int] = {}
        for chunk_index, (section_path, content) in enumerate(fragments):
            content_hash = sha256(content.encode("utf-8")).hexdigest()
            signature = (section_path, content_hash)
            occurrence = signature_occurrences.get(signature, 0)
            signature_occurrences[signature] = occurrence + 1
            chunks.append(
                DocumentChunk(
                    chunk_id=_stable_chunk_id(
                        document_id=document.metadata.document_id,
                        section_path=section_path,
                        content_hash=content_hash,
                        occurrence=occurrence,
                    ),
                    document_id=document.metadata.document_id,
                    chunk_index=chunk_index,
                    section_path=section_path,
                    content=content,
                    content_hash=content_hash,
                    token_count=max(1, self._token_counter(content)),
                )
            )
        return tuple(chunks)

# 处理代码围栏内的井号
def _markdown_sections(
    document: LoadedDocument,
) -> tuple[tuple[tuple[str, ...], str], ...]:
    """忽略代码围栏内的井号, 按ATX标题维护完整层级路径。"""

    sections: list[tuple[tuple[str, ...], str]] = []
    headings: list[tuple[int, str]] = []
    current_path: tuple[str, ...] = (document.metadata.title,)
    current_lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_path, content))

    for line in document.content.splitlines():
        fence_match = _FENCE_PATTERN.match(line)
        if fence_character is not None:
            current_lines.append(line)
            if (
                fence_match is not None
                and fence_match.group(1)[0] == fence_character
                and len(fence_match.group(1)) >= fence_length
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence_match is not None:
            marker = fence_match.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            current_lines.append(line)
            continue

        heading_match = _HEADING_PATTERN.match(line)
        if heading_match is None:
            current_lines.append(line)
            continue

        flush()
        level = len(heading_match.group(1))
        heading_title = re.sub(r"[ \t]+#+[ \t]*$", "", heading_match.group(2)).strip()
        # 遇到同级或更高级标题时:
        while headings and headings[-1][0] >= level:
            headings.pop()
        headings.append((level, heading_title))
        current_path = tuple(title for _, title in headings)
        current_lines = [line]

    flush()
    return tuple(sections)

# 超长章节二次切分
# 第一层: 优先保持完整章节
# 如果整个章节不超过上限, 直接作为一个Chunk
# 第二层: 按空行识别段落
# 多个短段落会尽量合并, 直到接近长度上限
# 第三层: 单个段落仍然超长
# 如果一个段落自身超过上限, 会寻找后半段中的句末符号
def _split_oversized_text(text: str, *, max_characters: int) -> tuple[str, ...]:
    """优先按空行组合段落, 单段超长时优先在句末切断。"""

    paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n+", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_characters:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_characters:
            current = paragraph
            continue
        chunks.extend(_split_long_paragraph(paragraph, max_characters=max_characters))
    if current:
        chunks.append(current)
    return tuple(chunks)


def _split_long_paragraph(paragraph: str, *, max_characters: int) -> tuple[str, ...]:
    """为无法按段落切分的正文选择稳定句末边界或字符硬边界。"""

    remaining = paragraph.strip()
    parts: list[str] = []
    minimum_boundary = max_characters // 2
    while len(remaining) > max_characters:
        window = remaining[:max_characters]
        boundary = max(
            (
                index + 1
                for index, character in enumerate(window)
                if index + 1 >= minimum_boundary and character in _SPLIT_PUNCTUATION
            ),
            default=max_characters,
        )
        part = remaining[:boundary].strip()
        if part:
            parts.append(part)
        remaining = remaining[boundary:].lstrip()
    if remaining:
        parts.append(remaining)
    return tuple(parts)


def _count_lexical_tokens(content: str) -> int:
    """提供不绑定Embedding供应商的中英文确定性词元近似值。"""

    return len(_TOKEN_PATTERN.findall(content))

# 稳定Chunk ID算法
def _stable_chunk_id(
    *,
    document_id: str,
    section_path: tuple[str, ...],
    content_hash: str,
    occurrence: int,
) -> str:
    """以文档、章节、内容和同内容序号生成不依赖位置的稳定ID。"""

    payload = json.dumps(
        {
            "document_id": document_id,
            "section_path": section_path,
            "content_hash": content_hash,
            # 记录同签名出现次数, 避免同一文档内完全相同分块发生身份冲突。
            "occurrence": occurrence,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # 不使用chunk_index, 否则会导致:
    # 已生成的Embedding无法复用。
    # 历史引用找不到原Chunk。
    # 序列化后计算SHA-256哈希值
    return f"KCH-{sha256(payload.encode('utf-8')).hexdigest()[:40].upper()}"
    # 增量更新退化成全量重建
