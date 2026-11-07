"""发布候选与人工确认的内容绑定、过期输入和授权失败隔离。"""

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import date
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.errors import ToolException
from app.repositories.managed_knowledge import (
    ManagedKnowledgeRepository,
    PublicationRead,
    RevisionRead,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge import ManagedKnowledgeRevisionSnapshot
from app.services.knowledge_publication import KnowledgePublicationService
from app.settings import Settings
from tests.knowledge.managed_knowledge_fixtures import DOCUMENT_ID, VERSION_ID, revision_payload

IDENTITY = BusinessIdentity(user_id="publisher", role="REVIEWER")
BODY = "\n# 测试规范\n\n## 要求\n  审查正文 <script>不执行</script>  \n"
TARGET = KnowledgePublicationTarget(
    document_id=DOCUMENT_ID,
    version_id=VERSION_ID,
    expected_revision_no=1,
    expected_row_version=4,
)


@dataclass
class PublicationHarness:
    """真实授权Client配合知识读取替身，失败时断言没有下游调用。"""

    service: KnowledgePublicationService
    repository: Mock
    actions: list[str]
    outcomes: list[str]


@pytest_asyncio.fixture
async def publication() -> AsyncIterator[PublicationHarness]:
    """固定日期由知识读取快照提供，测试不依赖宿主日历或外部服务。"""

    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            body=BODY,
            normalized_hash=hashlib.sha256(BODY.encode()).hexdigest(),
            effective_date=date(2026, 11, 1),
        )
    )
    repository = Mock(spec=ManagedKnowledgeRepository)
    repository.read_publication_candidate = AsyncMock(
        return_value=PublicationRead(
            RevisionRead(
                DOCUMENT_ID, VERSION_ID, 4, 1, "DRAFT", snapshot, snapshot.metadata_digest()
            ),
            None,
            "2.0",
            True,
            date(2026, 11, 6),
        )
    )
    actions: list[str] = []
    outcomes: list[str] = []

    async def authorize(request: httpx.Request) -> httpx.Response:
        """真实Client仍负责用户、Trace、响应结构及上游错误校验。"""

        action = json.loads(request.content)["action"]
        actions.append(action)
        outcome = outcomes.pop(0) if outcomes else "SUCCESS"
        if outcome == "TIMEOUT":
            raise httpx.ReadTimeout("private upstream detail", request=request)
        status = 403 if outcome == "DENIED" else 200
        trace = request.headers["X-Trace-Id"]
        return httpx.Response(
            status,
            headers={"X-Trace-Id": trace},
            json={
                "success": status == 200,
                "code": "SUCCESS" if status == 200 else "PERMISSION_DENIED",
                "message": "private upstream detail",
                "trace_id": trace,
                "retryable": False,
                "data": {
                    "userId": request.headers["X-User-Id"],
                    "action": action,
                    "permissionScope": "INTERNAL_REVIEWER",
                    "confirmationRequired": outcome != "INVALID_POLICY",
                }
                if status == 200
                else None,
            },
        )

    client = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(authorize)
    )
    yield PublicationHarness(
        KnowledgePublicationService(repository, KnowledgeAuthorizationClient(client)),
        repository,
        actions,
        outcomes,
    )
    await client.aclose()


def confirm(digest: str, **updates: object) -> KnowledgePublicationConfirmCommand:
    """确认请求只传候选身份、预期计数和摘要，不传服务端完整快照。"""

    return KnowledgePublicationConfirmCommand.model_validate(
        {
            **TARGET.model_dump(),
            "confirmed": True,
            "confirmation_digest": digest,
            "idempotency_key": "publish-1",
            **updates,
        }
    )


@pytest.mark.parametrize("confirmed", [False, "true", "false", 0, 1, None])
def test_publication_requires_explicit_boolean_confirmation(confirmed: object) -> None:
    with pytest.raises(ValidationError):
        confirm("a" * 64, confirmed=confirmed)


@pytest.mark.parametrize(
    "extra",
    ["actor_id", "action", "permission_scope", "body", "raw_hash", "original_key", "generation_id"],
)
def test_publication_command_rejects_client_facts(extra: str) -> None:
    with pytest.raises(ValidationError):
        confirm("a" * 64, **{extra: "forged"})


