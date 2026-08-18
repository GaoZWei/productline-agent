"""M4.2 知识文档元数据Schema和SQLAlchemy模型测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.database import Base
from app.models import KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import (
    DocumentCatalog,
    DocumentLifecycle,
    DocumentMetadata,
    DocumentType,
)

_CATALOG_PATH = Path(__file__).resolve().parents[3] / "knowledge-base" / "catalog.json"


def _metadata(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "document_id": "COORDINATE-REFERENCE-002",
        "title": "DOM坐标参考要求",
        "file_path": "active/coordinate-system/coordinate-reference-v2.md",
        "lifecycle": DocumentLifecycle.ACTIVE,
        "replaced_by": None,
        "document_type": DocumentType.COORDINATE_SYSTEM_SPEC,
        "satellite_type": "GF-2",
        "product_type": "DOM",
        "processing_level": "L2",
        "specification_version": "2.0",
        "effective_date": date(2025, 1, 1),
        "expiry_date": None,
        "permission_scope": "INTERNAL_REVIEWER",
    }
    payload.update(updates)
    return payload


@pytest.mark.unit
def test_catalog_is_validated_into_strict_document_metadata() -> None:
    catalog = DocumentCatalog.model_validate_json(_CATALOG_PATH.read_text(encoding="utf-8"))

    assert catalog.schema_version == 1
    assert len(catalog.documents) == 16
    assert sum(
        document.lifecycle is DocumentLifecycle.ACTIVE for document in catalog.documents
    ) == 14
    historical = next(
        document
        for document in catalog.documents
        if document.document_id == "COORDINATE-REFERENCE-001"
    )
    assert historical.document_type is DocumentType.COORDINATE_SYSTEM_SPEC
    assert historical.expiry_date == date(2024, 12, 31)
    assert historical.replaced_by == "COORDINATE-REFERENCE-002"


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"expiry_date": date(2025, 12, 31)},
        {"replaced_by": "COORDINATE-REFERENCE-003"},
        {"file_path": "historical/coordinate-system/coordinate-reference-v2.md"},
        {"file_path": "../coordinate-reference-v2.md"},
        {"file_path": "/tmp/coordinate-reference-v2.md"},
    ],
)
def test_active_metadata_rejects_invalid_lifecycle_and_paths(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(_metadata(**updates))


@pytest.mark.unit
def test_historical_metadata_requires_expiry_and_newer_replacement() -> None:
    historical = _metadata(
        document_id="COORDINATE-REFERENCE-001",
        file_path="historical/coordinate-system/coordinate-reference-v1.md",
        lifecycle=DocumentLifecycle.HISTORICAL,
        specification_version="1.0",
        effective_date=date(2022, 1, 1),
        expiry_date=date(2024, 12, 31),
        replaced_by="COORDINATE-REFERENCE-002",
    )
    assert DocumentMetadata.model_validate(historical).expiry_date == date(2024, 12, 31)

    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate({**historical, "replaced_by": None})
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(
            {**historical, "expiry_date": date(2021, 12, 31)}
        )


@pytest.mark.unit
def test_sqlalchemy_metadata_contains_knowledge_tables_and_search_columns() -> None:
    assert KnowledgeDocument.metadata is Base.metadata
    assert KnowledgeChunk.metadata is Base.metadata
    assert {"knowledge_documents", "knowledge_chunks"} <= set(Base.metadata.tables)

    document_table = Base.metadata.tables["knowledge_documents"]
    assert set(document_table.columns.keys()) == {
        "document_id",
        "title",
        "file_path",
        "content_hash",
        "lifecycle",
        "replaced_by",
        "document_type",
        "satellite_type",
        "product_type",
        "processing_level",
        "specification_version",
        "effective_date",
        "expiry_date",
        "permission_scope",
        "embedding_provider",
        "embedding_model",
        "embedding_dimension",
        "index_version",
        "indexed_at",
        "created_at",
        "updated_at",
    }
    chunk_table = Base.metadata.tables["knowledge_chunks"]
    assert set(chunk_table.columns.keys()) == {
        "chunk_id",
        "document_id",
        "chunk_index",
        "section_path",
        "content",
        "content_hash",
        "token_count",
        "embedding",
        "search_vector",
        "created_at",
    }
    assert str(chunk_table.c.embedding.type) == "VECTOR(1536)"
    assert str(chunk_table.c.search_vector.type) == "TSVECTOR"
    assert chunk_table.c.search_vector.computed is not None
