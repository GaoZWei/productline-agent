"""T824隔离Java/PostgreSQL真实联调，确认Store仍为明确Fake，不冒充持久化恢复。"""

import json
import os
from urllib.parse import urlparse

import httpx
import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import create_async_engine

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode
from app.schemas.business import BusinessIdentity
from app.schemas.rework import CreateLifecycleReworkRequest, ReworkVersionRequest
from app.schemas.rework_operation_query import ReworkOperationQueryRequest
from app.settings import Settings
from app.tools.rework_operation_query import QueryReworkOperationTool
from app.tools.rework_write import create_rework_write_tool_registry
from tests.integration.tools.test_rework_write_tools import CASES, FakeStore, context, snapshot

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]
TASK = "TASK-T824-E2E"
ISSUE = "ISSUE-T824-E2E"
BASE = f"/api/tasks/{TASK}/reworks"


class LoseFirstWriteResponse(httpx.AsyncBaseTransport):
    """真实Java已提交后丢弃首次写响应，不能用MockTransport伪造业务成功。"""

    def __init__(self) -> None:
        """网络连接只由本测试创建与关闭，记录请求用于证明没有重发。"""

        self.inner = httpx.AsyncHTTPTransport()
        self.calls: list[httpx.Request] = []
        self.original: dict[str, object] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """等待真实Java成功回执完整返回后模拟接收端丢失结果。"""

        self.calls.append(request)
        response = await self.inner.handle_async_request(request)
        if request.method == "POST" and request.url.path == BASE:
            assert response.status_code == 200
            self.original = json.loads(await response.aread())["data"]
            await response.aclose()
            raise httpx.ReadTimeout("simulated loss after actual Java commit", request=request)
        return response

    async def aclose(self) -> None:
        """关闭真实传输连接池，不留下后台Java请求。"""

        await self.inner.aclose()


