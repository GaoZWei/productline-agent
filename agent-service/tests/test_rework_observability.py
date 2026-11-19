"""返工事件白名单及通知故障隔离；不替代数据库与真实Java验收。"""

import json
from collections.abc import Mapping
from datetime import timedelta

import pytest
from pydantic import JsonValue

from app.errors import ToolErrorCode
from app.schemas.events import RunEventType
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.services.rework_observation import ReworkStateObserver, elapsed_ms, rework_summary
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
                "approval_id", "revision", "operation", "status", "phase", "error_code"
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
