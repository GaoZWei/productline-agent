"""返工事件白名单及通知故障隔离，不替代数据库与真实Java验收。"""

import asyncio
import json
from collections.abc import Mapping
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolErrorCode
from app.models import AgentRun, AgentRunStatus, ReworkOperationLog
from app.schemas.events import RunEventType
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_progress import ReworkProgressSummary
from app.services.rework_observation import (
    ReworkStateObserver,
    elapsed_ms,
    rework_summary,
    validated_rework_replay,
)
from app.services.rework_observation_mode import (
    ReworkObservationModeError,
    require_rework_creation_mode,
    require_rework_observation_mode,
)
from app.tools.models import ToolError
from tests.integration.tools.test_rework_write_tools import CASES, Case
from tests.test_rework_confirmation import NOW, Harness
from tests.test_rework_draft_workflow import context
from tests.test_rework_execution import claimed

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class EventSink:
    """只保存事件白名单，故障开关用于证明通知不会变成重发条件。"""

    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken
        self.events: list[tuple[RunEventType, dict[str, JsonValue]]] = []

    async def publish(
        self,
        event_type: RunEventType,
        *,
        run_id: str | None = None,
        step_id: str | None = None,
        data: Mapping[str, JsonValue] | None = None,
    ) -> None:
        """模拟发布失败，不允许把异常正文写回事件或业务状态。"""

        if self.broken:
            raise RuntimeError("private-sink-body")
        self.events.append((event_type, dict(data or {})))


class CancellingEventSink(EventSink):
    """模拟发送子任务自行取消，不能把通知故障冒充调用者取消。"""

    def __init__(self, event_type: RunEventType | None = None) -> None:
        super().__init__()
        self.event_type = event_type
        self.cancelled_types: list[RunEventType] = []

    async def publish(
        self,
        event_type: RunEventType,
        *,
        run_id: str | None = None,
        step_id: str | None = None,
        data: Mapping[str, JsonValue] | None = None,
    ) -> None:
        """取消当前发送Task，不记录取消正文，也不取消外层请求Task。"""

        if self.event_type is None or self.event_type == event_type:
            self.cancelled_types.append(event_type)
            task = asyncio.current_task()
            assert task is not None
            task.cancel("private-notification-cancel")
            await asyncio.sleep(0)
        await super().publish(event_type, run_id=run_id, step_id=step_id, data=data)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.operation)
async def test_rework_observability_summary_uses_only_allowed_fields(case: Case) -> None:
    h = Harness(case)
    try:
        waiting = await h.create()
        confirmed = await h.service.confirm(h.request(), context=context())
        executing = claimed(confirmed)
        for snapshot in (waiting, confirmed, executing):
            summary = rework_summary(snapshot)
            assert set(summary) == {
                "approval_id",
                "revision",
                "operation",
                "status",
                "phase",
                "error_code",
            }
            assert summary["operation"] == case.operation
            encoded = json.dumps(summary)
            assert "request" not in encoded and "evidence" not in encoded
            assert "execution_key" not in encoded and "reviewer-test" not in encoded
        assert rework_summary(executing)["phase"] == "CLAIMED"
        assert elapsed_ms(NOW, NOW - timedelta(seconds=1)) == 0
    finally:
        await h.shared.aclose()


async def test_rework_observability_sink_failure_does_not_change_snapshot() -> None:
    h = Harness()
    try:
        snapshot = await h.create()
        original = snapshot.model_dump_json()
        await ReworkStateObserver(EventSink(broken=True)).publish(snapshot)
        assert snapshot.model_dump_json() == original
    finally:
        await h.shared.aclose()


async def test_rework_observability_sender_cancellation_does_not_cancel_owner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h, sink = Harness(), CancellingEventSink()
    try:
        snapshot = await h.create()
        original = snapshot.model_dump_json()
        await ReworkStateObserver(sink).publish(snapshot)
        assert snapshot.model_dump_json() == original
        assert sink.cancelled_types == [RunEventType.REWORK_PROGRESS] and not sink.events
        task = asyncio.current_task()
        assert task is not None and task.cancelling() == 0
        assert "private-notification-cancel" not in caplog.text
    finally:
        await h.shared.aclose()


