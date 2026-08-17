"""M4.3 标题分块、超长切分、稳定ID和重复文档测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.knowledge import (
    DocumentFormat,
    DocumentProcessingPipeline,
    DuplicateDocumentError,
    HeadingDocumentChunker,
    LoadedDocument,
)
from app.schemas.knowledge import (
    DocumentCatalog,
    DocumentLifecycle,
    DocumentMetadata,
    DocumentType,
    PermissionScope,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_KNOWLEDGE_ROOT = _REPOSITORY_ROOT / "knowledge-base"
_CATALOG_PATH = _KNOWLEDGE_ROOT / "catalog.json"


def _metadata(
    file_path: str = "active/demo.md",
    *,
    document_id: str = "QUALITY-DEMO-001",
) -> DocumentMetadata:
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


def _loaded(content: str) -> LoadedDocument:
    return LoadedDocument.from_content(
        metadata=_metadata(),
        document_format=DocumentFormat.MARKDOWN,
        content=content,
    )


@pytest.mark.unit
def test_markdown_is_chunked_by_heading_with_complete_section_paths() -> None:
    document = _loaded(
        """# 测试规范

导言。

## 第一章

第一章正文。

### 子节

子节正文。

## 第二章

第二章正文。
"""
    )

    chunks = HeadingDocumentChunker(max_chunk_characters=200).split(document)

    assert [chunk.section_path for chunk in chunks] == [
        ("测试规范",),
        ("测试规范", "第一章"),
        ("测试规范", "第一章", "子节"),
        ("测试规范", "第二章"),
    ]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]
    assert "第一章正文" in chunks[1].content


@pytest.mark.unit
def test_markdown_heading_inside_code_fence_does_not_change_section_path() -> None:
    document = _loaded(
        """# 测试规范

## 示例

```markdown
## 这不是章节
```

示例正文。

## 真实章节

真实正文。
"""
    )

    chunks = HeadingDocumentChunker(max_chunk_characters=200).split(document)

    assert [chunk.section_path for chunk in chunks] == [
        ("测试规范",),
        ("测试规范", "示例"),
        ("测试规范", "真实章节"),
    ]
    assert "## 这不是章节" in chunks[1].content


@pytest.mark.unit
def test_oversized_section_is_split_deterministically_within_limit() -> None:
    content = "# 测试规范\n\n## 处理要求\n\n" + "问题处理完成后必须重新提交复核。" * 20
    chunker = HeadingDocumentChunker(max_chunk_characters=64)

    first = chunker.split(_loaded(content))
    second = chunker.split(_loaded(content))
    section_chunks = [chunk for chunk in first if chunk.section_path[-1] == "处理要求"]

    assert len(section_chunks) > 1
    assert all(len(chunk.content) <= 64 for chunk in first)
    assert all(chunk.token_count > 0 for chunk in first)
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)


@pytest.mark.unit
def test_stable_id_does_not_depend_on_an_unrelated_chunk_index() -> None:
    original = _loaded("# 测试规范\n\n## 固定章节\n\n固定正文。\n")
    with_preamble = _loaded(
        "# 测试规范\n\n## 新增章节\n\n新增正文。\n\n## 固定章节\n\n固定正文。\n"
    )
    chunker = HeadingDocumentChunker(max_chunk_characters=200)

    original_chunk = next(
        chunk for chunk in chunker.split(original) if chunk.section_path[-1] == "固定章节"
    )
    shifted_chunk = next(
        chunk
        for chunk in chunker.split(with_preamble)
        if chunk.section_path[-1] == "固定章节"
    )

    assert original_chunk.chunk_index != shifted_chunk.chunk_index
    assert original_chunk.chunk_id == shifted_chunk.chunk_id


@pytest.mark.unit
def test_pipeline_loads_the_complete_catalog_without_duplicate_content() -> None:
    catalog = DocumentCatalog.model_validate_json(_CATALOG_PATH.read_text(encoding="utf-8"))

    processed = DocumentProcessingPipeline().process_catalog(_KNOWLEDGE_ROOT, catalog)

    assert len(processed) == 16
    assert all(document.chunks for document in processed)
    assert len({document.content_hash for document in processed}) == 16
    chunk_ids = [chunk.chunk_id for document in processed for chunk in document.chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


@pytest.mark.unit
def test_pipeline_rejects_normalized_duplicate_documents(tmp_path: Path) -> None:
    active = tmp_path / "active"
    active.mkdir()
    (active / "first.txt").write_text("相同正文。\r\n", encoding="utf-8", newline="")
    (active / "second.txt").write_text("相同正文。\n", encoding="utf-8")
    catalog = DocumentCatalog(
        schema_version=1,
        documents=(
            _metadata("active/first.txt", document_id="QUALITY-DEMO-001"),
            _metadata("active/second.txt", document_id="QUALITY-DEMO-002"),
        ),
    )

    with pytest.raises(DuplicateDocumentError, match="QUALITY-DEMO-001"):
        DocumentProcessingPipeline().process_catalog(tmp_path, catalog)
