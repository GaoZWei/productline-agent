"""真实隔离知识库验证发布候选归属、当前修订、哈希及无写入边界。"""

from datetime import date

import pytest
from sqlalchemy import func, select, update

from app.database import Database
from app.errors import ToolException
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationTarget,
)
from app.services.knowledge_publication import KnowledgePublicationService
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import byte_chunks
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
    revision_command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management


@pytest.mark.integration
async def test_knowledge_management_publication_review_revision_and_no_publication_writes(
    management: ManagementHarness, managed_database: Database
) -> None:
    service = KnowledgePublicationService(
        management.service.repository, management.service.authorizer
    )
    initial_command = command(
        metadata={**command().metadata.model_dump(), "effective_date": date(1970, 1, 1)}
    )
    uploaded = await management.service.upload(
        initial_command, byte_chunks("# 测试规范\n\n## 要求\n旧正文".encode()), identity=IDENTITY
    )
    target = KnowledgePublicationTarget(
        document_id=uploaded.document_id,
        version_id=uploaded.version_id,
        expected_revision_no=1,
        expected_row_version=uploaded.row_version,
    )
    candidate = await service.prepare(target, identity=IDENTITY)
    confirm = KnowledgePublicationConfirmCommand(
        **target.model_dump(),
        confirmed=True,
        confirmation_digest=candidate.confirmation_digest,
        idempotency_key="publish-draft-1",
    )
    snapshot = await service.validate_confirmation(confirm, identity=IDENTITY)
    assert snapshot.actor_id == IDENTITY.user_id
    assert snapshot.previous_version_id is None and snapshot.action == "PUBLISH"
    assert candidate.preview.body.endswith("旧正文")
    assert management.actions == ["UPLOAD", "PUBLISH", "PUBLISH"]
    management.denied.add("PUBLISH")
    with pytest.raises(ToolException):
        await service.validate_confirmation(confirm, identity=IDENTITY)
    management.denied.clear()
    # 修正草稿后，旧候选和即使手动更新计数的旧确认摘要都不能继续使用。
    revised = await management.service.upload(
        revision_command(
            initial_command, uploaded.document_id, uploaded.version_id, uploaded.row_version, 1
        ),
        byte_chunks("# 测试规范\n\n## 要求\n新正文".encode()),
        identity=IDENTITY,
    )
    with pytest.raises(KnowledgeManagementError, match="STALE_DOCUMENT"):
        await service.validate_confirmation(confirm, identity=IDENTITY)
    updated_confirm = KnowledgePublicationConfirmCommand.model_validate(
        {
            **confirm.model_dump(),
            "expected_revision_no": 2,
            "expected_row_version": revised.row_version,
        }
    )
    with pytest.raises(KnowledgeManagementError, match="STALE_CONFIRMATION"):
        await service.validate_confirmation(updated_confirm, identity=IDENTITY)
    async with managed_database.session() as session:
        for model, count in ((Operation, 2), (Task, 2), (Generation, 0), (Chunk, 0)):
            assert await session.scalar(select(func.count()).select_from(model)) == count
        document = await session.get(Document, uploaded.document_id)
        library = await session.get(Library, "DEFAULT")
        assert document is not None and document.current_version_id is None
        assert document.row_version == revised.row_version
        assert (
            library is not None
            and library.source_mode == "LEGACY"
            and library.release_revision == 0
        )


@pytest.mark.integration
async def test_knowledge_management_publication_scope_ownership_parse_and_integrity(
    management: ManagementHarness, managed_database: Database
) -> None:
    repository = management.service.repository
    service = KnowledgePublicationService(repository, management.service.authorizer)
    uploaded = await management.service.upload(
        command(metadata={**command().metadata.model_dump(), "effective_date": date(1970, 1, 1)}),
        byte_chunks("# 测试规范\n\n正文".encode()),
        identity=IDENTITY,
    )
    target = KnowledgePublicationTarget(
        document_id=uploaded.document_id,
        version_id=uploaded.version_id,
        expected_revision_no=1,
        expected_row_version=uploaded.row_version,
    )
    for document_id, version_id, revision_no, scope in (
        ("DOC-" + "0" * 32, uploaded.version_id, 1, "INTERNAL_REVIEWER"),
        (uploaded.document_id, "VER-" + "0" * 32, 1, "INTERNAL_REVIEWER"),
        (uploaded.document_id, uploaded.version_id, 2, "INTERNAL_REVIEWER"),
        (uploaded.document_id, uploaded.version_id, 1, "OUT_OF_SCOPE"),
    ):
        with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
            await repository.read_publication_candidate(document_id, version_id, revision_no, scope)
    record = await repository.read_publication_candidate(
        uploaded.document_id, uploaded.version_id, 1, "INTERNAL_REVIEWER"
    )
    assert isinstance(record.today, date) and record.parse_succeeded
    async with managed_database.session() as session, session.begin():
        await session.execute(
            update(Task)
            .where(Task.task_id == uploaded.task_id)
            .values(state="FAILED", error_code="PARSE_FAILED")
        )
    with pytest.raises(KnowledgeManagementError, match="PUBLICATION_PARSE_NOT_READY"):
        await service.prepare(target, identity=IDENTITY)
    async with managed_database.session() as session, session.begin():
        await session.execute(
            update(Task)
            .where(Task.task_id == uploaded.task_id)
            .values(state="SUCCEEDED", error_code=None)
        )
        await session.execute(
            update(Revision)
            .where(Revision.version_id == uploaded.version_id)
            .values(metadata_hash="0" * 64)
        )
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_DATA_INVALID"):
        await service.validate_confirmation(
            KnowledgePublicationConfirmCommand(
                **target.model_dump(),
                confirmed=True,
                confirmation_digest="0" * 64,
                idempotency_key="publish-corrupt",
            ),
            identity=IDENTITY,
        )