async def test_publication_review_then_confirmation_reauthorizes_without_side_effects(
    publication: PublicationHarness,
) -> None:
    service = publication.service
    candidate = await service.prepare(TARGET, identity=IDENTITY)
    assert candidate.preview.body == BODY
    assert candidate.preview.chunks and candidate.preview.is_current_revision
    assert candidate.preview.metadata.is_demo
    assert "original_key" not in candidate.model_dump_json()
    assert "raw_hash" not in candidate.model_dump_json()
    snapshot = await service.validate_confirmation(
        confirm(candidate.confirmation_digest), identity=IDENTITY
    )
    assert (snapshot.actor_id, snapshot.action, snapshot.expected_row_version) == (
        "publisher",
        "PUBLISH",
        4,
    )
    assert snapshot.raw_hash == "a" * 64 and snapshot.normalized_hash is not None
    assert publication.actions == ["PUBLISH", "PUBLISH"]
    assert publication.repository.read_publication_candidate.await_count == 2
    # 不能用READ授权代替PUBLISH，也不能在准备或确认校验时激活恢复和写记录。
    assert {call[0] for call in publication.repository.method_calls} == {
        "read_publication_candidate"
    }
    publication.repository.read_publication_candidate.assert_awaited_with(
        DOCUMENT_ID, VERSION_ID, 1, "INTERNAL_REVIEWER"
    )


@pytest.mark.parametrize("outcome", ["DENIED", "TIMEOUT", "INVALID_POLICY"])
async def test_publication_authorization_failure_does_not_read_knowledge(
    publication: PublicationHarness, outcome: str
) -> None:
    publication.outcomes.extend([outcome] * (2 if outcome == "TIMEOUT" else 1))
    with pytest.raises((ToolException, KnowledgeManagementError)):
        await publication.service.prepare(TARGET, identity=IDENTITY)
    publication.repository.read_publication_candidate.assert_not_awaited()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"publication_state": "PUBLISHED"}, "PUBLICATION_REQUIRES_DRAFT"),
        ({"publication_state": "DISABLED"}, "PUBLICATION_REQUIRES_DRAFT"),
        ({"publication_state": "SUPERSEDED"}, "PUBLICATION_REQUIRES_DRAFT"),
        ({"publication_state": "HISTORICAL"}, "PUBLICATION_REQUIRES_DRAFT"),
        ({"row_version": 5}, "STALE_DOCUMENT"),
        ({"current_revision_no": 2}, "STALE_REVISION"),
    ],
)
async def test_publication_rejects_stale_or_sealed_candidate(
    publication: PublicationHarness, change: dict[str, object], code: str
) -> None:
    original = publication.repository.read_publication_candidate.return_value
    publication.repository.read_publication_candidate.return_value = replace(
        original, revision=replace(original.revision, **change)
    )
    with pytest.raises(KnowledgeManagementError, match=code):
        await publication.service.prepare(TARGET, identity=IDENTITY)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"parse_succeeded": False}, "PUBLICATION_PARSE_NOT_READY"),
        ({"today": date(2026, 10, 31)}, "PUBLICATION_NOT_EFFECTIVE"),
        ({"specification_version": "9.9"}, "KNOWLEDGE_DATA_INVALID"),
        ({"previous_version_id": VERSION_ID}, "KNOWLEDGE_DATA_INVALID"),
    ],
)
async def test_publication_rejects_unready_or_invalid_facts(
    publication: PublicationHarness, change: dict[str, object], code: str
) -> None:
    original = publication.repository.read_publication_candidate.return_value
    publication.repository.read_publication_candidate.return_value = replace(original, **change)
    with pytest.raises(KnowledgeManagementError, match=code):
        await publication.service.prepare(TARGET, identity=IDENTITY)


@pytest.mark.parametrize("changed", ["actor", "raw", "metadata", "body", "pointer", "digest"])
async def test_publication_confirmation_cannot_reuse_other_reviewed_input(
    publication: PublicationHarness, changed: str
) -> None:
    candidate = await publication.service.prepare(TARGET, identity=IDENTITY)
    original = publication.repository.read_publication_candidate.return_value
    identity = IDENTITY
    digest = candidate.confirmation_digest
    if changed == "actor":
        identity = BusinessIdentity(user_id="another-reviewer", role="REVIEWER")
    elif changed == "pointer":
        original = replace(original, previous_version_id="VER-" + "2" * 32)
    elif changed == "digest":
        digest = "0" * 64
    else:
        data = original.revision.snapshot.model_dump()
        if changed == "raw":
            data["raw_hash"] = "b" * 64
        elif changed == "metadata":
            data["change_summary"] = "修改后的变更说明"
        else:
            data["body"] = BODY + "新要求\n"
            data["normalized_hash"] = hashlib.sha256(data["body"].encode()).hexdigest()
        snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(data)
        original = replace(
            original,
            revision=replace(
                original.revision, snapshot=snapshot, metadata_hash=snapshot.metadata_digest()
            ),
        )
    publication.repository.read_publication_candidate.return_value = original
    with pytest.raises(KnowledgeManagementError, match="STALE_CONFIRMATION"):
        await publication.service.validate_confirmation(confirm(digest), identity=identity)


