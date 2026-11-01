"""在临时数据库验证管理模型迁移，旧表哨兵不冒充完整旧索引集成。"""

from __future__ import annotations

import asyncio
import subprocess
from typing import cast

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import Database
from app.models import (
    ManagedKnowledgeChunk,
    ManagedKnowledgeDocument,
    ManagedKnowledgeIndexGeneration,
    ManagedKnowledgeLibrary,
    ManagedKnowledgeOperation,
    ManagedKnowledgeRevision,
    ManagedKnowledgeTask,
    ManagedKnowledgeVersion,
)
from app.schemas.managed_knowledge import ManagedKnowledgeRevisionSnapshot
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeGenerationRecord,
    ManagedKnowledgeOperationRecord,
    ManagedKnowledgeTaskRecord,
)
from tests.knowledge.managed_knowledge_database import (
    managed_database as managed_database,
)
from tests.knowledge.managed_knowledge_database import (
    run_alembic as _alembic,
)
from tests.knowledge.managed_knowledge_fixtures import (
    DOCUMENT_ID,
    GENERATION_ID,
    VERSION_ID,
    chunk_payload,
    confirmation_payload,
    generation_payload,
    operation_payload,
    revision_payload,
    task_payload,
    version_payload,
)

TABLES = [
    cls.__table__
    for cls in (
        ManagedKnowledgeLibrary,
        ManagedKnowledgeDocument,
        ManagedKnowledgeVersion,
        ManagedKnowledgeRevision,
        ManagedKnowledgeIndexGeneration,
        ManagedKnowledgeOperation,
        ManagedKnowledgeTask,
        ManagedKnowledgeChunk,
    )
]


async def _seed_draft(database: Database) -> None:
    """版本先插入、修订后插入，在同一事务提交时满足循环外键。"""

    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(revision_payload())
    async with database.engine.begin() as connection:
        await connection.execute(
            insert(ManagedKnowledgeDocument).values(
                document_id=DOCUMENT_ID,
                created_by="test-user",
            )
        )
        await connection.execute(insert(ManagedKnowledgeVersion).values(**version_payload()))
        await connection.execute(
            insert(ManagedKnowledgeRevision).values(
                **snapshot.model_dump(),
                metadata_hash=snapshot.metadata_digest(),
            )
        )


async def _wait_for_lock(database: Database, backend_pid: int) -> None:
    """等待真实数据库锁竞争，避免用固定延时猜测并发是否发生。"""

    async with database.engine.connect() as observer:
        async with asyncio.timeout(5):
            while True:
                waiting = await observer.execute(
                    text("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid = :pid AND NOT granted)"),
                    {"pid": backend_pid},
                )
                if waiting.scalar_one():
                    return
                await asyncio.sleep(0.01)


async def _insert_version(connection: AsyncConnection, version_id: str) -> None:
    """同一个规范版本号的不同请求身份，必须依赖唯一约束仲裁。"""

    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            version_id=version_id,
            specification_version="3.0",
            original_key=f"versions/{version_id}/revisions/1/original.md",
        )
    )
    await connection.execute(
        insert(ManagedKnowledgeVersion).values(
            **version_payload(
                version_id=version_id,
                citation_document_id=version_id,
                specification_version="3.0",
            )
        )
    )
    await connection.execute(
        insert(ManagedKnowledgeRevision).values(
            **snapshot.model_dump(),
            metadata_hash=snapshot.metadata_digest(),
        )
    )


@pytest.mark.integration
async def test_managed_knowledge_migration_matches_orm_and_downgrades_only_new_tables(
    managed_database: Database,
) -> None:
    async with managed_database.engine.connect() as connection:
        library = (await connection.execute(select(ManagedKnowledgeLibrary.__table__))).one()
        assert library.library_id == "DEFAULT"
        assert library.source_mode == "LEGACY"
        assert library.release_revision == 0
        metadata = MetaData()
        for table in TABLES:
            cast(Table, table).to_metadata(metadata)
        differences = await connection.run_sync(
            lambda sync: compare_metadata(
                MigrationContext.configure(
                    sync,
                    opts={
                        "include_object": lambda obj, name, kind, reflected, target: (
                            kind != "table" or name.startswith("managed_knowledge_")
                        ),
                    },
                ),
                metadata,
            )
        )
        assert differences == []
    url = managed_database.engine.url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    _alembic(url, "downgrade", "0014_review_source_run")
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename LIKE 'managed_knowledge_%'"
                )
            )
        ).all() == []
        old_body = await connection.execute(text("SELECT body FROM knowledge_documents"))
        assert old_body.scalar_one() == "旧规范哨兵"
        old_chunk = await connection.execute(text("SELECT content FROM knowledge_chunks"))
        assert old_chunk.scalar_one() == "旧引用哨兵"
    _alembic(url, "upgrade", "head")


