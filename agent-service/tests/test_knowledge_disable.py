"""停用Schema和应用边界：明确确认、独立授权、回执重放与安全异常。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.errors import ToolException
from app.knowledge.disable import disable_digest
from app.repositories.knowledge_disable import DisableRead, KnowledgeDisableRepository
from app.schemas.knowledge_disable import (
    KnowledgeDisableCommand,
    KnowledgeDisableReceipt,
    KnowledgeDisableTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge import ManagedKnowledgeMetadata
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation
from app.services.knowledge_disable import KnowledgeDisableService
from tests.knowledge.managed_knowledge_fixtures import DOCUMENT_ID, VERSION_ID
from tests.test_knowledge_publication import IDENTITY, PublicationHarness
from tests.test_knowledge_publication import publication as publication

TARGET = KnowledgeDisableTarget(
    document_id=DOCUMENT_ID, version_id=VERSION_ID, expected_revision_no=1, expected_row_version=4
)


def confirmation(**updates: object) -> KnowledgeDisableCommand:
    """停用请求只提交目标、计数、摘要和明确动作，不包含服务端事实。"""

    return KnowledgeDisableCommand.model_validate(
        {
            **TARGET.model_dump(),
            "confirmed": True,
            "confirmation_digest": "a" * 64,
            "idempotency_key": "disable-one",
            **updates,
        }
    )


@dataclass
class DisableHarness:
    """真实授权Client与知识读取替身，模型及文件系统均不参与停用。"""

    service: KnowledgeDisableService
    repository: Mock
    snapshot: ManagedKnowledgeConfirmation
    receipt: KnowledgeDisableReceipt


@pytest.fixture
def disable(publication: PublicationHarness) -> DisableHarness:
    """固定时区时间与发布身份，复用现有Java响应严格校验。"""

    snapshot = publication.repository.read_publication_candidate.return_value.revision.snapshot
    fact = ManagedKnowledgeConfirmation(
        actor_id=IDENTITY.user_id,
        action="DISABLE",
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        revision_no=1,
        raw_hash=snapshot.raw_hash,
        normalized_hash=snapshot.normalized_hash,
        metadata_hash=snapshot.metadata_digest(),
        expected_row_version=4,
        previous_version_id=VERSION_ID,
        generation_id="GEN-" + "1" * 32,
    )
    metadata = ManagedKnowledgeMetadata.model_validate(
        snapshot.model_dump(include=set(ManagedKnowledgeMetadata.model_fields))
    )
    repository = Mock(spec=KnowledgeDisableRepository)
    repository.prepare_disable = AsyncMock(
        return_value=DisableRead(fact, metadata, datetime(2026, 11, 6, tzinfo=UTC))
    )
    receipt = KnowledgeDisableReceipt(
        operation_id="OP-" + "2" * 32,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        revision_no=1,
        generation_id="GEN-" + "1" * 32,
        disabled_at=datetime(2026, 11, 7, tzinfo=UTC),
        current_version_id=None,
        row_version=5,
        release_revision=2,
        source_mode="LEGACY",
        replayed=False,
    )
    repository.disable = AsyncMock(return_value=receipt)
    return DisableHarness(
        KnowledgeDisableService(repository, publication.service.authorizer),
        repository,
        fact,
        receipt,
    )


@pytest.mark.parametrize("confirmed", [False, "true", "false", 0, 1, None])
def test_disable_requires_explicit_boolean_confirmation(confirmed: object) -> None:
    with pytest.raises(ValidationError):
        confirmation(confirmed=confirmed)


@pytest.mark.parametrize(
    "field",
    ["actor_id", "permission_scope", "action", "publication_state", "body", "generation_id"],
)
def test_disable_rejects_client_facts(field: str) -> None:
    with pytest.raises(ValidationError):
        confirmation(**{field: "forged"})


async def test_disable_preparation_commit_and_replay_reauthorize(
    disable: DisableHarness, publication: PublicationHarness
) -> None:
    candidate = await disable.service.prepare(TARGET, identity=IDENTITY)
    assert candidate.confirmation_digest == disable_digest(disable.snapshot)
    assert candidate.action == "DISABLE"
    assert all(
        key not in candidate.model_dump_json() for key in ("raw_hash", "body", "original_key")
    )
    command = confirmation(confirmation_digest=candidate.confirmation_digest)
    assert await disable.service.disable(command, identity=IDENTITY) == disable.receipt
    disable.repository.disable.return_value = disable.receipt.model_copy(update={"replayed": True})
    assert (await disable.service.disable(command, identity=IDENTITY)).replayed
    assert publication.actions == ["DISABLE", "DISABLE", "DISABLE"]
    disable.repository.disable.assert_awaited_with(
        command, actor=IDENTITY.user_id, scope="INTERNAL_REVIEWER"
    )


@pytest.mark.parametrize("outcome", ["DENIED", "TIMEOUT", "INVALID_POLICY"])
async def test_disable_authorization_failure_never_reads_or_writes(
    disable: DisableHarness, publication: PublicationHarness, outcome: str
) -> None:
    publication.outcomes.extend([outcome] * 2)
    with pytest.raises((ToolException, KnowledgeManagementError)):
        await disable.service.prepare(TARGET, identity=IDENTITY)
    disable.repository.prepare_disable.assert_not_awaited()
    disable.repository.disable.assert_not_awaited()


async def test_disable_permission_revoked_after_review_prevents_write(
    disable: DisableHarness, publication: PublicationHarness
) -> None:
    candidate = await disable.service.prepare(TARGET, identity=IDENTITY)
    publication.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await disable.service.disable(
            confirmation(confirmation_digest=candidate.confirmation_digest), identity=IDENTITY
        )
    disable.repository.disable.assert_not_awaited()


@pytest.mark.parametrize(
    ("stage", "exception", "expected"),
    [
        ("prepare", SQLAlchemyError("private connection"), "KNOWLEDGE_PERSISTENCE_UNAVAILABLE"),
        ("disable", SQLAlchemyError("private SQL"), "KNOWLEDGE_PERSISTENCE_UNAVAILABLE"),
        ("disable", IntegrityError("private SQL", {}, ValueError("private")), "KNOWLEDGE_CONFLICT"),
    ],
)
async def test_disable_database_errors_are_safe(
    disable: DisableHarness, stage: str, exception: SQLAlchemyError, expected: str
) -> None:
    if stage == "prepare":
        disable.repository.prepare_disable.side_effect = exception
    else:
        disable.repository.disable.side_effect = exception
    with pytest.raises(KnowledgeManagementError, match=expected):
        if stage == "prepare":
            await disable.service.prepare(TARGET, identity=IDENTITY)
        else:
            await disable.service.disable(confirmation(), identity=IDENTITY)
