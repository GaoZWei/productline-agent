"""真实管理库停用、幂等、发布竞争、旧引用保留及中途失败回滚。"""

import asyncio

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
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.knowledge_disable import KnowledgeDisableRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_disable import (
    KnowledgeDisableCommand,
    KnowledgeDisableReceipt,
    KnowledgeDisableTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationReceipt,
    KnowledgePublicationTarget,
)
from app.services.knowledge_disable import KnowledgeDisableService
from app.services.knowledge_index_build import KnowledgeIndexBuildService
from app.services.knowledge_publication import KnowledgePublicationService
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import byte_chunks
from tests.knowledge.test_knowledge_management_index_build_persistence import (
    BODY,
    ControlledProvider,
    prepared,
)
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.knowledge.test_knowledge_management_publication_finalize_persistence import finalizer
from tests.test_knowledge_index_build import INDEX


def service(management: ManagementHarness, database: Database) -> KnowledgeDisableService:
    """停用只需原授权Client与独立知识Repository，无模型或文件存储依赖。"""

    return KnowledgeDisableService(
        KnowledgeDisableRepository(database), management.service.authorizer
    )


async def published(
    management: ManagementHarness, database: Database
) -> tuple[KnowledgePublicationReceipt, KnowledgeIndexBuildService, ControlledProvider]:
    """从真实上传和候选构建完成管理库发布，外部模型传输仍使用替身。"""

    builder, accepted, provider, _ = await prepared(management, database)
    assert accepted.task_id is not None and await builder.process(
        accepted.task_id, identity=IDENTITY
    )
    return (
        await finalizer(management, database).finalize(accepted.operation_id, identity=IDENTITY),
        builder,
        provider,
    )


async def disable_command(
    disable: KnowledgeDisableService,
    receipt: KnowledgePublicationReceipt,
    row_version: int | None = None,
) -> KnowledgeDisableCommand:
    """确认绑定明确旧版本，不能用隐式最新指针替代用户所见目标。"""

    target = KnowledgeDisableTarget(
        document_id=receipt.document_id,
        version_id=receipt.version_id,
        expected_revision_no=receipt.revision_no,
        expected_row_version=receipt.row_version if row_version is None else row_version,
    )
    candidate = await disable.prepare(target, identity=IDENTITY)
    return KnowledgeDisableCommand(
        **target.model_dump(),
        confirmed=True,
        confirmation_digest=candidate.confirmation_digest,
        idempotency_key="disable-first",
    )


async def next_version(
    management: ManagementHarness, receipt: KnowledgePublicationReceipt, row_version: int
) -> KnowledgePublicationAcceptance:
    """仅创建独立演示新版并明确确认，未在此函数执行索引或最终发布。"""

    uploaded = await management.service.upload(
        command(
            document_id=receipt.document_id,
            expected_row_version=row_version,
            idempotency_key="upload-second-version",
            metadata={**command().metadata.model_dump(), "specification_version": "2.0"},
        ),
        byte_chunks((BODY + "第二版要求\n").encode()),
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
    return await publication.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=candidate.confirmation_digest,
            idempotency_key="publish-second-version",
        ),
        identity=IDENTITY,
    )