@pytest.mark.integration
async def test_managed_knowledge_missing_initial_revision_rolls_back_whole_draft(
    managed_database: Database,
) -> None:
    with pytest.raises(IntegrityError, match="fk_mkv_current_revision"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                insert(ManagedKnowledgeDocument).values(
                    document_id=DOCUMENT_ID,
                    created_by="test-user",
                )
            )
            await connection.execute(insert(ManagedKnowledgeVersion).values(**version_payload()))
    async with managed_database.engine.connect() as connection:
        assert (await connection.execute(select(ManagedKnowledgeDocument.document_id))).all() == []
        assert (await connection.execute(select(ManagedKnowledgeVersion.version_id))).all() == []


@pytest.mark.integration
async def test_managed_knowledge_revisions_preserve_old_snapshot_and_allow_same_body_versions(
    managed_database: Database,
) -> None:
    await _seed_draft(managed_database)
    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            revision_no=2,
            original_key=f"versions/{VERSION_ID}/revisions/2/original.md",
            title="修正标题",
        )
    )
    second_id = "VER-" + "2" * 32
    second = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            version_id=second_id,
            specification_version="3.0",
            original_key=f"versions/{second_id}/revisions/1/original.md",
        )
    )
    async with managed_database.engine.begin() as connection:
        await connection.execute(
            insert(ManagedKnowledgeRevision).values(
                **snapshot.model_dump(),
                metadata_hash=snapshot.metadata_digest(),
            )
        )
        result = await connection.execute(
            update(ManagedKnowledgeVersion)
            .where(
                ManagedKnowledgeVersion.version_id == VERSION_ID,
                ManagedKnowledgeVersion.current_revision_no == 1,
            )
            .values(current_revision_no=2)
        )
        assert result.rowcount == 1
        await connection.execute(
            insert(ManagedKnowledgeVersion).values(
                **version_payload(
                    version_id=second_id,
                    citation_document_id=second_id,
                    specification_version="3.0",
                )
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeRevision).values(
                **second.model_dump(),
                metadata_hash=second.metadata_digest(),
            )
        )
    async with managed_database.engine.connect() as connection:
        titles = (
            (
                await connection.execute(
                    select(ManagedKnowledgeRevision.title)
                    .where(
                        ManagedKnowledgeRevision.version_id == VERSION_ID,
                    )
                    .order_by(ManagedKnowledgeRevision.revision_no)
                )
            )
            .scalars()
            .all()
        )
        assert titles == ["测试规范", "修正标题"]
        assert (
            await connection.execute(
                select(ManagedKnowledgeVersion.current_revision_no).where(
                    ManagedKnowledgeVersion.version_id == VERSION_ID,
                )
            )
        ).scalar_one() == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE managed_knowledge_versions SET current_revision_no = 99",
            "fk_mkv_current_revision",
        ),
        (
            "UPDATE managed_knowledge_versions SET publication_state = 'PUBLISHED'",
            "ck_mkv_publication_fields",
        ),
        ("UPDATE managed_knowledge_documents SET row_version = -1", "ck_mkd_row_version"),
        ("UPDATE managed_knowledge_libraries SET source_mode = 'MANAGED'", "ck_mkl_source_mode"),
        (
            "UPDATE managed_knowledge_revisions SET specification_version = '9.0'",
            "fk_mkr_version_spec",
        ),
        ("UPDATE managed_knowledge_revisions SET original_key = '../x.md'", "ck_mkr_original_key"),
        ("UPDATE managed_knowledge_revisions SET raw_hash = repeat('g', 64)", "ck_mkr_raw_hash"),
        ("UPDATE managed_knowledge_revisions SET body = '单独正文'", "ck_mkr_parse_pair"),
        ("UPDATE managed_knowledge_revisions SET expiry_date = '2029-01-01'", "ck_mkr_dates"),
        ("UPDATE managed_knowledge_revisions SET file_format = 'PDF'", "ck_mkr_file_format"),
        ("UPDATE managed_knowledge_versions SET source_kind = 'UNKNOWN'", "ck_mkv_provenance"),
    ],
)
async def test_managed_knowledge_database_rejects_invalid_state_and_rolls_back(
    managed_database: Database,
    statement: str,
    constraint: str,
) -> None:
    await _seed_draft(managed_database)
    with pytest.raises(IntegrityError) as failure:
        async with managed_database.engine.begin() as connection:
            await connection.execute(text(statement))
    assert constraint in str(failure.value)
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(
                select(
                    ManagedKnowledgeVersion.current_revision_no,
                )
            )
        ).scalar_one() == 1


