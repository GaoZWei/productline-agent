"""纳管确认Schema、内容绑定、原件复用身份和授权边界。"""

from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.errors import ToolException
from app.knowledge.catalog_import import import_digest, import_keys, import_plan
from app.knowledge.import_preflight import capture_import_files, validate_import_source
from app.knowledge.storage import KnowledgeOriginalStorage
from app.repositories.catalog_import import KnowledgeCatalogImportRepository
from app.repositories.knowledge_import import KnowledgeImportPreflightRepository
from app.schemas.knowledge_import import KnowledgeImportCommand, KnowledgeImportPreflight
from app.schemas.knowledge_management import KnowledgeManagementError
from app.services.catalog_import import KnowledgeCatalogImportService
from app.services.knowledge_import import KnowledgeImportPreflightService
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT
from tests.knowledge.import_preflight_fixtures import INDEX, source_snapshot
from tests.test_knowledge_publication import IDENTITY, PublicationHarness
from tests.test_knowledge_publication import publication as publication


def reviewed() -> KnowledgeImportPreflight:
    """固定语料只读，假向量用于确认源的确定性身份。"""
    files = capture_import_files(DEFAULT_KNOWLEDGE_ROOT)
    return validate_import_source(
        files,
        source_snapshot(files),
        actor=IDENTITY.user_id,
        scope="INTERNAL_REVIEWER",
        expected_index=INDEX,
    )


def command(report: KnowledgeImportPreflight, **updates: object) -> KnowledgeImportCommand:
    """只从审查结果选取明确确认需要的字段，不提交原文或管理身份。"""
    return KnowledgeImportCommand.model_validate(
        {
            "confirmed": True,
            "source_catalog_hash": report.source_catalog_hash,
            "source_fingerprint": report.source_fingerprint,
            "expected_release_revision": report.library_release_revision,
            "confirmation_digest": import_digest(report),
            "idempotency_key": "catalog-import-1",
            **updates,
        }
    )


@pytest.mark.parametrize("value", [False, 0, 1, "true", "false", None])
def test_catalog_import_requires_explicit_confirmation(value: object) -> None:
    with pytest.raises(ValidationError):
        command(reviewed(), confirmed=value)


@pytest.mark.parametrize(
    "field", ["actor_id", "scope", "body", "version_id", "state", "embedding", "original_key"]
)
def test_catalog_import_rejects_client_facts(field: str) -> None:
    with pytest.raises(ValidationError):
        command(reviewed(), **{field: "forged"})


def test_catalog_import_identity_reuses_retry_but_separates_changed_requests() -> None:
    files = capture_import_files(DEFAULT_KNOWLEDGE_ROOT)
    request = command(reviewed())
    first = import_plan(files, request, actor=IDENTITY.user_id, index=INDEX)
    assert first == import_plan(files, request, actor=IDENTITY.user_id, index=INDEX)
    assert len({item.document_id for item in first}) == 14
    assert len({item.version_id for item in first}) == 16
    assert len(import_keys(request)) == 16 and all(len(item) < 128 for item in import_keys(request))
    changed = import_plan(
        files,
        request.model_copy(update={"idempotency_key": "other"}),
        actor=IDENTITY.user_id,
        index=INDEX,
    )
    assert {item.version_id for item in first}.isdisjoint(item.version_id for item in changed)
    other_actor = import_plan(files, request, actor="other-actor", index=INDEX)
    assert first[0].version_id != other_actor[0].version_id
    assert all(
        item.snapshot.body
        == next(
            source.parsed.body
            for source in files.files
            if source.metadata.document_id == item.source_id
        )
        for item in first
    )


@pytest.mark.parametrize("outcomes", [["DENIED"], ["SUCCESS", "DENIED"], ["INVALID_POLICY"]])
async def test_catalog_import_authorizes_before_replay_or_storage(
    publication: PublicationHarness, outcomes: list[str]
) -> None:
    source_repo = Mock(spec=KnowledgeImportPreflightRepository)
    preflight = KnowledgeImportPreflightService(
        source_repo, publication.service.authorizer, index_identity=INDEX
    )
    repository = Mock(spec=KnowledgeCatalogImportRepository)
    repository.replay = AsyncMock()
    storage = Mock(spec=KnowledgeOriginalStorage)
    service = KnowledgeCatalogImportService(repository, preflight, storage)
    publication.outcomes.extend(outcomes)
    with pytest.raises(ToolException):
        await service.confirm(command(reviewed()), identity=IDENTITY)
    repository.replay.assert_not_awaited()
    storage.stage.assert_not_called()


@pytest.mark.parametrize("kind", ["actor", "digest", "release", "source"])
async def test_catalog_import_rejects_stale_confirmation_before_copy(
    publication: PublicationHarness, kind: str
) -> None:
    files = capture_import_files(DEFAULT_KNOWLEDGE_ROOT)
    source_repo = Mock(spec=KnowledgeImportPreflightRepository)
    source_repo.read_source = AsyncMock(return_value=source_snapshot(files))
    preflight = KnowledgeImportPreflightService(
        source_repo, publication.service.authorizer, index_identity=INDEX
    )
    repository = Mock(spec=KnowledgeCatalogImportRepository)
    repository.replay = AsyncMock(return_value=None)
    storage = Mock(spec=KnowledgeOriginalStorage)
    service = KnowledgeCatalogImportService(repository, preflight, storage)
    report = reviewed()
    if kind == "actor":
        report = report.model_copy(update={"checked_by": "other-reviewer"})
    request = command(report)
    if kind == "digest":
        request = request.model_copy(update={"confirmation_digest": "a" * 64})
    elif kind == "release":
        request = request.model_copy(update={"expected_release_revision": 5})
    elif kind == "source":
        request = request.model_copy(update={"source_fingerprint": "a" * 64})
    with pytest.raises(KnowledgeManagementError):
        await service.confirm(request, identity=IDENTITY)
    storage.stage.assert_not_called()