@pytest.mark.integration
async def test_knowledge_management_disable_preserves_history_and_replay_reauthorizes(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    first, _, _ = await published(management, managed_database)
    disable = service(management, managed_database)
    statements: list[str] = []

    def capture(*args: object) -> None:
        """只观察审查SQL的列选择，正文与向量不应进入停用读取。"""

        statements.append(str(args[2]))

    event.listen(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        confirm = await disable_command(disable, first)
    finally:
        event.remove(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    assert all(
        "managed_knowledge_revisions.body" not in sql and "managed_knowledge_chunks" not in sql
        for sql in statements
    )
    original = await management.service.read_original(first.version_id, 1, identity=IDENTITY)
    result = await disable.disable(confirm, identity=IDENTITY)
    assert result.current_version_id is None and result.publication_state == "DISABLED"
    assert (
        result.row_version == first.row_version + 1
        and result.release_revision == first.release_revision + 1
    )
    assert result.source_mode == "LEGACY"
    replay = await disable.disable(confirm, identity=IDENTITY)
    assert replay.model_copy(update={"replayed": False}) == result
    with pytest.raises(KnowledgeManagementError, match="IDEMPOTENCY_CONFLICT"):
        await disable.disable(
            confirm.model_copy(update={"confirmation_digest": "0" * 64}), identity=IDENTITY
        )
    management.denied.add("DISABLE")
    with pytest.raises(ToolException):
        await disable.disable(confirm, identity=IDENTITY)
    management.denied.clear()
    historical = await finalizer(management, managed_database).finalize(
        first.operation_id, identity=IDENTITY
    )
    assert (
        historical.publication_state == "DISABLED"
        and historical.replayed
        and not historical.is_current_version
    )
    assert (
        await management.service.read_original(first.version_id, 1, identity=IDENTITY)
    ).content == original.content
    async with managed_database.session() as session:
        version = await session.get(Version, first.version_id)
        operation = await session.get(Operation, result.operation_id)
        assert (
            version is not None
            and version.published_at == first.published_at
            and version.published_generation_id == first.generation_id
        )
        assert (
            operation is not None
            and operation.actor_id == IDENTITY.user_id
            and operation.state == "SUCCEEDED"
        )
        assert operation.finished_at == result.disabled_at
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1
        chunk_count = await session.scalar(select(func.count()).select_from(Chunk))
        assert chunk_count is not None and chunk_count > 0
        assert await session.scalar(select(func.count()).select_from(Task)) == 2


@pytest.mark.integration
async def test_knowledge_management_disable_old_key_cannot_stop_later_publication(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    first, builder, _ = await published(management, managed_database)
    disable = service(management, managed_database)
    confirm = await disable_command(disable, first)
    stopped = await disable.disable(confirm, identity=IDENTITY)
    second = await next_version(management, first, stopped.row_version)
    assert second.task_id is not None and await builder.process(second.task_id, identity=IDENTITY)
    current = await finalizer(management, managed_database).finalize(
        second.operation_id, identity=IDENTITY
    )
    replay = await disable.disable(confirm, identity=IDENTITY)
    assert replay.replayed and replay.disabled_at == stopped.disabled_at
    assert (
        replay.current_version_id == current.version_id
        and replay.row_version == current.row_version
    )
    assert replay.release_revision == current.release_revision
    with pytest.raises(KnowledgeManagementError, match="DISABLE_REQUIRES_CURRENT_PUBLISHED"):
        await disable.disable(
            confirm.model_copy(update={"idempotency_key": "new-key-old-target"}), identity=IDENTITY
        )


@pytest.mark.integration
async def test_knowledge_management_disable_stale_confirmation_and_actor_binding(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    first, _, _ = await published(management, managed_database)
    disable = service(management, managed_database)
    confirm = await disable_command(disable, first)
    with pytest.raises(KnowledgeManagementError, match="STALE_CONFIRMATION"):
        await disable.disable(
            confirm, identity=BusinessIdentity(user_id="another-reviewer", role="REVIEWER")
        )
    await next_version(management, first, first.row_version)
    with pytest.raises(KnowledgeManagementError, match="STALE_DOCUMENT"):
        await disable.disable(confirm, identity=IDENTITY)
    with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
        await disable.repository.prepare_disable(
            KnowledgeDisableTarget(
                **confirm.model_dump(include=set(KnowledgeDisableTarget.model_fields))
            ),
            actor=IDENTITY.user_id,
            scope="OUT_OF_SCOPE",
        )
    async with managed_database.session() as session:
        document = await session.get(Document, first.document_id)
        assert document is not None and document.current_version_id == first.version_id
        assert (
            await session.scalar(
                select(func.count()).select_from(Operation).where(Operation.action == "DISABLE")
            )
            == 0
        )


@pytest.mark.integration
@pytest.mark.parametrize("same_key", [True, False])
async def test_knowledge_management_disable_concurrent_confirmations_do_not_repeat(
    management: ManagementHarness,
    managed_database: Database,
    same_key: bool,
) -> None:
    first, _, _ = await published(management, managed_database)
    disable = service(management, managed_database)
    confirm = await disable_command(disable, first)
    scope = await disable._authorize(IDENTITY, None)
    second = (
        confirm
        if same_key
        else confirm.model_copy(update={"idempotency_key": "different-disable-key"})
    )
    results = await asyncio.gather(
        disable.repository.disable(confirm, actor=IDENTITY.user_id, scope=scope),
        disable.repository.disable(second, actor=IDENTITY.user_id, scope=scope),
        return_exceptions=True,
    )
    receipts = [item for item in results if isinstance(item, KnowledgeDisableReceipt)]
    assert len(receipts) == (2 if same_key else 1)
    if same_key:
        assert {item.replayed for item in receipts} == {False, True}
        assert len({item.operation_id for item in receipts}) == 1
    else:
        errors = [item for item in results if isinstance(item, KnowledgeManagementError)]
        assert len(errors) == 1 and errors[0].code == "DISABLE_REQUIRES_CURRENT_PUBLISHED"
    async with managed_database.session() as session:
        library = await session.get(Library, "DEFAULT")
        assert library is not None and library.release_revision == first.release_revision + 1
        assert (
            await session.scalar(
                select(func.count()).select_from(Operation).where(Operation.action == "DISABLE")
            )
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["QUEUED", "RUNNING", "READY"])
async def test_knowledge_management_disable_invalidates_pending_publish_and_late_index(
    management: ManagementHarness,
    managed_database: Database,
    stage: str,
) -> None:
    first, builder, provider = await published(management, managed_database)
    second = await next_version(management, first, first.row_version)
    assert second.task_id is not None
    job: asyncio.Task[bool] | None = None
    release = asyncio.Event()
    if stage == "READY":
        assert await builder.process(second.task_id, identity=IDENTITY)
    elif stage == "RUNNING":
        entered = asyncio.Event()

        async def pause(call: int) -> None:
            """只在事务外模型阶段等待停用，不占用SQL连接。"""

            if not entered.is_set():
                entered.set()
                await release.wait()

        provider.hook = pause
        job = asyncio.create_task(builder.process(second.task_id, identity=IDENTITY))
        await asyncio.wait_for(entered.wait(), 5)
    disable = service(management, managed_database)
    try:
        confirm = await disable_command(disable, first, second.reserved_row_version)
        assert (await disable.disable(confirm, identity=IDENTITY)).current_version_id is None
    finally:
        release.set()
    if job is not None:
        assert not await job
    with pytest.raises(KnowledgeManagementError, match="PUBLICATION_OPERATION_NOT_ACTIVE"):
        await finalizer(management, managed_database).finalize(
            second.operation_id, identity=IDENTITY
        )
    async with managed_database.session() as session:
        operation = await session.get(Operation, second.operation_id)
        task = await session.get(Task, second.task_id)
        generation = await session.get(Generation, second.generation_id)
        assert (
            operation is not None
            and operation.state == "STALE"
            and operation.error_code == "STALE_INPUT"
        )
        assert task is not None and task.state == ("SUCCEEDED" if stage == "READY" else "STALE")
        assert generation is not None and generation.state == (
            "READY" if stage == "READY" else "FAILED"
        )
        old = await session.get(Version, first.version_id)
        assert old is not None and old.publication_state == "DISABLED"


@pytest.mark.integration
async def test_knowledge_management_disable_sql_failure_rolls_back_pending_states_and_pointer(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    first, _, _ = await published(management, managed_database)
    second = await next_version(management, first, first.row_version)
    disable = service(management, managed_database)
    confirm = await disable_command(disable, first, second.reserved_row_version)

    def fail_update(*args: object) -> None:
        """在停用UPDATE已执行时注入异常，旧意图失效及指针更新都必须回滚。"""

        if str(args[2]).startswith("UPDATE managed_knowledge_versions") and "DISABLED" in repr(
            args[3]
        ):
            raise SQLAlchemyError("private simulated disable failure")

    event.listen(managed_database.engine.sync_engine, "after_cursor_execute", fail_update)
    try:
        with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
            await disable.disable(confirm, identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "after_cursor_execute", fail_update)
    async with managed_database.session() as session:
        document = await session.get(Document, first.document_id)
        version = await session.get(Version, first.version_id)
        operation = await session.get(Operation, second.operation_id)
        task = await session.get(Task, second.task_id)
        generation = await session.get(Generation, second.generation_id)
        assert (
            document is not None
            and document.current_version_id == first.version_id
            and document.row_version == second.reserved_row_version
        )
        assert version is not None and version.publication_state == "PUBLISHED"
        assert operation is not None and operation.state == "CONFIRMED"
        assert task is not None and task.state == "QUEUED"
        assert generation is not None and generation.state == "BUILDING"
        assert (
            await session.scalar(
                select(func.count()).select_from(Operation).where(Operation.action == "DISABLE")
            )
            == 0
        )
    assert not (await disable.disable(confirm, identity=IDENTITY)).replayed


@pytest.mark.integration
async def test_knowledge_management_disable_can_withdraw_corrupt_evidence_without_loading_it(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    first, _, _ = await published(management, managed_database)
    async with managed_database.session() as session, session.begin():
        await session.execute(
            update(Revision).where(Revision.version_id == first.version_id).values(body="损坏正文")
        )
        await session.execute(delete(Chunk).where(Chunk.generation_id == first.generation_id))
    disable = service(management, managed_database)
    confirm = await disable_command(disable, first)
    assert (await disable.disable(confirm, identity=IDENTITY)).publication_state == "DISABLED"
