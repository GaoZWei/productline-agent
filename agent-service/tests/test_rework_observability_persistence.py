"""T830真实Agent数据库与HTTP Mock边界，未把Mock回执当作真实Java联调。"""

import asyncio
import json
import subprocess
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.errors import ToolErrorCode, ToolException
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    ReworkConfirmationRecord,
    ReworkOperationLog,
)
from app.schemas.events import RunEventType
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.services.observed_rework import ObservedReworkService
from app.services.rework_confirmation import ReworkConfirmationError
from app.tools.models import ToolContext
from tests.integration.tools.test_rework_write_tools import CASES, Case
from tests.test_agent_persistence import _run_alembic
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_rework_confirmation_persistence import seed
from tests.test_rework_draft_workflow import command, context, nested
from tests.test_rework_execution_persistence import ExecutionHarness
from tests.test_rework_observability import CancellingEventSink, EventSink

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def observed(
    database: Database, h: ExecutionHarness, sink: EventSink | None = None
) -> ObservedReworkService:
    """仅在测试显式内部装配，不修改生产依赖。"""

    return ObservedReworkService(
        database,
        h.http,
        context=context(),
        event_sink=sink,
        now=lambda: h.now,
        approval_id_factory=lambda: "approval-t830",
    )


async def prepare(
    service: ObservedReworkService, h: ExecutionHarness, *, confirm: bool = True
) -> None:
    """所有快照经真实Tool、确认Store和观察事务产生。"""

    h.snapshot = await service.create(command(h.case))
    if confirm:
        h.snapshot = await service.confirm(h.request())


