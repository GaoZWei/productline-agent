"""人工索引重试契约、独立授权及接收重放，不访问真实模型或数据库。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ToolException
from app.repositories.knowledge_index_retry import IndexRetryRead, KnowledgeIndexRetryRepository
from app.schemas.knowledge_index_retry import (
    KnowledgeIndexRetryCommand,
    KnowledgeIndexRetryReceipt,
    KnowledgeIndexRetryTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeTaskRecord,
)
from app.services.knowledge_index_retry import KnowledgeIndexRetryService
from tests.knowledge.managed_knowledge_fixtures import DOCUMENT_ID, TASK_ID, VERSION_ID
from tests.test_knowledge_index_build import INDEX
from tests.test_knowledge_publication import IDENTITY, PublicationHarness
from tests.test_knowledge_publication import publication as publication

TARGET = KnowledgeIndexRetryTarget(
    document_id=DOCUMENT_ID,
    version_id=VERSION_ID,
    expected_revision_no=1,
    expected_row_version=4,
    task_id=TASK_ID,
)


def confirmation(**updates: object) -> KnowledgeIndexRetryCommand:
    """请求只指定所见失败目标与确认，不接收用户自报状态、计数或索引配置。"""

    return KnowledgeIndexRetryCommand.model_validate(
        {
            **TARGET.model_dump(),
            "confirmed": True,
            "confirmation_digest": "a" * 64,
            "idempotency_key": "retry-one",
            **updates,
        }
    )


@dataclass
class RetryHarness:
    """复用真实Java Client，SQL与任务分配通过可观察替身隔离。"""

    service: KnowledgeIndexRetryService
    repository: Mock
    receipt: KnowledgeIndexRetryReceipt


@pytest.fixture
def retry(publication: PublicationHarness) -> RetryHarness:
    """输入元数据和失败时间固定，不依赖宿主日期或外部服务。"""

    record = publication.repository.read_publication_candidate.return_value
    snapshot = record.revision.snapshot
    fact = ManagedKnowledgeConfirmation(
        actor_id=IDENTITY.user_id,
        action="RETRY_INDEX",
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        revision_no=1,
        expected_row_version=4,
        raw_hash=snapshot.raw_hash,
        normalized_hash=snapshot.normalized_hash,
        metadata_hash=snapshot.metadata_digest(),
        task_id=TASK_ID,
        generation_id="GEN-" + "1" * 32,
    )
    at = datetime(2026, 11, 7, tzinfo=UTC)
    source = ManagedKnowledgeTaskRecord(
        task_id=TASK_ID,
        operation_id="OP-" + "1" * 32,
        operation_action="PUBLISH",
        version_id=VERSION_ID,
        revision_no=1,
        task_type="INDEX",
        generation_id=fact.generation_id,
        state="FAILED",
        owner_id="old-worker",
        error_code="TOOL_TIMEOUT",
        trace_id="retry-unit",
        created_at=at,
        started_at=at,
        finished_at=at,
    )
    receipt = KnowledgeIndexRetryReceipt(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        revision_no=1,
        operation_id="OP-" + "2" * 32,
        operation_state="CONFIRMED",
        generation_id="GEN-" + "2" * 32,
        generation_state="BUILDING",
        task_id="TASK-" + "2" * 32,
        task_state="QUEUED",
        error_code=None,
        reserved_row_version=5,
        replayed=False,
        retry_of_task_id=TASK_ID,
        attempt_no=2,
    )
    repository = Mock(spec=KnowledgeIndexRetryRepository)
    repository.prepare_retry = AsyncMock(return_value=IndexRetryRead(fact, record, source, INDEX))
    repository.accept_retry = AsyncMock(return_value=receipt)
    return RetryHarness(
        KnowledgeIndexRetryService(
            repository, publication.service.authorizer, index_identity=INDEX, owner_id="new-worker"
        ),
        repository,
        receipt,
    )


@pytest.mark.parametrize("confirmed", [False, "true", "false", 0, 1, None])
def test_index_retry_requires_explicit_confirmation(confirmed: object) -> None:
    with pytest.raises(ValidationError):
        confirmation(confirmed=confirmed)


@pytest.mark.parametrize(
    "field",
    [
        "actor_id",
        "action",
        "permission_scope",
        "state",
        "generation_id",
        "attempt_no",
        "index",
        "body",
    ],
)
def test_index_retry_rejects_client_facts(field: str) -> None:
    with pytest.raises(ValidationError):
        confirmation(**{field: "forged"})


async def test_index_retry_review_acceptance_and_replay_use_retry_authority(
    retry: RetryHarness, publication: PublicationHarness
) -> None:
    candidate = await retry.service.prepare(TARGET, identity=IDENTITY)
    assert candidate.source_state == "FAILED" and candidate.source_error_code == "TOOL_TIMEOUT"
    command = confirmation(confirmation_digest=candidate.confirmation_digest)
    assert await retry.service.retry(command, identity=IDENTITY) == retry.receipt
    retry.repository.accept_retry.return_value = retry.receipt.model_copy(update={"replayed": True})
    retry.service.index_identity = None
    assert (await retry.service.retry(command, identity=IDENTITY, trace_id="retry-replay")).replayed
    assert publication.actions == ["RETRY_INDEX", "RETRY_INDEX", "RETRY_INDEX"]
    retry.repository.accept_retry.assert_awaited_with(
        command,
        actor=IDENTITY.user_id,
        scope="INTERNAL_REVIEWER",
        index=None,
        owner_id="new-worker",
        trace_id="retry-replay",
    )


@pytest.mark.parametrize("outcome", ["DENIED", "TIMEOUT", "INVALID_POLICY"])
async def test_index_retry_denied_authorization_never_reads_or_writes(
    retry: RetryHarness, publication: PublicationHarness, outcome: str
) -> None:
    publication.outcomes.extend([outcome] * 2)
    with pytest.raises((ToolException, KnowledgeManagementError)):
        await retry.service.prepare(TARGET, identity=IDENTITY)
    retry.repository.prepare_retry.assert_not_awaited()
    retry.repository.accept_retry.assert_not_awaited()


async def test_index_retry_revoked_after_review_stops_acceptance(
    retry: RetryHarness, publication: PublicationHarness
) -> None:
    candidate = await retry.service.prepare(TARGET, identity=IDENTITY)
    publication.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await retry.service.retry(
            confirmation(confirmation_digest=candidate.confirmation_digest), identity=IDENTITY
        )
    retry.repository.accept_retry.assert_not_awaited()


async def test_index_retry_sql_failure_is_safe(retry: RetryHarness) -> None:
    retry.repository.accept_retry.side_effect = SQLAlchemyError("private connection detail")
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
        await retry.service.retry(confirmation(), identity=IDENTITY)