@pytest.mark.integration
async def test_managed_knowledge_duplicate_version_and_cross_document_pointer_are_blocked(
    managed_database: Database,
) -> None:
    await _seed_draft(managed_database)
    second_id = "VER-" + "2" * 32
    with pytest.raises(IntegrityError, match="uq_mkv_document_spec"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                insert(ManagedKnowledgeVersion).values(
                    **version_payload(
                        version_id=second_id,
                        citation_document_id=second_id,
                    )
                )
            )
    other_document = "DOC-" + "2" * 32
    with pytest.raises(IntegrityError, match="fk_mkd_current_version"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                insert(ManagedKnowledgeDocument).values(
                    document_id=other_document,
                    current_version_id=VERSION_ID,
                    created_by="test-user",
                )
            )


@pytest.mark.integration
async def test_managed_knowledge_concurrent_updates_have_one_winner(
    managed_database: Database,
) -> None:
    await _seed_draft(managed_database)
    # 首个事务持锁时第二个事务确实进入锁等待，提交后必须重新检查旧row_version。
    async with (
        managed_database.engine.connect() as first,
        managed_database.engine.connect() as second,
    ):
        assert (await first.execute(select(ManagedKnowledgeDocument.row_version))).scalar_one() == 0
        initial = await second.execute(select(ManagedKnowledgeDocument.row_version))
        assert initial.scalar_one() == 0
        await first.commit()
        await second.commit()
        result = await first.execute(
            update(ManagedKnowledgeDocument)
            .where(
                ManagedKnowledgeDocument.row_version == 0,
            )
            .values(row_version=1)
        )
        assert result.rowcount == 1
        pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        pending = asyncio.create_task(
            second.execute(
                update(ManagedKnowledgeDocument)
                .where(
                    ManagedKnowledgeDocument.row_version == 0,
                )
                .values(row_version=2)
            )
        )
        try:
            await _wait_for_lock(managed_database, pid)
            await first.commit()
            late_result = await asyncio.wait_for(pending, timeout=5)
            assert late_result.rowcount == 0
            await second.commit()
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    with pytest.raises(IntegrityError):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                insert(ManagedKnowledgeRevision).values(
                    **ManagedKnowledgeRevisionSnapshot.model_validate(
                        revision_payload()
                    ).model_dump(),
                    metadata_hash="a" * 64,
                )
            )


