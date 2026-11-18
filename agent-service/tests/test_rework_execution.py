"""T829纯本地Schema及领取竞争编排，显式Mock不替代数据库或真实Java验收。"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.database import Database
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_execution import (
    ReworkExecutionInput,
    ReworkExecutionReport,
    ReworkReceiptEvidence,
)
from app.schemas.rework_operation_query import ReworkOperationResolution
from app.services.rework_confirmation import ReworkConfirmationError
from app.services.rework_execution_service import ReworkExecutionService
from app.services.rework_execution_store import DatabaseReworkExecutionStore
from app.tools.models import ToolResult
from tests.integration.tools.test_rework_write_tools import CASES, Case, receipt
from tests.test_rework_confirmation import Harness
from tests.test_rework_draft_workflow import context, nested

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def claimed(snapshot: ReworkConfirmationSnapshot) -> ReworkConfirmationSnapshot:
    """测试明确构造领取状态，只用于Schema和Mock，不签发实际执行权。"""

    raw = snapshot.model_dump(mode="python")
    raw.update(
        status="EXECUTING",
        execution_key="rework:v1:test-only",
        claimed_at=snapshot.confirmed_at,
        revision=snapshot.revision + 1,
    )
    return ReworkConfirmationSnapshot.model_validate(raw)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.operation)
async def test_execution_projection_preserves_confirmed_material_and_original_binding(
    case: Case,
) -> None:
    h = Harness(case)
    try:
        await h.create()
        confirmed = await h.service.confirm(h.request(), context=context())
        execution = DatabaseReworkExecutionStore.projection(claimed(confirmed))
        assert execution is not None and confirmed.confirmed_draft is not None
        assert execution.request == confirmed.confirmed_draft.request
        assert execution.task_version == confirmed.confirmed_draft.target.task_version
        assert execution.processing_revision == confirmed.confirmed_draft.target.processing_revision
        assert execution.inspection_id == confirmed.confirmed_draft.target.inspection_id
        assert execution.operation == case.operation
        assert DatabaseReworkExecutionStore.projection(confirmed) is None
    finally:
        await h.shared.aclose()


@pytest.mark.parametrize(
    "change", ["unconfirmed", "late_claim", "late_submission", "receipt_missing", "unclaimed_key"]
)
async def test_invalid_claim_and_receipt_combinations_are_rejected(change: str) -> None:
    h = Harness()
    try:
        await h.create()
        confirmed = await h.service.confirm(h.request(), context=context())
        raw = claimed(confirmed).model_dump(mode="python")
        if change == "unconfirmed":
            raw["confirmed_draft"] = None
        elif change == "late_claim":
            raw["claimed_at"] = confirmed.expires_at
        elif change == "late_submission":
            raw["submission_started_at"] = confirmed.expires_at
        elif change == "receipt_missing":
            raw["status"] = "SUCCEEDED"
        else:
            raw["status"] = "CONFIRMED"
        with pytest.raises(ValidationError):
            ReworkConfirmationSnapshot.model_validate(raw)
        with pytest.raises(ValidationError):
            ReworkExecutionInput.model_validate(
                {"approval_id": "test", "idempotency_key": "forged"}
            )
    finally:
        await h.shared.aclose()


async def test_lookup_trace_cannot_be_forged_as_original_write_trace() -> None:
    raw: dict[str, object] = {
        "approval_id": "test",
        "receipt": receipt(),
        "source": "LOOKUP",
        "write_java_trace_id": "invented-first-trace",
        "lookup_java_trace_id": "actual-query-trace",
    }
    with pytest.raises(ValidationError):
        ReworkReceiptEvidence.model_validate(raw)
    raw["write_java_trace_id"] = None
    evidence = ReworkReceiptEvidence.model_validate(raw)
    assert evidence.write_java_trace_id is None
    with pytest.raises(ValidationError):
        ReworkExecutionReport(
            approval_id="test", outcome="UNKNOWN", receipt_evidence=evidence, error=None
        )


@pytest.mark.parametrize("expired", [False, True])
async def test_competing_claim_returns_existing_state_without_overwriting_or_writing(
    monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    h = Harness()
    # 引擎从不建立连接，所有Store调用均显式Mock，不能称为持久化验收。
    database = Database("postgresql://test:test@127.0.0.1:1/unused_t829_mock")
    try:
        await h.create()
        original = await h.service.confirm(h.request(), context=context())
        execution = claimed(original)
        if expired:
            h.now = original.expires_at + timedelta(seconds=1)
        else:
            nested(h.data[2], "reworkTask")["status"] = "RUNNING"
        executor = ReworkExecutionService(database, h.shared, context=context(), now=lambda: h.now)
        read = AsyncMock(side_effect=[original, execution])
        invalidate = AsyncMock(return_value=False)
        monkeypatch.setattr(executor.store, "read", read)
        monkeypatch.setattr(executor.store, "invalidate", invalidate)
        report = await executor.execute({"approval_id": original.approval_id})
        assert report.outcome == "IN_PROGRESS"
        invalidate.assert_awaited_once_with(original, expired=expired)
        assert all(call.method == "GET" for call in h.calls)
    finally:
        await h.shared.aclose()
        await database.dispose()


@pytest.mark.parametrize("allowed", [True, False])
async def test_receipt_lookup_uses_read_permission_without_restoring_write_permission(
    monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    h = Harness()
    database = Database("postgresql://test:test@127.0.0.1:1/unused_t829_mock")
    try:
        await h.create()
        confirmed = await h.service.confirm(h.request(), context=context())
        execution = claimed(confirmed)
        ctx = context(frozenset({"REWORK_READ"}) if allowed else frozenset())
        executor = ReworkExecutionService(database, h.shared, context=ctx, now=lambda: h.now)
        monkeypatch.setattr(executor.store, "read", AsyncMock(return_value=execution))
        lookup = AsyncMock(
            return_value=ToolResult(
                success=True,
                data=ReworkOperationResolution(
                    approval_id=execution.approval_id,
                    outcome="UNKNOWN",
                    receipt=None,
                    java_trace_id=ctx.trace_id,
                ),
            )
        )
        monkeypatch.setattr(executor._query, "execute", lookup)
        if allowed:
            assert (
                await executor.reconcile({"approval_id": execution.approval_id})
            ).outcome == "UNKNOWN"
            lookup.assert_awaited_once()
        else:
            with pytest.raises(ReworkConfirmationError):
                await executor.reconcile({"approval_id": execution.approval_id})
            lookup.assert_not_awaited()
    finally:
        await h.shared.aclose()
        await database.dispose()
