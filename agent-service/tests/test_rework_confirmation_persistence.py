"""T828真实迁移和隔离PostgreSQL确认持久化，Java读仍使用明确MockTransport。"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.database import Database
from app.models import AgentRun, AgentRunStatus, AgentSession, ReworkConfirmationRecord
from app.services.rework_confirmation import ReworkConfirmationError, ReworkConfirmationService
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from tests.integration.tools.test_rework_write_tools import CASES
from tests.test_agent_persistence import _run_alembic
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_rework_confirmation import NOW, Harness
from tests.test_rework_draft_workflow import command, context, workflow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def seed(database: Database) -> None:
    """只向本次隔离Agent库准备真实用户/Run关系，不触碰Java业务表。"""

    async with database.session() as session, session.begin():
        agent_session = AgentSession(
            session_id="session-t828", user_id="reviewer-test", expires_at=NOW + timedelta(days=1)
        )
        session.add(agent_session)
        await session.flush()
        session.add(
            AgentRun(
                run_id=context().run_id,
                session_id=agent_session.session_id,
                status=AgentRunStatus.RUNNING,
                version_snapshot={},
            )
        )


def service(
    database: Database, harness: Harness, identity: str = "approval-t828"
) -> ReworkConfirmationService:
    """使用可重新创建的真实Store，确保不依赖内存确认记录。"""

    return ReworkConfirmationService(
        store=DatabaseReworkConfirmationStore(database, now=lambda: harness.now),
        workflow=workflow(harness.shared),
        now=lambda: harness.now,
        approval_id_factory=lambda: identity,
    )


async def test_rework_confirmation_migration_matches_metadata_and_roundtrips(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        await seed(database)
        url = database.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
        _run_alembic(url, "check")
        _run_alembic(url, "downgrade", "0016_managed_knowledge_state")
        async with database.session() as session:
            assert (
                await session.scalar(text("SELECT to_regclass('rework_confirmation_records')"))
                is None
            )
            assert await session.scalar(select(AgentRun.run_id)) == context().run_id
        _run_alembic(url, "upgrade", "head")
        _run_alembic(url, "check")
    finally:
        await database.dispose()


async def test_rework_confirmation_nine_actions_survive_store_recreation(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        await seed(database)
        for index, case in enumerate(CASES):
            h = Harness(case)
            try:
                original = await service(database, h, f"approval-t828-{index}").create(
                    command(case), context=context()
                )
                h.snapshot = original
                result = await service(database, h).confirm(h.request(), context=context())
                assert result.status == "CONFIRMED" and result.prepared == original.prepared
                stored = await DatabaseReworkConfirmationStore(database).get(
                    original.approval_id, context=context(), now=NOW
                )
                assert stored == result
                with pytest.raises(ReworkConfirmationError):
                    await service(database, h).confirm(h.request(), context=context())
            finally:
                await h.shared.aclose()
        async with database.session() as session:
            rows = (await session.scalars(select(ReworkConfirmationRecord))).all()
            assert len(rows) == 9 and {row.status for row in rows} == {"CONFIRMED"}
    finally:
        await database.dispose()


async def test_rework_confirmation_full_snapshot_cas_and_terminal_constraints(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), Harness()
    try:
        await seed(database)
        original = await service(database, h).create(command(h.case), context=context())
        store = DatabaseReworkConfirmationStore(database, now=lambda: h.now)
        confirmed = h.service._updated(
            original, "CONFIRMED", draft=original.prepared.review.draft, now=NOW
        )
        cancelled = h.service._updated(original, "CANCELLED")
        outcomes = await asyncio.gather(
            store.transition(original, confirmed, context=context(), now=NOW),
            store.transition(original, cancelled, context=context(), now=NOW),
        )
        assert sorted(outcomes) == [False, True]
        final = await store.get(original.approval_id, context=context(), now=NOW)
        assert final in (confirmed, cancelled)
        assert not await store.transition(original, cancelled, context=context(), now=NOW)
        async with database.session() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    await session.execute(
                        update(ReworkConfirmationRecord).values(status="EXECUTING")
                    )
        # DB索引字段与JSON不一致时必须报错，不能从损坏状态恢复确认。
        async with database.session() as session, session.begin():
            await session.execute(update(ReworkConfirmationRecord).values(revision=3))
        with pytest.raises(ValueError):
            await store.get(original.approval_id, context=context(), now=NOW)
    finally:
        await h.shared.aclose()
        await database.dispose()


async def test_rework_confirmation_stale_and_store_deadline_are_persistent(
    migrated_database_url: str,
) -> None:
    from tests.test_rework_draft_workflow import nested

    database, h = Database(migrated_database_url), Harness(CASES[6])
    try:
        await seed(database)
        original = await service(database, h).create(command(h.case), context=context())
        h.snapshot = original
        nested(h.data[2], "processing", "artifact")["artifactVersion"] = "Release-Changed"
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_STALE"):
            await service(database, h).confirm(h.request(), context=context())
        store = DatabaseReworkConfirmationStore(database, now=lambda: h.now)
        stale = await store.get(original.approval_id, context=context(), now=NOW)
        assert stale is not None and stale.status == "STALE" and stale.prepared == original.prepared
        # 服务检查后、数据库取得行锁前到期，也必须拒绝保存CONFIRMED。
        pending = await service(database, h, "approval-t828-deadline").create(
            command(h.case), context=context()
        )
        confirmed = h.service._updated(
            pending, "CONFIRMED", draft=pending.prepared.review.draft, now=NOW
        )
        h.now = pending.expires_at
        assert not await store.transition(pending, confirmed, context=context(), now=NOW)
        stored = await store.get(pending.approval_id, context=context(), now=h.now)
        assert stored is not None and stored.status == "WAITING_CONFIRMATION"
    finally:
        await h.shared.aclose()
        await database.dispose()


async def test_rework_confirmation_expiry_cancel_and_session_revocation_persist(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), Harness()
    try:
        await seed(database)
        original = await service(database, h).create(command(h.case), context=context())
        h.snapshot = original
        h.now = original.expires_at
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_EXPIRED"):
            await service(database, h).confirm(h.request(), context=context())
        expired = await DatabaseReworkConfirmationStore(database).get(
            original.approval_id, context=context(), now=h.now
        )
        assert expired is not None and expired.status == "EXPIRED"
        h.now = NOW
        other = await service(database, h, "approval-t828-cancel").create(
            command(h.case), context=context()
        )
        result = await service(database, h).cancel(other.approval_id, context=context())
        assert result.status == "CANCELLED"
        pending = await service(database, h, "approval-t828-revoked").create(
            command(h.case), context=context()
        )
        async with database.session() as session, session.begin():
            await session.execute(update(AgentSession).values(expires_at=NOW))
        assert (
            await DatabaseReworkConfirmationStore(database).get(
                pending.approval_id, context=context(), now=NOW
            )
            is None
        )
        with pytest.raises(ReworkConfirmationError, match="RESOURCE_NOT_FOUND"):
            await service(database, h).cancel(pending.approval_id, context=context())
    finally:
        await h.shared.aclose()
        await database.dispose()