@pytest.mark.integration
async def test_managed_knowledge_concurrent_version_inserts_have_one_winner(
    managed_database: Database,
) -> None:
    await _seed_draft(managed_database)
    async with (
        managed_database.engine.connect() as first,
        managed_database.engine.connect() as second,
    ):
        await _insert_version(first, "VER-" + "3" * 32)
        pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        pending = asyncio.create_task(_insert_version(second, "VER-" + "4" * 32))
        try:
            await _wait_for_lock(managed_database, pid)
            await first.commit()
            with pytest.raises(IntegrityError, match="uq_mkv_document_spec"):
                await asyncio.wait_for(pending, timeout=5)
            await second.rollback()
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with managed_database.engine.connect() as connection:
        versions = (
            (
                await connection.execute(
                    select(ManagedKnowledgeVersion.version_id).where(
                        ManagedKnowledgeVersion.specification_version == "3.0",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert versions == ["VER-" + "3" * 32]


async def _seed_processing(database: Database) -> None:
    """四表基础上保存候选、操作、解析任务和分块，不执行发布。"""

    await _seed_draft(database)
    generation = ManagedKnowledgeGenerationRecord.model_validate(generation_payload())
    operation = ManagedKnowledgeOperationRecord.model_validate(operation_payload())
    task = ManagedKnowledgeTaskRecord.model_validate(task_payload())
    chunk = ManagedKnowledgeChunkRecord.model_validate(chunk_payload())
    async with database.engine.begin() as connection:
        await connection.execute(
            insert(ManagedKnowledgeIndexGeneration).values(**generation.model_dump())
        )
        await connection.execute(insert(ManagedKnowledgeOperation).values(**operation.model_dump()))
        await connection.execute(insert(ManagedKnowledgeTask).values(**task.model_dump()))
        await connection.execute(
            insert(ManagedKnowledgeChunk).values(**chunk.model_dump(mode="json"))
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE managed_knowledge_index_generations SET embedding_dimension = 1024",
            "ck_mkg_dimension",
        ),
        (
            "UPDATE managed_knowledge_index_generations "
            "SET state = 'READY', finished_at = created_at",
            "ck_mkg_state_fields",
        ),
        ("UPDATE managed_knowledge_index_generations SET state = 'UNKNOWN'", "ck_mkg_state_fields"),
        ("UPDATE managed_knowledge_operations SET action = 'READ'", "ck_mko_action"),
        ("UPDATE managed_knowledge_operations SET state = 'SUCCEEDED'", "ck_mko_state_fields"),
        ("UPDATE managed_knowledge_operations SET target_id = 'other-version'", "ck_mko_target"),
        (
            "UPDATE managed_knowledge_operations SET confirmation_snapshot = "
            'confirmation_snapshot || \'{"token":"forbidden"}\'::jsonb',
            "ck_mko_snapshot",
        ),
        (
            "UPDATE managed_knowledge_operations SET confirmation_snapshot = "
            "confirmation_snapshot || jsonb_build_object('actor_id', NULL)",
            "ck_mko_snapshot",
        ),
        (
            "UPDATE managed_knowledge_operations SET confirmation_snapshot = "
            "confirmation_snapshot - 'raw_hash'",
            "ck_mko_snapshot",
        ),
        ("UPDATE managed_knowledge_tasks SET state = 'SUCCEEDED'", "ck_mkt_state_fields"),
        ("UPDATE managed_knowledge_tasks SET operation_action = 'PUBLISH'", "ck_mkt_type_fields"),
        ("UPDATE managed_knowledge_tasks SET attempt_no = 2", "ck_mkt_attempt"),
        ("UPDATE managed_knowledge_tasks SET owner_id = ''", "ck_mkt_owner"),
        (
            "UPDATE managed_knowledge_tasks SET error_code = 'provider secret exception'",
            "ck_mkt_error",
        ),
        ("UPDATE managed_knowledge_chunks SET chunk_index = -1", "ck_mkc_counts"),
        ("UPDATE managed_knowledge_chunks SET section_path = '[]'::jsonb", "ck_mkc_section"),
        ("UPDATE managed_knowledge_chunks SET content_hash = repeat('g',64)", "ck_mkc_hash"),
    ],
)
async def test_managed_knowledge_processing_database_rejects_invalid_input(
    managed_database: Database,
    statement: str,
    constraint: str,
) -> None:
    await _seed_processing(managed_database)
    with pytest.raises(IntegrityError, match=constraint):
        async with managed_database.engine.begin() as connection:
            await connection.execute(text(statement))


@pytest.mark.integration
async def test_managed_knowledge_chunk_generations_preserve_history_and_own_search_indexes(
    managed_database: Database,
) -> None:
    await _seed_processing(managed_database)
    second_id = "GEN-" + "2" * 32
    second = ManagedKnowledgeGenerationRecord.model_validate(
        generation_payload(generation_id=second_id)
    )
    chunk = ManagedKnowledgeChunkRecord.model_validate(chunk_payload(generation_id=second_id))
    async with managed_database.engine.begin() as connection:
        await connection.execute(
            insert(ManagedKnowledgeIndexGeneration).values(**second.model_dump())
        )
        await connection.execute(
            insert(ManagedKnowledgeChunk).values(**chunk.model_dump(mode="json"))
        )
        assert len((await connection.execute(select(ManagedKnowledgeChunk.chunk_id))).all()) == 2
        assert (
            await connection.execute(
                text(
                    "SELECT count(*) FROM managed_knowledge_chunks "
                    "WHERE search_vector @@ plainto_tsquery('simple', '规范')"
                )
            )
        ).scalar_one() == 2
        indexes = (
            (
                await connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE tablename = 'managed_knowledge_chunks'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("USING gin" in definition for definition in indexes)
        assert any(
            "USING hnsw" in definition and "vector_cosine_ops" in definition
            for definition in indexes
        )
    with pytest.raises(IntegrityError, match="uq_mkc_generation_index"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                insert(ManagedKnowledgeChunk).values(
                    **{**chunk.model_dump(mode="json"), "chunk_id": "KCH-OTHER"},
                )
            )
    # 候选存在也不激活读源或填充任何资料发布指针。
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(select(ManagedKnowledgeLibrary.source_mode))
        ).scalar_one() == "LEGACY"
        assert (
            await connection.execute(select(ManagedKnowledgeDocument.current_version_id))
        ).scalar_one() is None


async def _publish_fixture(database: Database) -> None:
    """仅为数据库约束准备封存状态，不代表已有应用发布能力。"""

    async with database.engine.begin() as connection:
        await connection.execute(
            update(ManagedKnowledgeIndexGeneration).values(
                state="READY",
                chunk_count=1,
                finished_at=ManagedKnowledgeIndexGeneration.created_at,
            )
        )
        await connection.execute(
            update(ManagedKnowledgeVersion).values(
                publication_state="PUBLISHED",
                published_revision_no=1,
                published_generation_id=GENERATION_ID,
                published_at=text("CURRENT_TIMESTAMP"),
            )
        )
        await connection.execute(
            update(ManagedKnowledgeDocument).values(current_version_id=VERSION_ID)
        )


@pytest.mark.integration
async def test_managed_knowledge_publication_binds_revision_and_preserves_old_release_on_failure(
    managed_database: Database,
) -> None:
    await _seed_processing(managed_database)
    await _publish_fixture(managed_database)
    second_version = "VER-" + "2" * 32
    second_generation = "GEN-" + "2" * 32
    async with managed_database.engine.begin() as connection:
        await _insert_version(connection, second_version)
        generation = ManagedKnowledgeGenerationRecord.model_validate(
            generation_payload(
                version_id=second_version,
                generation_id=second_generation,
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeIndexGeneration).values(**generation.model_dump())
        )
    with pytest.raises(IntegrityError, match="fk_mkv_published_generation"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                update(ManagedKnowledgeVersion)
                .where(
                    ManagedKnowledgeVersion.version_id == VERSION_ID,
                )
                .values(published_generation_id=second_generation)
            )
    with pytest.raises(IntegrityError, match="uq_mkv_one_published"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                update(ManagedKnowledgeVersion)
                .where(
                    ManagedKnowledgeVersion.version_id == second_version,
                )
                .values(
                    publication_state="PUBLISHED",
                    published_revision_no=1,
                    published_generation_id=second_generation,
                    published_at=text("CURRENT_TIMESTAMP"),
                )
            )
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(select(ManagedKnowledgeDocument.current_version_id))
        ).scalar_one() == VERSION_ID
        assert (
            await connection.execute(
                select(ManagedKnowledgeVersion.published_generation_id).where(
                    ManagedKnowledgeVersion.version_id == VERSION_ID,
                )
            )
        ).scalar_one() == GENERATION_ID


@pytest.mark.integration
async def test_managed_knowledge_sealed_version_rejects_repointing_to_new_revision(
    managed_database: Database,
) -> None:
    await _seed_processing(managed_database)
    await _publish_fixture(managed_database)
    revision = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            revision_no=2,
            original_key=f"versions/{VERSION_ID}/revisions/2/original.md",
        )
    )
    with pytest.raises(IntegrityError, match="ck_mkv_publication_fields"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                insert(ManagedKnowledgeRevision).values(
                    **revision.model_dump(),
                    metadata_hash=revision.metadata_digest(),
                )
            )
            await connection.execute(update(ManagedKnowledgeVersion).values(current_revision_no=2))
    async with managed_database.engine.connect() as connection:
        assert (
            len((await connection.execute(select(ManagedKnowledgeRevision.revision_no))).all()) == 1
        )


