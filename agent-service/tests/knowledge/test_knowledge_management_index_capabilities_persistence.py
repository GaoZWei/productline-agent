"""管理库动态就绪的真实隔离快照、全量证据及发布集合变化测试。"""

from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import Result, event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql.base import Executable

from app.database import Database
from app.knowledge.publication import publication_generation_hash
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
from app.models.managed_knowledge_processing import ManagedKnowledgeChunk as Chunk
from app.models.managed_knowledge_processing import ManagedKnowledgeIndexGeneration as Generation
from app.repositories.knowledge_disable import KnowledgeDisableRepository
from app.repositories.managed_knowledge_index import (
    ManagedKnowledgeIndexRepository,
    ManagedPublishedIndexSnapshot,
)
from app.schemas.knowledge_disable import KnowledgeDisableCommand, KnowledgeDisableTarget
from app.schemas.knowledge_index import KnowledgeIndexStatus
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_index import (
    ManagedKnowledgeIndexCapabilities,
    ManagedKnowledgeIndexIdentity,
)
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation
from app.services.knowledge_disable import KnowledgeDisableService
from app.services.knowledge_import import KnowledgeImportPreflightService
from app.services.managed_knowledge_index import (
    ManagedKnowledgeIndexCapabilityService,
    evaluate_published_index,
)
from tests.knowledge.import_preflight_fixtures import INDEX
from tests.knowledge.managed_knowledge_fixtures import byte_chunks
from tests.knowledge.test_knowledge_management_catalog_import_persistence import (
    importer as importer,
)
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
from tests.knowledge.test_knowledge_management_persistence import IDENTITY as BUILD_IDENTITY
from tests.knowledge.test_knowledge_management_persistence import ManagementHarness, command
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.knowledge.test_knowledge_management_publication_finalize_persistence import (
    finalizer,
    ready,
)
from tests.knowledge.test_knowledge_management_search_persistence import SearchFixture
from tests.knowledge.test_knowledge_management_search_persistence import knowledge as knowledge
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_knowledge_index_build import INDEX as BUILD_INDEX


def capability(
    management: ManagementHarness, database: Database
) -> ManagedKnowledgeIndexCapabilityService:
    """复用READ客户端，没有文件系统、Query Embedding或回答模型依赖。"""
    return ManagedKnowledgeIndexCapabilityService(
        ManagedKnowledgeIndexRepository(database),
        management.service.authorizer,
        index_identity=INDEX,
    )


@pytest.mark.integration
async def test_knowledge_management_index_capabilities_checks_all_published_data_outside_sql(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
    service = capability(management, managed_database)
    before = await stored_rows(managed_database)
    statements: list[str] = []

    def capture(
        _conn: object,
        _cursor: object,
        statement: str,
        _params: object,
        _context: object,
        _many: object,
    ) -> None:
        """只记录语句，禁止输出正文、参数或完整向量。"""
        statements.append(statement)

    def evaluate(
        snapshot: ManagedPublishedIndexSnapshot, expected: KnowledgePublicationIndexIdentity
    ) -> ManagedKnowledgeIndexCapabilities:
        """完整正文/向量检查确实发生在SQL连接释放后。"""
        assert cast(QueuePool, managed_database.engine.pool).checkedout() == 0
        return evaluate_published_index(snapshot, expected)

    event.listen(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        with patch(
            "app.services.managed_knowledge_index.evaluate_published_index", side_effect=evaluate
        ):
            report = await service.get(identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    published = [
        entry for entry in knowledge.receipt.versions if entry.imported_state == "PUBLISHED"
    ]
    assert (
        report.ready
        and report.expected_document_count == report.document_count == len(published) == 14
    )
    async with managed_database.session() as session:
        expected_chunks = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.generation_id.in_([entry.generation_id for entry in published]))
        )
    assert report.chunk_count == expected_chunks and report.release_revision == 1
    assert report.source == "MANAGED" and report.configured_source_mode == "LEGACY"
    assert knowledge.generator.calls == [] and management.actions == ["READ"]
    assert all(
        statement.lstrip().startswith(("SELECT", "SET TRANSACTION")) for statement in statements
    )
    assert not any(
        "FROM knowledge_" in statement or "JOIN knowledge_documents" in statement
        for statement in statements
    )
    assert await stored_rows(managed_database) == before
    service.index = INDEX.model_copy(update={"index_version": "new-index"})
    mismatch = await service.get(identity=IDENTITY)
    assert mismatch.status == KnowledgeIndexStatus.INDEX_MISMATCH and not mismatch.ready


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind", ["missing", "content", "vector", "metadata", "input", "pointer", "state", "building"]
)
async def test_knowledge_management_index_capabilities_rejects_broken_published_data(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness, kind: str
) -> None:
    entry = next(item for item in knowledge.receipt.versions if item.imported_state == "PUBLISHED")
    async with managed_database.session() as session, session.begin():
        if kind in {"missing", "content", "vector"}:
            chunk = await session.scalar(
                select(Chunk)
                .where(Chunk.generation_id == entry.generation_id)
                .order_by(Chunk.chunk_index.desc())
                .limit(1)
            )
            assert chunk is not None
            if kind == "missing":
                await session.delete(chunk)
            elif kind == "content":
                chunk.content = "changed"
            else:
                chunk.embedding = [0.0] * 1536
        elif kind == "metadata":
            await session.execute(
                update(Revision)
                .where(Revision.version_id == entry.version_id)
                .values(metadata_hash="a" * 64)
            )
        elif kind == "input":
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == entry.generation_id)
                .values(input_hash="a" * 64)
            )
        elif kind == "pointer":
            await session.execute(
                update(Document)
                .where(Document.document_id == entry.document_id)
                .values(current_version_id=None)
            )
        elif kind == "state":
            await session.execute(
                update(Version)
                .where(Version.version_id == entry.version_id)
                .values(publication_state="DISABLED")
            )
        else:
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == entry.generation_id)
                .values(state="BUILDING", finished_at=None)
            )
    report = await capability(management, managed_database).get(identity=IDENTITY)
    assert report.expected_document_count == 14 and not report.ready
    assert report.status == KnowledgeIndexStatus.INCOMPLETE


