"""真实隔离知识库验证失败链、受控重试构建、重新发布及失败事务保护。"""

import asyncio

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.errors import ToolException
from app.knowledge.embeddings import EmbeddingErrorCode, EmbeddingProviderError
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.knowledge_disable import KnowledgeDisableRepository
from app.repositories.knowledge_index_retry import KnowledgeIndexRetryRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_disable import KnowledgeDisableCommand, KnowledgeDisableTarget
from app.schemas.knowledge_index_retry import (
    KnowledgeIndexRetryCommand,
    KnowledgeIndexRetryReceipt,
    KnowledgeIndexRetryTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationTarget,
)
from app.services.knowledge_disable import KnowledgeDisableService
from app.services.knowledge_index_build import KnowledgeIndexBuildService
from app.services.knowledge_index_retry import KnowledgeIndexRetryService
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
    revision_command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.knowledge.test_knowledge_management_publication_finalize_persistence import finalizer
from tests.test_knowledge_index_build import INDEX


async def failed(
    management: ManagementHarness,
    database: Database,
    *,
    interrupted: bool = False,
    previous_release: bool = False,
) -> tuple[KnowledgeIndexBuildService, KnowledgePublicationAcceptance, ControlledProvider]:
    """创建真实失败或显式恢复中断的PUBLISH索引任务，不调用真实模型。"""

    builder, accepted, provider, _ = await prepared(
        management, database, previous_release=previous_release
    )
    assert accepted.task_id is not None
    if interrupted:
        assert await builder.repository.recover_interrupted("restarted-worker") == 1
    else:

        async def timeout(call: int) -> None:
            """模拟明确Provider超时，原任务必须保存FAILED而非覆盖成成功。"""

            raise EmbeddingProviderError(
                code=EmbeddingErrorCode.TIMEOUT, message="private provider detail", retryable=False
            )

        provider.hook = timeout
        assert not await builder.process(accepted.task_id, identity=IDENTITY)
        provider.hook = None
    return builder, accepted, provider


def retry_service(management: ManagementHarness, database: Database) -> KnowledgeIndexRetryService:
    """使用同一管理owner和索引身份，每次请求仍查独立RETRY_INDEX权限。"""

    return KnowledgeIndexRetryService(
        KnowledgeIndexRetryRepository(database),
        management.service.authorizer,
        index_identity=INDEX,
        owner_id=management.service.owner_id,
    )


async def reviewed(
    service: KnowledgeIndexRetryService,
    accepted: KnowledgePublicationAcceptance | KnowledgeIndexRetryReceipt,
    *,
    key: str = "retry-first",
) -> KnowledgeIndexRetryCommand:
    """按当前草稿计数审查指定失败链尾，不让客户端指定尝试号。"""

    assert accepted.task_id is not None
    target = KnowledgeIndexRetryTarget(
        document_id=accepted.document_id,
        version_id=accepted.version_id,
        expected_revision_no=accepted.revision_no,
        expected_row_version=accepted.reserved_row_version,
        task_id=accepted.task_id,
    )
    candidate = await service.prepare(target, identity=IDENTITY)
    return KnowledgeIndexRetryCommand(
        **target.model_dump(),
        confirmed=True,
        confirmation_digest=candidate.confirmation_digest,
        idempotency_key=key,
    )