@pytest.mark.integration
async def test_managed_knowledge_retry_keeps_failed_task_and_cannot_cross_revision(
    managed_database: Database,
) -> None:
    await _seed_processing(managed_database)
    index_operation_id = "OP-" + "2" * 32
    index_task_id = "TASK-" + "2" * 32
    retry_operation_id = "OP-" + "3" * 32
    retry_generation_id = "GEN-" + "2" * 32
    retry_task_id = "TASK-" + "3" * 32
    async with managed_database.engine.begin() as connection:
        for operation_id, action, original in (
            (index_operation_id, "PUBLISH", None),
            (retry_operation_id, "RETRY_INDEX", index_task_id),
        ):
            operation = ManagedKnowledgeOperationRecord.model_validate(
                operation_payload(
                    operation_id=operation_id,
                    action=action,
                    confirmation_snapshot=confirmation_payload(
                        action=action,
                        normalized_hash="b" * 64,
                        task_id=original,
                    ),
                )
            )
            await connection.execute(
                insert(ManagedKnowledgeOperation).values(**operation.model_dump())
            )
        initial = ManagedKnowledgeTaskRecord.model_validate(
            task_payload(
                task_id=index_task_id,
                operation_id=index_operation_id,
                operation_action="PUBLISH",
                task_type="INDEX",
                generation_id=GENERATION_ID,
                state="FAILED",
                finished_at=ManagedKnowledgeTaskRecord.model_validate(task_payload()).created_at,
                error_code="INDEX_BUILD_FAILED",
            )
        )
        await connection.execute(insert(ManagedKnowledgeTask).values(**initial.model_dump()))
        generation = ManagedKnowledgeGenerationRecord.model_validate(
            generation_payload(
                generation_id=retry_generation_id,
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeIndexGeneration).values(**generation.model_dump())
        )
        retry = ManagedKnowledgeTaskRecord.model_validate(
            task_payload(
                task_id=retry_task_id,
                operation_id=retry_operation_id,
                operation_action="RETRY_INDEX",
                task_type="INDEX",
                generation_id=retry_generation_id,
                attempt_no=2,
                retry_of_task_id=index_task_id,
            )
        )
        await connection.execute(insert(ManagedKnowledgeTask).values(**retry.model_dump()))
        # 同一规范的另一修订也不允许成为本修订的重试来源或操作来源。
        other_revision = ManagedKnowledgeRevisionSnapshot.model_validate(
            revision_payload(
                revision_no=2,
                original_key=f"versions/{VERSION_ID}/revisions/2/original.md",
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeRevision).values(
                **other_revision.model_dump(),
                metadata_hash=other_revision.metadata_digest(),
            )
        )
        other_generation = ManagedKnowledgeGenerationRecord.model_validate(
            generation_payload(
                generation_id="GEN-" + "3" * 32,
                revision_no=2,
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeIndexGeneration).values(**other_generation.model_dump())
        )
        other_operation = ManagedKnowledgeOperationRecord.model_validate(
            operation_payload(
                operation_id="OP-" + "4" * 32,
                revision_no=2,
                action="PUBLISH",
                idempotency_key="publish-revision-2",
                confirmation_snapshot=confirmation_payload(
                    revision_no=2,
                    action="PUBLISH",
                    normalized_hash="b" * 64,
                ),
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeOperation).values(**other_operation.model_dump())
        )
        other_task = ManagedKnowledgeTaskRecord.model_validate(
            task_payload(
                task_id="TASK-" + "4" * 32,
                revision_no=2,
                operation_id=other_operation.operation_id,
                operation_action="PUBLISH",
                task_type="INDEX",
                generation_id=other_generation.generation_id,
            )
        )
        await connection.execute(insert(ManagedKnowledgeTask).values(**other_task.model_dump()))
        other_retry_operation = ManagedKnowledgeOperationRecord.model_validate(
            operation_payload(
                operation_id="OP-" + "5" * 32,
                revision_no=2,
                action="RETRY_INDEX",
                idempotency_key="retry-revision-2",
                confirmation_snapshot=confirmation_payload(
                    revision_no=2,
                    action="RETRY_INDEX",
                    normalized_hash="b" * 64,
                    task_id=other_task.task_id,
                ),
            )
        )
        await connection.execute(
            insert(ManagedKnowledgeOperation).values(
                **other_retry_operation.model_dump(),
            )
        )
    for target in ("TASK-" + "9" * 32, other_task.task_id):
        with pytest.raises(IntegrityError, match="fk_mkt_retry"):
            async with managed_database.engine.begin() as connection:
                await connection.execute(
                    update(ManagedKnowledgeTask)
                    .where(
                        ManagedKnowledgeTask.task_id == retry_task_id,
                    )
                    .values(retry_of_task_id=target)
                )
    with pytest.raises(IntegrityError, match="fk_mkt_operation"):
        async with managed_database.engine.begin() as connection:
            await connection.execute(
                update(ManagedKnowledgeTask)
                .where(
                    ManagedKnowledgeTask.task_id == retry_task_id,
                )
                .values(operation_id=other_retry_operation.operation_id)
            )
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(
                select(ManagedKnowledgeTask.state).where(
                    ManagedKnowledgeTask.task_id == index_task_id,
                )
            )
        ).scalar_one() == "FAILED"