async def records(
    database: Database,
) -> tuple[AgentRun, list[AgentStep], list[ReworkOperationLog]]:
    """返回真实持久化结果用于外部断言，不从被测事件反推状态。"""

    async with database.session() as session:
        run = await session.get(AgentRun, context().run_id)
        assert run is not None
        steps = list((await session.scalars(
            select(AgentStep).where(AgentStep.run_id == run.run_id)
            .order_by(AgentStep.sequence_number)
        )).all())
        logs = list((await session.scalars(
            select(ReworkOperationLog).where(ReworkOperationLog.run_id == run.run_id)
            .order_by(ReworkOperationLog.revision)
        )).all())
        return run, steps, logs


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.operation)
async def test_rework_observability_nine_actions_separate_wait_and_execution(
    migrated_database_url: str, case: Case
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(case), EventSink()
    try:
        await seed(database, now=h.now)
        service = observed(database, h, sink)
        await prepare(service, h, confirm=False)
        run, _, _ = await records(database)
        assert run.status == AgentRunStatus.WAITING_APPROVAL and not h.writes
        h.now += timedelta(seconds=50)
        await service.confirm(h.request())
        run, _, _ = await records(database)
        assert run.status == AgentRunStatus.WAITING_APPROVAL and not h.writes
        h.now += timedelta(seconds=3)
        result = await service.execute({"approval_id": "approval-t830"})
        assert result.outcome == "SUCCEEDED"
        repeated = await observed(database, h).execute({"approval_id": "approval-t830"})
        assert repeated == result and len(h.writes) == 1
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.SUCCEEDED and run.finished_at == h.now
        waiting = [step for step in steps if step.step_type == AgentStepType.APPROVAL]
        writing = [step for step in steps if step.step_type == AgentStepType.WRITEBACK]
        assert len(waiting) == len(writing) == 1
        assert waiting[0].duration_ms == 50_000 and writing[0].duration_ms == 0
        assert waiting[0].status == writing[0].status == AgentStepStatus.SUCCEEDED
        assert [log.phase for log in logs] == [
            "WAITING_CONFIRMATION", "CONFIRMED", "CLAIMED", "SUBMITTING", "SUCCEEDED"
        ]
        assert [log.revision for log in logs] == list(range(5))
        assert run.tool_call_count == len(h.calls) + len(h.writes) + len(h.lookups)
        encoded = json.dumps([log.summary for log in logs], ensure_ascii=False)
        for forbidden in ("execution_key", "request", "evidence_references", "reviewer-test"):
            assert forbidden not in encoded
        assert sink.events[-1][0] == RunEventType.RUN_COMPLETED
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_unconfirmed_and_cancelled_never_write(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        service = observed(database, h)
        await prepare(service, h, confirm=False)
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_WAITING_CONFIRMATION"):
            await service.execute({"approval_id": "approval-t830"})
        assert (await records(database))[0].status == AgentRunStatus.WAITING_APPROVAL
        await service.cancel("approval-t830")
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.CANCELLED and not h.writes
        assert logs[-1].phase == "CANCELLED"
        assert any(step.error_code == "APPROVAL_WAITING_CONFIRMATION" for step in steps)
        assert not any(step.step_type == AgentStepType.WRITEBACK for step in steps)
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("cancel", [False, True], ids=["lost-response", "cancelled-call"])
async def test_rework_observability_unknown_survives_restart_and_only_queries_original_key(
    migrated_database_url: str, cancel: bool
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    task = None
    try:
        await seed(database, now=h.now)
        service = observed(database, h, sink)
        await prepare(service, h)
        value = {"approval_id": "approval-t830"}
        if cancel:
            h.pause = True
            task = asyncio.create_task(service.execute(value))
            await asyncio.wait_for(h.entered.wait(), timeout=5)
            assert any(data.get("phase") == "SUBMITTING" for _, data in sink.events)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            h.lose_response = True
            assert (await service.execute(value)).outcome == "UNKNOWN"
        run, steps, _ = await records(database)
        assert run.status == AgentRunStatus.RUNNING and run.finished_at is None
        write_step = next(step for step in steps if step.step_type == AgentStepType.WRITEBACK)
        assert write_step.status == AgentStepStatus.RUNNING and write_step.finished_at is None
        service = observed(database, h)
        h.found = False
        assert (await service.reconcile(value)).outcome == "UNKNOWN"
        assert (await records(database))[0].status == AgentRunStatus.RUNNING
        h.found = True
        result = await service.reconcile(value)
        assert result.outcome == "SUCCEEDED" and result.receipt_evidence is not None
        assert result.receipt_evidence.source == "LOOKUP"
        assert result.receipt_evidence.write_java_trace_id is None
        assert len(h.writes) == 1 and len(h.lookups) == 2
        run, _, logs = await records(database)
        assert run.status == AgentRunStatus.SUCCEEDED
        assert logs[-1].summary["write_java_trace_id"] is None
        assert logs[-1].summary["lookup_java_trace_id"] is not None
    finally:
        h.release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_concurrent_execution_and_broken_sink_never_resubmit(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    task = None
    try:
        await seed(database, now=h.now)
        service = observed(database, h, EventSink(broken=True))
        await prepare(service, h)
        h.pause = True
        value = {"approval_id": "approval-t830"}
        task = asyncio.create_task(service.execute(value))
        await asyncio.wait_for(h.entered.wait(), timeout=5)
        assert (await observed(database, h).execute(value)).outcome == "IN_PROGRESS"
        h.release.set()
        assert (await task).outcome == "SUCCEEDED"
        _, _, logs = await records(database)
        assert len(h.writes) == 1
        assert len([log for log in logs if log.phase == "SUCCEEDED"]) == 1
        sink = EventSink()
        await observed(database, h, sink).publish_progress(after_revision=1)
        assert [data["revision"] for kind, data in sink.events
                if kind == RunEventType.REWORK_PROGRESS] == [2, 3, 4]
        assert sink.events[-1][0] == RunEventType.RUN_COMPLETED
    finally:
        h.release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("expired", [False, True], ids=["changed-facts", "expired"])
@pytest.mark.parametrize("after_confirm", [False, True], ids=["before-confirm", "before-execute"])
async def test_rework_observability_stale_or_expired_confirmation_is_terminal_without_write(
    migrated_database_url: str, expired: bool, after_confirm: bool
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        service = observed(database, h)
        await prepare(service, h, confirm=after_confirm)
        if expired:
            h.now += timedelta(seconds=600)
        else:
            h.data[0]["version"] = 5
            nested(h.data[1], "tasks", 0)["taskVersion"] = 5
        code = "APPROVAL_EXPIRED" if expired else "APPROVAL_STALE"
        with pytest.raises(ReworkConfirmationError, match=code):
            if after_confirm:
                await service.execute({"approval_id": "approval-t830"})
            else:
                await service.confirm(h.request())
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.FAILED and run.error_code == code
        assert logs[-1].phase == ("EXPIRED" if expired else "STALE")
        if after_confirm:
            waiting = next(step for step in steps if step.step_type == AgentStepType.APPROVAL)
            invalidation = next(step for step in steps if step.step_name == "rework_invalidation")
            assert waiting.status == AgentStepStatus.SUCCEEDED
            assert invalidation.status == AgentStepStatus.FAILED
        assert not h.writes
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_state_audit_and_steps_roll_back_together(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        service = observed(database, h)
        original = service._observer.record

        async def fail_after_record(
            session: AsyncSession, snapshot: ReworkConfirmationSnapshot, *, now: datetime
        ) -> None:
            """在真实观察修改之后制造故障，证明事务不会留下半份状态。"""

            await original(session, snapshot, now=now)
            raise RuntimeError("private-database-error")

        monkeypatch.setattr(service._observer, "record", AsyncMock(side_effect=fail_after_record))
        with pytest.raises(RuntimeError, match="private-database-error"):
            await service.create(command(h.case))
        run, steps, logs = await records(database)
        assert not logs and run.status == AgentRunStatus.FAILED
        assert len(steps) == 1 and steps[0].error_code == "INTERNAL_ERROR"
        async with database.session() as session:
            assert await session.get(ReworkConfirmationRecord, "approval-t830") is None
        assert not h.writes
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_preparation_failure_preserves_safe_upstream_code(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        service = observed(database, h, sink)
        failure = ToolException(
            code=ToolErrorCode.TOOL_TIMEOUT,
            message="private-upstream-evidence",
            retryable=False,
        )
        monkeypatch.setattr(
            service._confirmation._workflow, "ainvoke", AsyncMock(side_effect=failure)
        )
        with pytest.raises(ToolException):
            await service.create(command(h.case))
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.FAILED and run.error_code == "TOOL_TIMEOUT"
        assert len(steps) == 1 and steps[0].error_code == "TOOL_TIMEOUT"
        assert not logs and not h.writes
        assert "private-upstream-evidence" not in json.dumps(sink.events)
        assert sink.events[-1][0] == RunEventType.RUN_FAILED
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_replay_and_execution_respect_trusted_permissions(
    migrated_database_url: str,
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        await prepare(observed(database, h), h)
        restricted = ObservedReworkService(
            database, h.http, context=context(frozenset({"TASK_READ"})),
            event_sink=sink, now=lambda: h.now,
        )
        await restricted.publish_progress()
        with pytest.raises(ReworkConfirmationError, match="PERMISSION_DENIED"):
            await restricted.execute({"approval_id": "approval-t830"})
        assert not sink.events and not h.writes
        run, _, logs = await records(database)
        assert run.status == AgentRunStatus.WAITING_APPROVAL and logs[-1].phase == "CONFIRMED"
        wrong_owner = ToolContext.model_validate({
            **context().model_dump(), "identity": {"user_id": "other-user", "role": "REVIEWER"}
        })
        other = ObservedReworkService(
            database, h.http, context=wrong_owner, event_sink=sink, now=lambda: h.now
        )
        await other.publish_progress()
        with pytest.raises(ReworkConfirmationError, match="RESOURCE_NOT_FOUND"):
            await other.execute({"approval_id": "approval-t830"})
        assert not sink.events and not h.writes
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("change", [
    "extra_material", "approval_binding", "revision_binding", "operation_binding",
    "phase_binding", "history_gap", "receipt_trace", "receipt_identity", "run_status",
])
async def test_rework_observability_corrupt_replay_emits_nothing_even_behind_cursor(
    migrated_database_url: str, change: str
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        service = observed(database, h)
        await prepare(service, h)
        await service.execute({"approval_id": "approval-t830"})
        _, _, logs = await records(database)
        target = logs[4] if change.startswith("receipt_") else logs[1]
        summary = dict(target.summary)
        async with database.session() as session, session.begin():
            approval = await session.get(ReworkConfirmationRecord, "approval-t830")
            assert approval is not None
            original = approval.snapshot
            if change == "history_gap":
                await session.execute(delete(ReworkOperationLog).where(
                    ReworkOperationLog.approval_id == target.approval_id,
                    ReworkOperationLog.revision == target.revision,
                ))
            elif change == "run_status":
                await session.execute(update(AgentRun).where(
                    AgentRun.run_id == context().run_id
                ).values(status=AgentRunStatus.FAILED))
            elif change == "phase_binding":
                await session.execute(update(ReworkOperationLog).where(
                    ReworkOperationLog.approval_id == target.approval_id,
                    ReworkOperationLog.revision == target.revision,
                ).values(phase="CLAIMED"))
            else:
                if change == "extra_material":
                    summary["processing_comment"] = "private-replay-material"
                elif change == "approval_binding":
                    summary["approval_id"] = "approval-other"
                elif change == "revision_binding":
                    summary["revision"] = 0
                elif change == "operation_binding":
                    summary["operation"] = "FAIL_REWORK"
                elif change == "receipt_trace":
                    summary["lookup_java_trace_id"] = "invented-lookup-trace"
                else:
                    summary["receipt_operation_id"] = "OP-OTHER"
                await session.execute(update(ReworkOperationLog).where(
                    ReworkOperationLog.approval_id == target.approval_id,
                    ReworkOperationLog.revision == target.revision,
                ).values(summary=summary))
        counts = len(h.calls), len(h.writes), len(h.lookups)
        with pytest.raises(ReworkConfirmationError) as caught:
            await observed(database, h, sink).publish_progress(after_revision=4)
        assert caught.value.code == "REWORK_AUDIT_INVALID" and caught.value.status_code == 500
        assert "private-replay-material" not in str(caught.value)
        assert not sink.events and counts == (len(h.calls), len(h.writes), len(h.lookups))
        async with database.session() as session:
            approval = await session.get(ReworkConfirmationRecord, "approval-t830")
            assert approval is not None and approval.snapshot == original
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("cursor", [-2, True, "0", 1.0, 9007199254740992, 100])
async def test_rework_observability_replay_rejects_invalid_or_future_cursor(
    migrated_database_url: str, cursor: object
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        await prepare(observed(database, h), h, confirm=False)
        with pytest.raises(ReworkConfirmationError) as caught:
            await observed(database, h, sink).publish_progress(after_revision=cast(int, cursor))
        assert caught.value.code == "PARAM_VALIDATION_ERROR" and caught.value.status_code == 400
        assert not sink.events and not h.writes
        assert (await records(database))[0].status == AgentRunStatus.WAITING_APPROVAL
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_terminal_replay_uses_confirmed_fact_not_raw_run_error(
    migrated_database_url: str,
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        service = observed(database, h)
        await prepare(service, h)
        await service.execute({"approval_id": "approval-t830"})
        async with database.session() as session, session.begin():
            await session.execute(update(AgentRun).where(
                AgentRun.run_id == context().run_id
            ).values(error_code="private-run-error"))
        counts = len(h.calls), len(h.writes), len(h.lookups)
        await observed(database, h, sink).publish_progress(after_revision=3)
        assert len(sink.events) == 2 and sink.events[-1] == (
            RunEventType.RUN_COMPLETED, {"status": "SUCCEEDED", "error_code": None}
        )
        assert "private-run-error" not in json.dumps(sink.events)
        assert counts == (len(h.calls), len(h.writes), len(h.lookups))
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_unrelated_terminal_run_does_not_emit_rework_event(
    migrated_database_url: str,
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        async with database.session() as session, session.begin():
            await session.execute(update(AgentRun).where(
                AgentRun.run_id == context().run_id
            ).values(status=AgentRunStatus.FAILED, error_code="private-run-error"))
        await observed(database, h, sink).publish_progress()
        assert not sink.events and not h.calls and not h.writes
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_preparation_replay_rejects_arbitrary_run_error(
    migrated_database_url: str,
) -> None:
    database, h, sink = Database(migrated_database_url), ExecutionHarness(), EventSink()
    try:
        await seed(database, now=h.now)
        with pytest.raises(ToolException):
            await observed(database, h).create({"operation": "UNKNOWN_OPERATION"})
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.FAILED and not logs
        async with database.session() as session, session.begin():
            await session.execute(update(AgentRun).where(
                AgentRun.run_id == run.run_id
            ).values(error_code="private-preparation-body"))
            await session.execute(update(AgentStep).where(
                AgentStep.step_id == steps[0].step_id
            ).values(error_code="private-preparation-body"))
        with pytest.raises(ReworkConfirmationError) as caught:
            await observed(database, h, sink).publish_progress()
        assert caught.value.code == "REWORK_AUDIT_INVALID"
        assert "private-preparation-body" not in str(caught.value)
        assert not sink.events and not h.calls and not h.writes
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("terminal_only", [False, True], ids=["all-notifications", "terminal"])
async def test_rework_observability_notification_cancellation_keeps_saved_success(
    migrated_database_url: str, terminal_only: bool, caplog: pytest.LogCaptureFixture
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    sink = CancellingEventSink(RunEventType.RUN_COMPLETED if terminal_only else None)
    try:
        await seed(database, now=h.now)
        service = observed(database, h, sink)
        await prepare(service, h)
        value = {"approval_id": "approval-t830"}
        result = await service.execute(value)
        assert result.outcome == "SUCCEEDED" and result.receipt_evidence is not None
        assert await service.execute(value) == result and len(h.writes) == 1
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.SUCCEEDED and run.error_code is None
        assert all(step.status == AgentStepStatus.SUCCEEDED for step in steps)
        assert [log.revision for log in logs] == list(range(5))
        assert RunEventType.RUN_COMPLETED in sink.cancelled_types
        assert "private-notification-cancel" not in caplog.text
        task = asyncio.current_task()
        assert task is not None and task.cancelling() == 0
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_notification_cancellation_keeps_original_failure(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    sink = CancellingEventSink(RunEventType.RUN_FAILED)
    try:
        await seed(database, now=h.now)
        service = observed(database, h, sink)
        failure = ToolException(
            code=ToolErrorCode.TOOL_TIMEOUT, message="private-upstream-body", retryable=False
        )
        monkeypatch.setattr(
            service._confirmation._workflow, "ainvoke", AsyncMock(side_effect=failure)
        )
        with pytest.raises(ToolException) as caught:
            await service.create(command(h.case))
        assert caught.value is failure
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.FAILED and run.error_code == "TOOL_TIMEOUT"
        assert len(steps) == 1 and steps[0].error_code == "TOOL_TIMEOUT" and not logs
        assert sink.cancelled_types == [RunEventType.RUN_FAILED] and not h.writes
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_real_cancellation_after_receipt_preserves_evidence(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    entered, release = asyncio.Event(), asyncio.Event()
    task = None

    class BlockingTerminalSink(EventSink):
        """只阻塞已保存回执后的终态通知，不阻塞业务执行。"""

        async def publish(
            self,
            event_type: RunEventType,
            *,
            run_id: str | None = None,
            step_id: str | None = None,
            data: Mapping[str, JsonValue] | None = None,
        ) -> None:
            """在外层调用者取消时允许发送Task正常退出。"""

            if event_type == RunEventType.RUN_COMPLETED:
                entered.set()
                await release.wait()
            await super().publish(event_type, run_id=run_id, step_id=step_id, data=data)

    try:
        await seed(database, now=h.now)
        service = observed(database, h, BlockingTerminalSink())
        await prepare(service, h)
        value = {"approval_id": "approval-t830"}
        task = asyncio.create_task(service.execute(value))
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        run, steps, logs = await records(database)
        assert run.status == AgentRunStatus.SUCCEEDED and logs[-1].phase == "SUCCEEDED"
        assert all(step.status == AgentStepStatus.SUCCEEDED for step in steps)
        recovered = await observed(database, h).execute(value)
        assert recovered.outcome == "SUCCEEDED" and recovered.receipt_evidence is not None
        assert recovered.receipt_evidence.source == "WRITE"
        assert len(h.writes) == 1 and not h.lookups
    finally:
        release.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await h.shared.aclose()
        await h.close()
        await database.dispose()


async def test_rework_observability_migration_matches_metadata_and_preserves_audit(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        url = database.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
        _run_alembic(url, "check")
        await prepare(observed(database, h), h, confirm=False)
        with pytest.raises(subprocess.CalledProcessError) as caught:
            _run_alembic(url, "downgrade", "0018_rework_execution")
        assert "cannot downgrade persisted rework operation logs" in (
            caught.value.stdout + caught.value.stderr
        )
        assert (await records(database))[2][0].phase == "WAITING_CONFIRMATION"
    finally:
        await h.shared.aclose()
        await h.close()
        await database.dispose()
