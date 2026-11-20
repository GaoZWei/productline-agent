"""T839真实Java幂等、最终版本冲突、越权归属及数据库故障回滚验收。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest

from app import main
from app.clients.business import BusinessHttpClient
from app.models import ReworkConfirmationRecord
from app.settings import Settings
from tests.e2e.rework_acceptance_fixtures import (
    AcceptancePreview,
    ReworkAcceptance,
    inspection_materials,
    isolated_rework,
    result_materials,
)
from tests.e2e.test_rework_acceptance_flows import endpoints

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


class AcceptanceTransport(httpx.AsyncBaseTransport):
    """真实网络传输，只同步竞争或丢弃已提交响应，不伪造Java成功。"""

    def __init__(self) -> None:
        """每个用例独占传输与日志，写请求和只读核对分开记录。"""

        self.inner = httpx.AsyncHTTPTransport()
        self.writes: list[httpx.Request] = []
        self.lookups: list[httpx.Request] = []
        self.barrier = asyncio.Event()
        self.compete = False
        self.waiting = 0
        self.lose_next = False
        self.lost_receipt: dict[str, Any] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """竞争者都经确认并到达写边界后才放行，超时必须失败而非绕过屏障。"""

        if request.method == "POST":
            if request.url.path.endswith("/operations/query"):
                self.lookups.append(request)
            else:
                self.writes.append(request)
                if self.compete and request.url.path.endswith(("/block", "/fail")):
                    self.waiting += 1
                    if self.waiting == 2:
                        self.barrier.set()
                    await asyncio.wait_for(self.barrier.wait(), timeout=2)
        response = await self.inner.handle_async_request(request)
        if (
            self.lose_next
            and request.method == "POST"
            and not request.url.path.endswith("/operations/query")
        ):
            self.lose_next = False
            assert response.status_code == 200
            self.lost_receipt = json.loads(await response.aread())["data"]
            await response.aclose()
            raise httpx.ReadTimeout(
                "simulated response loss after real Java commit", request=request
            )
        return response

    async def aclose(self) -> None:
        """随生产Client生命周期释放测试传输。"""

        await self.inner.aclose()


def install_transport(monkeypatch: pytest.MonkeyPatch, transport: AcceptanceTransport) -> None:
    """仅在当前测试装配生产Client时替换传输，退出用例由pytest恢复。"""

    def client(settings: Settings) -> BusinessHttpClient:
        """读取与写入仍经过同一真实Client和Java服务。"""

        return BusinessHttpClient(settings, transport=transport)

    monkeypatch.setattr(main, "BusinessHttpClient", client)


async def execution_key(fixture: ReworkAcceptance, preview: AcceptancePreview) -> str:
    """仅从测试Agent自有审批表取原键，用来证明重放和核对不换键。"""

    async with fixture.database.session() as session:
        row = await session.get(ReworkConfirmationRecord, preview.approval_id)
        assert row is not None and row.execution_key is not None
        return row.execution_key


async def test_rework_acceptance_replay_and_final_version_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同键只重放原回执，异内容冲突，两个独立已确认动作在Java最终版本处互斥。"""

    db, java = endpoints()
    transport = AcceptanceTransport()
    install_transport(monkeypatch, transport)
    async with isolated_rework(db, java, case="T839-REPLAY", storage_root=tmp_path) as fixture:
        start = await fixture.preview("START_REWORK")
        accepted = await fixture.confirm(start)
        key = await execution_key(fixture, start)
        original = json.loads(transport.writes[0].content)
        path = f"/api/tasks/{fixture.ids.task}/reworks/{fixture.rework_id}/start"
        first_receipt = transport.writes[0]
        assert first_receipt.headers["Idempotency-Key"] == key
        replay1 = await fixture.java.post(path, json=original, headers={"Idempotency-Key": key})
        replay2 = await fixture.java.post(path, json=original, headers={"Idempotency-Key": key})
        assert replay1.status_code == replay2.status_code == 200
        assert replay1.json()["data"] == replay2.json()["data"]
        assert replay1.json()["data"]["operationId"] == accepted.operation_id
        assert replay1.json()["data"]["taskVersion"] == 2
        changed = await fixture.java.post(
            path, json={"expectedVersion": 2}, headers={"Idempotency-Key": key}
        )
        assert changed.status_code == 409 and (await fixture.detail()).task_version == 2
        one = await fixture.preview("BLOCK_REWORK", reason="并发阻塞")
        two = await fixture.preview("FAIL_REWORK", reason="并发失败")
        transport.compete = True
        responses = await asyncio.gather(
            *(
                fixture.page.post(
                    f"{fixture.approval_path(item)}/confirm", json={"decision": "CONFIRM"}
                )
                for item in (one, two)
            )
        )
        assert transport.waiting == 2 and all(response.status_code == 200 for response in responses)
        outcomes = [response.json() for response in responses]
        assert sorted(item["outcome"] for item in outcomes) == ["SUCCEEDED", "UNKNOWN"]
        loser = next(item for item in outcomes if item["outcome"] == "UNKNOWN")
        assert loser["error_code"] == "BUSINESS_CONFLICT" and loser["operation_id"] is None
        result = await fixture.detail()
        assert result.task_version == 3 and result.rework_task.status in {"BLOCKED", "FAILED"}
        assert len(transport.writes) == 3
        assert len({request.headers["Idempotency-Key"] for request in transport.writes}) == 3
        later_replay = await fixture.java.post(
            path, json=original, headers={"Idempotency-Key": key}
        )
        assert (
            later_replay.status_code == 200
            and later_replay.json()["data"] == replay1.json()["data"]
        )
        assert await fixture.detail() == result