@pytest.mark.integration
async def test_managed_knowledge_downgrade_preserves_drafts_and_refuses_sealed_versions(
    managed_database: Database,
) -> None:
    await _seed_processing(managed_database)
    url = managed_database.engine.url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    _alembic(url, "downgrade", "0015_managed_knowledge_drafts")
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(
                text("SELECT current_revision_no FROM managed_knowledge_versions")
            )
        ).scalar_one() == 1
        assert (
            await connection.execute(text("SELECT body FROM knowledge_documents"))
        ).scalar_one() == "旧规范哨兵"
    _alembic(url, "upgrade", "head")
    async with managed_database.engine.begin() as connection:
        generation = ManagedKnowledgeGenerationRecord.model_validate(generation_payload())
        await connection.execute(
            insert(ManagedKnowledgeIndexGeneration).values(**generation.model_dump())
        )
    await _publish_fixture(managed_database)
    with pytest.raises(subprocess.CalledProcessError):
        _alembic(url, "downgrade", "0015_managed_knowledge_drafts")
    async with managed_database.engine.connect() as connection:
        assert (
            await connection.execute(select(ManagedKnowledgeVersion.publication_state))
        ).scalar_one() == "PUBLISHED"
        assert (
            await connection.execute(text("SELECT version_num FROM agent_alembic_version"))
        ).scalar_one() == "0016_managed_knowledge_state"