@pytest.mark.integration
@pytest.mark.parametrize("interrupted", [False, True])
async def test_knowledge_management_index_retry_builds_candidate_but_needs_new_publish(
    management: ManagementHarness,
    managed_database: Database,
    interrupted: bool,
) -> None:
    old_builder, original, provider = await failed(
        management, managed_database, interrupted=interrupted
    )
    retry = retry_service(management, managed_database)
    confirm = await reviewed(retry, original)
    accepted = await retry.retry(confirm, identity=IDENTITY)
    assert accepted.attempt_no == 2 and accepted.retry_of_task_id == original.task_id
    assert accepted.task_id != original.task_id and accepted.generation_id != original.generation_id
    builder = KnowledgeIndexBuildService(
        retry.repository,
        retry.authorizer,
        old_builder.generator,
        index_identity=INDEX,
        owner_id=retry.owner_id,
    )
    assert accepted.task_id is not None
    before = provider.calls
    assert not await old_builder.process(accepted.task_id, identity=IDENTITY)
    management.denied.add("PUBLISH")
    assert await builder.process(accepted.task_id, identity=IDENTITY)
    assert provider.calls > before
    after_build = provider.calls
    with pytest.raises(ToolException):
        await finalizer(management, managed_database).finalize(
            original.operation_id, identity=IDENTITY
        )
    management.denied.clear()
    # 重新获得PUBLISH权限也不能直接发布RETRY操作，必须有新的发布确认。
    with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
        await finalizer(management, managed_database).finalize(
            accepted.operation_id, identity=IDENTITY
        )
    replay = await retry.retry(confirm, identity=IDENTITY)
    assert (
        replay.replayed
        and replay.operation_state == "SUCCEEDED"
        and replay.task_state == "SUCCEEDED"
    )
    async with managed_database.session() as session:
        old = await session.get(Task, original.task_id)
        old_operation = await session.get(Operation, original.operation_id)
        document = await session.get(Document, original.document_id)
        assert old is not None and old.state == ("INTERRUPTED" if interrupted else "FAILED")
        assert old_operation is not None and old_operation.state == "FAILED"
        assert document is not None and document.current_version_id is None
        for model in (Version, Revision):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
    publication = KnowledgePublicationService(
        management.service.repository,
        management.service.authorizer,
        index_identity=INDEX,
        owner_id=retry.owner_id,
    )
    target = KnowledgePublicationTarget(
        document_id=original.document_id,
        version_id=original.version_id,
        expected_revision_no=1,
        expected_row_version=accepted.reserved_row_version,
    )
    candidate = await publication.prepare(target, identity=IDENTITY)
    publish = await publication.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=candidate.confirmation_digest,
            idempotency_key="publish-after-retry",
        ),
        identity=IDENTITY,
    )
    assert publish.task_id is None and publish.generation_id == accepted.generation_id
    assert (
        await finalizer(management, managed_database).finalize(
            publish.operation_id, identity=IDENTITY
        )
    ).is_current_version
    assert provider.calls == after_build


@pytest.mark.integration
async def test_knowledge_management_index_retry_chain_does_not_branch_or_requeue_replays(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    old_builder, original, provider = await failed(management, managed_database)
    retry = retry_service(management, managed_database)
    confirm = await reviewed(retry, original)
    second = await retry.retry(confirm, identity=IDENTITY)
    assert (await retry.retry(confirm, identity=IDENTITY)).task_id == second.task_id
    with pytest.raises(KnowledgeManagementError, match="IDEMPOTENCY_CONFLICT"):
        await retry.retry(
            confirm.model_copy(update={"confirmation_digest": "0" * 64}), identity=IDENTITY
        )

    # 第2次仍失败时，只能从其节点继续，不能从原任务创建分支。
    async def fail_again(call: int) -> None:
        """只模拟一次任务级失败，不修改原失败或重试历史。"""

        raise EmbeddingProviderError(
            code=EmbeddingErrorCode.UPSTREAM_UNAVAILABLE, message="private", retryable=False
        )

    provider.hook = fail_again
    builder = KnowledgeIndexBuildService(
        retry.repository,
        retry.authorizer,
        old_builder.generator,
        index_identity=INDEX,
        owner_id=retry.owner_id,
    )
    assert second.task_id is not None and not await builder.process(
        second.task_id, identity=IDENTITY
    )
    provider.hook = None
    with pytest.raises(KnowledgeManagementError, match="INDEX_RETRY_SOURCE_NOT_LATEST"):
        await retry.prepare(
            KnowledgeIndexRetryTarget(
                **confirm.model_dump(include=set(KnowledgeIndexRetryTarget.model_fields))
            ).model_copy(update={"expected_row_version": second.reserved_row_version}),
            identity=IDENTITY,
        )
    third = await retry.retry(await reviewed(retry, second, key="retry-third"), identity=IDENTITY)
    assert third.attempt_no == 3 and third.retry_of_task_id == second.task_id
    assert third.task_id is not None and await builder.process(third.task_id, identity=IDENTITY)
    retry.index_identity = None
    assert (await retry.retry(confirm, identity=IDENTITY)).task_id == second.task_id
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Generation)) == 3
        assert await session.scalar(select(func.count()).select_from(Version)) == 1
        old = await session.get(Task, original.task_id)
        middle = await session.get(Task, second.task_id)
        assert old is not None and middle is not None and old.state == middle.state == "FAILED"


