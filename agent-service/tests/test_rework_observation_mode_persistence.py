"""T830双向装配隔离，真实Agent隔离库与HTTP Mock，不冒充Java联调。"""

import asyncio

import pytest
from sqlalchemy import delete, select, update

from app.database import Database
from app.models import AgentRun, AgentRunStatus, ReworkConfirmationRecord, ReworkOperationLog
from app.services.rework_confirmation import ReworkConfirmationService
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from app.services.rework_observation_mode import ReworkObservationModeError
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_rework_confirmation_persistence import seed
from tests.test_rework_confirmation_persistence import service as legacy_confirmation
from tests.test_rework_draft_workflow import command, context
from tests.test_rework_execution_persistence import ExecutionHarness
from tests.test_rework_observability_persistence import observed, prepare, records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def capture(database: Database) -> dict[str, object]:
    """比较误装配前后状态和观测记录，不从服务返回值反推零写入。"""

    run, steps, logs = await records(database)
    async with database.session() as session:
        approvals = list(
            (
                await session.scalars(
                    select(ReworkConfirmationRecord)
                    .order_by(ReworkConfirmationRecord.approval_id)
                )
            ).all()
        )
    return {
        "run": (
            run.status, run.final_result, run.started_at, run.finished_at,
            run.updated_at, run.error_code, run.error_step, run.tool_call_count,
        ),
        "approvals": [
            (row.approval_id, row.status, row.revision, row.execution_key, row.snapshot)
            for row in approvals
        ],
        "steps": [
            (row.step_id, row.status, row.output_summary, row.error_code, row.finished_at)
            for row in steps
        ],
        "logs": [(row.approval_id, row.revision, row.phase, row.summary) for row in logs],
    }


@pytest.mark.parametrize("action", [
    "confirm", "cancel", "execute", "raw_transition", "raw_claim", "second_create",
    "completed_execute",
])
async def test_rework_observation_mode_legacy_entry_cannot_bypass_observed_approval(
    migrated_database_url: str, action: str
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        owner = observed(database, h)
        waiting = action in {"confirm", "cancel", "raw_transition", "second_create"}
        await prepare(owner, h, confirm=not waiting)
        if action == "completed_execute":
            assert (await owner.execute({"approval_id": "approval-t830"})).outcome == "SUCCEEDED"
        before = await capture(database)
        writes, lookups = len(h.writes), len(h.lookups)
        legacy = legacy_confirmation(database, h, "approval-legacy-other")
        with pytest.raises(ReworkObservationModeError):
            if action == "confirm":
                await legacy.confirm(h.request(), context=context())
            elif action == "cancel":
                await legacy.cancel("approval-t830", context=context())
            elif action == "raw_transition":
                assert h.snapshot is not None
                updated = ReworkConfirmationService._updated(h.snapshot, "CANCELLED", now=h.now)
                await DatabaseReworkConfirmationStore(database, now=lambda: h.now).transition(
                    h.snapshot, updated, context=context(), now=h.now
                )
            elif action == "raw_claim":
                assert h.snapshot is not None
                await h.executor(database).store.claim(h.snapshot)
            elif action == "second_create":
                await legacy.create(command(h.case), context=context())
            else:
                await h.executor(database).execute({"approval_id": "approval-t830"})
        assert await capture(database) == before
        assert (len(h.writes), len(h.lookups)) == (writes, lookups)
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("stage", ["WAITING", "CONFIRMED", "SUCCEEDED"])
async def test_rework_observation_mode_observed_entry_does_not_take_over_legacy_run(
    migrated_database_url: str, stage: str
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        legacy = legacy_confirmation(database, h, "approval-legacy")
        h.snapshot = await legacy.create(command(h.case), context=context())
        if stage != "WAITING":
            h.snapshot = await legacy.confirm(h.request(), context=context())
        if stage == "SUCCEEDED":
            result = await h.executor(database).execute({"approval_id": "approval-legacy"})
            assert result.outcome == "SUCCEEDED"
        before, calls = await capture(database), (len(h.calls), len(h.writes), len(h.lookups))
        with pytest.raises(ReworkObservationModeError):
            await observed(database, h).execute({"approval_id": "approval-legacy"})
        assert await capture(database) == before
        assert (len(h.calls), len(h.writes), len(h.lookups)) == calls
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("missing", ["audit", "marker", "binding"])
async def test_rework_observation_mode_missing_evidence_never_enables_fallback(
    migrated_database_url: str, missing: str
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        await prepare(observed(database, h), h)
        async with database.session() as session, session.begin():
            if missing == "audit":
                await session.execute(delete(ReworkOperationLog))
            else:
                marker = None if missing == "marker" else {
                    "kind": "REWORK_APPROVAL", "approval_id": "approval-other"
                }
                await session.execute(update(AgentRun).where(
                    AgentRun.run_id == context().run_id
                ).values(final_result=marker))
        before, calls = await capture(database), len(h.calls)
        for entry in (observed(database, h), h.executor(database)):
            with pytest.raises(ReworkObservationModeError):
                await entry.execute({"approval_id": "approval-t830"})
        assert await capture(database) == before
        assert len(h.calls) == calls and not h.writes and not h.lookups
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observation_mode_unknown_only_recovers_through_original_mode(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        owner = observed(database, h)
        await prepare(owner, h)
        h.lose_response = True
        value = {"approval_id": "approval-t830"}
        assert (await owner.execute(value)).outcome == "UNKNOWN"
        before = await capture(database)
        with pytest.raises(ReworkObservationModeError):
            await h.executor(database).reconcile(value)
        assert await capture(database) == before and not h.lookups
        recovered = await observed(database, h).reconcile(value)
        assert recovered.outcome == "SUCCEEDED" and recovered.receipt_evidence is not None
        assert recovered.receipt_evidence.source == "LOOKUP"
        assert len(h.writes) == len(h.lookups) == 1
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observation_mode_concurrent_legacy_entry_cannot_consume_another_permit(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    task = None
    try:
        await seed(database, now=h.now)
        owner = observed(database, h)
        await prepare(owner, h)
        h.pause = True
        value = {"approval_id": "approval-t830"}
        task = asyncio.create_task(owner.execute(value))
        await asyncio.wait_for(h.entered.wait(), timeout=5)
        before = await capture(database)
        with pytest.raises(ReworkObservationModeError):
            await h.executor(database).execute(value)
        assert await capture(database) == before and len(h.writes) == 1
        h.release.set()
        assert (await task).outcome == "SUCCEEDED"
        run, _, logs = await records(database)
        assert run.status == AgentRunStatus.SUCCEEDED and len(h.writes) == 1
        assert [row.revision for row in logs] == list(range(5))
    finally:
        h.release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await h.shared.aclose()
        await h.close()
        await database.dispose()
