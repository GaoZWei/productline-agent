import asyncio
import os
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
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
    ProcessedDocument,
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
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.repositories import (
    AgentRunRepository,
    AgentStepRepository,
    KnowledgeIndexRepository,
)
from app.schemas.knowledge import (
    DocumentLifecycle,
    DocumentMetadata,
    DocumentType,
    PermissionScope,
)
from app.services import (
    InvalidRunTransitionError,
    InvalidStepTransitionError,
    RunLifecycleService,
    RunLifecycleValidationError,
    RunNotFoundError,
    StepLifecycleService,
    StepLifecycleValidationError,
    StepNotFoundError,
    StepRunUnavailableError,
)
from app.settings import Settings
from app.workflows import DatabaseWorkflowStepRecorder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL_ENV = "AGENT_PERSISTENCE_TEST_DATABASE_URL"


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
        "agent_runs",
        "agent_sessions",
        "agent_steps",
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
            run = AgentRun(run_id="run-duplicate", session=agent_session)
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
                        step_type=AgentStepType.RULE,
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
                )
                assert created.status is AgentRunStatus.PENDING
                assert created.started_at is None
                assert created.finished_at is None

                running = await service.mark_running("run-success")
                assert running.status is AgentRunStatus.RUNNING
                assert running.started_at == started_at

                succeeded = await service.mark_succeeded(
                    "run-success",
                    final_result={"blocking_stage": "QUALITY_REVIEW"},
                )
                assert succeeded.status is AgentRunStatus.SUCCEEDED
                assert succeeded.final_result == {"blocking_stage": "QUALITY_REVIEW"}
                assert succeeded.finished_at == finished_at
                assert succeeded.error_code is None
                assert succeeded.error_step is None

        async with database.session() as verification_session:
            stored = await AgentRunRepository(verification_session).get("run-success")
            assert stored is not None
            assert stored.status is AgentRunStatus.SUCCEEDED
            assert stored.final_result == {"blocking_stage": "QUALITY_REVIEW"}
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
                await service.create_run(run_id="run-failed", session_id="session-failed")
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
                await service.create_run(run_id="run-invalid", session_id="session-invalid")

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
                await setup_service.create_run(run_id="run-race", session_id="session-race")
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
                    step_type=AgentStepType.RULE,
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