@pytest.mark.integration
async def test_knowledge_management_index_capabilities_checks_full_mixed_identity(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
    entry = next(item for item in knowledge.receipt.versions if item.imported_state == "PUBLISHED")
    async with managed_database.session() as session, session.begin():
        generation = await session.get(Generation, entry.generation_id)
        revision = await session.get(Revision, (entry.version_id, 1))
        assert generation is not None and revision is not None
        generation.chunking_version = "heading-v2"
        identity = ManagedKnowledgeIndexIdentity(
            provider=INDEX.provider,
            model=INDEX.model,
            dimension=1536,
            index_version=INDEX.index_version,
            chunking_version="heading-v2",
        )
        generation.input_hash = publication_generation_hash(
            ManagedKnowledgeConfirmation(
                actor_id=IDENTITY.user_id,
                action="PUBLISH",
                document_id=entry.document_id,
                version_id=entry.version_id,
                revision_no=1,
                raw_hash=revision.raw_hash,
                normalized_hash=revision.normalized_hash,
                metadata_hash=revision.metadata_hash,
                expected_row_version=0,
            ),
            entry.source_document_id,
            identity,
        )
    report = await capability(management, managed_database).get(identity=IDENTITY)
    assert report.status == KnowledgeIndexStatus.INDEX_MISMATCH and report.stored_index is None
    assert report.document_count == report.expected_document_count == 14


@pytest.mark.integration
async def test_knowledge_management_index_capabilities_all_disabled_is_explicit_zero(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
    disable = KnowledgeDisableService(
        KnowledgeDisableRepository(managed_database), management.service.authorizer
    )
    entries = [entry for entry in knowledge.receipt.versions if entry.imported_state == "PUBLISHED"]
    for entry in entries:
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
                idempotency_key="disable-" + entry.version_id,
            ),
            identity=IDENTITY,
        )
    report = await capability(management, managed_database).get(identity=IDENTITY)
    assert report.status == KnowledgeIndexStatus.NOT_INDEXED and report.message == "无已发布资料"
    assert report.expected_document_count == report.document_count == report.chunk_count == 0
    assert report.release_revision == 1 + len(entries) and report.stored_index is None


@pytest.mark.integration
async def test_knowledge_management_index_capabilities_ignores_draft_and_unused_failed_generation(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
    service = capability(management, managed_database)
    before = await service.get(identity=IDENTITY)
    await management.service.upload(
        command(), byte_chunks("# 测试规范\n\n## 要求\n草稿正文。\n".encode()), identity=IDENTITY
    )
    historical = next(
        entry for entry in knowledge.receipt.versions if entry.imported_state == "HISTORICAL"
    )
    async with managed_database.session() as session, session.begin():
        await session.execute(
            update(Generation)
            .where(Generation.generation_id == historical.generation_id)
            .values(state="FAILED", error_code="INDEX_BUILD_FAILED")
        )
    assert await service.get(identity=IDENTITY) == before


@pytest.mark.integration
async def test_knowledge_management_index_capabilities_empty_and_single_release_are_dynamic(
    preflight: KnowledgeImportPreflightService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    service = capability(management, managed_database)
    empty = await service.get(identity=IDENTITY)
    assert empty.expected_document_count == 0 and empty.status == KnowledgeIndexStatus.NOT_INDEXED
    accepted = await ready(management, managed_database)
    await finalizer(management, managed_database).finalize(
        accepted.operation_id, identity=BUILD_IDENTITY
    )
    service.index = BUILD_INDEX
    report = await service.get(identity=BUILD_IDENTITY)
    assert report.ready and report.expected_document_count == report.document_count == 1


@pytest.mark.integration
async def test_knowledge_management_index_capabilities_same_snapshot_during_disable(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
    original = AsyncSession.execute
    changed = False

    async def execute(session: AsyncSession, statement: Executable, **kwargs: Any) -> Result[Any]:
        """发布声明读出后独立提交停用，分块/计数仍须属于原只读快照。"""
        nonlocal changed
        result = await original(session, statement, **kwargs)
        if (
            "LEFT OUTER JOIN" in str(statement)
            and "managed_knowledge_versions" in str(statement)
            and not changed
        ):
            changed = True
            async with managed_database.session() as writer, writer.begin():
                await writer.execute(
                    update(Version)
                    .where(Version.publication_state == "PUBLISHED")
                    .values(publication_state="DISABLED")
                )
                await writer.execute(update(Document).values(current_version_id=None))
                await writer.execute(update(Library).values(release_revision=2))
        return result

    service = capability(management, managed_database)
    with patch.object(AsyncSession, "execute", new=execute):
        first = await service.get(identity=IDENTITY)
    assert (
        changed
        and first.ready
        and first.expected_document_count == 14
        and first.release_revision == 1
    )
    second = await service.get(identity=IDENTITY)
    assert not second.ready and second.expected_document_count == 0 and second.release_revision == 2