async def test_rework_acceptance_permissions_binding_and_lost_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """拒绝越权及错误归属，真正丢响应后只能按原键核对，不能重发。"""

    db, java = endpoints()
    transport = AcceptanceTransport()
    install_transport(monkeypatch, transport)
    async with isolated_rework(db, java, case="T839-OWNERSHIP", storage_root=tmp_path) as fixture:
        original = await fixture.detail()
        command = {
            "operation": "START_REWORK",
            "task_id": fixture.ids.task,
            "rework_task_id": fixture.rework_id,
        }
        denied = await fixture.page.post(
            "/api/agent/rework-actions/preview",
            json={"order_id": fixture.ids.order, "command": command},
            headers={"X-User-Role": "VIEWER"},
        )
        assert denied.status_code == 403
        wrong_order = await fixture.page.post(
            "/api/agent/rework-actions/preview", json={"order_id": "ORDER-003", "command": command}
        )
        # 页面定位不属于原订单时隐藏资源，Java路径父子归属冲突仍单独验证409。
        assert wrong_order.status_code == 404
        assert wrong_order.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"
        wrong_task = await fixture.java.get(f"/api/tasks/TASK-003/reworks/{fixture.rework_id}")
        assert wrong_task.status_code == 409
        preview = await fixture.preview("START_REWORK")
        address = fixture.approval_path(preview)
        other = await fixture.page.post(
            f"{address}/confirm",
            json={"decision": "CONFIRM"},
            headers={"X-User-Id": "other-reviewer"},
        )
        assert other.status_code == 404
        assert await fixture.detail() == original and not transport.writes
        transport.lose_next = True
        response = await fixture.page.post(f"{address}/confirm", json={"decision": "CONFIRM"})
        assert response.status_code == 200 and response.json()["outcome"] == "UNKNOWN"
        assert response.json()["operation_id"] is None
        key = await execution_key(fixture, preview)
        assert (await fixture.detail()).task_version == 2
        assert (
            await fixture.page.post(f"{address}/confirm", json={"decision": "CONFIRM"})
        ).status_code == 409
        target = {
            "order_id": fixture.ids.order,
            "task_id": fixture.ids.task,
            "rework_task_id": fixture.rework_id,
        }
        wrong_target = await fixture.page.post(
            f"{address}/reconcile", json={**target, "task_id": "TASK-003"}
        )
        assert wrong_target.status_code == 404 and not transport.lookups
        for _ in range(2):
            recovered = await fixture.page.post(f"{address}/reconcile", json=target)
            assert recovered.status_code == 200 and recovered.json()["outcome"] == "SUCCEEDED"
            assert transport.lost_receipt is not None
            assert recovered.json()["operation_id"] == transport.lost_receipt["operationId"]
        assert len(transport.writes) == len(transport.lookups) == 1
        assert json.loads(transport.lookups[0].content)["idempotencyKey"] == key
        async with fixture.database.session() as session:
            saved = await session.get(ReworkConfirmationRecord, preview.approval_id)
            assert saved is not None and saved.status == "SUCCEEDED"
            evidence = saved.snapshot["receipt_evidence"]
            assert evidence["source"] == "LOOKUP" and evidence["write_java_trace_id"] is None
            assert evidence["lookup_java_trace_id"] is not None


