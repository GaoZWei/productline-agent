"""最终发布编排的重复授权、完整证据校验及安全异常边界。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.errors import ToolException
from app.knowledge.index_build import index_chunk_records, parse_index_input
from app.repositories.knowledge_publication_finalize import (
    KnowledgePublicationFinalizeRepository,
    PublicationFinalizeRead,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationReceipt
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeGenerationRecord,
)
from app.services.knowledge_publication_finalize import KnowledgePublicationFinalizeService
from tests.knowledge.managed_knowledge_fixtures import generation_payload
from tests.test_knowledge_index_build import INDEX, BuildHarness, valid_generation
from tests.test_knowledge_index_build import build as build
from tests.test_knowledge_publication import IDENTITY, PublicationHarness
from tests.test_knowledge_publication import publication as publication


@dataclass
class FinalizeHarness:
    """保留真实Java Client和完整证据校验，只替换发布Repository。"""

    service: KnowledgePublicationFinalizeService
    repository: Mock
    prepared: PublicationFinalizeRead
    receipt: KnowledgePublicationReceipt


@pytest.fixture
def finalize(build: BuildHarness) -> FinalizeHarness:
    """固定合法向量和时区时间，不依赖网络或宿主日期。"""

    claim = build.claim
    snapshot = claim.record.revision.snapshot
    confirmation = ManagedKnowledgeConfirmation(
        actor_id=IDENTITY.user_id,
        action="PUBLISH",
        document_id=claim.record.revision.document_id,
        version_id=snapshot.version_id,
        revision_no=1,
        raw_hash=snapshot.raw_hash,
        normalized_hash=snapshot.normalized_hash,
        metadata_hash=snapshot.metadata_digest(),
        expected_row_version=3,
        generation_id=claim.generation_id,
    )
    chunks = index_chunk_records(claim, parse_index_input(claim), valid_generation(claim))
    generation = ManagedKnowledgeGenerationRecord.model_validate(
        generation_payload(
            generation_id=claim.generation_id,
            version_id=snapshot.version_id,
            state="READY",
            chunk_count=len(chunks),
            finished_at=datetime(2026, 11, 6, tzinfo=UTC),
        )
    )
    prepared = PublicationFinalizeRead(
        "OP-" + "1" * 32, confirmation, claim.record, INDEX, claim.generation_id, generation, chunks
    )
    receipt = KnowledgePublicationReceipt(
        operation_id=prepared.operation_id,
        document_id=confirmation.document_id,
        version_id=confirmation.version_id,
        revision_no=1,
        generation_id=claim.generation_id,
        replaced_version_id=None,
        publication_state="PUBLISHED",
        published_at=datetime(2026, 11, 6, tzinfo=UTC),
        is_current_version=True,
        row_version=5,
        release_revision=1,
        source_mode="LEGACY",
        replayed=False,
    )
    repository = Mock(spec=KnowledgePublicationFinalizeRepository)
    repository.prepare_finalization = AsyncMock(return_value=prepared)
    repository.commit_finalization = AsyncMock(return_value=receipt)
    repository.reject_finalization = AsyncMock()
    return FinalizeHarness(
        KnowledgePublicationFinalizeService(
            repository, build.service.authorizer, index_identity=INDEX
        ),
        repository,
        prepared,
        receipt,
    )


async def test_finalization_validates_then_reauthorizes_and_replay_is_readonly(
    finalize: FinalizeHarness,
    publication: PublicationHarness,
) -> None:
    assert (
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
        == finalize.receipt
    )
    assert publication.actions == ["PUBLISH", "PUBLISH"]
    assert finalize.repository.commit_finalization.call_args.args[0] == finalize.prepared
    assert len(finalize.repository.commit_finalization.call_args.args[1]) == 64
    finalize.repository.prepare_finalization.return_value = finalize.receipt.model_copy(
        update={"replayed": True}
    )
    finalize.service.index_identity = None
    assert (
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
    ).replayed
    assert publication.actions == ["PUBLISH", "PUBLISH", "PUBLISH"]
    assert finalize.repository.commit_finalization.await_count == 1
    finalize.repository.reject_finalization.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["DENIED", "TIMEOUT", "INVALID_POLICY"])
async def test_finalization_initial_authorization_failure_never_reads_knowledge(
    finalize: FinalizeHarness,
    publication: PublicationHarness,
    outcome: str,
) -> None:
    publication.outcomes.extend([outcome] * 2)
    with pytest.raises((ToolException, KnowledgeManagementError)):
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
    finalize.repository.prepare_finalization.assert_not_awaited()
    finalize.repository.commit_finalization.assert_not_awaited()


async def test_finalization_final_authorization_revocation_prevents_commit(
    finalize: FinalizeHarness,
    publication: PublicationHarness,
) -> None:
    async def revoke(*args: object, **kwargs: object) -> PublicationFinalizeRead:
        """在已授权准备后撤销权限，最终事务必须被阻断。"""

        publication.outcomes.append("DENIED")
        return finalize.prepared

    finalize.repository.prepare_finalization.side_effect = revoke
    with pytest.raises(ToolException):
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
    finalize.repository.commit_finalization.assert_not_awaited()
    finalize.repository.reject_finalization.assert_not_awaited()


async def test_finalization_invalid_evidence_records_safe_failure(
    finalize: FinalizeHarness,
) -> None:
    damaged = finalize.prepared.chunks[0].model_copy(update={"content": "外来正文"})
    from dataclasses import replace

    finalize.repository.prepare_finalization.return_value = replace(
        finalize.prepared, chunks=(damaged, *finalize.prepared.chunks[1:])
    )
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_DATA_INVALID"):
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
    finalize.repository.reject_finalization.assert_awaited_with(
        finalize.prepared.operation_id,
        actor=IDENTITY.user_id,
        scope="INTERNAL_REVIEWER",
        stale=False,
    )
    finalize.repository.commit_finalization.assert_not_awaited()


@pytest.mark.parametrize(
    ("code", "stale"),
    [
        ("STALE_DOCUMENT", True),
        ("STALE_CONFIRMATION", True),
        ("PUBLICATION_EXPIRED", True),
        ("KNOWLEDGE_DATA_INVALID", False),
    ],
)
async def test_finalization_recheck_failure_is_recorded(
    finalize: FinalizeHarness, code: str, stale: bool
) -> None:
    finalize.repository.commit_finalization.side_effect = KnowledgeManagementError(code)
    with pytest.raises(KnowledgeManagementError, match=code):
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
    assert finalize.repository.reject_finalization.call_args.kwargs["stale"] is stale


@pytest.mark.parametrize("stage", ["prepare_finalization", "commit_finalization"])
async def test_finalization_sql_failure_is_safe_and_does_not_fake_terminal_state(
    finalize: FinalizeHarness, stage: str
) -> None:
    getattr(finalize.repository, stage).side_effect = SQLAlchemyError("private connection detail")
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
    finalize.repository.reject_finalization.assert_not_awaited()


async def test_finalization_integrity_conflict_is_safe(finalize: FinalizeHarness) -> None:
    finalize.repository.commit_finalization.side_effect = IntegrityError(
        "private SQL", {}, ValueError("private")
    )
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_CONFLICT"):
        await finalize.service.finalize(finalize.prepared.operation_id, identity=IDENTITY)
