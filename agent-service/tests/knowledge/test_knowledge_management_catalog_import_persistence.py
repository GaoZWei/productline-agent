"""整批受确认纳管的真实隔离事务、原件、并发及失败回滚。"""

import asyncio
from typing import TypedDict, Unpack
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.errors import ToolException
from app.knowledge.catalog_import import CatalogImportVersion
from app.knowledge.import_preflight import LegacyImportSnapshot, capture_import_files
from app.knowledge.storage import StagedOriginal
from app.models import KnowledgeChunk
from app.models.managed_knowledge import (
    ManagedKnowledgeDocument as Document,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeLibrary as Library,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeRevision as Revision,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeVersion as Version,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeChunk as Chunk,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeIndexGeneration as Generation,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeOperation as Operation,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeTask as Task,
)
from app.repositories.catalog_import import KnowledgeCatalogImportRepository
from app.repositories.knowledge_disable import KnowledgeDisableRepository
from app.schemas.knowledge_disable import KnowledgeDisableCommand, KnowledgeDisableTarget
from app.schemas.knowledge_import import KnowledgeImportCommand, KnowledgeImportReceipt
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_processing import ManagedKnowledgeChunkRecord
from app.services.catalog_import import KnowledgeCatalogImportService
from app.services.knowledge_disable import KnowledgeDisableService
from app.services.knowledge_import import KnowledgeImportPreflightService
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT
from tests.knowledge.test_knowledge_management_import_preflight_persistence import (
    IDENTITY,
    stored_rows,
)
from tests.knowledge.test_knowledge_management_import_preflight_persistence import (
    managed_database as managed_database,
)
from tests.knowledge.test_knowledge_management_import_preflight_persistence import (
    preflight as preflight,
)
from tests.knowledge.test_knowledge_management_persistence import ManagementHarness
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_catalog_import import command


class CommitOptions(TypedDict):
    """并发和故障注入保留真实提交契约，避免动态参数绕过类型检查。"""

    actor: str
    scope: str
    expected_source: LegacyImportSnapshot
    plan: tuple[CatalogImportVersion, ...]
    chunks: tuple[ManagedKnowledgeChunkRecord, ...]
    index: KnowledgePublicationIndexIdentity
    owner_id: str
    trace_id: str


@pytest.fixture
def importer(
    preflight: KnowledgeImportPreflightService,
    managed_database: Database,
    management: ManagementHarness,
) -> KnowledgeCatalogImportService:
    """复用完整迁移、真实旧Repository及16/80假向量源，不调用模型。"""
    return KnowledgeCatalogImportService(
        KnowledgeCatalogImportRepository(managed_database), preflight, management.service.storage
    )


async def request(importer: KnowledgeCatalogImportService) -> KnowledgeImportCommand:
    """候选展示后由测试模拟明确人工确认，不冒充HTTP交互。"""
    return command((await importer.prepare(identity=IDENTITY)).preflight)