async def test_rework_observability_real_owner_cancellation_is_not_swallowed() -> None:
    h = Harness()
    entered, release = asyncio.Event(), asyncio.Event()
    sender: asyncio.Task[None] | None = None
    owner: asyncio.Task[None] | None = None

    class BlockingSink(EventSink):
        """发送中等待外部信号，以便在真实请求Task上触发取消。"""

        async def publish(
            self,
            event_type: RunEventType,
            *,
            run_id: str | None = None,
            step_id: str | None = None,
            data: Mapping[str, JsonValue] | None = None,
        ) -> None:
            """保留发送Task用于检查取消后已结束，不遗留后台通知。"""

            nonlocal sender
            sender = asyncio.current_task()
            entered.set()
            await release.wait()

    try:
        snapshot = await h.create()
        owner = asyncio.create_task(ReworkStateObserver(BlockingSink()).publish(snapshot))
        await asyncio.wait_for(entered.wait(), timeout=5)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert owner.cancelled() and sender is not None and sender.done()
        assert sender is not owner
    finally:
        release.set()
        if owner is not None:
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        await h.shared.aclose()


async def test_rework_observability_projection_failure_does_not_escape_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h, sink = Harness(), EventSink()
    try:
        snapshot = await h.create()

        def fail_summary(value: ReworkConfirmationSnapshot) -> dict[str, str | int | None]:
            """模拟通知投影故障，不能向调用者传播内部材料。"""

            raise ValueError("private-projection-body")

        monkeypatch.setattr("app.services.rework_observation.rework_summary", fail_summary)
        await ReworkStateObserver(sink).publish(snapshot)
        assert not sink.events
    finally:
        await h.shared.aclose()


