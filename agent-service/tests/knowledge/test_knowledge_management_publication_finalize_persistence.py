"""真实管理数据、候选向量和发布事务的原子性、幂等及历史保留验收。"""

import asyncio
import hashlib

import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.errors import ToolException
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.knowledge_publication_finalize import (
    KnowledgePublicationFinalizeRepository,
    PublicationFinalizeRead,
    finalization_hash,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationReceipt,
    KnowledgePublicationTarget,
)
from app.services.knowledge_publication import KnowledgePublicationService
from app.services.knowledge_publication_finalize import KnowledgePublicationFinalizeService
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import byte_chunks
from tests.knowledge.test_knowledge_management_index_build_persistence import BODY, prepared
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
    revision_command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.test_knowledge_index_build import INDEX


def finalizer(
    management: ManagementHarness, database: Database
) -> KnowledgePublicationFinalizeService:
    """与上传/构建共享真实授权Client，最终发布不创建任何模型Client。"""

    return KnowledgePublicationFinalizeService(
        KnowledgePublicationFinalizeRepository(database),
        management.service.authorizer,
        index_identity=INDEX,
    )


async def ready(
    management: ManagementHarness, database: Database
) -> KnowledgePublicationAcceptance:
    """执行真实批量生成器及隔离写入，外部向量传输沿用替身。"""

    builder, accepted, _, _ = await prepared(management, database)
    assert accepted.task_id is not None
    assert await builder.process(accepted.task_id, identity=IDENTITY)
    return accepted


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_first_release_replay_and_permission(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    accepted = await ready(management, managed_database)
    service = finalizer(management, managed_database)
    result = await service.finalize(accepted.operation_id, identity=IDENTITY)
    assert (
        result.publication_state == "PUBLISHED"
        and result.is_current_version
        and not result.replayed
    )
    assert result.row_version == accepted.reserved_row_version + 1 and result.release_revision == 1
    assert result.source_mode == "LEGACY" and result.replaced_version_id is None
    service.index_identity = None
    replay = await service.finalize(accepted.operation_id, identity=IDENTITY)
    assert replay.model_copy(update={"replayed": False}) == result
    management.denied.add("PUBLISH")
    with pytest.raises(ToolException):
        await service.finalize(accepted.operation_id, identity=IDENTITY)
    async with managed_database.session() as session:
        operation = await session.get(Operation, accepted.operation_id)
        assert (
            operation is not None
            and operation.state == "SUCCEEDED"
            and operation.result_id == accepted.version_id
        )
        task = await session.get(Task, accepted.task_id)
        assert task is not None and task.state == "SUCCEEDED"
        library = await session.get(Library, "DEFAULT")
        assert (
            library is not None
            and library.source_mode == "LEGACY"
            and library.release_revision == 1
        )


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_replacement_and_old_citation_unchanged(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    builder, accepted, _, _ = await prepared(management, managed_database)
    assert accepted.task_id is not None
    assert await builder.process(accepted.task_id, identity=IDENTITY)
    service = finalizer(management, managed_database)
    first = await service.finalize(accepted.operation_id, identity=IDENTITY)
    async with managed_database.session() as session:
        old_chunks = [
            (chunk.chunk_id, chunk.content, tuple(float(v) for v in chunk.embedding))
            for chunk in (
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.generation_id == accepted.generation_id)
                    .order_by(Chunk.chunk_index)
                )
            ).all()
        ]
    original = await management.service.read_original(first.version_id, 1, identity=IDENTITY)
    uploaded = await management.service.upload(
        command(
            document_id=first.document_id,
            expected_row_version=first.row_version,
            idempotency_key="upload-release-two",
            metadata={**command().metadata.model_dump(), "specification_version": "2.0"},
        ),
        byte_chunks((BODY + "新增要求\n").encode()),
        identity=IDENTITY,
    )
    publication = KnowledgePublicationService(
        management.service.repository,
        management.service.authorizer,
        index_identity=INDEX,
        owner_id=management.service.owner_id,
    )
    target = KnowledgePublicationTarget(
        document_id=uploaded.document_id,
        version_id=uploaded.version_id,
        expected_revision_no=1,
        expected_row_version=uploaded.row_version,
    )
    candidate = await publication.prepare(target, identity=IDENTITY)
    second = await publication.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=candidate.confirmation_digest,
            idempotency_key="publish-release-two",
        ),
        identity=IDENTITY,
    )
    assert second.task_id is not None and await builder.process(second.task_id, identity=IDENTITY)
    published = await service.finalize(second.operation_id, identity=IDENTITY)
    assert published.replaced_version_id == first.version_id and published.release_revision == 2
    old = await service.finalize(first.operation_id, identity=IDENTITY)
    assert old.replayed and old.publication_state == "SUPERSEDED" and not old.is_current_version
    assert old.published_at == first.published_at and old.release_revision == 2
    async with managed_database.session() as session:
        chunks = [
            (chunk.chunk_id, chunk.content, tuple(float(v) for v in chunk.embedding))
            for chunk in (
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.generation_id == accepted.generation_id)
                    .order_by(Chunk.chunk_index)
                )
            ).all()
        ]
        assert chunks == old_chunks
        document = await session.get(Document, first.document_id)
        assert document is not None and document.current_version_id == published.version_id
    assert (
        await management.service.read_original(first.version_id, 1, identity=IDENTITY)
    ).content == original.content


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_concurrent_commit_is_once(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    accepted = await ready(management, managed_database)
    service = finalizer(management, managed_database)
    scope = await service._authorize(IDENTITY, None)
    read = await service.repository.prepare_finalization(
        accepted.operation_id, actor=IDENTITY.user_id, scope=scope
    )
    assert isinstance(read, PublicationFinalizeRead)
    digest = finalization_hash(read)
    results = await asyncio.gather(
        *[
            service.repository.commit_finalization(
                read, digest, actor=IDENTITY.user_id, scope=scope
            )
            for _ in range(2)
        ]
    )
    assert {result.replayed for result in results} == {True, False}
    assert {result.release_revision for result in results} == {1}
    assert len({result.published_at for result in results}) == 1


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["count", "missing", "zero", "body", "index"])
async def test_knowledge_management_publication_finalize_invalid_ready_evidence_rejected(
    management: ManagementHarness,
    managed_database: Database,
    damage: str,
) -> None:
    accepted = await ready(management, managed_database)
    async with managed_database.session() as session, session.begin():
        if damage == "count":
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == accepted.generation_id)
                .values(chunk_count=99)
            )
        elif damage == "missing":
            await session.execute(
                delete(Chunk).where(
                    Chunk.generation_id == accepted.generation_id, Chunk.chunk_index == 0
                )
            )
        elif damage == "zero":
            await session.execute(
                update(Chunk)
                .where(Chunk.generation_id == accepted.generation_id, Chunk.chunk_index == 0)
                .values(embedding=[0.0] * 1536)
            )
        elif damage == "body":
            await session.execute(
                update(Chunk)
                .where(Chunk.generation_id == accepted.generation_id, Chunk.chunk_index == 0)
                .values(
                    content="外来正文", content_hash=hashlib.sha256("外来正文".encode()).hexdigest()
                )
            )
        else:
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == accepted.generation_id)
                .values(embedding_model="different-model")
            )
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_DATA_INVALID"):
        await finalizer(management, managed_database).finalize(
            accepted.operation_id, identity=IDENTITY
        )
    async with managed_database.session() as session:
        document = await session.get(Document, accepted.document_id)
        operation = await session.get(Operation, accepted.operation_id)
        library = await session.get(Library, "DEFAULT")
        assert (
            document is not None
            and document.current_version_id is None
            and document.row_version == accepted.reserved_row_version
        )
        assert (
            operation is not None
            and operation.state == "FAILED"
            and operation.error_code == "INDEX_VALIDATION_FAILED"
        )
        assert library is not None and library.release_revision == 0


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_rechecks_after_preparation(
    management: ManagementHarness,
    managed_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = await ready(management, managed_database)
    service = finalizer(management, managed_database)
    original = service.repository.commit_finalization

    async def change_then_commit(
        read: PublicationFinalizeRead, digest: str, *, actor: str, scope: str
    ) -> KnowledgePublicationReceipt:
        """只改变合法向量值，必须由最终清单摘要发现校验后的变化。"""

        async with managed_database.session() as session, session.begin():
            await session.execute(
                update(Chunk)
                .where(Chunk.generation_id == accepted.generation_id, Chunk.chunk_index == 0)
                .values(embedding=[2.0] + [0.0] * 1535)
            )
        return await original(read, digest, actor=actor, scope=scope)

    monkeypatch.setattr(service.repository, "commit_finalization", change_then_commit)
    with pytest.raises(KnowledgeManagementError, match="STALE_CONFIRMATION"):
        await service.finalize(accepted.operation_id, identity=IDENTITY)
    async with managed_database.session() as session:
        operation = await session.get(Operation, accepted.operation_id)
        assert operation is not None and operation.state == "STALE"


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_ready_reuse_without_new_task(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    accepted = await ready(management, managed_database)
    service = finalizer(management, managed_database)
    await service.repository.reject_finalization(
        accepted.operation_id, actor=IDENTITY.user_id, scope="INTERNAL_REVIEWER", stale=False
    )
    publication = KnowledgePublicationService(
        management.service.repository,
        management.service.authorizer,
        index_identity=INDEX,
        owner_id=management.service.owner_id,
    )
    target = KnowledgePublicationTarget(
        document_id=accepted.document_id,
        version_id=accepted.version_id,
        expected_revision_no=1,
        expected_row_version=accepted.reserved_row_version,
    )
    candidate = await publication.prepare(target, identity=IDENTITY)
    reused = await publication.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=candidate.confirmation_digest,
            idempotency_key="publish-reuse-ready",
        ),
        identity=IDENTITY,
    )
    assert reused.task_id is None and reused.generation_id == accepted.generation_id
    result = await service.finalize(reused.operation_id, identity=IDENTITY)
    assert result.publication_state == "PUBLISHED"
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1
        assert (
            await session.scalar(
                select(func.count()).select_from(Task).where(Task.task_type == "INDEX")
            )
            == 1
        )


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_sql_failure_rolls_back_and_retries(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    builder, accepted, _, previous = await prepared(
        management, managed_database, previous_release=True
    )
    assert accepted.task_id is not None and await builder.process(
        accepted.task_id, identity=IDENTITY
    )
    service = finalizer(management, managed_database)

    def fail_publish(*args: object) -> None:
        """旧版状态已flush、新版UPDATE已执行后注入异常，检查全部回滚。"""

        if str(args[2]).startswith("UPDATE managed_knowledge_versions") and "PUBLISHED" in repr(
            args[3]
        ):
            raise SQLAlchemyError("private simulated publish failure")

    event.listen(managed_database.engine.sync_engine, "after_cursor_execute", fail_publish)
    try:
        with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
            await service.finalize(accepted.operation_id, identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "after_cursor_execute", fail_publish)
    async with managed_database.session() as session:
        document = await session.get(Document, accepted.document_id)
        old = await session.get(Version, previous)
        new = await session.get(Version, accepted.version_id)
        library = await session.get(Library, "DEFAULT")
        operation = await session.get(Operation, accepted.operation_id)
        assert (
            document is not None
            and document.current_version_id == previous
            and document.row_version == accepted.reserved_row_version
        )
        assert old is not None and old.publication_state == "PUBLISHED"
        assert new is not None and new.publication_state == "DRAFT"
        assert library is not None and library.release_revision == 0
        assert operation is not None and operation.state == "EXECUTING"
    assert (
        await service.finalize(accepted.operation_id, identity=IDENTITY)
    ).publication_state == "PUBLISHED"


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_actor_and_readiness_guards(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    builder, accepted, _, _ = await prepared(management, managed_database)
    service = finalizer(management, managed_database)
    with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
        await service.finalize(
            accepted.operation_id,
            identity=BusinessIdentity(user_id="another-reviewer", role="REVIEWER"),
        )
    with pytest.raises(KnowledgeManagementError, match="PUBLICATION_INDEX_NOT_READY"):
        await service.finalize(accepted.operation_id, identity=IDENTITY)
    async with managed_database.session() as session:
        operation = await session.get(Operation, accepted.operation_id)
        assert operation is not None and operation.state == "CONFIRMED"
    assert accepted.task_id is not None and await builder.process(
        accepted.task_id, identity=IDENTITY
    )
    assert (await service.finalize(accepted.operation_id, identity=IDENTITY)).is_current_version


@pytest.mark.integration
async def test_knowledge_management_publication_finalize_draft_change_after_preparation(
    management: ManagementHarness,
    managed_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = await ready(management, managed_database)
    service = finalizer(management, managed_database)
    original_commit = service.repository.commit_finalization

    async def revise_then_commit(
        read: PublicationFinalizeRead, digest: str, *, actor: str, scope: str
    ) -> KnowledgePublicationReceipt:
        """最终提交前修正草稿，保留原READY证据但使旧发布意图失效。"""

        await management.service.upload(
            revision_command(
                command(),
                accepted.document_id,
                accepted.version_id,
                accepted.reserved_row_version,
                1,
            ),
            byte_chunks((BODY + "新修订\n").encode()),
            identity=IDENTITY,
        )
        return await original_commit(read, digest, actor=actor, scope=scope)

    monkeypatch.setattr(service.repository, "commit_finalization", revise_then_commit)
    with pytest.raises(KnowledgeManagementError, match="PUBLICATION_OPERATION_NOT_ACTIVE"):
        await service.finalize(accepted.operation_id, identity=IDENTITY)
    async with managed_database.session() as session:
        document = await session.get(Document, accepted.document_id)
        operation = await session.get(Operation, accepted.operation_id)
        assert document is not None and document.current_version_id is None
        assert operation is not None and operation.state == "STALE"