@pytest.mark.integration
@pytest.mark.parametrize("resource", ["OPERATION", "TASK"])
async def test_managed_knowledge_concurrent_idempotency_and_active_task_have_one_winner(
    managed_database: Database,
    resource: str,
) -> None:
    await _seed_draft(managed_database)
    operations = [
        ManagedKnowledgeOperationRecord.model_validate(
            operation_payload(
                operation_id="OP-" + digit * 32,
                idempotency_key=f"upload-{digit}",
            )
        )
        for digit in ("2", "3")
    ]
    if resource == "TASK":
        async with managed_database.engine.begin() as connection:
            for operation in operations:
                await connection.execute(
                    insert(ManagedKnowledgeOperation).values(**operation.model_dump())
                )
    async with (
        managed_database.engine.connect() as first,
        managed_database.engine.connect() as second,
    ):
        if resource == "OPERATION":
            first_statement = insert(ManagedKnowledgeOperation).values(**operations[0].model_dump())
            second_statement = insert(ManagedKnowledgeOperation).values(
                **{
                    **operations[1].model_dump(),
                    "idempotency_key": operations[0].idempotency_key,
                }
            )
            expected = "uq_mko_idempotency"
        else:
            tasks = [
                ManagedKnowledgeTaskRecord.model_validate(
                    task_payload(
                        task_id="TASK-" + digit * 32,
                        operation_id=operation.operation_id,
                    )
                )
                for digit, operation in zip(("2", "3"), operations, strict=True)
            ]
            first_statement = insert(ManagedKnowledgeTask).values(**tasks[0].model_dump())
            second_statement = insert(ManagedKnowledgeTask).values(**tasks[1].model_dump())
            expected = "uq_mkt_active"
        await first.execute(first_statement)
        pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        pending = asyncio.create_task(second.execute(second_statement))
        try:
            await _wait_for_lock(managed_database, pid)
            await first.commit()
            with pytest.raises(IntegrityError, match=expected):
                await asyncio.wait_for(pending, timeout=5)
            await second.rollback()
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