async def test_publication_confirmation_permission_revocation_is_not_cached(
    publication: PublicationHarness,
) -> None:
    candidate = await publication.service.prepare(TARGET, identity=IDENTITY)
    publication.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await publication.service.validate_confirmation(
            confirm(candidate.confirmation_digest), identity=IDENTITY
        )
    assert publication.repository.read_publication_candidate.await_count == 1


async def test_publication_database_failure_is_safe(publication: PublicationHarness) -> None:
    publication.repository.read_publication_candidate.side_effect = SQLAlchemyError("private path")
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
        await publication.service.prepare(TARGET, identity=IDENTITY)


@pytest.mark.parametrize(
    ("effective", "expiry", "code"),
    [
        (date(2026, 11, 6), date(2026, 11, 6), None),
        (date(2026, 11, 1), date(2026, 11, 5), "PUBLICATION_EXPIRED"),
    ],
)
async def test_publication_uses_inclusive_validity_dates(
    publication: PublicationHarness, effective: date, expiry: date, code: str | None
) -> None:
    original = publication.repository.read_publication_candidate.return_value
    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        {
            **original.revision.snapshot.model_dump(),
            "effective_date": effective,
            "expiry_date": expiry,
        }
    )
    publication.repository.read_publication_candidate.return_value = replace(
        original,
        revision=replace(
            original.revision, snapshot=snapshot, metadata_hash=snapshot.metadata_digest()
        ),
    )
    if code:
        with pytest.raises(KnowledgeManagementError, match=code):
            await publication.service.prepare(TARGET, identity=IDENTITY)
    else:
        candidate = await publication.service.prepare(TARGET, identity=IDENTITY)
        await publication.service.validate_confirmation(
            confirm(candidate.confirmation_digest), identity=IDENTITY
        )
        # 即使正文不变，确认跨过失效日也必须失败。
        publication.repository.read_publication_candidate.return_value = replace(
            publication.repository.read_publication_candidate.return_value, today=date(2026, 11, 7)
        )
        with pytest.raises(KnowledgeManagementError, match="PUBLICATION_EXPIRED"):
            await publication.service.validate_confirmation(
                confirm(candidate.confirmation_digest), identity=IDENTITY
            )


async def test_publication_accept_reauthorizes_replay_and_uses_server_index(
    publication: PublicationHarness,
) -> None:
    index = KnowledgePublicationIndexIdentity.from_settings(Settings(environment="test"))
    publication.service.index_identity = index
    result = KnowledgePublicationAcceptance(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        revision_no=1,
        operation_id="OP-" + "1" * 32,
        operation_state="CONFIRMED",
        generation_id="GEN-" + "1" * 32,
        generation_state="BUILDING",
        task_id="TASK-" + "1" * 32,
        task_state="QUEUED",
        reserved_row_version=5,
        error_code=None,
        replayed=False,
    )
    publication.repository.accept_publication = AsyncMock(return_value=result)
    command = confirm("a" * 64)
    first = await publication.service.accept(command, identity=IDENTITY, trace_id="publish-accept")
    publication.repository.accept_publication.return_value = result.model_copy(
        update={"replayed": True}
    )
    replay = await publication.service.accept(command, identity=IDENTITY, trace_id="publish-replay")
    assert not first.replayed and replay.replayed
    assert replay.operation_id == first.operation_id
    assert publication.actions == ["PUBLISH", "PUBLISH"]
    publication.repository.read_publication_candidate.assert_not_awaited()
    publication.repository.accept_publication.assert_awaited_with(
        command,
        actor=IDENTITY.user_id,
        scope="INTERNAL_REVIEWER",
        index=index,
        trace_id="publish-replay",
        owner_id=publication.service.owner_id,
    )
    publication.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await publication.service.accept(command, identity=IDENTITY)
    assert publication.repository.accept_publication.await_count == 2


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (SQLAlchemyError("private connection"), "KNOWLEDGE_PERSISTENCE_UNAVAILABLE"),
        (IntegrityError("private SQL", {}, ValueError("private")), "KNOWLEDGE_CONFLICT"),
    ],
)
async def test_publication_accept_maps_transaction_errors(
    publication: PublicationHarness, error: SQLAlchemyError, code: str
) -> None:
    publication.repository.accept_publication = AsyncMock(side_effect=error)
    with pytest.raises(KnowledgeManagementError, match=code):
        await publication.service.accept(confirm("a" * 64), identity=IDENTITY)
