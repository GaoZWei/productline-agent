"""T828独立确认，真实只读Tool/Client配合显式内存Store，不代表数据库验收。"""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.services.rework_confirmation import ReworkConfirmationError, ReworkConfirmationService
from app.tools.models import ToolContext
from tests.integration.tools.test_rework_write_tools import CASES, Case
from tests.test_rework_draft_workflow import (
    PERMISSIONS,
    client,
    command,
    context,
    fact_handler,
    facts,
    nested,
    workflow,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]
NOW = datetime(2026, 11, 18, 3, tzinfo=UTC)


class MemoryStore:
    """仅模拟按完整快照比较，所有输入输出复制，不提供执行接口。"""

    def __init__(self) -> None:
        self.rows: dict[str, ReworkConfirmationSnapshot] = {}

    async def create(
        self, snapshot: ReworkConfirmationSnapshot, *, context: ToolContext, now: datetime
    ) -> bool:
        if snapshot.approval_id in self.rows:
            return False
        self.rows[snapshot.approval_id] = self.copy(snapshot)
        return True

    async def get(
        self, approval_id: str, *, context: ToolContext, now: datetime
    ) -> ReworkConfirmationSnapshot | None:
        value = self.rows.get(approval_id)
        if (
            value is None
            or value.run_id != context.run_id
            or value.owner_user_id != context.identity.user_id
        ):
            return None
        return self.copy(value)

    async def transition(
        self,
        expected: ReworkConfirmationSnapshot,
        updated: ReworkConfirmationSnapshot,
        *,
        context: ToolContext,
        now: datetime,
    ) -> bool:
        if self.rows.get(expected.approval_id) != expected:
            return False
        self.rows[expected.approval_id] = self.copy(updated)
        return True

    @staticmethod
    def copy(value: ReworkConfirmationSnapshot) -> ReworkConfirmationSnapshot:
        return ReworkConfirmationSnapshot.model_validate_json(value.model_dump_json())


