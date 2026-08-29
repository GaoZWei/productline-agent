import asyncio
import os
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database import Base, Database
from app.knowledge import (
    EMBEDDING_DIMENSION,
    ChunkEmbedding,
    DocumentChunk,
    DocumentFormat,
    EmbeddingGeneration,
    EmbeddingIndexDescriptor,
    KnowledgeSearchFilter,
    ProcessedDocument,
    QueryEmbedding,
    build_search_document,
    fuse_hybrid_results,
)
from app.models import (
    AgentMessage,
    AgentMessageRole,
    AgentRun,
    AgentRunStatus,
    AgentSession,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    ApprovalRecord,
    ApprovalStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    OperationType,
    PendingToolName,
)
from app.repositories import (
    AgentRunRepository,
    AgentStepRepository,
    ApprovalRecordRepository,
    KnowledgeIndexRepository,
    KnowledgeSearchRepository,
    KnowledgeSearchValidationError,
    OperationLogRepository,
)
from app.schemas import (
    Conclusion,
    PageContext,
    ReviewDraft,
    RouterResult,
    RunTokenUsage,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge import (
    DocumentLifecycle,
    DocumentMetadata,
    DocumentType,
    PermissionScope,
)
from app.schemas.versioning import (
    ModelRuntimeSnapshot,
    RagStrategySnapshot,
    RunVersionSnapshot,
    ToolSchemaSnapshot,
    VersionCaptureStatus,
)
from app.schemas.write_tools import WriteReviewResultOutput
from app.services import (
    ApprovalLifecycleService,
    DatabaseApprovalConfirmationStore,
    DatabaseApprovalExecutionStore,
    DatabaseReviewDraftStore,
    InvalidRunTransitionError,
    InvalidStepTransitionError,
    RunLifecycleService,
    RunLifecycleValidationError,
    RunNotFoundError,
    SessionAccessDeniedError,
    StepLifecycleService,
    StepLifecycleValidationError,
    StepNotFoundError,
    StepRunUnavailableError,
    build_operation_log_detail,
)
from app.settings import Settings
from app.workflows import DatabaseWorkflowStepRecorder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL_ENV = "AGENT_PERSISTENCE_TEST_DATABASE_URL"
TEST_RUN_VERSION_SNAPSHOT = RunVersionSnapshot(
    capture_status=VersionCaptureStatus.CAPTURED,
    router_prompt_version="router-test-v1",
    agent_prompt_version="agent-test-v1",
    model=ModelRuntimeSnapshot(
        configured=False,
        provider=None,
        model_name=None,
        parameters={},
    ),
    tool_schema=ToolSchemaSnapshot(
        version="tool-test-v1",
        digest="0" * 64,
        tool_names=(),
    ),
    rag_strategy=RagStrategySnapshot(
        version="rag-test-v1",
        embedding_provider="test-provider",
        embedding_model="test-embedding",
        embedding_index_version="test-index-v1",
        parameters={},
    ),
)
TEST_REVIEW_DRAFT = {
    "task_id": "TASK-003",
    "issue_id": "ISSUE-001",
    "conclusion": "REWORK_REQUIRED",
    "problem_summary": "存在未关闭的坐标系质量问题",
    "review_comment": "Agent原始意见",
    "specification_references": [
        {
            "document_id": "SPEC-COORD-001",
            "document_name": "坐标系统处理规范",
            "document_version": "2.0",
            "section": ["质量复核", "坐标系统"],
            "chunk_id": "CHUNK-COORD-001",
            "chunk_ids": ["CHUNK-COORD-001"],
            "content": "坐标系统问题关闭后方可重新提交复核。",
            "relevance_score": 0.98,
        }
    ],
    "suggested_rework": {
        "required": True,
        "type": "COORDINATE_SYSTEM_FIX",
    },
}


def _configured_url() -> str:
    database_url = os.getenv(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(f"需要通过 {TEST_DATABASE_URL_ENV} 提供隔离 PostgreSQL")
    return Settings(database_url=database_url).async_database_url


def _database_urls(configured_database_url: str, database_name: str) -> tuple[str, str]:
    configured_url = make_url(configured_database_url)
    async_url = configured_url.set(database=database_name)
    alembic_url = async_url.set(drivername="postgresql")
    return async_url.render_as_string(hide_password=False), alembic_url.render_as_string(
        hide_password=False
    )


def _database_name(database_url: str) -> str:
    database_name = make_url(database_url).database
    assert database_name is not None
    return database_name


def _run_alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        ["uv", "run", "--frozen", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


async def _admin_connection(configured_database_url: str) -> asyncpg.Connection:
    configured_url = make_url(configured_database_url)
    admin_url = configured_url.set(drivername="postgresql", database="postgres")
    return await asyncpg.connect(admin_url.render_as_string(hide_password=False))


@pytest_asyncio.fixture
async def migrated_database_url() -> AsyncIterator[str]:
    configured_database_url = _configured_url()
    database_name = f"agent_m21_{uuid4().hex}"
    async_url, alembic_url = _database_urls(configured_database_url, database_name)
    admin = await _admin_connection(configured_database_url)
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    await admin.close()

    try:
        _run_alembic(alembic_url, "upgrade", "head")
        yield async_url
    finally:
        admin = await _admin_connection(configured_database_url)
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE "{database_name}"')
        await admin.close()


@pytest.mark.unit
def test_agent_metadata_contains_agent_runtime_and_knowledge_tables() -> None:
    assert set(Base.metadata.tables) == {
        "agent_messages",
        "agent_operation_logs",
        "agent_runs",
        "agent_sessions",
        "agent_steps",
        "approval_records",
        "knowledge_chunks",
        "knowledge_documents",
    }

    assert set(Base.metadata.tables["agent_sessions"].columns.keys()) == {
        "session_id",
        "user_id",
        "context",
        "expires_at",
        "created_at",
        "updated_at",
    }
    assert set(Base.metadata.tables["agent_messages"].columns.keys()) == {
        "message_id",
        "session_id",
        "sequence_number",
        "role",
        "content",
        "created_at",
    }
    assert set(Base.metadata.tables["agent_runs"].columns.keys()) == {
        "run_id",
        "session_id",
        "request_message_id",
        "status",
        "version_snapshot",
        "page_context_snapshot",
        "router_result",
        "input_token_count",
        "output_token_count",
        "total_token_count",
        "tool_call_count",
        "duration_ms",
        "termination_reason",
        "final_result",
        "error_code",
        "error_step",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    }
    assert set(Base.metadata.tables["agent_steps"].columns.keys()) == {
        "step_id",
        "run_id",
        "sequence_number",
        "step_type",
        "step_name",
        "status",
        "input_summary",
        "output_summary",
        "error_code",
        "duration_ms",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert set(Base.metadata.tables["approval_records"].columns.keys()) == {
        "approval_id",
        "run_id",
        "status",
        "operation_type",
        "original_draft",
        "user_modified_draft",
        "pending_tool_name",
        "target_id",
        "target_version",
        "confirmed_by_user_id",
        "confirmed_at",
        "execution_result",
        "created_at",
        "updated_at",
    }
    assert set(Base.metadata.tables["agent_operation_logs"].columns.keys()) == {
        "operation_log_id",
        "approval_id",
        "operation_type",
        "outcome",
        "target_id",
        "target_version",
        "confirmed_by_user_id",
        "before_summary",
        "after_summary",
        "user_modification_diff",
        "java_trace_id",
        "created_at",
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_creates_agent_tables_and_repository_crud(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
        assert {
            "agent_alembic_version",
            "agent_messages",
            "agent_runs",
            "agent_sessions",
            "agent_steps",
            "approval_records",
            "agent_operation_logs",
            "knowledge_chunks",
            "knowledge_documents",
        } <= table_names
        _, alembic_url = _database_urls(
            migrated_database_url, _database_name(migrated_database_url)
        )
        _run_alembic(alembic_url, "check")

        async with database.session() as session:
            async with session.begin():
                agent_session = AgentSession(session_id="session-001", user_id="user-001")
                user_message = AgentMessage(
                    message_id="message-001",
                    session=agent_session,
                    sequence_number=1,
                    role=AgentMessageRole.USER,
                    content="这个订单为什么还没有交付?",
                )
                run = AgentRun(
                    run_id="run-001",
                    session=agent_session,
                    request_message=user_message,
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT.model_dump(mode="json"),
                )
                session.add(agent_session)
                run_repository = AgentRunRepository(session)
                step_repository = AgentStepRepository(session)
                await run_repository.create(run)
                await step_repository.create(
                    AgentStep(
                        step_id="step-001",
                        run=run,
                        sequence_number=1,
                        step_type=AgentStepType.CONTEXT,
                        step_name="load_page_context",
                    )
                )

            stored_run = await run_repository.get("run-001")
            stored_step = await step_repository.get("step-001")
            assert stored_run is not None
            assert stored_run.status is AgentRunStatus.PENDING
            assert stored_run.request_message_id == "message-001"
            assert stored_step is not None
            assert stored_step.status is AgentStepStatus.PENDING
            assert stored_step.run_id == "run-001"
            stored_runs = await run_repository.list_by_session("session-001")
            assert [item.run_id for item in stored_runs] == ["run-001"]
            assert [item.step_id for item in await step_repository.list_by_run("run-001")] == [
                "step-001"
            ]

            assert await step_repository.delete("step-001") is True
            assert await step_repository.delete("missing-step") is False
            await step_repository.create(
                AgentStep(
                    step_id="step-002",
                    run=stored_run,
                    sequence_number=2,
                    step_type=AgentStepType.TOOL,
                    step_name="get_order_detail",
                )
            )
            assert await run_repository.delete("run-001") is True
            assert await run_repository.delete("missing-run") is False
            await session.commit()

            assert await step_repository.get("step-001") is None
            assert await step_repository.get("step-002") is None
            assert await run_repository.get("run-001") is None
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_knowledge_models_persist_vector_and_generated_search_text(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.engine.connect() as connection:
            extension = await connection.scalar(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
        assert extension == "vector"

        async with database.session() as session:
            document = KnowledgeDocument(
                document_id="COORDINATE-EXCEPTION-002",
                title="坐标系异常处理规范",
                file_path="active/coordinate-system/coordinate-exception-v2.md",
                content_hash="a" * 64,
                lifecycle=DocumentLifecycle.ACTIVE,
                replaced_by=None,
                document_type=DocumentType.COORDINATE_SYSTEM_SPEC,
                satellite_type="GF-2",
                product_type="DOM",
                processing_level="L2",
                specification_version="2.0",
                effective_date=date(2025, 1, 1),
                expiry_date=None,
                permission_scope=PermissionScope.INTERNAL_REVIEWER,
            )
            chunk = KnowledgeChunk(
                chunk_id="chunk-coordinate-exception-001",
                document=document,
                chunk_index=0,
                section_path=["坐标系异常处理规范", "复核门禁"],
                content="问题处理完成后必须重新提交复核",
                content_hash="b" * 64,
                token_count=16,
                search_document=build_search_document(
                    content="问题处理完成后必须重新提交复核",
                    section_path=("坐标系异常处理规范", "复核门禁"),
                ),
                embedding=[0.1, *([0.0] * 1535)],
            )
            session.add(document)
            await session.commit()
            await session.refresh(chunk)

            stored = await session.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.chunk_id == "chunk-coordinate-exception-001"
                )
            )
            assert stored is not None
            assert stored.document_id == document.document_id
            assert stored.section_path == ["坐标系异常处理规范", "复核门禁"]
            assert stored.embedding is not None
            assert len(stored.embedding) == 1536
            assert stored.search_vector is not None

        async with database.session() as invalid_session:
            invalid_session.add(
                KnowledgeDocument(
                    document_id="INVALID-ACTIVE-001",
                    title="错误有效期示例",
                    file_path="active/invalid.md",
                    content_hash="c" * 64,
                    lifecycle=DocumentLifecycle.ACTIVE,
                    replaced_by=None,
                    document_type=DocumentType.DOM_PRODUCT_SPEC,
                    satellite_type="GF-2",
                    product_type="DOM",
                    processing_level="L2",
                    specification_version="1.0",
                    effective_date=date(2025, 1, 1),
                    expiry_date=date(2025, 12, 31),
                    permission_scope=PermissionScope.INTERNAL_REVIEWER,
                )
            )
            with pytest.raises(IntegrityError):
                await invalid_session.commit()
            await invalid_session.rollback()
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_knowledge_repository_reindexes_chunks_and_records_version(
    migrated_database_url: str,
) -> None:
    metadata = DocumentMetadata(
        document_id="QUALITY-REINDEX-001",
        title="质量重新索引规范",
        file_path="active/quality/reindex.md",
        lifecycle=DocumentLifecycle.ACTIVE,
        replaced_by=None,
        document_type=DocumentType.QUALITY_SPEC,
        satellite_type="GF-2",
        product_type="DOM",
        processing_level="L2",
        specification_version="1.0",
        effective_date=date(2025, 1, 1),
        expiry_date=None,
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )
    chunk = DocumentChunk(
        chunk_id="KCH-REINDEX-0000000000000000000000000001",
        document_id=metadata.document_id,
        chunk_index=0,
        section_path=(metadata.title, "处理要求"),
        content="问题处理完成后重新提交复核。",
        content_hash="d" * 64,
        token_count=15,
    )
    processed = ProcessedDocument(
        metadata=metadata,
        document_format=DocumentFormat.MARKDOWN,
        content_hash="e" * 64,
        chunks=(chunk,),
    )

    def generation(version: str, value: float, indexed_at: datetime) -> EmbeddingGeneration:
        return EmbeddingGeneration(
            descriptor=EmbeddingIndexDescriptor(
                provider="openai_compatible",
                model="text-embedding-3-small",
                dimension=EMBEDDING_DIMENSION,
                index_version=version,
            ),
            generated_at=indexed_at,
            embeddings=(
                ChunkEmbedding(
                    chunk_id=chunk.chunk_id,
                    vector=(value, *([0.0] * (EMBEDDING_DIMENSION - 1))),
                ),
            ),
        )

    database = Database(migrated_database_url)
    first_indexed_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    second_indexed_at = datetime(2026, 8, 17, 11, 0, tzinfo=UTC)
    try:
        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(
                (processed,), generation("embedding-v1", 0.1, first_indexed_at)
            )
            await session.commit()

        async with database.session() as session:
            stored_document = await session.get(KnowledgeDocument, metadata.document_id)
            stored_chunk = await session.get(KnowledgeChunk, chunk.chunk_id)
            assert stored_document is not None
            assert stored_document.embedding_provider == "openai_compatible"
            assert stored_document.embedding_model == "text-embedding-3-small"
            assert stored_document.embedding_dimension == EMBEDDING_DIMENSION
            assert stored_document.index_version == "embedding-v1"
            assert stored_document.indexed_at == first_indexed_at
            assert stored_chunk is not None
            assert stored_chunk.embedding is not None
            assert len(stored_chunk.embedding) == EMBEDDING_DIMENSION
            assert stored_chunk.embedding[0] == pytest.approx(0.1)

        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(
                (processed,), generation("embedding-v2", 0.2, second_indexed_at)
            )
            await session.commit()

        async with database.session() as session:
            stored_document = await session.get(KnowledgeDocument, metadata.document_id)
            stored_chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunk).where(
                            KnowledgeChunk.document_id == metadata.document_id
                        )
                    )
                ).all()
            )
            assert stored_document is not None
            assert stored_document.index_version == "embedding-v2"
            assert stored_document.indexed_at == second_indexed_at
            assert len(stored_chunks) == 1
            assert stored_chunks[0].embedding is not None
            assert stored_chunks[0].embedding[0] == pytest.approx(0.2)
    finally:
        await database.dispose()


def _search_processed_document(
    *,
    suffix: str,
    content: str,
    product_type: str = "DOM",
    satellite_type: str = "GF-2",
    document_type: DocumentType = DocumentType.QUALITY_SPEC,
    specification_version: str = "1.0",
    effective_date: date = date(2025, 1, 1),
    lifecycle: DocumentLifecycle = DocumentLifecycle.ACTIVE,
    expiry_date: date | None = None,
    replaced_by: str | None = None,
) -> ProcessedDocument:
    document_id = f"SEARCH-DEMO-{suffix}"
    parent_directory = "active" if lifecycle is DocumentLifecycle.ACTIVE else "historical"
    metadata = DocumentMetadata(
        document_id=document_id,
        title=f"检索测试规范{suffix}",
        file_path=f"{parent_directory}/quality/search-{suffix.lower()}.md",
        lifecycle=lifecycle,
        replaced_by=replaced_by,
        document_type=document_type,
        satellite_type=satellite_type,
        product_type=product_type,
        processing_level="L2",
        specification_version=specification_version,
        effective_date=effective_date,
        expiry_date=expiry_date,
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    chunk = DocumentChunk(
        chunk_id=f"KCH-SEARCH-{suffix}-000000000000000000000000",
        document_id=document_id,
        chunk_index=0,
        section_path=(metadata.title, "处理要求"),
        content=content,
        content_hash=content_hash,
        token_count=len(content),
    )
    return ProcessedDocument(
        metadata=metadata,
        document_format=DocumentFormat.MARKDOWN,
        content_hash=content_hash,
        chunks=(chunk,),
    )


def _search_generation(
    documents: tuple[ProcessedDocument, ...],
    vectors: tuple[tuple[float, ...], ...],
    *,
    index_version: str,
) -> EmbeddingGeneration:
    return EmbeddingGeneration(
        descriptor=EmbeddingIndexDescriptor(
            provider="openai_compatible",
            model="text-embedding-3-small",
            dimension=EMBEDDING_DIMENSION,
            index_version=index_version,
        ),
        generated_at=datetime(2026, 8, 18, 8, 0, tzinfo=UTC),
        embeddings=tuple(
            ChunkEmbedding(chunk_id=document.chunks[0].chunk_id, vector=vector)
            for document, vector in zip(documents, vectors, strict=True)
        ),
    )


def _search_filters(**updates: object) -> KnowledgeSearchFilter:
    values: dict[str, object] = {
        "effective_at": date(2026, 8, 19),
        "permission_scope": PermissionScope.INTERNAL_REVIEWER,
    }
    values.update(updates)
    return KnowledgeSearchFilter.model_validate(values)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_keyword_search_matches_chinese_bigrams_and_returns_rank(
    migrated_database_url: str,
) -> None:
    relevant = _search_processed_document(
        suffix="KEYWORD-A",
        content="坐标系问题必须完成返工处理, 处理后重新提交复核。",
    )
    unrelated = _search_processed_document(
        suffix="KEYWORD-B",
        content="影像云量检查通过后可以进入交付准备。",
    )
    documents = (relevant, unrelated)
    vector = (1.0, *([0.0] * (EMBEDDING_DIMENSION - 1)))
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(
                documents,
                _search_generation(documents, (vector, vector), index_version="search-v1"),
            )
            await session.commit()

        async with database.session() as session:
            hits = await KnowledgeSearchRepository(session).search_keywords(
                "坐标系问题 + !!!",
                filters=_search_filters(),
                top_k=5,
            )
            index_names = set(
                (
                    await session.scalars(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE tablename = 'knowledge_chunks'"
                        )
                    )
                ).all()
            )

        assert [hit.chunk_id for hit in hits] == [relevant.chunks[0].chunk_id]
        assert hits[0].document_id == relevant.metadata.document_id
        assert hits[0].document_name == relevant.metadata.title
        assert hits[0].document_version == relevant.metadata.specification_version
        assert hits[0].keyword_score > 0
        assert "ix_knowledge_chunks_search_vector" in index_names
        assert "ix_knowledge_chunks_embedding_cosine" in index_names
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_search_filters_index_version_top_k_and_similarity_threshold(
    migrated_database_url: str,
) -> None:
    exact = _search_processed_document(suffix="VECTOR-A", content="完全相关的坐标处理要求。")
    partial = _search_processed_document(suffix="VECTOR-B", content="部分相关的复核处理要求。")
    other_version = _search_processed_document(
        suffix="VECTOR-C",
        content="来自另一索引版本的处理要求。",
    )
    first_axis = (1.0, *([0.0] * (EMBEDDING_DIMENSION - 1)))
    partial_vector = (0.8, 0.6, *([0.0] * (EMBEDDING_DIMENSION - 2)))
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(
                (exact, partial),
                _search_generation(
                    (exact, partial),
                    (first_axis, partial_vector),
                    index_version="vector-v1",
                ),
            )
            await KnowledgeIndexRepository(session).reindex_documents(
                (other_version,),
                _search_generation(
                    (other_version,),
                    (first_axis,),
                    index_version="vector-v2",
                ),
            )
            await session.commit()

        query_embedding = QueryEmbedding(
            descriptor=EmbeddingIndexDescriptor(
                provider="openai_compatible",
                model="text-embedding-3-small",
                dimension=EMBEDDING_DIMENSION,
                index_version="vector-v1",
            ),
            vector=first_axis,
        )
        async with database.session() as session:
            repository = KnowledgeSearchRepository(session)
            hits = await repository.search_vectors(
                query_embedding,
                filters=_search_filters(),
                top_k=5,
                min_similarity=0.5,
            )
            top_hit = await repository.search_vectors(
                query_embedding,
                filters=_search_filters(),
                top_k=1,
            )

        assert [hit.chunk_id for hit in hits] == [
            exact.chunks[0].chunk_id,
            partial.chunks[0].chunk_id,
        ]
        assert hits[0].vector_score == pytest.approx(1.0)
        assert hits[1].vector_score == pytest.approx(0.8)
        assert hits[0].document_name == exact.metadata.title
        assert hits[0].document_version == exact.metadata.specification_version
        assert [hit.chunk_id for hit in top_hit] == [exact.chunks[0].chunk_id]

        invalid_query = QueryEmbedding(
            descriptor=query_embedding.descriptor,
            vector=(1.0, 0.0),
        )
        zero_query = QueryEmbedding(
            descriptor=query_embedding.descriptor,
            vector=tuple(0.0 for _ in range(EMBEDDING_DIMENSION)),
        )
        async with database.session() as session:
            with pytest.raises(KnowledgeSearchValidationError):
                await KnowledgeSearchRepository(session).search_vectors(
                    invalid_query,
                    filters=_search_filters(),
                )
            with pytest.raises(KnowledgeSearchValidationError):
                await KnowledgeSearchRepository(session).search_vectors(
                    zero_query,
                    filters=_search_filters(),
                )
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_fuses_real_keyword_and_vector_candidates(
    migrated_database_url: str,
) -> None:
    shared = _search_processed_document(
        suffix="HYBRID-A",
        content="混合检索坐标规则要求问题处理完成后重新复核。",
    )
    vector_only = _search_processed_document(
        suffix="HYBRID-B",
        content="交付归档需要保存审核记录。",
    )
    first_axis = (1.0, *([0.0] * (EMBEDDING_DIMENSION - 1)))
    second_axis = (0.0, 1.0, *([0.0] * (EMBEDDING_DIMENSION - 2)))
    documents = (shared, vector_only)
    generation = _search_generation(
        documents,
        (first_axis, second_axis),
        index_version="hybrid-v1",
    )
    query_embedding = QueryEmbedding(descriptor=generation.descriptor, vector=first_axis)
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(documents, generation)
            await session.commit()

        async with database.session() as session:
            repository = KnowledgeSearchRepository(session)
            keyword_hits = await repository.search_keywords(
                "混合检索坐标规则",
                filters=_search_filters(),
                top_k=10,
            )
            vector_hits = await repository.search_vectors(
                query_embedding,
                filters=_search_filters(),
                top_k=10,
            )
        results = fuse_hybrid_results(keyword_hits, vector_hits, top_k=2)

        assert [result.document_id for result in results] == [
            shared.metadata.document_id,
            vector_only.metadata.document_id,
        ]
        assert results[0].chunk_ids == (shared.chunks[0].chunk_id,)
        assert results[0].document_name == shared.metadata.title
        assert results[0].document_version == shared.metadata.specification_version
        assert results[0].keyword_rank == 1
        assert results[0].vector_rank == 1
        assert results[0].rrf_score == pytest.approx(2 / 61)
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_filters_prevent_cross_product_and_metadata_recall(
    migrated_database_url: str,
) -> None:
    relevant = _search_processed_document(
        suffix="FILTER-A",
        content="统一检索规则适用于DOM产品坐标处理。",
        specification_version="2.1",
    )
    wrong_product = _search_processed_document(
        suffix="FILTER-B",
        content="统一检索规则适用于DSM产品坐标处理。",
        product_type="DSM",
        specification_version="2.1",
    )
    wrong_satellite = _search_processed_document(
        suffix="FILTER-C",
        content="统一检索规则适用于GF-1产品坐标处理。",
        satellite_type="GF-1",
        specification_version="2.1",
    )
    wrong_type = _search_processed_document(
        suffix="FILTER-D",
        content="统一检索规则属于DOM生产类型。",
        document_type=DocumentType.DOM_PRODUCT_SPEC,
        specification_version="2.1",
    )
    wrong_version = _search_processed_document(
        suffix="FILTER-E",
        content="统一检索规则来自旧规范版本。",
        specification_version="1.0",
    )
    documents = (relevant, wrong_product, wrong_satellite, wrong_type, wrong_version)
    vector = (1.0, *([0.0] * (EMBEDDING_DIMENSION - 1)))
    generation = _search_generation(
        documents,
        tuple(vector for _ in documents),
        index_version="filter-v1",
    )
    filters = _search_filters(
        product_type="DOM",
        satellite_type="GF-2",
        document_type=DocumentType.QUALITY_SPEC,
        specification_version="2.1",
    )
    query_embedding = QueryEmbedding(descriptor=generation.descriptor, vector=vector)
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(documents, generation)
            await session.commit()

        async with database.session() as session:
            repository = KnowledgeSearchRepository(session)
            keyword_hits = await repository.search_keywords(
                "统一检索规则",
                filters=filters,
                top_k=10,
            )
            vector_hits = await repository.search_vectors(
                query_embedding,
                filters=filters,
                top_k=10,
            )

        assert [hit.document_id for hit in keyword_hits] == [relevant.metadata.document_id]
        assert [hit.document_id for hit in vector_hits] == [relevant.metadata.document_id]
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_filters_exclude_historical_expired_and_future_documents(
    migrated_database_url: str,
) -> None:
    active = _search_processed_document(
        suffix="LIFECYCLE-A",
        content="版本过滤规则使用当前有效规范。",
        specification_version="2.0",
        effective_date=date(2025, 1, 1),
    )
    historical = _search_processed_document(
        suffix="LIFECYCLE-H",
        content="版本过滤规则来自已经失效的历史规范。",
        specification_version="1.0",
        effective_date=date(2022, 1, 1),
        lifecycle=DocumentLifecycle.HISTORICAL,
        expiry_date=date(2024, 12, 31),
        replaced_by=active.metadata.document_id,
    )
    future = _search_processed_document(
        suffix="LIFECYCLE-F",
        content="版本过滤规则来自尚未生效的未来规范。",
        specification_version="3.0",
        effective_date=date(2027, 1, 1),
    )
    documents = (active, historical, future)
    vector = (1.0, *([0.0] * (EMBEDDING_DIMENSION - 1)))
    generation = _search_generation(
        documents,
        (vector, vector, vector),
        index_version="lifecycle-v1",
    )
    filters = _search_filters(effective_at=date(2026, 8, 19))
    query_embedding = QueryEmbedding(descriptor=generation.descriptor, vector=vector)
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            await KnowledgeIndexRepository(session).reindex_documents(documents, generation)
            await session.commit()

        async with database.session() as session:
            repository = KnowledgeSearchRepository(session)
            keyword_hits = await repository.search_keywords(
                "版本过滤规则",
                filters=filters,
                top_k=10,
            )
            vector_hits = await repository.search_vectors(
                query_embedding,
                filters=filters,
                top_k=10,
            )

        assert [hit.document_id for hit in keyword_hits] == [active.metadata.document_id]
        assert [hit.document_id for hit in vector_hits] == [active.metadata.document_id]
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_version_migration_marks_existing_runs_as_unavailable_legacy(
    migrated_database_url: str,
) -> None:
    database_name = _database_name(migrated_database_url)
    _, alembic_url = _database_urls(migrated_database_url, database_name)
    _run_alembic(alembic_url, "downgrade", "0006_vector_search")

    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO agent_sessions "
                    "(session_id, user_id, context, expires_at) "
                    "VALUES ('session-legacy', 'user-001', CAST('{}' AS JSON), "
                    "CURRENT_TIMESTAMP + INTERVAL '30 minutes')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO agent_runs (run_id, session_id) "
                    "VALUES ('run-legacy', 'session-legacy')"
                )
            )

        _run_alembic(alembic_url, "upgrade", "head")
        async with database.engine.connect() as connection:
            legacy_run = (
                await connection.execute(
                    text(
                        "SELECT version_snapshot, page_context_snapshot, router_result, "
                        "input_token_count, output_token_count, total_token_count, "
                        "tool_call_count, duration_ms, termination_reason "
                        "FROM agent_runs "
                        "WHERE run_id = 'run-legacy'"
                    )
                )
            ).mappings().one()
            columns = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns("agent_runs")
            )

        snapshot = legacy_run["version_snapshot"]
        assert snapshot["capture_status"] == "UNAVAILABLE_LEGACY"
        assert snapshot["router_prompt_version"] is None
        assert legacy_run["page_context_snapshot"] is None
        assert legacy_run["router_result"] is None
        assert legacy_run["input_token_count"] == 0
        assert legacy_run["output_token_count"] == 0
        assert legacy_run["total_token_count"] == 0
        assert legacy_run["tool_call_count"] == 0
        assert legacy_run["duration_ms"] is None
        assert legacy_run["termination_reason"] is None
        version_column = next(
            column for column in columns if column["name"] == "version_snapshot"
        )
        assert version_column["nullable"] is False
        assert version_column["default"] is None
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_type_migration_converts_legacy_rule_and_supports_downgrade(
    migrated_database_url: str,
) -> None:
    database_name = _database_name(migrated_database_url)
    _, alembic_url = _database_urls(migrated_database_url, database_name)
    _run_alembic(alembic_url, "downgrade", "0011_run_observability")

    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO agent_sessions "
                    "(session_id, user_id, context, expires_at) "
                    "VALUES ('session-step-type-legacy', 'user-001', "
                    "CAST('{}' AS JSON), CURRENT_TIMESTAMP + INTERVAL '30 minutes')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO agent_runs (run_id, session_id, version_snapshot) "
                    "VALUES ('run-step-type-legacy', 'session-step-type-legacy', "
                    "CAST('{}' AS JSON))"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO agent_steps "
                    "(step_id, run_id, sequence_number, step_type, step_name) "
                    "VALUES ('step-type-legacy', 'run-step-type-legacy', 1, "
                    "'RULE', 'diagnose_by_rules')"
                )
            )

        _run_alembic(alembic_url, "upgrade", "head")
        async with database.session() as session, session.begin():
            upgraded_type = await session.scalar(
                text(
                    "SELECT step_type FROM agent_steps "
                    "WHERE step_id = 'step-type-legacy'"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO agent_steps "
                    "(step_id, run_id, sequence_number, step_type, step_name) "
                    "VALUES ('step-type-router', 'run-step-type-legacy', 2, "
                    "'ROUTER', 'route_intent')"
                )
            )
        assert upgraded_type == "WORKFLOW"

        _run_alembic(alembic_url, "downgrade", "0011_run_observability")
        async with database.engine.connect() as connection:
            downgraded_types = tuple(
                (
                    await connection.execute(
                        text(
                            "SELECT step_type FROM agent_steps "
                            "WHERE run_id = 'run-step-type-legacy' "
                            "ORDER BY sequence_number"
                        )
                    )
                ).scalars()
            )
        assert downgraded_types == ("RULE", "RULE")
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_lifecycle_persists_drafts_confirmation_and_run_detachment(
    migrated_database_url: str,
) -> None:
    confirmed_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            session.add(AgentSession(session_id="session-approval", user_id="reviewer-001"))
            run_service = RunLifecycleService(AgentRunRepository(session))
            await run_service.create_run(
                run_id="run-approval",
                session_id="session-approval",
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
            )
            approval_service = ApprovalLifecycleService(
                ApprovalRecordRepository(session),
                now=lambda: confirmed_at,
            )
            approval = await approval_service.create_draft(
                approval_id="approval-001",
                run_id="run-approval",
                operation_type=OperationType.SUBMIT_REVIEW,
                original_draft=TEST_REVIEW_DRAFT,
                pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
                target_id="TASK-003",
                target_version=0,
            )
            await approval_service.mark_waiting_confirmation(approval.approval_id)
            await approval_service.save_user_modification(
                approval.approval_id,
                modified_draft={**TEST_REVIEW_DRAFT, "review_comment": "用户修改意见"},
            )
            confirmed = await approval_service.confirm(
                approval.approval_id,
                confirmed_by_user_id="reviewer-001",
            )
            assert confirmed.status is ApprovalStatus.CONFIRMED

        async with database.session() as verification_session:
            repository = ApprovalRecordRepository(verification_session)
            stored = await repository.get("approval-001")
            assert stored is not None
            assert stored.original_draft == TEST_REVIEW_DRAFT
            assert stored.user_modified_draft == {
                **TEST_REVIEW_DRAFT,
                "review_comment": "用户修改意见",
            }
            assert stored.target_id == "TASK-003"
            assert stored.target_version == 0
            assert stored.confirmed_by_user_id == "reviewer-001"
            assert stored.confirmed_at == confirmed_at
            effective = ApprovalLifecycleService.effective_review_draft(stored)
            assert effective.conclusion is Conclusion.REWORK_REQUIRED
            assert effective.specification_references[0].chunk_ids == (
                "CHUNK-COORD-001",
            )

        async with database.session() as delete_session, delete_session.begin():
            assert await AgentRunRepository(delete_session).delete("run-approval") is True

        async with database.session() as final_session:
            retained = await ApprovalRecordRepository(final_session).get("approval-001")
            assert retained is not None
            assert retained.run_id is None
            assert retained.status is ApprovalStatus.CONFIRMED
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_execution_store_saves_only_the_first_java_result(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            session.add(AgentSession(session_id="session-execution", user_id="reviewer-001"))
            await RunLifecycleService(AgentRunRepository(session)).create_run(
                run_id="run-execution",
                session_id="session-execution",
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
            )
            lifecycle = ApprovalLifecycleService(ApprovalRecordRepository(session))
            approval = await lifecycle.create_draft(
                approval_id="approval-execution",
                run_id="run-execution",
                operation_type=OperationType.SUBMIT_REVIEW,
                original_draft=TEST_REVIEW_DRAFT,
                pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
                target_id="TASK-003",
                target_version=7,
            )
            await lifecycle.mark_waiting_confirmation(approval.approval_id)
            await lifecycle.confirm(
                approval.approval_id,
                confirmed_by_user_id="reviewer-001",
            )
            await lifecycle.mark_executing(approval.approval_id)

        store = DatabaseApprovalExecutionStore(database)
        snapshot = await store.get_execution_snapshot("approval-execution")
        assert snapshot is not None
        assert snapshot.status is ApprovalStatus.EXECUTING
        assert snapshot.draft.issue_id == "ISSUE-001"

        result = {
            "approval_id": "approval-execution",
            "review_id": "REVIEW-WRITE-003",
            "task_version": 8,
            "java_trace_id": "trace-first",
        }
        assert await store.save_execution_result("approval-execution", result=result) is True
        assert (
            await store.save_execution_result(
                "approval-execution",
                result={**result, "java_trace_id": "trace-replay"},
            )
            is True
        )
        assert (
            await store.save_execution_result(
                "approval-execution",
                result={**result, "review_id": "REVIEW-WRITE-OTHER"},
            )
            is False
        )

        async with database.session() as verification_session:
            stored = await ApprovalRecordRepository(verification_session).get(
                "approval-execution"
            )
            assert stored is not None
            assert stored.execution_result == result
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_confirmation_store_atomically_confirms_and_allows_one_execution_lock(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            session.add(AgentSession(session_id="session-confirm-cas", user_id="reviewer-001"))
            await RunLifecycleService(AgentRunRepository(session)).create_run(
                run_id="run-confirm-cas",
                session_id="session-confirm-cas",
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
            )
            lifecycle = ApprovalLifecycleService(ApprovalRecordRepository(session))
            approval = await lifecycle.create_draft(
                approval_id="approval-confirm-cas",
                run_id="run-confirm-cas",
                operation_type=OperationType.SUBMIT_REVIEW,
                original_draft=TEST_REVIEW_DRAFT,
                pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
                target_id="TASK-003",
                target_version=7,
            )
            await lifecycle.mark_waiting_confirmation(approval.approval_id)

        store = DatabaseApprovalConfirmationStore(database)
        modified = ReviewDraft.model_validate(
            {**TEST_REVIEW_DRAFT, "review_comment": "用户确认意见"}
        )
        confirmed = await store.confirm_waiting(
            "approval-confirm-cas",
            draft=modified,
            confirmed_by_user_id="reviewer-001",
            confirmed_at=datetime.now(UTC),
        )
        assert confirmed is not None
        assert confirmed.status is ApprovalStatus.CONFIRMED
        assert confirmed.draft.review_comment == "用户确认意见"

        first, second = await asyncio.gather(
            store.transition(
                "approval-confirm-cas",
                expected_status=ApprovalStatus.CONFIRMED,
                target_status=ApprovalStatus.EXECUTING,
                updated_at=datetime.now(UTC),
            ),
            store.transition(
                "approval-confirm-cas",
                expected_status=ApprovalStatus.CONFIRMED,
                target_status=ApprovalStatus.EXECUTING,
                updated_at=datetime.now(UTC),
            ),
        )

        assert sum(result is not None for result in (first, second)) == 1
        current = await store.get_snapshot("approval-confirm-cas")
        assert current is not None
        assert current.status is ApprovalStatus.EXECUTING
        assert current.confirmed_by_user_id == "reviewer-001"

        result = WriteReviewResultOutput(
            approval_id="approval-confirm-cas",
            task_id="TASK-003",
            issue_id=modified.issue_id,
            review_id="REVIEW-CONFIRM-CAS",
            status="REWORK_REQUIRED",
            review_comment=modified.review_comment,
            task_version=8,
            java_trace_id="trace-java-confirm-cas",
        )
        completed_at = datetime.now(UTC)
        detail = build_operation_log_detail(
            approval_id=current.approval_id,
            operation_type=OperationType.SUBMIT_REVIEW,
            target_id=current.target_id,
            target_version=current.target_version,
            confirmed_by_user_id="reviewer-001",
            original_draft=ReviewDraft.model_validate(TEST_REVIEW_DRAFT),
            effective_draft=modified,
            outcome=ApprovalStatus.SUCCEEDED,
            result=result,
            failure=None,
            created_at=completed_at,
        )
        completed = await store.finish_with_operation_log(
            current.approval_id,
            target_status=ApprovalStatus.SUCCEEDED,
            detail=detail,
            updated_at=completed_at,
        )

        assert completed is not None
        assert completed.status is ApprovalStatus.SUCCEEDED
        async with database.session() as session:
            operation_log = await OperationLogRepository(session).get_by_approval(
                current.approval_id
            )
            assert operation_log is not None
            assert operation_log.outcome == ApprovalStatus.SUCCEEDED.value
            assert operation_log.java_trace_id == "trace-java-confirm-cas"
            assert operation_log.user_modification_diff == [
                {
                    "field_path": "review_comment",
                    "before": TEST_REVIEW_DRAFT["review_comment"],
                    "after": "用户确认意见",
                }
            ]
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_review_draft_store_atomically_waits_approval_and_run(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            session.add(AgentSession(session_id="session-draft", user_id="reviewer-001"))
            run_service = RunLifecycleService(AgentRunRepository(session))
            await run_service.create_run(
                run_id="run-draft",
                session_id="session-draft",
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
            )
            await run_service.mark_running("run-draft")
            await run_service.mark_succeeded(
                "run-draft",
                final_result={
                    "order_id": "ORDER-003",
                    "blocking_stage": "QUALITY_REVIEW",
                    "summary": "订单阻塞在质量复核环节。",
                    "root_causes": [
                        {
                            "code": "OPEN_COORDINATE_SYSTEM_ISSUE",
                            "description": "存在未关闭的坐标系问题",
                        }
                    ],
                    "evidence": [
                        {
                            "source_type": "TOOL",
                            "tool_name": "get_quality_issues",
                            "field_path": "issues[0].status",
                            "value": "OPEN",
                            "description": "ISSUE-001问题状态为OPEN",
                        }
                    ],
                    "suggestions": [
                        {
                            "action_type": "CREATE_COORDINATE_SYSTEM_REWORK",
                            "description": "创建坐标系处理返工任务",
                        }
                    ],
                    "confidence": 1.0,
                },
            )

        store = DatabaseReviewDraftStore(database)
        identity = BusinessIdentity(user_id="reviewer-001", role="INTERNAL_REVIEWER")
        source = await store.latest_diagnosis("session-draft", identity=identity)
        assert source is not None
        assert source.run_id == "run-draft"
        assert source.status is AgentRunStatus.SUCCEEDED

        with pytest.raises(SessionAccessDeniedError):
            await store.latest_diagnosis(
                "session-draft",
                identity=BusinessIdentity(
                    user_id="reviewer-other",
                    role="INTERNAL_REVIEWER",
                ),
            )

        persisted = await store.save_waiting_approval(
            approval_id="approval-draft",
            run_id=source.run_id,
            draft=ReviewDraft.model_validate(TEST_REVIEW_DRAFT),
            target_version=7,
        )
        assert persisted.approval_status is ApprovalStatus.WAITING_CONFIRMATION
        assert persisted.run_status is AgentRunStatus.WAITING_APPROVAL

        async with database.session() as verification_session:
            run = await AgentRunRepository(verification_session).get("run-draft")
            approval = await ApprovalRecordRepository(verification_session).get(
                "approval-draft"
            )
            assert run is not None
            assert run.status is AgentRunStatus.WAITING_APPROVAL
            assert run.final_result is not None
            assert run.finished_at is not None
            assert approval is not None
            assert approval.status is ApprovalStatus.WAITING_CONFIRMATION
            assert approval.target_version == 7

        latest = await store.latest_diagnosis("session-draft", identity=identity)
        assert latest is not None
        assert latest.status is AgentRunStatus.WAITING_APPROVAL
        with pytest.raises(InvalidRunTransitionError):
            await store.save_waiting_approval(
                approval_id="approval-duplicate",
                run_id=latest.run_id,
                draft=ReviewDraft.model_validate(TEST_REVIEW_DRAFT),
                target_version=7,
            )

        async with database.session() as final_session:
            assert (
                await ApprovalRecordRepository(final_session).get("approval-duplicate")
                is None
            )
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_database_rejects_operation_tool_mismatch(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            agent_session = AgentSession(session_id="session-mismatch", user_id="reviewer-001")
            run = AgentRun(
                run_id="run-mismatch",
                session=agent_session,
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT.model_dump(mode="json"),
            )
            session.add(
                ApprovalRecord(
                    approval_id="approval-mismatch",
                    run=run,
                    status=ApprovalStatus.DRAFT,
                    operation_type=OperationType.SUBMIT_REVIEW,
                    original_draft={"review_comment": "原始意见"},
                    user_modified_draft=None,
                    pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
                    target_id="TASK-003",
                    target_version=0,
                    confirmed_by_user_id=None,
                    confirmed_at=None,
                )
            )

            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_downgrade_removes_only_agent_runtime_tables(
    migrated_database_url: str,
) -> None:
    database_name = _database_name(migrated_database_url)
    _, alembic_url = _database_urls(migrated_database_url, database_name)
    _run_alembic(alembic_url, "downgrade", "base")

    database = Database(migrated_database_url)
    try:
        async with database.engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
        assert table_names == {"agent_alembic_version"}
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_sequence_is_unique_inside_one_run(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            agent_session = AgentSession(session_id="session-duplicate", user_id="user-001")
            run = AgentRun(
                run_id="run-duplicate",
                session=agent_session,
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT.model_dump(mode="json"),
            )
            session.add(agent_session)
            session.add_all(
                [
                    AgentStep(
                        step_id="step-a",
                        run=run,
                        sequence_number=1,
                        step_type=AgentStepType.TOOL,
                        step_name="get_order_detail",
                    ),
                    AgentStep(
                        step_id="step-b",
                        run=run,
                        sequence_number=1,
                        step_type=AgentStepType.WORKFLOW,
                        step_name="diagnose_blocker",
                    ),
                ]
            )

            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_lifecycle_persists_success_result(migrated_database_url: str) -> None:
    started_at = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 9, 1, 0, 2, tzinfo=UTC)
    clock_values = iter([started_at, finished_at])
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(AgentSession(session_id="session-success", user_id="user-001"))
                service = RunLifecycleService(
                    AgentRunRepository(session), now=lambda: next(clock_values)
                )
                created = await service.create_run(
                    run_id="run-success",
                    session_id="session-success",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                    page_context_snapshot=PageContext.model_validate(
                        {
                            "current_system": "production-system",
                            "current_page": "order-detail",
                            "order_id": "ORDER-003",
                            "user_role": "REVIEWER",
                        }
                    ),
                )
                assert created.status is AgentRunStatus.PENDING
                assert created.started_at is None
                assert created.finished_at is None

                running = await service.mark_running("run-success")
                assert running.status is AgentRunStatus.RUNNING
                assert running.started_at == started_at
                routed = await service.record_router_result(
                    "run-success",
                    router_result=RouterResult.model_validate(
                        {
                            "intent": "ORDER_DIAGNOSIS",
                            "confidence": 0.98,
                            "entities": {"order_id": "ORDER-003"},
                            "missing_fields": [],
                            "need_clarification": False,
                        }
                    ),
                )
                assert routed.router_result is not None

                succeeded = await service.mark_succeeded(
                    "run-success",
                    final_result={"blocking_stage": "QUALITY_REVIEW"},
                    token_usage=RunTokenUsage.from_counts(
                        input_tokens=120,
                        output_tokens=30,
                    ),
                    tool_call_count=6,
                    termination_reason="SUFFICIENT_INFORMATION",
                )
                assert succeeded.status is AgentRunStatus.SUCCEEDED
                assert succeeded.final_result == {"blocking_stage": "QUALITY_REVIEW"}
                assert succeeded.finished_at == finished_at
                assert succeeded.error_code is None
                assert succeeded.error_step is None
                assert succeeded.input_token_count == 120
                assert succeeded.output_token_count == 30
                assert succeeded.total_token_count == 150
                assert succeeded.tool_call_count == 6
                assert succeeded.duration_ms == 2000
                assert succeeded.termination_reason == "SUFFICIENT_INFORMATION"

        async with database.session() as verification_session:
            stored = await AgentRunRepository(verification_session).get("run-success")
            assert stored is not None
            assert stored.status is AgentRunStatus.SUCCEEDED
            assert stored.final_result == {"blocking_stage": "QUALITY_REVIEW"}
            assert stored.page_context_snapshot == {
                "current_system": "production-system",
                "current_page": "order-detail",
                "order_id": "ORDER-003",
                "task_id": None,
                "issue_id": None,
                "batch_id": None,
                "product_type": None,
                "satellite_type": None,
                "user_role": "REVIEWER",
            }
            assert stored.router_result is not None
            assert stored.router_result["intent"] == "ORDER_DIAGNOSIS"
            assert stored.version_snapshot["model"]["configured"] is False
            assert stored.version_snapshot["router_prompt_version"] == "router-test-v1"
            assert stored.version_snapshot["tool_schema"]["version"] == "tool-test-v1"
            assert stored.version_snapshot["rag_strategy"]["version"] == "rag-test-v1"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_lifecycle_persists_failure_details(migrated_database_url: str) -> None:
    started_at = datetime(2026, 8, 9, 2, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 9, 2, 0, 1, tzinfo=UTC)
    clock_values = iter([started_at, finished_at])
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(AgentSession(session_id="session-failed", user_id="user-001"))
                service = RunLifecycleService(
                    AgentRunRepository(session), now=lambda: next(clock_values)
                )
                await service.create_run(
                    run_id="run-failed",
                    session_id="session-failed",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await service.mark_running("run-failed")
                failed = await service.mark_failed(
                    "run-failed",
                    error_code="TOOL_TIMEOUT",
                    error_step="get_quality_issues",
                )

                assert failed.status is AgentRunStatus.FAILED
                assert failed.started_at == started_at
                assert failed.finished_at == finished_at
                assert failed.final_result is None
                assert failed.error_code == "TOOL_TIMEOUT"
                assert failed.error_step == "get_quality_issues"
                assert failed.input_token_count == 0
                assert failed.output_token_count == 0
                assert failed.total_token_count == 0
                assert failed.tool_call_count == 0
                assert failed.duration_ms == 1000
                assert failed.termination_reason == "EXECUTION_ERROR"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_lifecycle_rejects_invalid_transitions_and_failure_data(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(AgentSession(session_id="session-invalid", user_id="user-001"))
                service = RunLifecycleService(
                    AgentRunRepository(session),
                    now=lambda: datetime(2026, 8, 9, 3, 0, tzinfo=UTC),
                )
                await service.create_run(
                    run_id="run-invalid",
                    session_id="session-invalid",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )

                with pytest.raises(InvalidRunTransitionError) as pending_success:
                    await service.mark_succeeded("run-invalid", final_result={})
                assert pending_success.value.current_status is AgentRunStatus.PENDING
                assert pending_success.value.target_status is AgentRunStatus.SUCCEEDED

                await service.mark_running("run-invalid")
                with pytest.raises(InvalidRunTransitionError):
                    await service.mark_running("run-invalid")
                with pytest.raises(RunLifecycleValidationError) as invalid_error:
                    await service.mark_failed(
                        "run-invalid",
                        error_code=" ",
                        error_step="get_order_detail",
                    )
                assert invalid_error.value.field_name == "error_code"
                with pytest.raises(RunLifecycleValidationError) as invalid_result:
                    await service.mark_succeeded(
                        "run-invalid",
                        final_result={"generated_at": datetime(2026, 8, 9, tzinfo=UTC)},
                    )
                assert invalid_result.value.field_name == "final_result"

                failed = await service.mark_failed(
                    "run-invalid",
                    error_code="TOOL_TIMEOUT",
                    error_step="get_order_detail",
                )
                assert failed.status is AgentRunStatus.FAILED
                with pytest.raises(InvalidRunTransitionError):
                    await service.mark_succeeded("run-invalid", final_result={})
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_lifecycle_reports_missing_run(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            service = RunLifecycleService(AgentRunRepository(session))
            with pytest.raises(RunNotFoundError) as missing:
                await service.mark_running("run-missing")
            assert missing.value.run_id == "run-missing"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_lifecycle_allows_only_one_concurrent_terminal_transition(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as setup_session:
            async with setup_session.begin():
                setup_session.add(AgentSession(session_id="session-race", user_id="user-001"))
                setup_service = RunLifecycleService(AgentRunRepository(setup_session))
                await setup_service.create_run(
                    run_id="run-race",
                    session_id="session-race",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await setup_service.mark_running("run-race")

        async def mark_succeeded() -> str:
            async with database.session() as session:
                async with session.begin():
                    service = RunLifecycleService(AgentRunRepository(session))
                    try:
                        await service.mark_succeeded("run-race", final_result={"result": "ok"})
                    except InvalidRunTransitionError:
                        return "rejected"
                    return "succeeded"

        async def mark_failed() -> str:
            async with database.session() as session:
                async with session.begin():
                    service = RunLifecycleService(AgentRunRepository(session))
                    try:
                        await service.mark_failed(
                            "run-race",
                            error_code="TOOL_TIMEOUT",
                            error_step="get_order_detail",
                        )
                    except InvalidRunTransitionError:
                        return "rejected"
                    return "failed"

        outcomes = await asyncio.gather(mark_succeeded(), mark_failed())
        assert sorted(outcomes) in (["rejected", "succeeded"], ["failed", "rejected"])

        async with database.session() as verification_session:
            stored = await AgentRunRepository(verification_session).get("run-race")
            assert stored is not None
            if stored.status is AgentRunStatus.SUCCEEDED:
                assert stored.final_result == {"result": "ok"}
                assert stored.error_code is None
                assert stored.error_step is None
            else:
                assert stored.status is AgentRunStatus.FAILED
                assert stored.final_result is None
                assert stored.error_code == "TOOL_TIMEOUT"
                assert stored.error_step == "get_order_detail"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_persists_success_summaries_and_duration(
    migrated_database_url: str,
) -> None:
    started_at = datetime(2026, 8, 9, 4, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 9, 4, 0, 1, 250000, tzinfo=UTC)
    clock_values = iter([started_at, finished_at])
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(AgentSession(session_id="session-step-success", user_id="user-001"))
                run_service = RunLifecycleService(AgentRunRepository(session))
                await run_service.create_run(
                    run_id="run-step-success",
                    session_id="session-step-success",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await run_service.mark_running("run-step-success")
                step_service = StepLifecycleService(
                    AgentStepRepository(session),
                    AgentRunRepository(session),
                    now=lambda: next(clock_values),
                )

                started = await step_service.start_step(
                    step_id="step-success",
                    run_id="run-step-success",
                    sequence_number=1,
                    step_type=AgentStepType.TOOL,
                    step_name="get_quality_issues",
                    input_summary=(
                        " order_id=ORDER-003\nAuthorization: Bearer top-secret-token "
                    ),
                )
                assert started.status is AgentStepStatus.RUNNING
                assert started.run_id == "run-step-success"
                assert started.started_at == started_at
                assert started.input_summary == (
                    "order_id=ORDER-003 Authorization: Bearer [REDACTED]"
                )

                succeeded = await step_service.mark_succeeded(
                    "step-success",
                    output_summary="api_key=private-key " + "x" * 1200,
                )
                assert succeeded.status is AgentStepStatus.SUCCEEDED
                assert succeeded.finished_at == finished_at
                assert succeeded.duration_ms == 1250
                assert succeeded.error_code is None
                assert succeeded.output_summary is not None
                assert "private-key" not in succeeded.output_summary
                assert "[REDACTED]" in succeeded.output_summary
                assert len(succeeded.output_summary) == 1000
                assert succeeded.output_summary.endswith("...")

        async with database.session() as verification_session:
            stored = await AgentStepRepository(verification_session).get("step-success")
            assert stored is not None
            assert stored.status is AgentStepStatus.SUCCEEDED
            assert stored.run_id == "run-step-success"
            assert stored.duration_ms == 1250
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_persists_all_complete_types_with_safe_summaries(
    migrated_database_url: str,
) -> None:
    expected_types = (
        AgentStepType.CONTEXT,
        AgentStepType.ROUTER,
        AgentStepType.WORKFLOW,
        AgentStepType.AGENT,
        AgentStepType.TOOL,
        AgentStepType.RAG,
        AgentStepType.LLM,
        AgentStepType.APPROVAL,
        AgentStepType.WRITEBACK,
    )
    assert tuple(AgentStepType) == expected_types

    timestamp = datetime(2026, 8, 29, 2, 0, tzinfo=UTC)
    database = Database(migrated_database_url)
    try:
        async with database.session() as session, session.begin():
            session.add(AgentSession(session_id="session-step-types", user_id="user-001"))
            run_repository = AgentRunRepository(session)
            run_service = RunLifecycleService(run_repository, now=lambda: timestamp)
            await run_service.create_run(
                run_id="run-step-types",
                session_id="session-step-types",
                version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
            )
            await run_service.mark_running("run-step-types")
            step_service = StepLifecycleService(
                AgentStepRepository(session),
                run_repository,
                now=lambda: timestamp,
            )

            for sequence_number, step_type in enumerate(expected_types, start=1):
                step_id = f"step-type-{step_type.value.lower()}"
                started = await step_service.start_step(
                    step_id=step_id,
                    run_id="run-step-types",
                    sequence_number=sequence_number,
                    step_type=step_type,
                    step_name=f"record_{step_type.value.lower()}",
                    input_summary=(
                        f"type={step_type.value}; password=input-secret; "
                        "refresh_token=refresh-secret"
                    ),
                )
                succeeded = await step_service.mark_succeeded(
                    step_id,
                    output_summary=(
                        "Authorization: Bearer output-secret " + "x" * 1200
                    ),
                )

                assert started.input_summary == (
                    f"type={step_type.value}; password=[REDACTED]; "
                    "refresh_token=[REDACTED]"
                )
                assert succeeded.output_summary is not None
                assert "output-secret" not in succeeded.output_summary
                assert len(succeeded.output_summary) == 1000

        async with database.session() as verification_session:
            stored_steps = await AgentStepRepository(verification_session).list_by_run(
                "run-step-types"
            )
        assert tuple(step.step_type for step in stored_steps) == expected_types
        assert all(step.status is AgentStepStatus.SUCCEEDED for step in stored_steps)
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_persists_failure_details(migrated_database_url: str) -> None:
    started_at = datetime(2026, 8, 9, 5, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 9, 5, 0, 0, 750000, tzinfo=UTC)
    clock_values = iter([started_at, finished_at])
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(AgentSession(session_id="session-step-failed", user_id="user-001"))
                run_service = RunLifecycleService(AgentRunRepository(session))
                await run_service.create_run(
                    run_id="run-step-failed",
                    session_id="session-step-failed",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await run_service.mark_running("run-step-failed")
                step_service = StepLifecycleService(
                    AgentStepRepository(session),
                    AgentRunRepository(session),
                    now=lambda: next(clock_values),
                )
                await step_service.start_step(
                    step_id="step-failed",
                    run_id="run-step-failed",
                    sequence_number=1,
                    step_type=AgentStepType.TOOL,
                    step_name="get_order_detail",
                    input_summary="order_id=ORDER-003",
                )
                failed = await step_service.mark_failed(
                    "step-failed",
                    error_code="TOOL_TIMEOUT",
                    output_summary="Java业务服务请求超时",
                )

                assert failed.status is AgentStepStatus.FAILED
                assert failed.finished_at == finished_at
                assert failed.duration_ms == 750
                assert failed.error_code == "TOOL_TIMEOUT"
                assert failed.output_summary == "Java业务服务请求超时"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_rejects_unavailable_run_invalid_data_and_transitions(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(AgentSession(session_id="session-step-invalid", user_id="user-001"))
                run_repository = AgentRunRepository(session)
                run_service = RunLifecycleService(run_repository)
                await run_service.create_run(
                    run_id="run-step-invalid",
                    session_id="session-step-invalid",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                step_service = StepLifecycleService(
                    AgentStepRepository(session),
                    run_repository,
                    now=lambda: datetime(2026, 8, 9, 6, 0, tzinfo=UTC),
                )

                with pytest.raises(StepRunUnavailableError) as pending_run:
                    await step_service.start_step(
                        step_id="step-pending-run",
                        run_id="run-step-invalid",
                        sequence_number=1,
                        step_type=AgentStepType.CONTEXT,
                        step_name="load_context",
                    )
                assert pending_run.value.current_status is AgentRunStatus.PENDING
                with pytest.raises(StepRunUnavailableError) as missing_run:
                    await step_service.start_step(
                        step_id="step-missing-run",
                        run_id="run-missing",
                        sequence_number=1,
                        step_type=AgentStepType.CONTEXT,
                        step_name="load_context",
                    )
                assert missing_run.value.current_status is None

                await run_service.mark_running("run-step-invalid")
                with pytest.raises(StepLifecycleValidationError) as invalid_sequence:
                    await step_service.start_step(
                        step_id="step-invalid-sequence",
                        run_id="run-step-invalid",
                        sequence_number=0,
                        step_type=AgentStepType.CONTEXT,
                        step_name="load_context",
                    )
                assert invalid_sequence.value.field_name == "sequence_number"
                with pytest.raises(StepLifecycleValidationError) as invalid_name:
                    await step_service.start_step(
                        step_id="step-invalid-name",
                        run_id="run-step-invalid",
                        sequence_number=1,
                        step_type=AgentStepType.CONTEXT,
                        step_name=" ",
                    )
                assert invalid_name.value.field_name == "step_name"

                await step_service.start_step(
                    step_id="step-invalid",
                    run_id="run-step-invalid",
                    sequence_number=1,
                    step_type=AgentStepType.CONTEXT,
                    step_name="load_context",
                )
                with pytest.raises(StepLifecycleValidationError) as invalid_error:
                    await step_service.mark_failed("step-invalid", error_code=" ")
                assert invalid_error.value.field_name == "error_code"
                await step_service.mark_succeeded("step-invalid", output_summary="上下文已加载")
                with pytest.raises(InvalidStepTransitionError) as terminal_retry:
                    await step_service.mark_failed(
                        "step-invalid",
                        error_code="CONTEXT_FAILED",
                    )
                assert terminal_retry.value.current_status is AgentStepStatus.SUCCEEDED
                assert terminal_retry.value.target_status is AgentStepStatus.FAILED
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_reports_missing_step(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as session:
            service = StepLifecycleService(
                AgentStepRepository(session),
                AgentRunRepository(session),
            )
            with pytest.raises(StepNotFoundError) as missing:
                await service.mark_succeeded("step-missing")
            assert missing.value.step_id == "step-missing"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_allows_only_one_concurrent_terminal_transition(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as setup_session:
            async with setup_session.begin():
                setup_session.add(AgentSession(session_id="session-step-race", user_id="user-001"))
                run_repository = AgentRunRepository(setup_session)
                run_service = RunLifecycleService(run_repository)
                await run_service.create_run(
                    run_id="run-step-race",
                    session_id="session-step-race",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await run_service.mark_running("run-step-race")
                step_service = StepLifecycleService(
                    AgentStepRepository(setup_session),
                    run_repository,
                    now=lambda: datetime(2026, 8, 9, 7, 0, tzinfo=UTC),
                )
                await step_service.start_step(
                    step_id="step-race",
                    run_id="run-step-race",
                    sequence_number=1,
                    step_type=AgentStepType.WORKFLOW,
                    step_name="diagnose_blocker",
                )

        async def mark_succeeded() -> str:
            async with database.session() as session:
                async with session.begin():
                    service = StepLifecycleService(
                        AgentStepRepository(session),
                        AgentRunRepository(session),
                        now=lambda: datetime(2026, 8, 9, 7, 0, 1, tzinfo=UTC),
                    )
                    try:
                        await service.mark_succeeded("step-race", output_summary="规则命中")
                    except InvalidStepTransitionError:
                        return "rejected"
                    return "succeeded"

        async def mark_failed() -> str:
            async with database.session() as session:
                async with session.begin():
                    service = StepLifecycleService(
                        AgentStepRepository(session),
                        AgentRunRepository(session),
                        now=lambda: datetime(2026, 8, 9, 7, 0, 1, tzinfo=UTC),
                    )
                    try:
                        await service.mark_failed(
                            "step-race",
                            error_code="RULE_FAILED",
                        )
                    except InvalidStepTransitionError:
                        return "rejected"
                    return "failed"

        outcomes = await asyncio.gather(mark_succeeded(), mark_failed())
        assert sorted(outcomes) in (["rejected", "succeeded"], ["failed", "rejected"])

        async with database.session() as verification_session:
            stored = await AgentStepRepository(verification_session).get("step-race")
            assert stored is not None
            assert stored.duration_ms == 1000
            if stored.status is AgentStepStatus.SUCCEEDED:
                assert stored.output_summary == "规则命中"
                assert stored.error_code is None
            else:
                assert stored.status is AgentStepStatus.FAILED
                assert stored.error_code == "RULE_FAILED"
    finally:
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_lifecycle_serializes_step_start_with_parent_run_terminal_update(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    lock_held = asyncio.Event()
    release_lock = asyncio.Event()
    try:
        async with database.session() as setup_session:
            async with setup_session.begin():
                setup_session.add(
                    AgentSession(session_id="session-step-parent-lock", user_id="user-001")
                )
                run_service = RunLifecycleService(AgentRunRepository(setup_session))
                await run_service.create_run(
                    run_id="run-step-parent-lock",
                    session_id="session-step-parent-lock",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await run_service.mark_running("run-step-parent-lock")

        async def start_step_and_hold_parent_lock() -> None:
            async with database.session() as session:
                async with session.begin():
                    service = StepLifecycleService(
                        AgentStepRepository(session),
                        AgentRunRepository(session),
                    )
                    await service.start_step(
                        step_id="step-parent-lock",
                        run_id="run-step-parent-lock",
                        sequence_number=1,
                        step_type=AgentStepType.CONTEXT,
                        step_name="load_context",
                    )
                    lock_held.set()
                    await release_lock.wait()

        start_task = asyncio.create_task(start_step_and_hold_parent_lock())
        await lock_held.wait()
        try:
            with pytest.raises(DBAPIError):
                async with database.session() as blocked_session:
                    async with blocked_session.begin():
                        await blocked_session.execute(text("SET LOCAL lock_timeout = '100ms'"))
                        run_service = RunLifecycleService(AgentRunRepository(blocked_session))
                        await run_service.mark_succeeded(
                            "run-step-parent-lock",
                            final_result={"result": "premature"},
                        )
        finally:
            release_lock.set()
            await start_task

        async with database.session() as finish_session:
            async with finish_session.begin():
                run_service = RunLifecycleService(AgentRunRepository(finish_session))
                finished = await run_service.mark_succeeded(
                    "run-step-parent-lock",
                    final_result={"result": "after-step-start-commit"},
                )
                assert finished.status is AgentRunStatus.SUCCEEDED
                stored_step = await AgentStepRepository(finish_session).get("step-parent-lock")
                assert stored_step is not None
                assert stored_step.run_id == "run-step-parent-lock"
    finally:
        release_lock.set()
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_step_recorder_uses_committed_short_transactions(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session() as setup_session:
            async with setup_session.begin():
                setup_session.add(
                    AgentSession(session_id="session-workflow-recorder", user_id="user-001")
                )
                run_service = RunLifecycleService(AgentRunRepository(setup_session))
                await run_service.create_run(
                    run_id="run-workflow-recorder",
                    session_id="session-workflow-recorder",
                    version_snapshot=TEST_RUN_VERSION_SNAPSHOT,
                )
                await run_service.mark_running("run-workflow-recorder")

        recorder = DatabaseWorkflowStepRecorder(database)
        await recorder.start_step(
            step_id="step-workflow-context",
            run_id="run-workflow-recorder",
            sequence_number=1,
            step_type=AgentStepType.CONTEXT,
            step_name="load_context",
            input_summary="order_id=ORDER-003",
        )
        await recorder.mark_succeeded(
            "step-workflow-context",
            output_summary="order_id=ORDER-003",
        )
        await recorder.start_step(
            step_id="step-workflow-quality",
            run_id="run-workflow-recorder",
            sequence_number=2,
            step_type=AgentStepType.TOOL,
            step_name="load_quality",
            input_summary="task_id=TASK-003",
        )
        await recorder.mark_failed(
            "step-workflow-quality",
            error_code="RESOURCE_NOT_FOUND",
            output_summary="code=RESOURCE_NOT_FOUND; retryable=false",
        )

        async with database.session() as verification_session:
            stored_steps = await AgentStepRepository(verification_session).list_by_run(
                "run-workflow-recorder"
            )
            stored_run = await AgentRunRepository(verification_session).get(
                "run-workflow-recorder"
            )
            assert stored_run is not None
            assert stored_run.status is AgentRunStatus.RUNNING
            assert [step.status for step in stored_steps] == [
                AgentStepStatus.SUCCEEDED,
                AgentStepStatus.FAILED,
            ]
            assert stored_steps[0].output_summary == "order_id=ORDER-003"
            assert stored_steps[1].error_code == "RESOURCE_NOT_FOUND"
    finally:
        await database.dispose()