@pytest.mark.integration
async def test_knowledge_management_catalog_import_copies_whole_batch_and_preserves_references(
    importer: KnowledgeCatalogImportService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    before = await stored_rows(managed_database)
    candidate = await request(importer)
    assert await stored_rows(managed_database) == before
    assert not importer.storage.root.exists()
    receipt = await importer.confirm(candidate, identity=IDENTITY)
    assert not receipt.replayed and receipt.source_mode == "LEGACY"
    assert receipt.import_release_revision == receipt.current_release_revision == 1
    after = await stored_rows(managed_database)
    assert after["knowledge_documents"] == before["knowledge_documents"]
    assert after["knowledge_chunks"] == before["knowledge_chunks"]
    async with managed_database.session() as session:
        for model, count in (
            (Document, 14),
            (Version, 16),
            (Revision, 16),
            (Generation, 16),
            (Chunk, 80),
            (Operation, 32),
            (Task, 32),
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == count
        for version in await session.scalars(select(Version)):
            assert version.citation_document_id == version.source_document_id
            assert version.created_by == IDENTITY.user_id
            assert (version.publication_state, version.published_at is None) == (
                ("HISTORICAL", True)
                if version.source_lifecycle == "HISTORICAL"
                else ("PUBLISHED", False)
            )
        for generation in await session.scalars(select(Generation)):
            assert generation.build_method == "COPIED_LEGACY" and generation.state == "READY"
        legacy = {item.chunk_id: item for item in await session.scalars(select(KnowledgeChunk))}
        for copied in await session.scalars(select(Chunk)):
            old = legacy[copied.chunk_id]
            assert (
                copied.chunk_index,
                copied.section_path,
                copied.content,
                copied.content_hash,
                copied.token_count,
                copied.search_document,
            ) == (
                old.chunk_index,
                old.section_path,
                old.content,
                old.content_hash,
                old.token_count,
                old.search_document,
            )
            assert old.embedding is not None
            assert tuple(copied.embedding) == tuple(old.embedding)
        for document in await session.scalars(select(Document)):
            assert document.row_version == 1 and document.current_version_id is not None
        for operation in await session.scalars(select(Operation)):
            assert operation.actor_id == IDENTITY.user_id and operation.state == "SUCCEEDED"
    # 管理预览与原件读取复用已有应用，引用仍使用旧规范ID。
    sources = {
        item.metadata.document_id: item
        for item in capture_import_files(DEFAULT_KNOWLEDGE_ROOT).files
    }
    for entry in receipt.versions:
        preview = await management.service.preview(entry.version_id, 1, identity=IDENTITY)
        source = sources[entry.source_document_id]
        assert [chunk.chunk_id for chunk in preview.chunks] == [
            chunk.chunk_id for chunk in source.parsed.chunks
        ]
        original = await management.service.read_original(entry.version_id, 1, identity=IDENTITY)
        assert original.content == source.raw and preview.body == source.parsed.body
    assert len(list(importer.storage.root.glob("versions/*/revisions/1/original.md"))) == 16
    assert list((importer.storage.root / "_temporary").iterdir()) == []


@pytest.mark.integration
async def test_knowledge_management_catalog_import_replay_does_not_restore_disabled_version(
    importer: KnowledgeCatalogImportService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    candidate = await request(importer)
    first = await importer.confirm(candidate, identity=IDENTITY)
    entry = next(item for item in first.versions if item.imported_state == "PUBLISHED")
    disable = KnowledgeDisableService(
        KnowledgeDisableRepository(managed_database), management.service.authorizer
    )
    target = KnowledgeDisableTarget(
        document_id=entry.document_id,
        version_id=entry.version_id,
        expected_revision_no=1,
        expected_row_version=1,
    )
    review = await disable.prepare(target, identity=IDENTITY)
    await disable.disable(
        KnowledgeDisableCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=review.confirmation_digest,
            idempotency_key="disable-import",
        ),
        identity=IDENTITY,
    )
    # 成功重放不需要旧源仍存在，也不依赖当前模型配置。
    importer.preflight.knowledge_root = importer.storage.root / "missing-source"
    importer.preflight.index_identity = importer.preflight.index_identity.model_copy(
        update={"model": "changed-model"}
    )
    async with managed_database.session() as session, session.begin():
        await session.execute(delete(KnowledgeChunk))
    before = await stored_rows(managed_database)
    replay = await importer.confirm(candidate, identity=IDENTITY)
    assert replay.replayed and replay.imported_at == first.imported_at
    assert replay.versions == first.versions and replay.current_release_revision == 2
    assert await stored_rows(managed_database) == before
    async with managed_database.session() as session:
        document = await session.get(Document, entry.document_id)
        assert document is not None and document.current_version_id is None


@pytest.mark.integration
async def test_knowledge_management_catalog_import_replay_requires_authority_and_same_request(
    importer: KnowledgeCatalogImportService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    candidate = await request(importer)
    await importer.confirm(candidate, identity=IDENTITY)
    before = await stored_rows(managed_database)
    changed = candidate.model_copy(update={"source_fingerprint": "a" * 64})
    with pytest.raises(KnowledgeManagementError, match="IDEMPOTENCY_CONFLICT"):
        await importer.confirm(changed, identity=IDENTITY)
    management.denied.add("PUBLISH")
    with pytest.raises(ToolException):
        await importer.confirm(candidate, identity=IDENTITY)
    assert await stored_rows(managed_database) == before


@pytest.mark.integration
@pytest.mark.parametrize("different_key", [False, True])
async def test_knowledge_management_catalog_import_concurrent_commits_are_atomic(
    importer: KnowledgeCatalogImportService, managed_database: Database, different_key: bool
) -> None:
    candidate = await request(importer)
    other = (
        candidate.model_copy(update={"idempotency_key": "other-import"})
        if different_key
        else candidate
    )
    original_commit = importer.repository.commit
    # 先分别完成真实Client授权和原件复制，再并发Repository提交。
    # 既有夹具断言整个连接池为空，不能拿它冒充并发HTTP授权验收。
    pending = AsyncMock(return_value=None)
    with patch.object(importer.repository, "commit", pending):
        await importer.confirm(candidate, identity=IDENTITY)
        await importer.confirm(other, identity=IDENTITY)
    assert pending.await_count == 2
    results = await asyncio.wait_for(
        asyncio.gather(
            *(original_commit(*call.args, **call.kwargs) for call in pending.await_args_list),
            return_exceptions=True,
        ),
        timeout=10,
    )
    receipts = [item for item in results if isinstance(item, KnowledgeImportReceipt)]
    if different_key:
        assert len(receipts) == 1
        assert sum(isinstance(item, KnowledgeManagementError) for item in results) == 1
    else:
        assert len(receipts) == 2 and sum(item.replayed for item in receipts) == 1
        assert receipts[0].versions == receipts[1].versions
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Version)) == 16
        library = await session.get(Library, "DEFAULT")
        assert library is not None and library.release_revision == 1


@pytest.mark.integration
async def test_knowledge_management_catalog_import_rolls_back_and_retry_reuses_originals(
    importer: KnowledgeCatalogImportService, managed_database: Database
) -> None:
    candidate = await request(importer)
    before = await stored_rows(managed_database)

    def fail(
        _conn: object,
        _cursor: object,
        statement: str,
        _params: object,
        _context: object,
        _many: object,
    ) -> None:
        """已执行首个版本封存后故障，验证所有表和来源标记回滚。"""
        if statement.startswith("UPDATE managed_knowledge_versions"):
            raise SQLAlchemyError("injected private database detail")

    event.listen(managed_database.engine.sync_engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
            await importer.confirm(candidate, identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "after_cursor_execute", fail)
    assert await stored_rows(managed_database) == before
    originals = sorted(importer.storage.root.glob("versions/*/revisions/1/original.md"))
    assert len(originals) == 16
    receipt = await importer.confirm(candidate, identity=IDENTITY)
    assert not receipt.replayed
    assert sorted(importer.storage.root.glob("versions/*/revisions/1/original.md")) == originals


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["vector", "library"])
async def test_knowledge_management_catalog_import_rechecks_legacy_after_copy(
    importer: KnowledgeCatalogImportService, managed_database: Database, kind: str
) -> None:
    candidate = await request(importer)
    original_commit = importer.repository.commit

    async def commit(
        command: KnowledgeImportCommand, **kwargs: Unpack[CommitOptions]
    ) -> KnowledgeImportReceipt:
        """最终源表锁前外部旧CLI已更新向量，本次确认必须失败。"""
        async with managed_database.session() as session, session.begin():
            if kind == "vector":
                chunk = await session.scalar(select(KnowledgeChunk).limit(1))
                assert chunk is not None
                chunk.embedding = [2.5] + [0.0] * 1535
            else:
                await session.execute(update(Library).values(release_revision=1))
        return await original_commit(command, **kwargs)

    with patch.object(importer.repository, "commit", side_effect=commit):
        with pytest.raises(
            KnowledgeManagementError,
            match="IMPORT_SOURCE_CHANGED" if kind == "vector" else "STALE_LIBRARY",
        ):
            await importer.confirm(candidate, identity=IDENTITY)
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Version)) == 0


