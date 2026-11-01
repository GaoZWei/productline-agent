"""管理草稿内部Schema的输入、哈希及阶段边界测试。"""

import hashlib
from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.managed_knowledge import (
    ManagedKnowledgeDocumentState,
    ManagedKnowledgeDraftVersion,
    ManagedKnowledgeLibraryState,
    ManagedKnowledgeMetadata,
    ManagedKnowledgeRevisionSnapshot,
)
from tests.knowledge.managed_knowledge_fixtures import (
    DOCUMENT_ID,
    VERSION_ID,
    revision_payload,
    version_payload,
)


@pytest.mark.unit
def test_library_and_document_state_reject_early_activation_and_invalid_counter() -> None:
    assert ManagedKnowledgeLibraryState().source_mode == "LEGACY"
    with pytest.raises(ValidationError):
        ManagedKnowledgeLibraryState.model_validate({"source_mode": "MANAGED"})
    with pytest.raises(ValidationError):
        ManagedKnowledgeDocumentState.model_validate(
            {
                "document_id": DOCUMENT_ID,
                "created_by": "test-user",
                "row_version": -1,
            }
        )


@pytest.mark.unit
def test_metadata_hash_is_canonical_and_tracks_metadata_only() -> None:
    first = ManagedKnowledgeRevisionSnapshot.model_validate(revision_payload())
    second = ManagedKnowledgeRevisionSnapshot.model_validate(
        dict(
            reversed(
                list(
                    revision_payload(
                        revision_no=2,
                        original_key=(f"versions/{VERSION_ID}/revisions/2/original.md"),
                    ).items()
                )
            )
        )
    )
    assert first.metadata_digest() == second.metadata_digest()
    changed = ManagedKnowledgeRevisionSnapshot.model_validate(revision_payload(title="新版标题"))
    assert first.metadata_digest() != changed.metadata_digest()
    metadata = ManagedKnowledgeMetadata.model_validate(
        first.model_dump(include=set(ManagedKnowledgeMetadata.model_fields))
    )
    assert metadata.metadata_digest() == first.metadata_digest()
    assert first.body is None
    with pytest.raises(ValidationError):
        first.title = "覆盖原快照"  # type: ignore[misc]


@pytest.mark.unit
def test_txt_parsed_snapshot_and_expired_draft_are_allowed() -> None:
    body = "  规范正文\n"
    result = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            file_format="TXT",
            original_key=f"versions/{VERSION_ID}/revisions/1/original.txt",
            body=body,
            normalized_hash=hashlib.sha256(body.encode()).hexdigest(),
            effective_date=date(2020, 1, 1),
            expiry_date=date(2021, 1, 1),
        )
    )
    assert result.body == body


@pytest.mark.unit
@pytest.mark.parametrize("body", ["\ufeff规范正文", "规范\r\n正文", " \n "])
def test_snapshot_requires_normalized_nonblank_body(body: str) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeRevisionSnapshot.model_validate(
            revision_payload(
                body=body,
                normalized_hash=hashlib.sha256(body.encode()).hexdigest(),
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"revision_no": 0},
        {"revision_no": True},
        {"revision_no": "1"},
        {"byte_size": 0},
        {"byte_size": 10485761},
        {"file_format": "PDF"},
        {"raw_hash": "g" * 64},
        {"original_key": "../original.md"},
        {"original_key": f"versions/{VERSION_ID}/revisions/2/original.md"},
        {"body": "规范正文"},
        {"normalized_hash": "a" * 64},
        {"body": "规范正文", "normalized_hash": "a" * 64},
        {"title": " "},
        {"specification_version": "v2"},
        {"expiry_date": date(2029, 1, 1)},
        {"permission_scope": "PUBLIC"},
        {"is_demo": False},
        {"maintainer": "未审核主体"},
        {"metadata_hash": "a" * 64},
        {"unknown": "value"},
    ],
)
def test_revision_rejects_invalid_input(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeRevisionSnapshot.model_validate(revision_payload(**updates))


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"publication_state": "PUBLISHED"},
        {"current_revision_no": 0},
        {"source_kind": "UNKNOWN"},
        {"source_document_id": "QUALITY-001"},
        {"citation_document_id": "QUALITY-001"},
        {"version_id": "../../file"},
        {"source_kind": "CATALOG_IMPORT"},
    ],
)
def test_version_rejects_unsupported_state_and_provenance(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeDraftVersion.model_validate(version_payload(**updates))


@pytest.mark.unit
def test_import_retains_catalog_identity_without_claiming_publication() -> None:
    result = ManagedKnowledgeDraftVersion.model_validate(
        version_payload(
            source_kind="CATALOG_IMPORT",
            citation_document_id="QUALITY-001",
            source_document_id="QUALITY-001",
            source_catalog_hash="a" * 64,
            source_lifecycle="HISTORICAL",
            source_replaced_by="QUALITY-002",
        )
    )
    assert result.publication_state == "DRAFT"
    with pytest.raises(ValidationError):
        ManagedKnowledgeDraftVersion.model_validate(
            {
                **result.model_dump(),
                "source_replaced_by": None,
            }
        )