async def test_rework_observability_unknown_drops_error_body_and_execution_key() -> None:
    h = Harness()
    try:
        await h.create()
        confirmed = await h.service.confirm(h.request(), context=context())
        raw = claimed(confirmed).model_dump(mode="python")
        raw["execution_error"] = ToolError(
            code=ToolErrorCode.TOOL_TIMEOUT,
            message="private-evidence-reference",
            retryable=False,
        )
        snapshot = ReworkConfirmationSnapshot.model_validate(raw)
        summary = rework_summary(snapshot)
        assert summary["phase"] == "UNKNOWN" and summary["status"] == "EXECUTING"
        assert summary["error_code"] == "TOOL_TIMEOUT"
        encoded = json.dumps(summary)
        assert "private-evidence-reference" not in encoded and "rework:v1:test-only" not in encoded
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "boolean_revision",
        "string_revision",
        "unsafe_revision",
        "phase",
        "unfinished_receipt",
        "unknown_error",
        "error_body",
        "missing_field",
    ],
)
async def test_rework_observability_progress_schema_rejects_untrusted_json(change: str) -> None:
    h = Harness()
    try:
        raw: dict[str, object] = dict(rework_summary(await h.create()))
        if change == "extra":
            raw["evidence_references"] = ["private-evidence"]
        elif change == "boolean_revision":
            raw["revision"] = True
        elif change == "string_revision":
            raw["revision"] = "0"
        elif change == "unsafe_revision":
            raw["revision"] = 9007199254740992
        elif change == "phase":
            raw["phase"] = "SUCCEEDED"
        elif change == "unfinished_receipt":
            raw["receipt_source"] = None
        elif change == "unknown_error":
            raw.update(status="EXECUTING", phase="UNKNOWN")
        elif change == "error_body":
            raw.update(status="EXECUTING", phase="UNKNOWN", error_code="private-error-body")
        else:
            del raw["approval_id"]
        with pytest.raises(ValidationError):
            ReworkProgressSummary.model_validate_json(json.dumps(raw))
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize("change", ["valid", "forged_write_trace", "missing_source"])
async def test_rework_observability_progress_schema_preserves_lookup_trace_boundary(
    change: str,
) -> None:
    raw = {
        "approval_id": "approval-test",
        "revision": 5,
        "operation": "START_REWORK",
        "status": "SUCCEEDED",
        "phase": "SUCCEEDED",
        "error_code": None,
        "receipt_source": "LOOKUP",
        "receipt_operation_id": "OP-T830",
        "receipt_status": "RUNNING",
        "write_java_trace_id": None,
        "lookup_java_trace_id": "trace-read",
    }
    if change == "forged_write_trace":
        raw["write_java_trace_id"] = "invented-write-trace"
    elif change == "missing_source":
        del raw["receipt_source"]
    if change != "valid":
        with pytest.raises(ValidationError):
            ReworkProgressSummary.model_validate_json(json.dumps(raw))
    else:
        data = ReworkProgressSummary.model_validate_json(json.dumps(raw)).event_data()
        assert data == raw and data["write_java_trace_id"] is None


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "extra",
        "approval",
        "revision",
        "row_phase",
        "run",
        "operation",
        "latest",
        "missing_history",
    ],
)
async def test_rework_observability_replay_validates_row_binding_and_complete_batch(
    change: str,
) -> None:
    h = Harness()
    try:
        snapshot = await h.create()
        summary = rework_summary(snapshot)
        row = ReworkOperationLog(
            approval_id=snapshot.approval_id,
            revision=0,
            run_id=snapshot.run_id,
            phase="WAITING_CONFIRMATION",
            summary=dict(summary),
            recorded_at=NOW,
        )
        if change == "extra":
            row.summary["processing_comment"] = "private-comment"
        elif change == "approval":
            row.summary["approval_id"] = "approval-other"
        elif change == "revision":
            row.summary["revision"] = 1
        elif change == "row_phase":
            row.phase = "CONFIRMED"
        elif change == "run":
            row.run_id = "run-other"
        elif change == "operation":
            row.summary["operation"] = "BLOCK_REWORK"
        elif change == "latest":
            row.summary.update(status="CONFIRMED", phase="CONFIRMED")
            row.phase = "CONFIRMED"
        rows = [] if change == "missing_history" else [row]
        if change != "valid":
            with pytest.raises(ValueError, match=r"^rework audit history is inconsistent$"):
                validated_rework_replay(rows, snapshot=snapshot)
        else:
            parsed = validated_rework_replay(rows, snapshot=snapshot)
            row.summary["processing_comment"] = "private-later-change"
            assert parsed[0].event_data() == summary
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize(
    ("observed", "audited", "marker", "allowed"),
    [
        (False, False, None, True),
        (True, True, "same", True),
        (False, True, "same", False),
        (False, True, None, False),
        (False, False, "same", False),
        (True, False, None, False),
        (True, False, "same", False),
        (True, True, None, False),
        (True, True, "other", False),
    ],
)
async def test_rework_observability_mode_does_not_follow_constructor_alone(
    observed: bool, audited: bool, marker: str | None, allowed: bool
) -> None:
    h = Harness()
    try:
        snapshot = await h.create()
        result = (
            None
            if marker is None
            else {
                "kind": "REWORK_APPROVAL",
                "approval_id": snapshot.approval_id if marker == "same" else "approval-other",
            }
        )
        run = AgentRun(
            run_id=snapshot.run_id,
            session_id="session-test",
            status=AgentRunStatus.RUNNING,
            version_snapshot={},
            final_result=result,
        )
        session = AsyncMock(spec=AsyncSession)
        session.scalar.return_value = snapshot.approval_id if audited else None
        if allowed:
            await require_rework_observation_mode(session, snapshot, observed=observed, run=run)
        else:
            with pytest.raises(ReworkObservationModeError) as caught:
                await require_rework_observation_mode(session, snapshot, observed=observed, run=run)
            assert caught.value.code == ToolErrorCode.RESPONSE_VALIDATION_ERROR
            assert caught.value.status_code == 500 and not caught.value.retryable
            assert snapshot.approval_id not in str(caught.value)
        assert run.final_result == result
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize(
    ("observed", "audited", "reserved", "existing", "allowed"),
    [
        (False, False, False, False, True),
        (False, False, False, True, True),
        (True, False, False, False, True),
        (True, False, False, True, False),
        (False, False, True, False, False),
        (False, True, False, False, False),
        (True, True, True, True, False),
    ],
)
async def test_rework_observability_creation_preserves_dedicated_run(
    observed: bool, audited: bool, reserved: bool, existing: bool, allowed: bool
) -> None:
    run = AgentRun(
        run_id="run-test",
        session_id="session-test",
        status=AgentRunStatus.RUNNING,
        version_snapshot={},
        final_result={"kind": "REWORK_APPROVAL"} if reserved else None,
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [
        "approval-audited" if audited else None,
        "approval-existing" if existing else None,
    ]
    if allowed:
        await require_rework_creation_mode(session, run, observed=observed)
    else:
        with pytest.raises(ReworkObservationModeError):
            await require_rework_creation_mode(session, run, observed=observed)