async def test_rework_acceptance_receipt_failure_rolls_back_all_business_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅在独占库给本任务回执插入注入错误，检查/问题/版本/审计必须整体回滚。"""

    db, java = endpoints()
    transport = AcceptanceTransport()
    install_transport(monkeypatch, transport)
    async with isolated_rework(db, java, case="T839-ROLLBACK", storage_root=tmp_path) as fixture:
        await fixture.apply("START_REWORK")
        before = await fixture.apply("REGISTER_REWORK_RESULT", **result_materials())
        preview = await fixture.preview("REGISTER_REWORK_INSPECTION", **inspection_materials())
        admin = await asyncpg.connect(db)
        try:
            await admin.execute("""
                CREATE FUNCTION acceptance_fail_receipt() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.task_id = 'TASK-ACCEPT-T839-ROLLBACK'
                       AND NEW.operation_type = 'REGISTER_REWORK_INSPECTION' THEN
                        RAISE EXCEPTION 'isolated acceptance failure' USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END; $$;
                CREATE TRIGGER acceptance_fail_receipt BEFORE INSERT ON rework_operation_receipts
                FOR EACH ROW EXECUTE FUNCTION acceptance_fail_receipt();
            """)
            response = await fixture.page.post(
                f"{fixture.approval_path(preview)}/confirm", json={"decision": "CONFIRM"}
            )
            assert response.status_code == 200 and response.json()["outcome"] == "UNKNOWN"
            assert response.json()["operation_id"] is None
            key = await execution_key(fixture, preview)
            assert await fixture.detail() == before
            assert await fixture.history("inspections") == []
            for table, field, value in (
                ("rework_operation_receipts", "idempotency_key", key),
                ("idempotency_records", "idempotency_key", key),
            ):
                assert (
                    await admin.fetchval(f"SELECT count(*) FROM {table} WHERE {field}=$1", value)
                    == 0
                )
            assert (
                await admin.fetchval(
                    "SELECT count(*) FROM operation_logs WHERE target_id=$1 "
                    "AND operation_type='REGISTER_REWORK_INSPECTION'",
                    fixture.ids.task,
                )
                == 0
            )
        finally:
            try:
                await admin.execute(
                    "DROP TRIGGER IF EXISTS acceptance_fail_receipt ON rework_operation_receipts; "
                    "DROP FUNCTION IF EXISTS acceptance_fail_receipt();"
                )
            finally:
                await admin.close()
        # 移除故障后查无回执仍保持未知，不释放原键或自动再次提交。
        target = {
            "order_id": fixture.ids.order,
            "task_id": fixture.ids.task,
            "rework_task_id": fixture.rework_id,
        }
        checked = await fixture.page.post(
            f"{fixture.approval_path(preview)}/reconcile", json=target
        )
        assert checked.status_code == 200 and checked.json()["outcome"] == "UNKNOWN"
        assert json.loads(transport.lookups[-1].content)["idempotencyKey"] == key
        assert len(transport.writes) == 3 and len(transport.lookups) == 1
        assert await fixture.detail() == before