@pytest.mark.integration
async def test_knowledge_management_catalog_import_locks_legacy_until_atomic_commit(
    importer: KnowledgeCatalogImportService, managed_database: Database
) -> None:
    candidate = await request(importer)
    original_read = importer.repository.source.read_in_session

    async def legacy_writer() -> None:
        """模拟旧CLI的分块写入，必须被纳管事务的SHARE锁拒绝。"""
        async with managed_database.session() as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
            await session.execute(update(KnowledgeChunk).values(content="should-be-blocked"))

    async def read(session: AsyncSession, ids: tuple[str, ...], scope: str) -> LegacyImportSnapshot:
        """测试在已取得真实源表锁后启动独立连接，不在生产流程增加等待。"""
        source = await original_read(session, ids, scope)
        with pytest.raises(DBAPIError):
            await legacy_writer()
        return source

    with patch.object(importer.repository.source, "read_in_session", side_effect=read):
        receipt = await importer.confirm(candidate, identity=IDENTITY)
    assert receipt.import_release_revision == 1


@pytest.mark.integration
async def test_knowledge_management_catalog_import_storage_failure_never_writes_management(
    importer: KnowledgeCatalogImportService, managed_database: Database
) -> None:
    candidate = await request(importer)
    before = await stored_rows(managed_database)
    original_commit = importer.storage.commit
    calls = 0

    def commit(staged: StagedOriginal, key: str) -> None:
        """复制第二份原件失败，首份原件保留供同一请求受控重试。"""
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KnowledgeManagementError("STORAGE_ERROR")
        original_commit(staged, key)

    with patch.object(importer.storage, "commit", side_effect=commit):
        with pytest.raises(KnowledgeManagementError, match="STORAGE_ERROR"):
            await importer.confirm(candidate, identity=IDENTITY)
    assert await stored_rows(managed_database) == before
    receipt = await importer.confirm(candidate, identity=IDENTITY)
    assert not receipt.replayed


@pytest.mark.integration
async def test_knowledge_management_catalog_import_reauthorizes_after_copy(
    importer: KnowledgeCatalogImportService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    candidate = await request(importer)
    before = await stored_rows(managed_database)
    original_read = importer.storage.read

    def revoke(key: str, raw_hash: str, byte_size: int) -> bytes:
        """复制之后撤销发布权限，确认不能继续写入整批管理记录。"""
        data = original_read(key, raw_hash, byte_size)
        management.denied.add("PUBLISH")
        return data

    with patch.object(importer.storage, "read", side_effect=revoke):
        with pytest.raises(ToolException):
            await importer.confirm(candidate, identity=IDENTITY)
    assert await stored_rows(managed_database) == before
    management.denied.clear()
    receipt = await importer.confirm(candidate, identity=IDENTITY)
    assert not receipt.replayed