@pytest.mark.integration
@pytest.mark.parametrize("same_key", [True, False])
async def test_knowledge_management_index_retry_concurrency_creates_one_child(
    management: ManagementHarness,
    managed_database: Database,
    same_key: bool,
) -> None:
    _, original, _ = await failed(management, managed_database)
    retry = retry_service(management, managed_database)
    confirm = await reviewed(retry, original)
    scope, trace = await retry._authorize(IDENTITY, None)
    commands = [
        confirm,
        confirm if same_key else confirm.model_copy(update={"idempotency_key": "other-retry-key"}),
    ]
    results = await asyncio.gather(
        *[
            retry.repository.accept_retry(
                item,
                actor=IDENTITY.user_id,
                scope=scope,
                index=INDEX,
                owner_id=retry.owner_id,
                trace_id=trace,
            )
            for item in commands
        ],
        return_exceptions=True,
    )
    receipts = [result for result in results if isinstance(result, KnowledgeIndexRetryReceipt)]
    assert len(receipts) == (2 if same_key else 1)
    if same_key:
        assert {result.replayed for result in receipts} == {False, True}
        assert len({result.task_id for result in receipts}) == 1
    else:
        errors = [result for result in results if isinstance(result, KnowledgeManagementError)]
        assert len(errors) == 1 and errors[0].code == "STALE_DOCUMENT"
    async with managed_database.session() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.retry_of_task_id == original.task_id)
            )
            == 1
        )


