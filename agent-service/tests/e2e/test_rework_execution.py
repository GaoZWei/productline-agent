"""T829真实Java九动作/两轮闭环及丢响应核对，Agent证据使用分离测试库。"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.database import Base, Database
from app.models import AgentRun, AgentRunStatus, AgentSession
from app.schemas.business import BusinessIdentity
from app.schemas.rework import ReworkWriteReceipt
from app.services.rework_confirmation import ReworkConfirmationService
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from app.services.rework_execution_service import ReworkExecutionService
from app.settings import Settings
from app.tools.models import ToolContext
from app.tools.readonly import create_read_tool_registry
from app.tools.rework_readonly import create_rework_read_tool_registry
from app.workflows.rework_draft import ReworkDraftWorkflow

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]
ORDER, TASK, ISSUE = "ORDER-T829-E2E", "TASK-T829-E2E", "ISSUE-T829-E2E"


class LoseFirstWrite(httpx.AsyncBaseTransport):
    """真实Java成功提交后丢弃一次响应，按请求记录证明没有自动重发。"""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.writes: list[httpx.Request] = []
        self.lookups: list[httpx.Request] = []
        self.original: dict[str, object] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        result = await self.inner.handle_async_request(request)
        if request.method == "POST":
            if request.url.path.endswith("/operations/query"):
                self.lookups.append(request)
            else:
                self.writes.append(request)
                if self.original is None:
                    assert result.status_code == 200
                    self.original = json.loads(await result.aread())["data"]
                    await result.aclose()
                    raise httpx.ReadTimeout("simulated loss after Java commit", request=request)
        return result

    async def aclose(self) -> None:
        await self.inner.aclose()


async def test_real_java_nine_actions_two_rounds_and_unknown_receipt_never_rewrite() -> None:
    db, url = (
        os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL"),
        os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL"),
    )
    if db is None or url is None:
        pytest.skip("通过make test-rework-execution-e2e启动独占Java/PostgreSQL")
    assert (
        urlparse(db).hostname == "127.0.0.1"
        and urlparse(db).path == "/business_service_test_rework_query"
    )
    assert urlparse(url).hostname == "127.0.0.1"
    admin = await asyncpg.connect(
        make_url(db).set(database="postgres").render_as_string(hide_password=False)
    )
    name = "agent_t829_execution_e2e"
    await admin.execute(f'CREATE DATABASE "{name}"')
    database = Database(make_url(db).set(database=name).render_as_string(hide_password=False))
    fixture = create_async_engine(db.replace("postgresql://", "postgresql+asyncpg://", 1))
    transport = LoseFirstWrite()
    shared = BusinessHttpClient(
        Settings(_env_file=None, environment="test", business_service_url=AnyHttpUrl(url)),
        transport=transport,
    )
    java = ReworkHttpClient(shared)
    identity = BusinessIdentity(user_id="reviewer-t829-e2e", role="REVIEWER")
    ctx = ToolContext(
        identity=identity,
        permissions=frozenset({"TASK_READ", "REWORK_READ", "REWORK_WRITE", "REVIEW_WRITE"}),
        trace_id="trace-t829-e2e",
        run_id="run-t829-e2e",
    )
    flow = ReworkDraftWorkflow(
        task_tools=create_read_tool_registry(shared),
        rework_tools=create_rework_read_tool_registry(java),
    )
    confirmations = ReworkConfirmationService(
        store=DatabaseReworkConfirmationStore(database), workflow=flow
    )
    seen: set[str] = set()

    async def act(
        operation: str, rework: str | None = None, *, concurrent: bool = False, **materials: object
    ) -> ReworkWriteReceipt:
        """每次动作独立生成、审查和确认，所有业务写入实际经过新执行服务。"""

        command: dict[str, object] = {"operation": operation, "task_id": TASK, **materials}
        if rework is not None:
            command["rework_task_id"] = rework
        pending = await confirmations.create(command, context=ctx)
        confirmed = await confirmations.confirm(
            {"approval_id": pending.approval_id, "draft": pending.prepared.review.draft},
            context=ctx,
        )
        assert confirmed.confirmed_draft is not None
        value = {"approval_id": pending.approval_id}
        count = len(transport.writes)
        executor = ReworkExecutionService(database, shared, context=ctx)
        if concurrent:
            reports = await asyncio.gather(
                executor.execute(value),
                ReworkExecutionService(database, shared, context=ctx).execute(value),
            )
            report = next(r for r in reports if r.outcome == "SUCCEEDED")
        else:
            report = await executor.execute(value)
        if operation == "CREATE_LIFECYCLE_REWORK":
            assert report.outcome == "UNKNOWN" and len(transport.writes) == count + 1
            assert (
                await ReworkExecutionService(database, shared, context=ctx).execute(value)
            ).outcome == "UNKNOWN"
            report = await ReworkExecutionService(database, shared, context=ctx).reconcile(value)
            assert (
                report.receipt_evidence is not None and report.receipt_evidence.source == "LOOKUP"
            )
            assert report.receipt_evidence.write_java_trace_id is None
            assert (
                report.receipt_evidence.receipt.model_dump(mode="json", by_alias=True)
                == transport.original
            )
        assert report.outcome == "SUCCEEDED" and report.receipt_evidence is not None
        assert len(transport.writes) == count + 1
        assert await ReworkExecutionService(database, shared, context=ctx).execute(value) == report
        seen.add(operation)
        return report.receipt_evidence.receipt

    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(
                    sync,
                    tables=[
                        Base.metadata.tables[n]
                        for n in (
                            "agent_sessions",
                            "agent_messages",
                            "agent_runs",
                            "rework_confirmation_records",
                        )
                    ],
                )
            )
        async with database.session() as session, session.begin():
            session.add(
                AgentSession(
                    session_id="session-t829-e2e",
                    user_id=identity.user_id,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            await session.flush()
            session.add(
                AgentRun(
                    run_id=ctx.run_id,
                    session_id="session-t829-e2e",
                    status=AgentRunStatus.RUNNING,
                    version_snapshot={},
                )
            )
        golden = (await java.get_delivery_conditions("ORDER-003", identity=identity)).data
        async with fixture.begin() as connection:
            # 仅准备独占业务库初始场景，之后全部状态推进由新受控执行链完成。
            await connection.exec_driver_sql(
                "INSERT INTO production_orders VALUES ('ORDER-T829-E2E','DOM','QUALITY_CHECKING')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO production_tasks(task_id,order_id,status,version) "
                "VALUES ('TASK-T829-E2E','ORDER-T829-E2E','COMPLETED',0)"
            )
            await connection.exec_driver_sql(
                "INSERT INTO quality_issues "
                "VALUES ('ISSUE-T829-E2E','TASK-T829-E2E','COORDINATE_SYSTEM','OPEN','返工执行')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO delivery_records "
                "VALUES ('DELIVERY-T829-E2E','ORDER-T829-E2E','BLOCKED')"
            )
        created = await act("CREATE_LIFECYCLE_REWORK", source_issue_id=ISSUE, reason="首轮返工")
        rework = created.rework_task_id
        for round_number in (1, 2):
            await act("START_REWORK", rework, concurrent=round_number == 1)
            if round_number == 1:
                for action in ("BLOCK_REWORK", "FAIL_REWORK"):
                    await act(action, rework, reason="人工异常说明")
                    await act("RESUME_REWORK", rework, reason="人工恢复说明")
            await act(
                "REGISTER_REWORK_RESULT",
                rework,
                artifact={"artifactId": "成果-T829", "artifactVersion": f"Release-{round_number}"},
                processing_comment="人工实际修正",
                evidence_references=["report:t829-result"],
            )
            if round_number == 1:
                failed = await act(
                    "REGISTER_REWORK_INSPECTION",
                    rework,
                    items=[
                        {
                            "checkItem": "坐标系",
                            "result": "FAILED",
                            "comment": "人工失败检查",
                            "evidenceReferences": ["report:t829-failed"],
                        }
                    ],
                )
                assert failed.status == "RUNNING" and failed.issue_status == "PROCESSING"
            checked = await act(
                "REGISTER_REWORK_INSPECTION",
                rework,
                items=[
                    {
                        "checkItem": "坐标系",
                        "result": "PASSED",
                        "comment": "人工检查通过",
                        "evidenceReferences": ["report:t829-passed"],
                    }
                ],
            )
            assert checked.status == "COMPLETED" and checked.issue_status == "RESOLVED"
            reviewed = await act(
                "SUBMIT_REWORK_REVIEW",
                rework,
                status="REWORK_REQUIRED" if round_number == 1 else "APPROVED",
                review_comment="人工再次复核",
            )
            if round_number == 1:
                assert reviewed.issue_status == "OPEN"
                rework = (
                    await act("CREATE_NEXT_REWORK", rework, reason="第二轮返工")
                ).rework_task_id
            else:
                assert reviewed.issue_status == "CLOSED"
        conditions = (await java.get_delivery_conditions(ORDER, identity=identity)).data
        assert conditions.has_blockers and conditions.tasks[0].production_status == "COMPLETED"
        assert conditions.tasks[0].issues[0].issue.status == "CLOSED"
        assert len(seen) == 9 and len(transport.lookups) == 1
        assert len({r.headers["Idempotency-Key"] for r in transport.writes}) == len(
            transport.writes
        )
        assert (await java.get_delivery_conditions("ORDER-003", identity=identity)).data == golden
    finally:
        await shared.aclose()
        await fixture.dispose()
        await database.dispose()
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
