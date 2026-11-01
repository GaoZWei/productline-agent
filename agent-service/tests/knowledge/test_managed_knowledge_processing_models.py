"""候选索引、确认及任务内部Schema的关键输入与失败边界。"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.managed_knowledge import ManagedKnowledgeVersionState
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeGenerationRecord,
    ManagedKnowledgeOperationRecord,
    ManagedKnowledgeTaskRecord,
)
from tests.knowledge.managed_knowledge_fixtures import (
    CREATED_AT,
    GENERATION_ID,
    TASK_ID,
    chunk_payload,
    confirmation_payload,
    generation_payload,
    operation_payload,
    task_payload,
    version_payload,
)


@pytest.mark.unit
def test_processing_records_keep_minimal_safe_inputs_and_exact_chunk_content() -> None:
    operation = ManagedKnowledgeOperationRecord.model_validate(operation_payload())
    assert operation.confirmation_snapshot.library_id == "DEFAULT"
    assert operation.state == "CONFIRMED"
    assert ManagedKnowledgeTaskRecord.model_validate(task_payload()).generation_id is None
    assert ManagedKnowledgeGenerationRecord.model_validate(generation_payload()).state == "BUILDING"
    chunk = ManagedKnowledgeChunkRecord.model_validate(chunk_payload())
    assert chunk.content == " 测试规范正文\n"
    assert len(chunk.embedding) == 1536


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"action": "READ"},
        {"token": "forbidden"},
        {"body": "forbidden"},
        {"action": "PUBLISH"},
        {"action": "RETRY_INDEX", "normalized_hash": "d" * 64},
        {"task_id": TASK_ID},
        {"generation_id": GENERATION_ID},
        {"expected_row_version": True},
    ],
)
def test_confirmation_rejects_unreviewable_or_incomplete_input(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeConfirmation.model_validate(confirmation_payload(**updates))


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"actor_id": "other-user"},
        {"idempotency_key": "key with newline\n"},
        {"action": "DISABLE"},
        {"revision_no": 2},
        {"state": "SUCCEEDED"},
        {"state": "FAILED", "finished_at": CREATED_AT},
        {"error_code": "provider raw error"},
        {"created_at": datetime(2026, 1, 1)},
    ],
)
def test_operation_rejects_mismatched_snapshot_or_result(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeOperationRecord.model_validate(operation_payload(**updates))


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"embedding_dimension": 1024},
        {"state": "READY", "finished_at": CREATED_AT},
        {"state": "FAILED", "finished_at": CREATED_AT},
        {"chunk_count": -1},
        {"embedding_provider": " "},
        {"build_method": "AUTO_RECOVERED"},
    ],
)
def test_generation_rejects_invalid_index_identity_and_state(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeGenerationRecord.model_validate(generation_payload(**updates))


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"generation_id": GENERATION_ID},
        {"task_type": "INDEX"},
        {"operation_action": "DISABLE"},
        {"attempt_no": 2},
        {"retry_of_task_id": TASK_ID},
        {"state": "RUNNING"},
        {"state": "INTERRUPTED", "finished_at": CREATED_AT},
        {"started_at": CREATED_AT},
        {"trace_id": "-"},
    ],
)
def test_task_rejects_type_retry_and_state_mismatch(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeTaskRecord.model_validate(task_payload(**updates))


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"embedding": (1.0,)},
        {"embedding": (0.0,) * 1536},
        {"embedding": (float("nan"),) + (0.0,) * 1535},
        {"embedding": (float("inf"),) + (0.0,) * 1535},
        {"embedding": (1e40,) + (0.0,) * 1535},
        {"content_hash": "d" * 64},
        {"section_path": ()},
        {"chunk_index": -1},
    ],
)
def test_chunk_rejects_invalid_vector_or_citation(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeChunkRecord.model_validate(chunk_payload(**updates))


@pytest.mark.unit
def test_version_seals_current_revision_and_historical_import_does_not_fake_publication() -> None:
    payload = version_payload(
        publication_state="PUBLISHED",
        published_revision_no=1,
        published_generation_id=GENERATION_ID,
        published_at=CREATED_AT,
    )
    assert ManagedKnowledgeVersionState.model_validate(payload).published_revision_no == 1
    for updates in (
        {"published_revision_no": 2},
        {"published_generation_id": None},
        {"published_at": None},
        {"publication_state": "DRAFT"},
        {"publication_state": "HISTORICAL", "published_at": None},
    ):
        with pytest.raises(ValidationError):
            ManagedKnowledgeVersionState.model_validate({**payload, **updates})
    historical = version_payload(
        source_kind="CATALOG_IMPORT",
        source_lifecycle="HISTORICAL",
        source_document_id="QUALITY-001",
        citation_document_id="QUALITY-001",
        source_replaced_by="QUALITY-002",
        source_catalog_hash="a" * 64,
        publication_state="HISTORICAL",
        published_revision_no=1,
        published_generation_id=GENERATION_ID,
    )
    assert ManagedKnowledgeVersionState.model_validate(historical).published_at is None


@pytest.mark.unit
def test_index_retry_keeps_original_task_and_failed_records_are_valid() -> None:
    retry = ManagedKnowledgeTaskRecord.model_validate(
        task_payload(
            task_type="INDEX",
            operation_action="RETRY_INDEX",
            generation_id=GENERATION_ID,
            attempt_no=2,
            retry_of_task_id="TASK-" + "2" * 32,
        )
    )
    assert retry.retry_of_task_id is not None
    failed = ManagedKnowledgeTaskRecord.model_validate(
        task_payload(
            state="INTERRUPTED",
            finished_at=CREATED_AT,
            error_code="PROCESSING_INTERRUPTED",
        )
    )
    assert failed.started_at is None
