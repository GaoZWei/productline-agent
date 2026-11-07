"""真实PostgreSQL与批量生成器验证候选完整保存、失败隔离和迟到结果。"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import cast

import pytest
from pydantic import AnyHttpUrl, SecretStr
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.database import Database
from app.knowledge.embeddings import (
    EmbeddingBatchGenerator,
    EmbeddingConfig,
    EmbeddingErrorCode,
    EmbeddingIndexDescriptor,
    EmbeddingProviderError,
)
from app.knowledge.index_build import index_chunk_records, parse_index_input
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.knowledge_index_build import KnowledgeIndexBuildRepository
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationTarget,
)
from app.services.knowledge_index_build import KnowledgeIndexBuildService
from app.services.knowledge_publication import KnowledgePublicationService
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import byte_chunks, generation_payload
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
    revision_command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.test_knowledge_index_build import INDEX, valid_generation

BODY = "# 测试规范\n\n## 要求一\n原文一\n\n## 要求二\n原文二\n"


@dataclass
class ControlledProvider:
    """仅替代外部模型传输，真实批量生成器仍执行分批、身份与向量校验。"""

    database: Database
    descriptor: EmbeddingIndexDescriptor
    hook: Callable[[int], Awaitable[None]] | None = None
    calls: int = 0

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """在每个批次断言没有SQL连接被占用，并返回确定性1536维向量。"""

        assert cast(QueuePool, self.database.engine.pool).checkedout() == 0
        self.calls += 1
        if self.hook:
            await self.hook(self.calls)
        return tuple((float(self.calls),) + (0.0,) * 1535 for _ in texts)


async def prepared(
    management: ManagementHarness,
    database: Database,
    *,
    previous_release: bool = False,
) -> tuple[
    KnowledgeIndexBuildService, KnowledgePublicationAcceptance, ControlledProvider, str | None
]:
    """独立规范与模型配置，不纳管固定语料，不调用真实Provider。"""

    initial = command(
        metadata={**command().metadata.model_dump(), "effective_date": date(1970, 1, 1)}
    )
    uploaded = await management.service.upload(
        initial, byte_chunks(BODY.encode()), identity=IDENTITY
    )
    previous_id = None
    if previous_release:
        previous_id = uploaded.version_id
        generation_id = "GEN-" + "7" * 32
        async with database.session() as session, session.begin():
            await session.execute(
                insert(Generation).values(
                    **generation_payload(
                        generation_id=generation_id,
                        version_id=previous_id,
                        state="READY",
                        chunk_count=1,
                        finished_at=func.now(),
                    )
                )
            )
            await session.execute(
                update(Version)
                .where(Version.version_id == previous_id)
                .values(
                    publication_state="PUBLISHED",
                    published_revision_no=1,
                    published_generation_id=generation_id,
                    published_at=func.now(),
                )
            )
            await session.execute(
                update(Document)
                .where(Document.document_id == uploaded.document_id)
                .values(current_version_id=previous_id)
            )
        uploaded = await management.service.upload(
            command(
                document_id=uploaded.document_id,
                expected_row_version=uploaded.row_version,
                idempotency_key="upload-second",
                metadata={**initial.metadata.model_dump(), "specification_version": "2.0"},
            ),
            byte_chunks(BODY.encode()),
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
    accepted = await publication.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=candidate.confirmation_digest,
            idempotency_key="index-confirm",
        ),
        identity=IDENTITY,
    )
    provider = ControlledProvider(
        database,
        EmbeddingIndexDescriptor(INDEX.provider, INDEX.model, INDEX.dimension, INDEX.index_version),
    )
    config = EmbeddingConfig(
        provider="openai_compatible",
        model=INDEX.model,
        base_url=AnyHttpUrl("https://embedding.invalid/v1"),
        api_key=SecretStr("test-only"),
        index_version=INDEX.index_version,
        batch_size=1,
        max_retries=0,
    )
    service = KnowledgeIndexBuildService(
        KnowledgeIndexBuildRepository(database),
        management.service.authorizer,
        EmbeddingBatchGenerator(config, provider),
        index_identity=INDEX,
        owner_id=management.service.owner_id,
    )
    return service, accepted, provider, previous_id


@pytest.mark.integration
async def test_knowledge_management_index_build_ready_duplicate_and_previous_release_kept(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, accepted, provider, previous = await prepared(
        management, managed_database, previous_release=True
    )
    assert accepted.task_id is not None
    assert await service.process(accepted.task_id, identity=IDENTITY)
    calls = provider.calls
    assert calls >= 2 and not await service.process(accepted.task_id, identity=IDENTITY)
    assert provider.calls == calls
    async with managed_database.session() as session:
        generation = await session.get(Generation, accepted.generation_id)
        task = await session.get(Task, accepted.task_id)
        operation = await session.get(Operation, accepted.operation_id)
        chunks = (
            await session.scalars(
                select(Chunk)
                .where(Chunk.generation_id == accepted.generation_id)
                .order_by(Chunk.chunk_index)
            )
        ).all()
        assert (
            generation is not None
            and generation.state == "READY"
            and generation.chunk_count == len(chunks) == calls
        )
        assert task is not None and task.state == "SUCCEEDED"
        assert (
            operation is not None
            and operation.state == "EXECUTING"
            and operation.finished_at is None
        )
        assert "原文一" in "".join(chunk.content for chunk in chunks)
        assert all(
            len(chunk.embedding) == 1536 and chunk.embedding[0] == chunk.chunk_index + 1
            for chunk in chunks
        )
        document = await session.get(Document, accepted.document_id)
        version = await session.get(Version, accepted.version_id)
        old = await session.get(Version, previous)
        library = await session.get(Library, "DEFAULT")
        assert document is not None and document.current_version_id == previous
        assert version is not None and version.publication_state == "DRAFT"
        assert old is not None and old.publication_state == "PUBLISHED"
        assert (
            library is not None
            and library.source_mode == "LEGACY"
            and library.release_revision == 0
        )


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["timeout", "revoked", "revision", "recovery", "sql"])
async def test_knowledge_management_index_build_failure_has_no_partial_chunks_or_release_change(
    management: ManagementHarness,
    managed_database: Database,
    failure: str,
) -> None:
    service, accepted, provider, previous = await prepared(
        management, managed_database, previous_release=True
    )
    assert accepted.task_id is not None

    async def hook(call: int) -> None:
        """模型期间注入失败或管理变化，SQL持久化仍由真实事务完成。"""

        if failure == "timeout" and call == 2:
            raise EmbeddingProviderError(
                code=EmbeddingErrorCode.TIMEOUT, message="private provider message", retryable=False
            )
        if call != 1:
            return
        if failure == "revoked":
            management.denied.add("PUBLISH")
        elif failure == "revision":
            await management.service.upload(
                revision_command(
                    command(
                        metadata={**command().metadata.model_dump(), "specification_version": "2.0"}
                    ),
                    accepted.document_id,
                    accepted.version_id,
                    accepted.reserved_row_version,
                    1,
                ),
                byte_chunks((BODY + "新修订\n").encode()),
                identity=IDENTITY,
            )
        elif failure == "recovery":
            assert await service.repository.recover_interrupted("new-worker") == 1

    provider.hook = hook

    def fail_insert(*args: object) -> None:
        """只对隔离库分块写入注入故障，验证整批回滚及独立失败收尾。"""

        if str(args[2]).startswith("INSERT INTO managed_knowledge_chunks"):
            raise SQLAlchemyError("private simulated write error")

    if failure == "sql":
        event.listen(managed_database.engine.sync_engine, "after_cursor_execute", fail_insert)
    try:
        if failure == "sql":
            with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
                await service.process(accepted.task_id, identity=IDENTITY)
        else:
            assert not await service.process(accepted.task_id, identity=IDENTITY)
    finally:
        if failure == "sql":
            event.remove(managed_database.engine.sync_engine, "after_cursor_execute", fail_insert)
    async with managed_database.session() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.generation_id == accepted.generation_id)
            )
            == 0
        )
        generation = await session.get(Generation, accepted.generation_id)
        task = await session.get(Task, accepted.task_id)
        operation = await session.get(Operation, accepted.operation_id)
        document = await session.get(Document, accepted.document_id)
        assert generation is not None and generation.state == "FAILED"
        assert task is not None and task.state == {
            "revision": "STALE",
            "recovery": "INTERRUPTED",
        }.get(failure, "FAILED")
        assert operation is not None and operation.state == (
            "STALE" if failure == "revision" else "FAILED"
        )
        assert (
            task.error_code
            == {
                "timeout": "TOOL_TIMEOUT",
                "revoked": "PERMISSION_DENIED",
                "revision": "STALE_INPUT",
                "recovery": "PROCESSING_INTERRUPTED",
                "sql": "INDEX_BUILD_FAILED",
            }[failure]
        )
        assert document is not None and document.current_version_id == previous


@pytest.mark.integration
async def test_knowledge_management_index_build_inflight_duplicate_owner_and_actor_guards(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, accepted, provider, _ = await prepared(management, managed_database)
    assert accepted.task_id is not None
    repository = service.repository
    assert (
        await repository.claim_index(
            accepted.task_id,
            actor="another-reviewer",
            scope="INTERNAL_REVIEWER",
            owner_id=service.owner_id,
            index=INDEX,
        )
        is None
    )
    assert (
        await repository.claim_index(
            accepted.task_id,
            actor=IDENTITY.user_id,
            scope="INTERNAL_REVIEWER",
            owner_id="wrong-owner",
            index=INDEX,
        )
        is None
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait(call: int) -> None:
        """在无SQL连接的模型阶段暂停，让重复请求检查执行权。"""

        if call == 1:
            entered.set()
            await release.wait()

    provider.hook = wait
    task = asyncio.create_task(service.process(accepted.task_id, identity=IDENTITY))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert not await service.process(accepted.task_id, identity=IDENTITY)
    finally:
        release.set()
    assert await task


@pytest.mark.integration
async def test_knowledge_management_index_build_changed_index_rejected_before_model(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, accepted, provider, _ = await prepared(management, managed_database)
    assert accepted.task_id is not None
    async with managed_database.session() as session, session.begin():
        await session.execute(
            update(Generation)
            .where(Generation.generation_id == accepted.generation_id)
            .values(embedding_model="changed-model")
        )
    assert not await service.process(accepted.task_id, identity=IDENTITY)
    assert provider.calls == 0
    async with managed_database.session() as session:
        task = await session.get(Task, accepted.task_id)
        assert (
            task is not None
            and task.state == "FAILED"
            and task.error_code == "INDEX_VALIDATION_FAILED"
        )


@pytest.mark.integration
async def test_knowledge_management_index_build_forged_manifest_cannot_be_saved(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, accepted, _, _ = await prepared(management, managed_database)
    assert accepted.task_id is not None
    claim = await service.repository.claim_index(
        accepted.task_id,
        actor=IDENTITY.user_id,
        scope="INTERNAL_REVIEWER",
        owner_id=service.owner_id,
        index=INDEX,
    )
    assert claim is not None
    records = list(index_chunk_records(claim, parse_index_input(claim), valid_generation(claim)))
    # 合法的正文哈希和向量仍不能让外来正文成为该修订的证据。
    records[0] = records[0].model_copy(
        update={
            "content": "替换正文",
            "content_hash": hashlib.sha256("替换正文".encode()).hexdigest(),
        }
    )
    assert not await service.repository.finish_index(
        claim, tuple(records), scope="INTERNAL_REVIEWER", owner_id=service.owner_id
    )
    async with managed_database.session() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.generation_id == accepted.generation_id)
            )
            == 0
        )
        task = await session.get(Task, accepted.task_id)
        assert (
            task is not None
            and task.state == "FAILED"
            and task.error_code == "INDEX_VALIDATION_FAILED"
        )


@pytest.mark.integration
async def test_knowledge_management_index_build_cancel_persists_interrupted_state(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service, accepted, provider, _ = await prepared(management, managed_database)
    assert accepted.task_id is not None
    entered = asyncio.Event()

    async def wait(call: int) -> None:
        """只在模型阶段等待主动取消，保持数据库连接已释放。"""

        entered.set()
        await asyncio.Event().wait()

    provider.hook = wait
    task = asyncio.create_task(service.process(accepted.task_id, identity=IDENTITY))
    try:
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with managed_database.session() as session:
        record = await session.get(Task, accepted.task_id)
        assert (
            record is not None
            and record.state == "INTERRUPTED"
            and record.error_code == "PROCESSING_INTERRUPTED"
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.generation_id == accepted.generation_id)
            )
            == 0
        )
