"""T829隔离PostgreSQL执行互斥、原键核对和实际Tool/Client，不冒充真实Java。"""

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.database import Database
from app.models import ReworkConfirmationRecord
from app.schemas.rework_write_tools import ReworkWriteOutput
from app.services.rework_confirmation import ReworkConfirmationError
from app.services.rework_execution_service import ReworkExecutionService
from app.tools.models import ToolContext
from tests.integration.tools.test_rework_write_tools import CASES, Case, receipt
from tests.test_agent_persistence import _run_alembic
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_rework_confirmation import Harness
from tests.test_rework_confirmation_persistence import seed, service
from tests.test_rework_draft_workflow import (
    client,
    command,
    context,
    fact_handler,
    nested,
    response,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class ExecutionHarness(Harness):
    """真实数据库负责互斥，Mock只在HTTP边界提供可控事实与响应。"""

    def __init__(self, case: Case = CASES[1]) -> None:
        super().__init__(case)
        self.now = datetime.now(UTC)
        self.writes: list[httpx.Request] = []
        self.lookups: list[httpx.Request] = []
        self.lose_response = False
        self.found = True
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.pause = False
        self.raw_receipt = receipt(case)
        if case.operation not in {"CREATE_LIFECYCLE_REWORK", "START_REWORK", "CREATE_NEXT_REWORK"}:
            self.raw_receipt.update(
                processingRevision=2, inspectionId="CHECK-T827-CURRENT", reviewId=None
            )
        if case.operation == "REGISTER_REWORK_RESULT":
            self.raw_receipt.update(processingRevision=3, inspectionId=None)
        elif case.operation == "REGISTER_REWORK_INSPECTION":
            self.raw_receipt["inspectionId"] = "CHECK-T829-NEW"
        elif case.operation == "SUBMIT_REWORK_REVIEW":
            self.raw_receipt["reviewId"] = "REVIEW-T829-NEW"
        self.http = client(httpx.MockTransport(self.handle))

    async def handle(self, request: httpx.Request) -> httpx.Response:
        """写与核对分开记录，只有写带原幂等Header，查询没有写Header。"""

        if request.method == "GET":
            return fact_handler(self.data, self.calls)(request)
        assert request.method == "POST"
        if request.url.path.endswith("/operations/query"):
            self.lookups.append(request)
            assert "Idempotency-Key" not in request.headers
            return response(
                {"found": self.found, "receipt": self.raw_receipt if self.found else None}
            )
        self.writes.append(request)
        assert request.headers["Idempotency-Key"].startswith("rework:v1:")
        self.entered.set()
        if self.pause:
            await self.release.wait()
        if self.lose_response:
            raise httpx.ReadTimeout("private response body", request=request)
        return response(self.raw_receipt)

    async def confirmed(
        self, database: Database, identity: str = "approval-t829"
    ) -> ReworkExecutionService:
        """使用T828真实服务创建并确认，禁止手工补造已确认数据库行。"""

        await self.shared.aclose()
        self.shared = self.http
        confirmation = service(database, self, identity)
        self.snapshot = await confirmation.create(command(self.case), context=context())
        self.snapshot = await confirmation.confirm(self.request(), context=context())
        return self.executor(database)

    def executor(
        self, database: Database, ctx: ToolContext | None = None
    ) -> ReworkExecutionService:
        """跨实例使用同一数据库，验证互斥不依赖进程内锁。"""

        return ReworkExecutionService(
            database, self.http, context=ctx or context(), now=lambda: self.now
        )

    async def close(self) -> None:
        await self.http.aclose()


async def test_rework_execution_nine_actions_save_original_receipt_and_never_resubmit(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        # 写Tool使用真实UTC时钟，会话也须从本轮时钟起算，不能在固定日期后失效。
        await seed(database, now=datetime.now(UTC))
        for index, case in enumerate(CASES):
            h = ExecutionHarness(case)
            try:
                executor = await h.confirmed(database, f"approval-t829-{index}")
                value = {"approval_id": f"approval-t829-{index}"}
                result = await executor.execute(value)
                assert result.outcome == "SUCCEEDED" and result.receipt_evidence is not None
                assert (
                    result.receipt_evidence.receipt.model_dump(mode="json", by_alias=True)
                    == h.raw_receipt
                )
                assert (
                    result.receipt_evidence.source == "WRITE"
                    and result.receipt_evidence.lookup_java_trace_id is None
                )
                assert await h.executor(database).execute(value) == result
                assert await h.executor(database).reconcile(value) == result
                assert len(h.writes) == 1 and not h.lookups
                stored = await executor.store.read(value["approval_id"])
                assert (
                    stored is not None
                    and stored.status == "SUCCEEDED"
                    and stored.submission_started_at is not None
                )
                assert stored.confirmed_draft == h.snapshot.confirmed_draft if h.snapshot else False
            finally:
                await h.close()
        async with database.session() as session:
            keys = (await session.scalars(select(ReworkConfirmationRecord.execution_key))).all()
            assert len(keys) == len(set(keys)) == 9
    finally:
        await database.dispose()


async def test_rework_execution_parallel_and_forced_tool_refresh_share_one_submission(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        executor = await h.confirmed(database)
        h.pause = True
        value = {"approval_id": "approval-t829"}
        pending = asyncio.create_task(executor.execute(value))
        await asyncio.wait_for(h.entered.wait(), 3)
        other = h.executor(database)
        assert (await other.execute(value)).outcome == "IN_PROGRESS"
        stored = await other.store.read("approval-t829")
        assert stored is not None and stored.execution_key is not None
        duplicate = await other._writes.get("start_rework").execute(
            {**value, "idempotency_key": stored.execution_key}, context(), force_refresh=True
        )
        assert duplicate.error is not None and len(h.writes) == 1
        h.release.set()
        assert (await pending).outcome == "SUCCEEDED"
        assert (await other.execute(value)).outcome == "SUCCEEDED" and len(h.writes) == 1
    finally:
        h.release.set()
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("save_failure", [False, True], ids=["response_lost", "save_conflict"])
async def test_rework_execution_unknown_queries_original_key_without_rewriting(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, save_failure: bool
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        executor = await h.confirmed(database)
        if save_failure:
            monkeypatch.setattr(
                executor.store, "save_execution_result", AsyncMock(return_value=False)
            )
        else:
            h.lose_response = True
        value = {"approval_id": "approval-t829"}
        report = await executor.execute(value)
        assert (
            report.outcome == "UNKNOWN" and report.error is not None and not report.error.retryable
        )
        assert "private" not in report.error.message
        original = await executor.store.read("approval-t829")
        assert original is not None and original.execution_key is not None
        assert (await h.executor(database).execute(value)).outcome == "UNKNOWN" and len(
            h.writes
        ) == 1
        h.found = False
        assert (await h.executor(database).reconcile(value)).outcome == "UNKNOWN"
        h.found = True
        h.now += timedelta(hours=1)  # 已过审批期限仍允许核对，不能重新获得写入权。
        recovered = await h.executor(database).reconcile(value)
        assert recovered.outcome == "SUCCEEDED" and recovered.receipt_evidence is not None
        assert recovered.receipt_evidence.source == "LOOKUP"
        assert recovered.receipt_evidence.write_java_trace_id is None
        assert recovered.receipt_evidence.lookup_java_trace_id == context().trace_id
        assert len(h.writes) == 1 and len(h.lookups) == 2
        assert all(original.execution_key.encode() in call.content for call in h.lookups)
        assert await h.executor(database).execute(value) == recovered
    finally:
        await h.close()
        await database.dispose()


@pytest.mark.parametrize("reason", ["expired", "stale", "permission", "run", "unconfirmed"])
async def test_rework_execution_ineligible_records_never_write(
    migrated_database_url: str, reason: str
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness(CASES[5])
    try:
        await seed(database, now=h.now)
        if reason == "unconfirmed":
            await h.shared.aclose()
            h.shared = h.http
            h.snapshot = await service(database, h, "approval-t829").create(
                command(h.case), context=context()
            )
            executor = h.executor(database)
        else:
            executor = await h.confirmed(database)
        if reason == "expired":
            assert h.snapshot is not None
            h.now = h.snapshot.expires_at
        elif reason == "stale":
            nested(h.data[2], "processing", "artifact")["artifactVersion"] = "Changed"
        elif reason == "permission":
            executor = h.executor(database, context(frozenset({"TASK_READ", "REWORK_READ"})))
        elif reason == "run":
            raw = context().model_dump(mode="python")
            raw["run_id"] = "run-other"
            executor = h.executor(database, ToolContext.model_validate(raw))
        with pytest.raises(ReworkConfirmationError):
            await executor.execute({"approval_id": "approval-t829"})
        assert not h.writes
    finally:
        await h.close()
        await database.dispose()


async def test_rework_execution_claim_race_and_downgrade_preserve_execution_evidence(
    migrated_database_url: str,
) -> None:
    database, h = Database(migrated_database_url), ExecutionHarness()
    try:
        await seed(database, now=h.now)
        executor = await h.confirmed(database)
        assert h.snapshot is not None
        claims = await asyncio.gather(
            executor.store.claim(h.snapshot), h.executor(database).store.claim(h.snapshot)
        )
        assert sum(c is not None for c in claims) == 1
        claimed = next(c for c in claims if c is not None)
        expected = executor.store.projection(claimed)
        assert expected is not None
        submissions = await asyncio.gather(
            executor.store.begin_submission(expected),
            h.executor(database).store.begin_submission(expected),
        )
        assert sorted(submissions) == [False, True]
        output = ReworkWriteOutput.model_validate(
            {
                "approval_id": "approval-t829",
                "receipt": h.raw_receipt,
                "java_trace_id": "first-write",
            }
        )
        assert await executor.store.save_execution_result(expected, output)
        replay = ReworkWriteOutput.model_validate(
            {**output.model_dump(mode="python"), "java_trace_id": "later-write"}
        )
        assert await executor.store.save_execution_result(expected, replay)
        saved = await executor.store.read("approval-t829")
        assert saved is not None and saved.receipt_evidence is not None
        assert saved.receipt_evidence.write_java_trace_id == "first-write"
        url = database.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
        _run_alembic(url, "check")
        with pytest.raises(subprocess.CalledProcessError) as error:
            _run_alembic(url, "downgrade", "0017_rework_confirmation")
        assert "cannot downgrade persisted rework executions" in str(error.value.stderr)
        assert await executor.store.read("approval-t829") == saved
    finally:
        await h.close()
        await database.dispose()