class Harness:
    """每份待确认记录从真实只读编排生成，测试不直接伪造合法业务快照。"""

    def __init__(self, case: Case = CASES[1]) -> None:
        self.case, self.data = case, facts(case)
        self.calls: list[httpx.Request] = []
        self.store = MemoryStore()
        self.now = NOW
        self.shared = client(httpx.MockTransport(fact_handler(self.data, self.calls)))
        self.service = ReworkConfirmationService(
            store=self.store,
            workflow=workflow(self.shared),
            now=lambda: self.now,
            approval_id_factory=lambda: "approval-t828",
        )
        self.snapshot: ReworkConfirmationSnapshot | None = None

    async def create(self) -> ReworkConfirmationSnapshot:
        self.snapshot = await self.service.create(command(self.case), context=context())
        return self.snapshot

    def request(self) -> dict[str, object]:
        assert self.snapshot is not None
        return {
            "approval_id": self.snapshot.approval_id,
            "draft": self.snapshot.prepared.review.draft.model_dump(mode="python"),
        }


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.operation)
async def test_nine_actions_require_separate_confirmation_and_only_read_java(case: Case) -> None:
    h = Harness(case)
    try:
        original = await h.create()
        result = await h.service.confirm(h.request(), context=context())
        assert result.status == "CONFIRMED" and result.confirmed_by_user_id == "reviewer-test"
        assert result.confirmed_at == NOW and result.prepared == original.prepared
        assert result.confirmed_draft == original.prepared.review.draft and result.revision == 1
        assert len(h.calls) == (4 if case is CASES[0] else 6)
        assert all(call.method == "GET" for call in h.calls)
        assert (
            "idempotency_key" not in result.model_dump()
            and "EXECUTING" not in result.model_dump_json()
        )
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_CONFIRMED"):
            await h.service.confirm(h.request(), context=context())
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize(
    "change", ["version", "artifact", "revision", "evidence", "inspection", "issue", "round"]
)
async def test_material_or_state_changes_make_original_approval_stale(change: str) -> None:
    h = Harness(CASES[6])
    try:
        original = await h.create()
        if change == "version":
            h.data[0]["version"] = 5
            nested(h.data[1], "tasks", 0)["taskVersion"] = 5
            h.data[2]["taskVersion"] = 5
        elif change == "artifact":
            nested(h.data[2], "processing", "artifact")["artifactVersion"] = "Release-3"
        elif change == "revision":
            nested(h.data[2], "processing")["processingRevision"] = 3
            nested(h.data[2], "inspection")["processingRevision"] = 3
            nested(h.data[1], "tasks", 0, "issues", 0, "effectiveReview")["processingRevision"] = 3
        elif change == "evidence":
            nested(h.data[2], "processing")["evidenceReferences"] = ["report:changed"]
        elif change == "inspection":
            nested(h.data[2], "inspection")["inspectionId"] = "CHECK-T828-NEW"
            nested(h.data[1], "tasks", 0, "issues", 0, "effectiveReview")["inspectionId"] = (
                "CHECK-T828-NEW"
            )
        elif change == "issue":
            nested(h.data[1], "tasks", 0, "issues", 0, "issue")["status"] = "CLOSED"
            h.data[2]["issueStatus"] = "CLOSED"
            h.data[2]["allowedActions"] = []
        elif change == "round":
            h.data[2]["roundNumber"] = 2
            h.data[2]["previousReworkTaskId"] = "REWORK-T828-PREV"
            nested(h.data[2], "inspection")["roundNumber"] = 2
            nested(h.data[1], "tasks", 0, "issues", 0, "effectiveReview")["roundNumber"] = 2
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_STALE"):
            await h.service.confirm(h.request(), context=context())
        row = h.store.rows[original.approval_id]
        assert row.status == "STALE" and row.prepared == original.prepared
        assert row.confirmed_draft is None
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize("state", ["cancelled", "expired", "permissions", "owner", "run"])
async def test_ineligible_confirmation_stops_before_java_read(state: str) -> None:
    h = Harness()
    try:
        original = await h.create()
        ctx = context()
        if state == "cancelled":
            await h.service.cancel(original.approval_id, context=ctx)
        elif state == "expired":
            h.now = original.expires_at
        elif state == "permissions":
            ctx = context(PERMISSIONS - {"REWORK_WRITE"})
        elif state == "owner":
            raw = ctx.model_dump(mode="python")
            raw["identity"]["user_id"] = "other-user"
            ctx = ToolContext.model_validate(raw)
        elif state == "run":
            raw = ctx.model_dump(mode="python")
            raw["run_id"] = "other-run"
            ctx = ToolContext.model_validate(raw)
        before = len(h.calls)
        with pytest.raises(ReworkConfirmationError):
            await h.service.confirm(h.request(), context=ctx)
        assert len(h.calls) == before
        row = h.store.rows[original.approval_id]
        assert row.status == {"cancelled": "CANCELLED", "expired": "EXPIRED"}.get(
            state, "WAITING_CONFIRMATION"
        )
    finally:
        await h.shared.aclose()


