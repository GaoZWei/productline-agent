"""真实隔离PostgreSQL核对固定语料与假向量，绝不读取运行中的索引。"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select, text, update

from app.database import Base, Database
from app.knowledge.embeddings import ChunkEmbedding, EmbeddingGeneration, EmbeddingIndexDescriptor
from app.knowledge.import_preflight import capture_import_files
from app.knowledge.loaders import DocumentFormat
from app.knowledge.pipeline import ProcessedDocument
from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.managed_knowledge import ManagedKnowledgeLibrary, ManagedKnowledgeVersion
from app.repositories.knowledge import KnowledgeIndexRepository
from app.repositories.knowledge_import import KnowledgeImportPreflightRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_management import KnowledgeManagementError
from app.services.knowledge_import import KnowledgeImportPreflightService
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT
from tests.knowledge.import_preflight_fixtures import INDEX, INDEXED_AT, source_snapshot
from tests.knowledge.managed_knowledge_fixtures import byte_chunks
from tests.knowledge.test_knowledge_management_persistence import ManagementHarness, command
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.test_agent_persistence import migrated_database_url as migrated_database_url

IDENTITY = BusinessIdentity(user_id="import-reviewer", role="REVIEWER")


@pytest_asyncio.fixture
async def managed_database(migrated_database_url: str) -> AsyncIterator[Database]:
    """完整迁移独立数据库，不能借用仅含占位旧表的管理库夹具。"""

    database = Database(migrated_database_url)
    yield database
    await database.dispose()


@pytest_asyncio.fixture
async def preflight(
    management: ManagementHarness, managed_database: Database
) -> KnowledgeImportPreflightService:
    """通过原CLI的Repository种入真实16/80测试索引，不访问Provider。"""

    files = capture_import_files(DEFAULT_KNOWLEDGE_ROOT)
    snapshot = source_snapshot(files)
    processed = tuple(
        ProcessedDocument(
            item.metadata,
            DocumentFormat.MARKDOWN
            if item.metadata.file_path.endswith(".md")
            else DocumentFormat.PLAIN_TEXT,
            item.parsed.normalized_hash,
            item.parsed.chunks,
        )
        for item in files.files
    )
    generation = EmbeddingGeneration(
        descriptor=EmbeddingIndexDescriptor(
            provider=INDEX.provider,
            model=INDEX.model,
            dimension=1536,
            index_version=INDEX.index_version,
        ),
        generated_at=INDEXED_AT,
        embeddings=tuple(ChunkEmbedding(item.chunk_id, item.embedding) for item in snapshot.chunks),
    )
    async with managed_database.session() as session, session.begin():
        await KnowledgeIndexRepository(session).reindex_documents(processed, generation)
    return KnowledgeImportPreflightService(
        KnowledgeImportPreflightRepository(managed_database),
        management.service.authorizer,
        index_identity=INDEX,
    )


async def stored_rows(database: Database) -> dict[str, str]:
    """比较旧索引与八张管理表所有持久字段，捕获隐式恢复或触碰审计。"""

    result: dict[str, str] = {}
    async with database.session() as session:
        for name in sorted(Base.metadata.tables):
            if name.startswith(("knowledge_", "managed_knowledge_")):
                value = await session.scalar(
                    text(
                        "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), "
                        f"'[]'::jsonb)::text FROM {name} t"
                    )
                )
                assert isinstance(value, str)
                result[name] = value
    assert len(result) == 10
    return result


@pytest.mark.integration
async def test_knowledge_management_import_preflight_is_read_only_and_repeatable(
    preflight: KnowledgeImportPreflightService,
    managed_database: Database,
    management: ManagementHarness,
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
        """只捕获语句类型，不输出参数、原件或完整向量。"""
        statements.append(statement)

    event.listen(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        report = await preflight.check(identity=IDENTITY)
        repeated = await preflight.check(identity=IDENTITY)
    finally:
        event.remove(managed_database.engine.sync_engine, "before_cursor_execute", capture)
    assert report == repeated and report.checked_by == IDENTITY.user_id
    assert (
        report.logical_document_count == 14
        and report.version_count == 16
        and report.chunk_count == 80
    )
    assert management.actions == ["UPLOAD", "PUBLISH"] * 2
    assert (
        sum(
            statement.startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for statement in statements
        )
        == 2
    )
    assert all(
        statement.lstrip().startswith(("SELECT", "SET TRANSACTION")) for statement in statements
    )
    assert await stored_rows(managed_database) == before
    assert not management.service.storage.root.exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("missing-document", "IMPORT_LEGACY_INCOMPLETE"),
        ("missing-chunk", "IMPORT_LEGACY_CHUNKS_INVALID"),
        ("metadata", "IMPORT_LEGACY_DOCUMENT_MISMATCH"),
        ("invalid-section", "IMPORT_LEGACY_CHUNKS_INVALID"),
        ("null-vector", "IMPORT_LEGACY_VECTOR_INVALID"),
        ("zero-vector", "IMPORT_LEGACY_VECTOR_INVALID"),
        ("index", "IMPORT_INDEX_IDENTITY_MISMATCH"),
        ("other-import", "IMPORT_SOURCE_CONFLICT"),
        ("imported", "IMPORT_ALREADY_PRESENT"),
    ],
)
async def test_knowledge_management_import_preflight_rejects_corrupt_or_used_source(
    preflight: KnowledgeImportPreflightService, managed_database: Database, kind: str, code: str
) -> None:
    async with managed_database.session() as session, session.begin():
        document = await session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.lifecycle == "HISTORICAL").limit(1)
        )
        chunk = await session.scalar(select(KnowledgeChunk).limit(1))
        assert document is not None and chunk is not None
        if kind == "missing-document":
            await session.execute(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.document_id == document.document_id
                )
            )
        elif kind == "missing-chunk":
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.chunk_id == chunk.chunk_id)
            )
        elif kind == "metadata":
            document.title = "changed"
        elif kind == "invalid-section":
            await session.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.chunk_id == chunk.chunk_id)
                .values(section_path=None)
            )
        elif kind == "null-vector":
            chunk.embedding = None
        elif kind == "zero-vector":
            chunk.embedding = [0.0] * 1536
        elif kind == "index":
            document.embedding_model = "other-model"
        elif kind == "other-import":
            await session.execute(
                update(ManagedKnowledgeLibrary).values(source_catalog_hash="f" * 64)
            )
        else:
            await session.execute(
                update(ManagedKnowledgeLibrary).values(
                    source_catalog_hash=capture_import_files(DEFAULT_KNOWLEDGE_ROOT).catalog_hash
                )
            )
    before = await stored_rows(managed_database)
    with pytest.raises(KnowledgeManagementError, match=code):
        await preflight.check(identity=IDENTITY)
    assert await stored_rows(managed_database) == before


@pytest.mark.integration
async def test_knowledge_management_import_preflight_preserves_upload_and_binds_vectors(
    preflight: KnowledgeImportPreflightService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    upload = await management.service.upload(
        command(), byte_chunks("# 测试规范\n\n## 要求\n正文\n".encode()), identity=IDENTITY
    )
    before = await stored_rows(managed_database)
    first = await preflight.check(identity=IDENTITY)
    assert await stored_rows(managed_database) == before
    assert upload.version_id not in {item.source_document_id for item in first.versions}
    async with managed_database.session() as session, session.begin():
        chunk = await session.scalar(select(KnowledgeChunk).limit(1))
        assert chunk is not None
        chunk.embedding = [2.5] + [0.0] * 1535
    second = await preflight.check(identity=IDENTITY)
    assert first.source_fingerprint != second.source_fingerprint
    assert first.source_catalog_hash == second.source_catalog_hash


@pytest.mark.integration
async def test_knowledge_management_import_preflight_does_not_read_unauthorized_chunks(
    preflight: KnowledgeImportPreflightService, managed_database: Database
) -> None:
    ids = tuple(
        item.metadata.document_id for item in capture_import_files(DEFAULT_KNOWLEDGE_ROOT).files
    )
    with pytest.raises(KnowledgeManagementError, match="PERMISSION_DENIED"):
        await preflight.repository.read_source(ids, "OUT_OF_SCOPE")


@pytest.mark.integration
async def test_knowledge_management_import_preflight_does_not_overwrite_citation_collision(
    preflight: KnowledgeImportPreflightService,
    managed_database: Database,
    management: ManagementHarness,
) -> None:
    upload = await management.service.upload(
        command(), byte_chunks("# 测试规范\n\n## 要求\n正文\n".encode()), identity=IDENTITY
    )
    files = capture_import_files(DEFAULT_KNOWLEDGE_ROOT)
    metadata = files.files[0].metadata
    async with managed_database.session() as session, session.begin():
        await session.execute(
            update(ManagedKnowledgeVersion)
            .where(ManagedKnowledgeVersion.version_id == upload.version_id)
            .values(
                source_kind="CATALOG_IMPORT",
                source_document_id=metadata.document_id,
                citation_document_id=metadata.document_id,
                source_catalog_hash=files.catalog_hash,
                source_lifecycle="ACTIVE",
            )
        )
    before = await stored_rows(managed_database)
    with pytest.raises(KnowledgeManagementError, match="IMPORT_TARGET_CONFLICT"):
        await preflight.check(identity=IDENTITY)
    assert await stored_rows(managed_database) == before
