"""真实隔离PostgreSQL管理检索，假向量及模拟并发提交不访问线上数据。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import Result, event, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql.base import Executable

from app.database import Database
from app.knowledge.chunking import DocumentChunk
from app.knowledge.embeddings import (
    ChunkEmbedding,
    EmbeddingGeneration,
    EmbeddingIndexDescriptor,
    QueryEmbedding,
)
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
from app.repositories.knowledge_index_build import KnowledgeIndexBuildRepository
from app.repositories.knowledge_publication_finalize import KnowledgePublicationFinalizeRepository
from app.repositories.managed_knowledge import ManagedKnowledgeRepository
from app.repositories.managed_knowledge_search import ManagedKnowledgeSearchRepository
from app.schemas.knowledge import PermissionScope
from app.schemas.knowledge_import import KnowledgeImportReceipt
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge_search import (
    ManagedKnowledgeSearchFilter,
    ManagedKnowledgeSearchOptions,
)
from app.services.catalog_import import KnowledgeCatalogImportService
from app.services.knowledge_import import KnowledgeImportPreflightService
from app.services.knowledge_index_build import KnowledgeIndexBuildService
from app.services.knowledge_publication import KnowledgePublicationService
from app.services.knowledge_publication_finalize import KnowledgePublicationFinalizeService
from app.services.managed_knowledge_search import ManagedKnowledgeSearchService
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
from tests.knowledge.test_knowledge_management_persistence import ManagementHarness, command
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_catalog_import import command as import_command

FILTERS = ManagedKnowledgeSearchFilter(
    effective_at=date(2026, 11, 7), permission_scope=PermissionScope.INTERNAL_REVIEWER
)
OPTIONS = ManagedKnowledgeSearchOptions(channel_top_k=100, hybrid_top_k=100)
DESCRIPTOR = EmbeddingIndexDescriptor(INDEX.provider, INDEX.model, 1536, INDEX.index_version)


class FakeGenerator:
    """假查询/文档向量，断言整个测试连接池在模型阶段没有被借用。"""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.calls: list[str] = []

    async def generate_query(self, query: str) -> QueryEmbedding:
        """向量阶段不持有SQL事务。"""
        assert cast(QueuePool, self.database.engine.pool).checkedout() == 0
        self.calls.append(query)
        return QueryEmbedding(DESCRIPTOR, (1.0,) + (0.0,) * 1535)

    async def generate(self, chunks: Sequence[DocumentChunk]) -> EmbeddingGeneration:
        """沿用真实构建/发布应用，仅供应商调用为固定响应。"""
        assert cast(QueuePool, self.database.engine.pool).checkedout() == 0
        return EmbeddingGeneration(
            DESCRIPTOR,
            datetime(2026, 11, 7, tzinfo=UTC),
            tuple(ChunkEmbedding(chunk.chunk_id, (1.0,) + (0.0,) * 1535) for chunk in chunks),
        )


@dataclass
class SearchFixture:
    """真实纳管后的管理库与检索应用，原LEGACY16/80同时保留用于隔离验证。"""

    service: ManagedKnowledgeSearchService
    repository: ManagedKnowledgeSearchRepository
    generator: FakeGenerator
    receipt: KnowledgeImportReceipt


@pytest_asyncio.fixture
async def knowledge(
    importer: KnowledgeCatalogImportService,
    managed_database: Database,
    management: ManagementHarness,
) -> SearchFixture:
    """用真实受确认纳管准备发布集合，不手工伪造可检索版本。"""
    report = (await importer.prepare(identity=IDENTITY)).preflight
    receipt = await importer.confirm(import_command(report), identity=IDENTITY)
    generator = FakeGenerator(managed_database)
    repository = ManagedKnowledgeSearchRepository(managed_database, index_identity=INDEX)
    service = ManagedKnowledgeSearchService(
        repository, management.service.authorizer, generator, options=OPTIONS
    )
    management.actions.clear()
    return SearchFixture(service, repository, generator, receipt)


@pytest.mark.integration
async def test_knowledge_management_search_is_read_only_and_preserves_version_bindings(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
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
        """只看语句，不记录查询、原文或完整向量参数。"""
        statements.append(statement)

    event.listen(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await knowledge.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    assert result.results and result.evidence
    assert result.context.source == "MANAGED" and result.context.configured_source_mode == "LEGACY"
    assert result.context.release_revision == 1 and management.actions == ["READ"]
    assert knowledge.generator.calls == ["坐标"]
    published = {
        entry.source_document_id: entry
        for entry in knowledge.receipt.versions
        if entry.imported_state == "PUBLISHED"
    }
    for binding in result.evidence:
        entry = published[binding.citation_document_id]
        assert (binding.document_id, binding.version_id, binding.generation_id) == (
            entry.document_id,
            entry.version_id,
            entry.generation_id,
        )
    assert all(item.document_id in published for item in result.results)
    assert all(
        statement.lstrip().startswith(("SELECT", "SET TRANSACTION")) for statement in statements
    )
    assert any("REPEATABLE READ READ ONLY" in statement for statement in statements)
    assert not any(
        "FROM knowledge_chunks" in statement or "JOIN knowledge_documents" in statement
        for statement in statements
    )
    assert await stored_rows(managed_database) == before


@pytest.mark.integration
@pytest.mark.parametrize(
    "field,value",
    [
        ("product_type", "OTHER"),
        ("satellite_type", "GF-9"),
        ("processing_level", "L9"),
        ("specification_version", "9.0"),
        ("effective_at", date(2024, 1, 1)),
    ],
)
async def test_knowledge_management_search_filters_both_channels_before_topk(
    knowledge: SearchFixture, field: str, value: object
) -> None:
    filters = ManagedKnowledgeSearchFilter.model_validate({**FILTERS.model_dump(), field: value})
    snapshot = await knowledge.repository.search(
        "坐标",
        await knowledge.generator.generate_query("坐标"),
        filters=filters,
        options=ManagedKnowledgeSearchOptions(channel_top_k=1),
    )
    assert snapshot.keyword_hits == () and snapshot.vector_hits == ()


@pytest.mark.integration
async def test_knowledge_management_search_filters_document_type_and_version_before_vector_topk(
    knowledge: SearchFixture,
) -> None:
    filters = ManagedKnowledgeSearchFilter.model_validate(
        {
            **FILTERS.model_dump(),
            "document_type": "QUALITY_SPEC",
            "specification_version": "2.1",
            "processing_level": "L2",
            "product_type": "DOM",
            "satellite_type": "GF-2",
        }
    )
    snapshot = await knowledge.repository.search(
        "质量",
        await knowledge.generator.generate_query("质量"),
        filters=filters,
        options=ManagedKnowledgeSearchOptions(channel_top_k=1),
    )
    assert len(snapshot.vector_hits) == 1
    assert snapshot.vector_hits[0].document_id.startswith("QUALITY-")
    assert snapshot.vector_hits[0].document_version == "2.1"
    assert len(snapshot.keyword_hits) == 1
    assert all(item.document_id.startswith("QUALITY-") for item in snapshot.keyword_hits)


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind",
    ["disabled", "superseded", "pointer", "building", "model", "chunking", "future", "expired"],
)
async def test_knowledge_management_search_excludes_unpublished_inapplicable_or_wrong_index(
    knowledge: SearchFixture, managed_database: Database, kind: str
) -> None:
    entry = next(
        item
        for item in knowledge.receipt.versions
        if item.source_document_id == "COORDINATE-REFERENCE-002"
    )
    async with managed_database.session() as session, session.begin():
        if kind in {"disabled", "superseded"}:
            await session.execute(
                update(Version)
                .where(Version.version_id == entry.version_id)
                .values(publication_state=kind.upper())
            )
        elif kind == "pointer":
            await session.execute(
                update(Document)
                .where(Document.document_id == entry.document_id)
                .values(current_version_id=None)
            )
        elif kind == "building":
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == entry.generation_id)
                .values(state="BUILDING", finished_at=None)
            )
        elif kind in {"model", "chunking"}:
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == entry.generation_id)
                .values(
                    **(
                        {"embedding_model": "another-model"}
                        if kind == "model"
                        else {"chunking_version": "other-v1"}
                    )
                )
            )
        else:
            await session.execute(
                update(Revision)
                .where(Revision.version_id == entry.version_id)
                .values(
                    **(
                        {"effective_date": date(2030, 1, 1)}
                        if kind == "future"
                        else {"expiry_date": date(2025, 12, 31)}
                    )
                )
            )
    result = await knowledge.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert all(item.version_id != entry.version_id for item in result.evidence)
    assert all(item.document_id != entry.source_document_id for item in result.results)


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["chunk", "metadata", "input", "count", "zero-vector"])
async def test_knowledge_management_search_rejects_corrupt_sealed_candidates(
    knowledge: SearchFixture, managed_database: Database, kind: str
) -> None:
    entry = next(
        item
        for item in knowledge.receipt.versions
        if item.source_document_id == "COORDINATE-REFERENCE-002"
    )
    async with managed_database.session() as session, session.begin():
        if kind == "metadata":
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
        elif kind == "count":
            await session.execute(
                update(Generation)
                .where(Generation.generation_id == entry.generation_id)
                .values(chunk_count=1)
            )
        else:
            await session.execute(
                update(Chunk)
                .where(Chunk.generation_id == entry.generation_id)
                .values(
                    **({"content": "changed"} if kind == "chunk" else {"embedding": [0.0] * 1536})
                )
            )
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_DATA_INVALID"):
        await knowledge.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)


@pytest.mark.integration
async def test_knowledge_management_search_empty_managed_library_never_reads_legacy(
    preflight: KnowledgeImportPreflightService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    # preflight夹具仅建立旧16/80，不执行纳管。
    service = ManagedKnowledgeSearchService(
        ManagedKnowledgeSearchRepository(managed_database, index_identity=INDEX),
        management.service.authorizer,
        FakeGenerator(managed_database),
    )
    result = await service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert result.results == () and result.evidence == () and result.context.release_revision == 0


@pytest.mark.integration
async def test_knowledge_management_search_two_channels_keep_one_snapshot_during_disable(
    knowledge: SearchFixture, managed_database: Database
) -> None:
    entry = next(
        item
        for item in knowledge.receipt.versions
        if item.source_document_id == "COORDINATE-REFERENCE-002"
    )
    original = AsyncSession.execute
    changed = False

    async def execute(session: AsyncSession, statement: Executable) -> Result[Any]:
        """关键词读出后用独立事务模拟已获授权的停用提交，不触碰当前读事务。"""
        nonlocal changed
        result = await original(session, statement)
        if "keyword_score" in str(statement) and not changed:
            changed = True
            async with managed_database.session() as writer, writer.begin():
                await writer.execute(
                    update(Version)
                    .where(Version.version_id == entry.version_id)
                    .values(publication_state="DISABLED")
                )
                await writer.execute(
                    update(Document)
                    .where(Document.document_id == entry.document_id)
                    .values(current_version_id=None, row_version=2)
                )
                await writer.execute(update(Library).values(release_revision=2))
        return result

    with patch.object(AsyncSession, "execute", new=execute):
        snapshot = await knowledge.repository.search(
            "坐标",
            await knowledge.generator.generate_query("坐标"),
            filters=FILTERS,
            options=OPTIONS,
        )
    assert changed and snapshot.context.release_revision == 1
    assert any(item.document_id == entry.source_document_id for item in snapshot.keyword_hits)
    assert any(item.document_id == entry.source_document_id for item in snapshot.vector_hits)
    next_result = await knowledge.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert next_result.context.release_revision == 2
    assert all(item.version_id != entry.version_id for item in next_result.evidence)


@pytest.mark.integration
async def test_knowledge_management_search_new_version_is_hidden_until_final_publish(
    knowledge: SearchFixture, managed_database: Database, management: ManagementHarness
) -> None:
    entry = next(
        item
        for item in knowledge.receipt.versions
        if item.source_document_id == "DOM-PRODUCTION-002"
    )
    raw = "# 更新规范\n\n## 要求\n新版本规范正文。\n".encode()
    upload = await management.service.upload(
        command(
            document_id=entry.document_id,
            expected_row_version=1,
            metadata={
                "title": "更新规范",
                "document_type": "DOM_PRODUCT_SPEC",
                "specification_version": "3.0",
                "product_type": "DOM",
                "satellite_type": "GF-2",
                "processing_level": "L2",
                "effective_date": date(1970, 1, 1),
                "permission_scope": "INTERNAL_REVIEWER",
                "change_summary": "更新演示规范",
            },
        ),
        byte_chunks(raw),
        identity=IDENTITY,
    )
    target = KnowledgePublicationTarget(
        document_id=entry.document_id,
        version_id=upload.version_id,
        expected_revision_no=1,
        expected_row_version=upload.row_version,
    )
    publication = KnowledgePublicationService(
        ManagedKnowledgeRepository(managed_database),
        management.service.authorizer,
        index_identity=INDEX,
        owner_id=management.service.owner_id,
    )
    review = await publication.prepare(target, identity=IDENTITY)
    accepted = await publication.accept(
        KnowledgePublicationConfirmCommand(
            **target.model_dump(),
            confirmed=True,
            confirmation_digest=review.confirmation_digest,
            idempotency_key="new-spec-publish",
        ),
        identity=IDENTITY,
    )
    before = await knowledge.service.retrieve("规范", filters=FILTERS, identity=IDENTITY)
    assert any(item.version_id == entry.version_id for item in before.evidence)
    assert all(item.version_id != upload.version_id for item in before.evidence)
    builder = KnowledgeIndexBuildService(
        KnowledgeIndexBuildRepository(managed_database),
        management.service.authorizer,
        knowledge.generator,
        index_identity=INDEX,
        owner_id=management.service.owner_id,
    )
    assert accepted.task_id is not None and await builder.process(
        accepted.task_id, identity=IDENTITY
    )
    ready_result = await knowledge.service.retrieve("规范", filters=FILTERS, identity=IDENTITY)
    assert all(item.version_id != upload.version_id for item in ready_result.evidence)
    finalizer = KnowledgePublicationFinalizeService(
        KnowledgePublicationFinalizeRepository(managed_database),
        management.service.authorizer,
        index_identity=INDEX,
    )
    await finalizer.finalize(accepted.operation_id, identity=IDENTITY)
    after = await knowledge.service.retrieve("规范", filters=FILTERS, identity=IDENTITY)
    assert any(item.version_id == upload.version_id for item in after.evidence)
    assert all(item.version_id != entry.version_id for item in after.evidence)
    assert any(
        item.document_id == upload.version_id and item.document_version == "3.0"
        for item in after.results
    )
    assert any(item.document_id == entry.source_document_id for item in before.results)