async def test_user_edits_are_confirmed_exactly_without_replacing_original_evidence() -> None:
    h = Harness(CASES[5])
    try:
        original = await h.create()
        request = h.request()
        nested(request, "draft", "request")["processing_comment"] = "  人工最终说明🚀  "
        result = await h.service.confirm(request, context=context())
        assert result.confirmed_draft is not None
        assert (
            result.confirmed_draft.request.model_dump()["processing_comment"]
            == "  人工最终说明🚀  "
        )
        assert result.prepared == original.prepared
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize("kind", ["target", "operation", "authority"])
async def test_modified_target_operation_or_extra_confirmation_is_never_accepted(kind: str) -> None:
    h = Harness()
    try:
        await h.create()
        request = h.request()
        if kind == "target":
            nested(request, "draft", "target")["rework_task_id"] = "REWORK-T828-OTHER"
        elif kind == "operation":
            nested(request, "draft")["operation"] = "REGISTER_REWORK_RESULT"
        else:
            request["confirmed"] = True
        before = len(h.calls)
        with pytest.raises(ReworkConfirmationError):
            await h.service.confirm(request, context=context())
        assert len(h.calls) == before
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize("race", ["cancel", "expire", "parallel_confirm"])
async def test_changes_during_java_read_cannot_be_overwritten(race: str) -> None:
    h = Harness()
    try:
        original = await h.create()
        entered, release = asyncio.Event(), asyncio.Event()
        handler = fact_handler(h.data, h.calls)

        async def delayed(request: httpx.Request) -> httpx.Response:
            entered.set()
            await release.wait()
            return handler(request)

        await h.shared.aclose()
        h.shared = client(httpx.MockTransport(delayed))
        h.service = ReworkConfirmationService(
            store=h.store, workflow=workflow(h.shared), now=lambda: h.now
        )
        pending = asyncio.create_task(h.service.confirm(h.request(), context=context()))
        await asyncio.wait_for(entered.wait(), 2)
        if race == "cancel":
            await h.service.cancel(original.approval_id, context=context())
        elif race == "expire":
            h.now = original.expires_at
        else:
            h.store.rows[original.approval_id] = h.service._updated(
                original, "CONFIRMED", draft=original.prepared.review.draft, now=NOW
            )
        release.set()
        with pytest.raises(ReworkConfirmationError):
            await pending
        assert (
            h.store.rows[original.approval_id].status
            == {"cancel": "CANCELLED", "expire": "EXPIRED", "parallel_confirm": "CONFIRMED"}[race]
        )
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize(
    "status,code",
    [(403, "PERMISSION_DENIED"), (500, "UPSTREAM_UNAVAILABLE"), (404, "APPROVAL_STALE")],
)
async def test_read_failure_is_safe_and_only_disappearance_marks_stale(
    status: int, code: str
) -> None:
    h = Harness()
    try:
        original = await h.create()
        await h.shared.aclose()

        def fail(request: httpx.Request) -> httpx.Response:
            h.calls.append(request)
            return httpx.Response(
                status,
                headers={"X-Trace-Id": context().trace_id},
                json={
                    "success": False,
                    "code": {
                        403: "PERMISSION_DENIED",
                        500: "INTERNAL_SERVER_ERROR",
                        404: "RESOURCE_NOT_FOUND",
                    }[status],
                    "message": "private-evidence-body",
                    "data": None,
                    "trace_id": context().trace_id,
                    "retryable": False,
                },
            )

        h.shared = client(httpx.MockTransport(fail))
        h.service = ReworkConfirmationService(
            store=h.store, workflow=workflow(h.shared), now=lambda: h.now
        )
        with pytest.raises(ReworkConfirmationError) as error:
            await h.service.confirm(h.request(), context=context())
        assert error.value.code == code and "private" not in str(error.value)
        assert h.store.rows[original.approval_id].status == (
            "STALE" if status == 404 else "WAITING_CONFIRMATION"
        )
    finally:
        await h.shared.aclose()


async def test_snapshot_rejects_forged_confirmation_and_clock_without_timezone() -> None:
    h = Harness()
    try:
        original = await h.create()
        raw = original.model_dump(mode="python")
        raw["status"] = "CONFIRMED"
        with pytest.raises(ValidationError):
            ReworkConfirmationSnapshot.model_validate(raw)
        h.now = NOW.replace(tzinfo=None)
        with pytest.raises(ValueError):
            await h.service.confirm(h.request(), context=context())
    finally:
        await h.shared.aclose()


async def test_new_chain_created_after_first_draft_invalidates_only_that_draft() -> None:
    h = Harness(CASES[0])
    try:
        original = await h.create()
        current = facts(CASES[1])
        h.data[1].clear()
        h.data[1].update(current[1])
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_STALE"):
            await h.service.confirm(h.request(), context=context())
        assert h.store.rows[original.approval_id].status == "STALE"
    finally:
        await h.shared.aclose()


async def test_cancelling_confirmation_task_during_read_does_not_confirm() -> None:
    h = Harness()
    try:
        original = await h.create()
        await h.shared.aclose()
        entered = asyncio.Event()

        async def pending_read(request: httpx.Request) -> httpx.Response:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled read cannot finish")

        h.shared = client(httpx.MockTransport(pending_read))
        h.service = ReworkConfirmationService(
            store=h.store, workflow=workflow(h.shared), now=lambda: h.now
        )
        task = asyncio.create_task(h.service.confirm(h.request(), context=context()))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert h.store.rows[original.approval_id] == original
    finally:
        await h.shared.aclose()