async def test_real_committed_write_loss_and_save_conflict_are_reconciled_without_rewriting() -> (
    None
):
    database_url = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    business_url = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if database_url is None or business_url is None:
        pytest.skip("需要通过make test-rework-query-e2e启动独占Java和PostgreSQL")
    database_address, business_address = urlparse(database_url), urlparse(business_url)
    assert database_address.hostname == "127.0.0.1"
    assert database_address.path == "/business_service_test_rework_query"
    assert business_address.scheme == "http" and business_address.hostname == "127.0.0.1"
    settings = Settings(
        _env_file=None, environment="test", business_service_url=AnyHttpUrl(business_url)
    )
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://", 1))
    connection = await engine.connect()
    transport = LoseFirstWriteResponse()
    shared = BusinessHttpClient(settings, transport=transport)
    client = ReworkHttpClient(shared)
    golden_sql = """
        SELECT 'order:' || to_jsonb(o)::text AS value
        FROM production_orders o WHERE order_id='ORDER-003'
        UNION ALL SELECT 'task:' || to_jsonb(t)::text
        FROM production_tasks t WHERE task_id='TASK-003'
        UNION ALL SELECT 'issue:' || to_jsonb(q)::text
        FROM quality_issues q WHERE task_id='TASK-003'
        UNION ALL SELECT 'rework:' || to_jsonb(r)::text
        FROM rework_tasks r WHERE task_id='TASK-003'
        UNION ALL SELECT 'review:' || to_jsonb(r)::text
        FROM review_records r WHERE issue_id='ISSUE-001'
        UNION ALL SELECT 'delivery:' || to_jsonb(d)::text
        FROM delivery_records d WHERE order_id='ORDER-003' ORDER BY 1
    """
    try:
        golden_before = (await connection.exec_driver_sql(golden_sql)).all()
        # 仅测试准备数据直写本次独占库，产品Python仍只通过Java获取业务事实。
        await connection.exec_driver_sql(
            "INSERT INTO production_orders VALUES ('ORDER-T824-E2E','DOM','QUALITY_CHECKING')"
        )
        await connection.exec_driver_sql(
            "INSERT INTO production_tasks(task_id,order_id,status,version) "
            "VALUES ($1,'ORDER-T824-E2E','COMPLETED',0)",
            (TASK,),
        )
        await connection.exec_driver_sql(
            "INSERT INTO quality_issues VALUES ($1,$2,'COORDINATE_SYSTEM','OPEN','隔离核对夹具')",
            (ISSUE, TASK),
        )
        await connection.commit()
        value = snapshot(CASES[0]).model_copy(
            update={
                "task_id": TASK,
                "task_version": 0,
                "source_issue_id": ISSUE,
                "idempotency_key": "key-t824-e2e-first",
                "request": CreateLifecycleReworkRequest(
                    source_issue_id=ISSUE, expected_version=0, reason="人工确认"
                ),
            }
        )
        store = FakeStore(value)
        tool_input = {"approval_id": value.approval_id, "idempotency_key": value.idempotency_key}
        written = (
            await create_rework_write_tool_registry(client, store)
            .get("create_lifecycle_rework")
            .execute(tool_input, context())
        )
        assert written.error is not None and written.error.code is ToolErrorCode.TOOL_TIMEOUT
        assert not written.error.retryable and store.saved == []
        matched = await QueryReworkOperationTool(client, store).execute(
            tool_input, context("REWORK_READ")
        )
        assert matched.data is not None and matched.data.outcome == "MATCHED_RECEIPT"
        assert matched.data.receipt is not None
        assert matched.data.receipt.model_dump(mode="json", by_alias=True) == transport.original
        first = matched.data.receipt
        assert (
            await connection.exec_driver_sql(
                "SELECT version FROM production_tasks WHERE task_id=$1", (TASK,)
            )
        ).scalar_one() == 1

        # 第二次真实写入成功，但确认Store拒绝保存，核对仍不能改写确认终态或重发。
        started_value = snapshot().model_copy(
            update={
                "task_id": TASK,
                "task_version": 1,
                "source_issue_id": ISSUE,
                "rework_task_id": first.rework_task_id,
                "idempotency_key": "key-t824-e2e-start",
                "request": ReworkVersionRequest(expected_version=1),
            }
        )
        start_store = FakeStore(started_value)
        start_store.allow_save = False
        start_input = {
            "approval_id": started_value.approval_id,
            "idempotency_key": started_value.idempotency_key,
        }
        failed_save = (
            await create_rework_write_tool_registry(client, start_store)
            .get("start_rework")
            .execute(start_input, context())
        )
        assert (
            failed_save.error is not None
            and failed_save.error.code is ToolErrorCode.BUSINESS_CONFLICT
        )
        start_result = await QueryReworkOperationTool(client, start_store).execute(
            start_input, context("REWORK_READ")
        )
        assert start_result.data is not None and start_result.data.receipt is not None
        assert (
            start_result.data.outcome == "MATCHED_RECEIPT"
            and start_result.data.receipt.status == "RUNNING"
        )
        assert start_store.saved == [] and start_store.snapshot == started_value

        # 后来状态变化不能重建首轮创建的PENDING原结果。其他用户仍查不到此回执。
        original = await QueryReworkOperationTool(client, store).execute(
            tool_input, context("REWORK_READ")
        )
        assert (
            original.data is not None
            and original.data.receipt == first
            and first.status == "PENDING"
        )
        absent = await client.query_operation(
            TASK,
            ReworkOperationQueryRequest(idempotency_key=value.idempotency_key),
            identity=BusinessIdentity(user_id="reviewer-other", role="REVIEWER"),
            trace_id="trace-e2e-query-other",
        )
        assert not absent.data.found and absent.data.receipt is None
        unknown_value = value.model_copy(update={"idempotency_key": "key-t824-e2e-unknown"})
        unknown = await QueryReworkOperationTool(client, FakeStore(unknown_value)).execute(
            {
                "approval_id": unknown_value.approval_id,
                "idempotency_key": unknown_value.idempotency_key,
            },
            context("REWORK_READ"),
        )
        assert (
            unknown.data is not None
            and unknown.data.outcome == "UNKNOWN"
            and unknown.data.receipt is None
        )
        writes = [r for r in transport.calls if not r.url.path.endswith("/operations/query")]
        queries = [r for r in transport.calls if r.url.path.endswith("/operations/query")]
        assert len(writes) == 2 and all("Idempotency-Key" not in r.headers for r in queries)
        for sql, expected in [
            ("SELECT version FROM production_tasks WHERE task_id=$1", 2),
            ("SELECT count(*) FROM rework_tasks WHERE task_id=$1", 1),
            ("SELECT count(*) FROM rework_operation_receipts WHERE task_id=$1", 2),
            ("SELECT count(*) FROM operation_logs WHERE target_id=$1", 2),
        ]:
            assert (await connection.exec_driver_sql(sql, (TASK,))).scalar_one() == expected
        assert (await connection.exec_driver_sql(golden_sql)).all() == golden_before
    finally:
        await shared.aclose()
        await connection.close()
        await engine.dispose()
