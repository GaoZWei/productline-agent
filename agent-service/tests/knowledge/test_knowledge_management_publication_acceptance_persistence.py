"""真实短事务验证发布接收的幂等、并发、快照复查、回滚与候选复用。"""

import asyncio
from datetime import date

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.errors import ToolException
from app.knowledge.managed_parsing import parse_managed_revision
from app.knowledge.publication import publication_generation_hash
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation
from app.services.knowledge_publication import KnowledgePublicationService
from app.settings import Settings
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import byte_chunks, generation_payload
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
    revision_command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management

INDEX = KnowledgePublicationIndexIdentity.from_settings(Settings(environment="test"))
BODY = "# 测试规范\n\n待发布正文"


async def draft(
    management: ManagementHarness,
) -> tuple[KnowledgePublicationService, KnowledgePublicationConfirmCommand]:
    """独立测试草稿采用长期有效的日期，模型配置只读取身份，不创建Provider。"""

    uploaded = await management.service.upload(
        command(metadata={**command().metadata.model_dump(), "effective_date": date(1970, 1, 1)}),
        byte_chunks(BODY.encode()),
        identity=IDENTITY,
    )
    service = KnowledgePublicationService(
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
    candidate = await service.prepare(target, identity=IDENTITY)
    return service, KnowledgePublicationConfirmCommand(
        **target.model_dump(),
        confirmed=True,
        confirmation_digest=candidate.confirmation_digest,
        idempotency_key="publish-accept-1",
    )


@pytest.mark.integration
async def test_knowledge_management_publication_accept_replay_failure_recovery_and_correction(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, confirmation = await draft(management)
    accepted = await service.accept(confirmation, identity=IDENTITY)
    assert (accepted.operation_state, accepted.generation_state, accepted.task_state) == (
        "CONFIRMED",
        "BUILDING",
        "QUEUED",
    )
    assert accepted.reserved_row_version == confirmation.expected_row_version + 1
    assert not accepted.replayed
    # 服务器配置变化不更改原确认的幂等身份，也不新建任务。
    service.index_identity = None
    replay = await service.accept(confirmation, identity=IDENTITY)
    assert replay.model_copy(update={"replayed": False}) == accepted
    with pytest.raises(KnowledgeManagementError, match="IDEMPOTENCY_CONFLICT"):
        await service.accept(
            confirmation.model_copy(update={"confirmation_digest": "0" * 64}), identity=IDENTITY
        )
    management.denied.add("PUBLISH")
    with pytest.raises(ToolException):
        await service.accept(confirmation, identity=IDENTITY)
    management.denied.clear()
    # 接收只预留，恢复中断时明确失败，同键重放失败记录，不重新排队。
    assert await service.repository.recover_interrupted("another-owner") == 1
    interrupted = await service.accept(confirmation, identity=IDENTITY)
    assert interrupted.operation_state == "FAILED" and interrupted.task_state == "INTERRUPTED"
    assert (
        interrupted.generation_state == "FAILED"
        and interrupted.error_code == "PROCESSING_INTERRUPTED"
    )
    revised = await management.service.upload(
        revision_command(
            command(),
            confirmation.document_id,
            confirmation.version_id,
            accepted.reserved_row_version,
            1,
        ),
        byte_chunks("# 测试规范\n\n修正正文".encode()),
        identity=IDENTITY,
    )
    assert revised.revision_no == 2
    assert (
        await service.accept(confirmation, identity=IDENTITY)
    ).operation_id == accepted.operation_id
    async with managed_database.session() as session:
        operation = await session.get(Operation, accepted.operation_id)
        assert operation is not None
        snapshot = ManagedKnowledgeConfirmation.model_validate(operation.confirmation_snapshot)
        assert (
            snapshot.actor_id == IDENTITY.user_id
            and snapshot.generation_id == accepted.generation_id
        )
        assert snapshot.expected_row_version == confirmation.expected_row_version
        assert "正文" not in str(operation.confirmation_snapshot)
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 0
        document = await session.get(Document, confirmation.document_id)
        library = await session.get(Library, "DEFAULT")
        assert document is not None and document.current_version_id is None
        assert (
            library is not None
            and library.source_mode == "LEGACY"
            and library.release_revision == 0
        )


@pytest.mark.integration
async def test_knowledge_management_publication_same_key_concurrent_services_and_new_key_blocked(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, confirmation = await draft(management)
    other = KnowledgePublicationService(
        service.repository, service.authorizer, index_identity=INDEX
    )
    management.authorization_barrier = asyncio.Barrier(2)
    first, second = await asyncio.gather(
        service.accept(confirmation, identity=IDENTITY),
        other.accept(confirmation, identity=IDENTITY),
    )
    management.authorization_barrier = None
    assert {first.replayed, second.replayed} == {False, True}
    assert first.operation_id == second.operation_id and first.task_id == second.task_id
    # 新幂等键不能绕过同一资料的执行权，即使刷新计数和摘要仍然拒绝。
    target = KnowledgePublicationTarget(
        document_id=confirmation.document_id,
        version_id=confirmation.version_id,
        expected_revision_no=1,
        expected_row_version=first.reserved_row_version,
    )
    candidate = await service.prepare(target, identity=IDENTITY)
    with pytest.raises(KnowledgeManagementError, match="PUBLICATION_IN_PROGRESS"):
        await other.accept(
            KnowledgePublicationConfirmCommand(
                **target.model_dump(),
                confirmed=True,
                confirmation_digest=candidate.confirmation_digest,
                idempotency_key="different-publish-key",
            ),
            identity=IDENTITY,
        )
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1
        assert (
            await session.scalar(
                select(func.count()).select_from(Task).where(Task.task_type == "INDEX")
            )
            == 1
        )


@pytest.mark.integration
async def test_knowledge_management_publication_accept_rechecks_changed_draft_inside_transaction(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, confirmation = await draft(management)
    await management.service.upload(
        revision_command(
            command(),
            confirmation.document_id,
            confirmation.version_id,
            confirmation.expected_row_version,
            1,
        ),
        byte_chunks("# 测试规范\n\n变更正文".encode()),
        identity=IDENTITY,
    )
    with pytest.raises(KnowledgeManagementError, match="STALE_DOCUMENT"):
        await service.accept(confirmation, identity=IDENTITY)
    async with managed_database.session() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Operation).where(Operation.action == "PUBLISH")
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(Generation)) == 0


@pytest.mark.integration
async def test_knowledge_management_publication_task_insert_failure_rolls_back_every_reservation(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, confirmation = await draft(management)

    def fail_task_insert(*args: object) -> None:
        """仅故障注入当前隔离库的任务INSERT，不改生产代码或弱化数据库约束。"""

        statement = str(args[2])
        if statement.startswith("INSERT INTO managed_knowledge_tasks"):
            raise SQLAlchemyError("private injected storage failure")

    event.listen(managed_database.engine.sync_engine, "before_cursor_execute", fail_task_insert)
    try:
        with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
            await service.accept(confirmation, identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "before_cursor_execute", fail_task_insert)
    async with managed_database.session() as session:
        document = await session.get(Document, confirmation.document_id)
        assert document is not None and document.row_version == confirmation.expected_row_version
        assert await session.scalar(select(func.count()).select_from(Generation)) == 0
        assert (
            await session.scalar(
                select(func.count()).select_from(Operation).where(Operation.action == "PUBLISH")
            )
            == 0
        )
    assert not (await service.accept(confirmation, identity=IDENTITY)).replayed


@pytest.mark.integration
@pytest.mark.parametrize("matching_identity", [True, False])
async def test_knowledge_management_publication_reuses_only_matching_ready_candidate(
    management: ManagementHarness,
    managed_database: Database,
    matching_identity: bool,
) -> None:
    service, confirmation = await draft(management)
    snapshot = await service.validate_confirmation(confirmation, identity=IDENTITY)
    digest = publication_generation_hash(snapshot, confirmation.version_id, INDEX)
    ready_id = "GEN-" + "9" * 32
    chunks = parse_managed_revision(
        BODY.encode(),
        citation_document_id=confirmation.version_id,
        title="测试规范",
        file_format="MD",
    ).chunks
    async with managed_database.session() as session, session.begin():
        await session.execute(
            insert(Generation).values(
                **generation_payload(
                    generation_id=ready_id,
                    version_id=confirmation.version_id,
                    embedding_provider=INDEX.provider,
                    embedding_model=INDEX.model if matching_identity else "different-model",
                    index_version=INDEX.index_version,
                    chunking_version=INDEX.chunking_version,
                    input_hash=digest,
                    state="READY",
                    chunk_count=len(chunks),
                    finished_at=func.now(),
                )
            )
        )
        for chunk in chunks:
            await session.execute(
                insert(Chunk).values(
                    generation_id=ready_id,
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    section_path=list(chunk.section_path),
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    token_count=chunk.token_count,
                    search_document=chunk.content,
                    embedding=[1.0] + [0.0] * 1535,
                )
            )
    accepted = await service.accept(confirmation, identity=IDENTITY)
    if matching_identity:
        assert accepted.generation_id == ready_id and accepted.generation_state == "READY"
        assert accepted.task_id is None and accepted.task_state is None
        assert (await service.accept(confirmation, identity=IDENTITY)).replayed
    else:
        assert accepted.generation_id != ready_id and accepted.task_state == "QUEUED"
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Generation)) == (
            1 if matching_identity else 2
        )
        assert await session.scalar(select(func.count()).select_from(Chunk)) == len(chunks)
        version = await session.get(Version, confirmation.version_id)
        assert version is not None and version.publication_state == "DRAFT"


@pytest.mark.integration
async def test_knowledge_management_publication_competing_keys_reserve_only_once(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, confirmation = await draft(management)
    other = KnowledgePublicationService(
        service.repository, service.authorizer, index_identity=INDEX
    )
    management.authorization_barrier = asyncio.Barrier(2)
    results = await asyncio.gather(
        service.accept(confirmation, identity=IDENTITY),
        other.accept(
            confirmation.model_copy(update={"idempotency_key": "competing-key"}), identity=IDENTITY
        ),
        return_exceptions=True,
    )
    management.authorization_barrier = None
    assert sum(isinstance(result, KnowledgePublicationAcceptance) for result in results) == 1
    failures = [result for result in results if isinstance(result, KnowledgeManagementError)]
    assert len(failures) == 1 and failures[0].code == "STALE_DOCUMENT"
    async with managed_database.session() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Operation).where(Operation.action == "PUBLISH")
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1


@pytest.mark.integration
async def test_knowledge_management_publication_reservation_preserves_previous_release(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, previous = await draft(management)
    previous_generation_id = "GEN-" + "8" * 32
    # 仅构造已有发布关系，用于检查接收事务不会抢先移动指针。
    async with managed_database.session() as session, session.begin():
        await session.execute(
            insert(Generation).values(
                **generation_payload(
                    generation_id=previous_generation_id,
                    version_id=previous.version_id,
                    state="READY",
                    chunk_count=1,
                    finished_at=func.now(),
                )
            )
        )
        await session.execute(
            update(Version)
            .where(Version.version_id == previous.version_id)
            .values(
                publication_state="PUBLISHED",
                published_revision_no=1,
                published_generation_id=previous_generation_id,
                published_at=func.now(),
            )
        )
        await session.execute(
            update(Document)
            .where(Document.document_id == previous.document_id)
            .values(current_version_id=previous.version_id)
        )
    uploaded = await management.service.upload(
        command(
            document_id=previous.document_id,
            expected_row_version=previous.expected_row_version,
            idempotency_key="upload-v2",
            metadata={
                **command().metadata.model_dump(),
                "specification_version": "2.0",
                "effective_date": date(1970, 1, 1),
            },
        ),
        byte_chunks("# 测试规范\n\n新版正文".encode()),
        identity=IDENTITY,
    )
    target = KnowledgePublicationTarget(
        document_id=uploaded.document_id,
        version_id=uploaded.version_id,
        expected_revision_no=1,
        expected_row_version=uploaded.row_version,
    )
    candidate = await service.prepare(target, identity=IDENTITY)
    accepted = await service.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=candidate.confirmation_digest,
            idempotency_key="publish-v2",
        ),
        identity=IDENTITY,
    )
    assert accepted.task_state == "QUEUED"
    async with managed_database.session() as session:
        document = await session.get(Document, previous.document_id)
        old = await session.get(Version, previous.version_id)
        new = await session.get(Version, uploaded.version_id)
        assert document is not None and document.current_version_id == previous.version_id
        assert old is not None and old.publication_state == "PUBLISHED"
        assert old.published_generation_id == previous_generation_id
        assert (
            new is not None
            and new.publication_state == "DRAFT"
            and new.published_generation_id is None
        )
    original = await management.service.read_original(previous.version_id, 1, identity=IDENTITY)
    assert original.content == BODY.encode()