@pytest.mark.integration
async def test_knowledge_management_index_retry_rejects_changed_revision_and_index(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    _, original, _ = await failed(management, managed_database)
    retry = retry_service(management, managed_database)
    confirm = await reviewed(retry, original)
    retry.index_identity = INDEX.model_copy(update={"model": "different-model"})
    with pytest.raises(KnowledgeManagementError, match="INDEX_RETRY_IDENTITY_CHANGED"):
        await retry.retry(confirm, identity=IDENTITY)
    retry.index_identity = INDEX
    with pytest.raises(KnowledgeManagementError, match="STALE_CONFIRMATION"):
        await retry.retry(
            confirm, identity=BusinessIdentity(user_id="another-reviewer", role="REVIEWER")
        )
    revised = await management.service.upload(
        revision_command(
            command(), original.document_id, original.version_id, original.reserved_row_version, 1
        ),
        byte_chunks((BODY + "新修订\n").encode()),
        identity=IDENTITY,
    )
    with pytest.raises(KnowledgeManagementError, match="STALE_DOCUMENT"):
        await retry.retry(confirm, identity=IDENTITY)
    with pytest.raises(KnowledgeManagementError, match="STALE_REVISION"):
        await retry.retry(
            confirm.model_copy(update={"expected_row_version": revised.row_version}),
            identity=IDENTITY,
        )
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1


@pytest.mark.integration
async def test_knowledge_management_index_retry_failure_rolls_back_and_original_request_can_retry(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    _, original, _ = await failed(management, managed_database)
    retry = retry_service(management, managed_database)
    confirm = await reviewed(retry, original)

    def fail_insert(*args: object) -> None:
        """在新任务INSERT已经执行后注入SQL错误，必须回滚所有新记录。"""

        if str(args[2]).startswith("INSERT INTO managed_knowledge_tasks"):
            raise SQLAlchemyError("private retry write failure")

    event.listen(managed_database.engine.sync_engine, "after_cursor_execute", fail_insert)
    try:
        with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
            await retry.retry(confirm, identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "after_cursor_execute", fail_insert)
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Generation)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.retry_of_task_id == original.task_id)
            )
            == 0
        )
        document = await session.get(Document, original.document_id)
        assert document is not None and document.row_version == original.reserved_row_version
    assert not (await retry.retry(confirm, identity=IDENTITY)).replayed


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["QUEUED", "SUCCEEDED", "PARSE"])
async def test_knowledge_management_index_retry_rejects_nonfailed_or_parse_targets(
    management: ManagementHarness,
    managed_database: Database,
    stage: str,
) -> None:
    builder, original, provider, _ = await prepared(management, managed_database)
    assert original.task_id is not None
    task_id = original.task_id
    if stage == "QUEUED":
        retry = retry_service(management, managed_database)
        retry_builder = KnowledgeIndexBuildService(
            retry.repository,
            retry.authorizer,
            builder.generator,
            index_identity=INDEX,
            owner_id=retry.owner_id,
        )
        management.denied.add("PUBLISH")
        assert not await retry_builder.process(task_id, identity=IDENTITY)
        assert provider.calls == 0
        management.denied.clear()
    if stage == "SUCCEEDED":
        assert await builder.process(task_id, identity=IDENTITY)
    elif stage == "PARSE":
        async with managed_database.session() as session:
            parse_id = await session.scalar(
                select(Task.task_id).where(
                    Task.version_id == original.version_id, Task.task_type == "PARSE"
                )
            )
        assert parse_id is not None
        task_id = parse_id
    target = KnowledgeIndexRetryTarget(
        document_id=original.document_id,
        version_id=original.version_id,
        expected_revision_no=1,
        expected_row_version=original.reserved_row_version,
        task_id=task_id,
    )
    with pytest.raises(KnowledgeManagementError, match="INDEX_RETRY_NOT_ELIGIBLE"):
        await retry_service(management, managed_database).prepare(target, identity=IDENTITY)


@pytest.mark.integration
async def test_knowledge_management_index_retry_late_result_cannot_reverse_disable(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    old_builder, original, provider = await failed(
        management, managed_database, previous_release=True
    )
    retry = retry_service(management, managed_database)
    accepted = await retry.retry(await reviewed(retry, original), identity=IDENTITY)
    assert accepted.task_id is not None
    builder = KnowledgeIndexBuildService(
        retry.repository,
        retry.authorizer,
        old_builder.generator,
        index_identity=INDEX,
        owner_id=retry.owner_id,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait(call: int) -> None:
        """重试在事务外模型阶段暂停，让明确停用先完成。"""

        if not entered.is_set():
            entered.set()
            await release.wait()

    provider.hook = wait
    job = asyncio.create_task(builder.process(accepted.task_id, identity=IDENTITY))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with managed_database.session() as session:
            document = await session.get(Document, original.document_id)
            assert document is not None and document.current_version_id is not None
            current_id = document.current_version_id
        disable = KnowledgeDisableService(
            KnowledgeDisableRepository(managed_database), management.service.authorizer
        )
        target = KnowledgeDisableTarget(
            document_id=original.document_id,
            version_id=current_id,
            expected_revision_no=1,
            expected_row_version=accepted.reserved_row_version,
        )
        candidate = await disable.prepare(target, identity=IDENTITY)
        await disable.disable(
            KnowledgeDisableCommand(
                **target.model_dump(),
                confirmed=True,
                confirmation_digest=candidate.confirmation_digest,
                idempotency_key="disable-during-retry",
            ),
            identity=IDENTITY,
        )
    finally:
        release.set()
    assert not await job
    async with managed_database.session() as session:
        document = await session.get(Document, original.document_id)
        task = await session.get(Task, accepted.task_id)
        operation = await session.get(Operation, accepted.operation_id)
        assert document is not None and document.current_version_id is None
        assert task is not None and task.state == "STALE"
        assert operation is not None and operation.state == "STALE"
