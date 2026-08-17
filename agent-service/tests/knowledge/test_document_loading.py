"""M4.3 Markdown、纯文本Loader和统一选择入口测试。"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from app.knowledge import (
    DocumentFormat,
    DocumentLoaderRegistry,
    DocumentLoadError,
    MarkdownDocumentLoader,
    PlainTextDocumentLoader,
    UnsupportedDocumentFormatError,
)
from app.schemas.knowledge import (
    DocumentLifecycle,
    DocumentMetadata,
    DocumentType,
    PermissionScope,
)


def _metadata(file_path: str, *, document_id: str = "QUALITY-DEMO-001") -> DocumentMetadata:
    return DocumentMetadata(
        document_id=document_id,
        title="测试规范",
        file_path=file_path,
        lifecycle=DocumentLifecycle.ACTIVE,
        replaced_by=None,
        document_type=DocumentType.QUALITY_SPEC,
        satellite_type="GF-2",
        product_type="DOM",
        processing_level="L2",
        specification_version="1.0",
        effective_date=date(2025, 1, 1),
        expiry_date=None,
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )


@pytest.mark.unit
def test_markdown_loader_normalizes_content_and_hash(tmp_path: Path) -> None:
    source = tmp_path / "demo.md"
    source.write_bytes("\ufeff# 测试规范\r\n\r\n## 范围\r\n正文\r\n".encode())

    loaded = MarkdownDocumentLoader().load(source, _metadata("active/demo.md"))

    assert loaded.document_format is DocumentFormat.MARKDOWN
    assert loaded.content == "# 测试规范\n\n## 范围\n正文\n"
    assert loaded.content_hash == sha256(loaded.content.encode()).hexdigest()


@pytest.mark.unit
def test_plain_text_loader_uses_the_same_document_contract(tmp_path: Path) -> None:
    source = tmp_path / "demo.txt"
    source.write_text("第一条。\r\n第二条。\r\n", encoding="utf-8", newline="")

    loaded = PlainTextDocumentLoader().load(source, _metadata("active/demo.txt"))

    assert loaded.document_format is DocumentFormat.PLAIN_TEXT
    assert loaded.content == "第一条。\n第二条。\n"
    assert loaded.metadata.file_path == "active/demo.txt"


@pytest.mark.unit
def test_loader_registry_selects_format_and_rejects_unsafe_inputs(tmp_path: Path) -> None:
    registry = DocumentLoaderRegistry.default()
    empty = tmp_path / "empty.md"
    empty.write_text(" \n", encoding="utf-8")
    binary = tmp_path / "demo.pdf"
    binary.write_bytes(b"%PDF")
    invalid_utf8 = tmp_path / "invalid.txt"
    invalid_utf8.write_bytes(b"\xff\xfe")

    with pytest.raises(DocumentLoadError, match="empty"):
        registry.load(empty, _metadata("active/empty.md"))
    with pytest.raises(UnsupportedDocumentFormatError, match=r"\.pdf"):
        registry.load(binary, _metadata("active/demo.md"))
    with pytest.raises(DocumentLoadError, match="UTF-8"):
        registry.load(invalid_utf8, _metadata("active/invalid.txt"))


@pytest.mark.unit
def test_markdown_loader_rejects_title_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "demo.md"
    source.write_text("# 另一份规范\n\n正文。\n", encoding="utf-8")

    with pytest.raises(DocumentLoadError, match="title"):
        MarkdownDocumentLoader().load(source, _metadata("active/demo.md"))
