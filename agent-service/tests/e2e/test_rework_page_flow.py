"""M8.7页面HTTP和Agent引导经生产装配读取及写入真实Java。"""

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from pydantic import AnyHttpUrl
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app import main
from app.clients.business import BusinessHttpClient
from app.database import Base, Database
from app.models import AgentRun, AgentRunStatus, ReworkConfirmationRecord
from app.settings import Settings
from tests.e2e.test_rework_execution import LoseFirstWrite

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

_ORDER = "ORDER-T835-E2E"
_TASK = "TASK-T835-MAIN"
_OTHER_TASK = "TASK-T835-OTHER"
_ISSUE = "ISSUE-T835-MAIN"
_OTHER_ISSUE = "ISSUE-T835-OTHER"
_AGENT_DATABASE = "agent_t835_page_e2e"
_ACTIONS = "/api/agent/rework-actions"
_HEADERS = {"X-User-Id": "reviewer-t835-e2e", "X-User-Role": "REVIEWER"}
_AGENT_TABLES = (
    "agent_sessions",
    "agent_messages",
    "agent_runs",
    "agent_steps",
    "rework_confirmation_records",
    "rework_operation_logs",
)


def _json(response: httpx.Response) -> dict[str, Any]:
    """检查真实端点返回，避免把错误信封当成事实。"""

    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


async def _seed_business(
    admin: asyncpg.Connection, java: httpx.AsyncClient
) -> tuple[str, str]:
    """准备同订单两个独立待开始返工。后续推进全部经过页面审批入口。"""

    async with admin.transaction():
        await admin.execute(
            "INSERT INTO production_orders VALUES ($1,'DOM','QUALITY_CHECKING')", _ORDER
        )
        for task, issue in ((_TASK, _ISSUE), (_OTHER_TASK, _OTHER_ISSUE)):
            await admin.execute(
                "INSERT INTO production_tasks(task_id,order_id,status,version) "
                "VALUES ($1,$2,'COMPLETED',0)",
                task,
                _ORDER,
            )
            await admin.execute(
                "INSERT INTO quality_issues VALUES "
                "($1,$2,'COORDINATE_SYSTEM','OPEN','返工页面联调')",
                issue,
                task,
            )

    async def create(task: str, issue: str) -> str:
        """借Java真实入口建立已有返工，避免测试直接拼装生命周期表。"""

        response = await java.post(
            f"/api/tasks/{task}/reworks",
            json={"expectedVersion": 0, "sourceIssueId": issue, "reason": "页面联调准备"},
            headers={"Idempotency-Key": f"t835-fixture-{task}"},
        )
        result = _json(response)["data"]
        assert result["taskVersion"] == 1
        rework_id = result["reworkTaskId"]
        assert isinstance(rework_id, str)
        return rework_id

    return await create(_TASK, _ISSUE), await create(_OTHER_TASK, _OTHER_ISSUE)


async def test_rework_page_flow_guidance_to_confirmation_and_next_round(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    url = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or url is None:
        pytest.skip("通过make test-rework-page-flow启动独占Java/PostgreSQL")
    assert urlparse(db).hostname == "127.0.0.1"
    assert urlparse(db).path == "/business_service_test_rework_query"
    assert urlparse(url).scheme == "http" and urlparse(url).hostname == "127.0.0.1"
    agent_url = make_url(db).set(database=_AGENT_DATABASE).render_as_string(hide_password=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=agent_url,
        business_service_url=AnyHttpUrl(url),
        knowledge_storage_root=tmp_path / "knowledge-storage",
        model_name=None,
        model_base_url=None,
        model_api_key=None,
        embedding_api_key=None,
    )
    transport = LoseFirstWrite()

    def use_real_java(config: Settings) -> BusinessHttpClient:
        """保留生产Client和真实Java，仅在首个已提交写入后注入丢响应。"""

        return BusinessHttpClient(config, transport=transport)

    monkeypatch.setattr(main, "BusinessHttpClient", use_real_java)
    app = main.create_app(settings)
    # 仅在脚本独占的PostgreSQL实例中创建Agent库。
    admin = await asyncpg.connect(db)
    created = False
    try:
        await admin.execute(f'CREATE DATABASE "{_AGENT_DATABASE}"')
        created = True
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(base_url=url, headers=_HEADERS, timeout=10, trust_env=False) as java,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://agent.test",
                headers=_HEADERS,
            ) as page,
        ):
            database: Database = app.state.database
            async with database.engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: Base.metadata.create_all(
                        sync, tables=[Base.metadata.tables[name] for name in _AGENT_TABLES]
                    )
                )
            golden_path = "/api/orders/ORDER-003/delivery-conditions"
            golden = _json(await java.get(golden_path))["data"]
            first, other = await _seed_business(admin, java)

            async def detail(rework_id: str, *, task: str = _TASK) -> dict[str, Any]:
                """始终重读真实Java详情验证页面写入效果。"""

                response = await java.get(f"/api/tasks/{task}/reworks/{rework_id}")
                data: dict[str, Any] = _json(response)["data"]
                return data

            page_context = {
                "current_system": "production-system", "current_page": "order-detail",
                "order_id": _ORDER, "user_role": "REVIEWER",
            }
            first_turn = _json(await page.post("/api/agent/messages", json={
                "message": "开始返工", "page_context": page_context,
            }))
            guidance = first_turn["result"]
            assert guidance["kind"] == "REWORK_GUIDANCE" and guidance["state"] == "CHOOSE_TARGET"
            assert {(row["task_id"], row["rework_task_id"]) for row in guidance["candidates"]} == {
                (_TASK, first), (_OTHER_TASK, other),
            }
            missing = _json(await page.post("/api/agent/messages", json={
                "message": f"开始返工 {_ORDER} {_TASK} REWORK-T835-MISSING",
                "session_id": first_turn["session_id"], "page_context": page_context,
            }))
            assert missing["result"] == {
                "kind": "REWORK_GUIDANCE", "state": "NOT_FOUND", "order_id": _ORDER,
                "operation": "START_REWORK", "candidates": [], "status": None, "round_number": None,
            }
            wrong_task = await page.post("/api/agent/messages", json={
                "message": f"开始返工 {_ORDER} {_TASK} {other}",
                "session_id": first_turn["session_id"], "page_context": page_context,
            })
            assert wrong_task.status_code == 409, wrong_task.text
            assert wrong_task.json()["code"] == "BUSINESS_CONFLICT"
            selected = _json(await page.post("/api/agent/messages", json={
                "message": f"开始返工 {_ORDER} {_TASK} {first}",
                "session_id": first_turn["session_id"], "page_context": page_context,
            }))["result"]
            assert selected["state"] == "READY" and selected["operation"] == "START_REWORK"
            assert selected["status"] == "PENDING"
            assert selected["candidates"] == [{"task_id": _TASK, "rework_task_id": first}]
            async with database.session() as session:
                count = await session.scalar(select(func.count()).select_from(ReworkConfirmationRecord))
                assert count == 0
                run = await session.get(AgentRun, missing["run_id"])
                assert run is not None and run.status is AgentRunStatus.SUCCEEDED
                assert run.tool_call_count == 2 and run.final_result == missing["result"]
            assert not transport.writes
            assert (await detail(first))["taskVersion"] == 1

            async def preview(
                operation: str, rework_id: str, **materials: object,
            ) -> tuple[str, dict[str, Any]]:
                """请求页面预览并记下本次独立审批身份。"""

                result = _json(await page.post(f"{_ACTIONS}/preview", json={
                    "order_id": _ORDER,
                    "command": {
                        "operation": operation, "task_id": _TASK,
                        "rework_task_id": rework_id, **materials,
                    },
                }))
                return f"{_ACTIONS}/{result['run_id']}/{result['approval_id']}", result

            async def confirm(path: str) -> dict[str, Any]:
                """明确确认保存的原草稿。"""

                return _json(await page.post(f"{path}/confirm", json={"decision": "CONFIRM"}))

            cancelled, _ = await preview("START_REWORK", first)
            assert _json(await page.post(f"{cancelled}/cancel"))["status"] == "CANCELLED"
            assert not transport.writes and (await detail(first))["taskVersion"] == 1
            start, _ = await preview("START_REWORK", first)
            assert start != cancelled and not transport.writes
            assert (await confirm(start))["outcome"] == "UNKNOWN"
            assert len(transport.writes) == 1 and transport.original is not None
            target = {"order_id": _ORDER, "task_id": _TASK, "rework_task_id": first}
            recovered = _json(await page.post(f"{start}/reconcile", json=target))
            assert recovered["outcome"] == "SUCCEEDED"
            assert recovered["operation_id"] == transport.original["operationId"]
            assert len(transport.writes) == len(transport.lookups) == 1
            original_key = transport.writes[0].headers["Idempotency-Key"]
            assert json.loads(transport.lookups[0].content)["idempotencyKey"] == original_key
            assert (await detail(first))["reworkTask"]["status"] == "RUNNING"

            async def apply_interruption(operation: str, expected_status: str, reason: str) -> None:
                """每次异常或恢复经独立审批，回执和状态都以Java提交后读取为准。"""

                before = await detail(first)
                writes_before = len(transport.writes)
                path, card = await preview(operation, first, reason=reason)
                review = card["review"]
                assert review["draft"]["request"]["reason"] == reason
                assert review["draft"]["target"]["task_version"] == before["taskVersion"]
                assert review["expected_effects"]["rework_status_after"] == expected_status
                assert review["expected_effects"]["issue_status_after"] == "PROCESSING"
                assert len(transport.writes) == writes_before
                assert await detail(first) == before

                result = await confirm(path)
                assert result["outcome"] == "SUCCEEDED" and result["operation_id"]
                assert len(transport.writes) == writes_before + 1
                submitted = json.loads(transport.writes[-1].content)
                assert submitted["reason"] == reason
                assert submitted["expectedVersion"] == before["taskVersion"]

                after = await detail(first)
                assert after["taskVersion"] == before["taskVersion"] + 1
                assert after["reworkTask"]["status"] == expected_status
                assert after["issueStatus"] == "PROCESSING"
                assert after["roundNumber"] == before["roundNumber"]
                if expected_status == "RUNNING":
                    assert "REGISTER_REWORK_RESULT" in after["allowedActions"]
                else:
                    assert after["allowedActions"] == ["RESUME_REWORK"]

            await apply_interruption("BLOCK_REWORK", "BLOCKED", "  等待人工核对证据  ")
            obsolete_resume, _ = await preview("RESUME_REWORK", first, reason="先前的阻塞恢复审批")
            await apply_interruption("RESUME_REWORK", "RUNNING", "人工核对完成")
            await apply_interruption("FAIL_REWORK", "FAILED", "成果输入校验失败")

            failed = await detail(first)
            writes_before = len(transport.writes)
            stale_resume = await page.post(f"{obsolete_resume}/confirm", json={"decision": "CONFIRM"})
            assert stale_resume.status_code == 409, stale_resume.text
            assert stale_resume.json()["detail"]["code"] == "APPROVAL_STALE"
            assert len(transport.writes) == writes_before
            assert await detail(first) == failed

            await apply_interruption("RESUME_REWORK", "RUNNING", "人工确认失败原因已处理")

            materials = {
                "artifact": {"artifactId": "坐标系成果", "artifactVersion": "001.0"},
                "processing_comment": "  人工处理坐标系  ",
                "evidence_references": ["report:t835-artifact"],
            }
            old, _ = await preview("REGISTER_REWORK_RESULT", first, **materials)
            register, _ = await preview("REGISTER_REWORK_RESULT", first, **materials)
            assert (await confirm(register))["outcome"] == "SUCCEEDED"
            rejected = await page.post(f"{old}/confirm", json={"decision": "CONFIRM"})
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "APPROVAL_STALE"
            assert len(transport.writes) == 6

            mixed_items = [
                {
                    "checkItem": "坐标系", "result": "PASSED", "comment": "坐标系核对通过",
                    "evidenceReferences": ["report:t835-coordinate"],
                },
                {
                    "checkItem": "范围边界", "result": "FAILED", "comment": "人工核对发现范围偏差",
                    "evidenceReferences": ["report:t835-boundary-failed"],
                },
            ]
            failed_path, failed_card = await preview(
                "REGISTER_REWORK_INSPECTION", first, items=mixed_items,
            )
            assert failed_card["review"]["expected_effects"]["rework_status_after"] == "RUNNING"
            assert (await confirm(failed_path))["outcome"] == "SUCCEEDED"
            failed_check = await detail(first)
            assert failed_check["reworkTask"]["status"] == "RUNNING"
            assert failed_check["issueStatus"] == "PROCESSING" and failed_check["review"] is None
            assert failed_check["inspection"]["result"] == "FAILED"
            assert failed_check["inspection"]["items"] == mixed_items
            assert "SUBMIT_REWORK_REVIEW" not in failed_check["allowedActions"]

            blocked_review = await page.post(f"{_ACTIONS}/preview", json={
                "order_id": _ORDER,
                "command": {
                    "operation": "SUBMIT_REWORK_REVIEW", "task_id": _TASK, "rework_task_id": first,
                    "status": "APPROVED", "review_comment": "尝试提前复核",
                },
            })
            assert blocked_review.status_code == 409, blocked_review.text
            error = blocked_review.json()["detail"]
            assert error["code"] == "BUSINESS_CONFLICT" and set(error) == {"code", "trace_id"}
            assert len(transport.writes) == 7
            assert await detail(first) == failed_check

            inspect, inspection_card = await preview("REGISTER_REWORK_INSPECTION", first, items=[
                {
                    "checkItem": "坐标系", "result": "PASSED", "comment": "人工核对通过",
                    "evidenceReferences": ["report:t835-inspection"],
                },
                {
                    "checkItem": "范围边界", "result": "PASSED", "comment": "重新核对范围通过",
                    "evidenceReferences": ["report:t835-boundary-passed"],
                },
            ])
            bound_artifact = inspection_card["bound_materials"]["processing"]["artifact"]
            assert bound_artifact == materials["artifact"]
            assert (await confirm(inspect))["outcome"] == "SUCCEEDED"
            inspected = await detail(first)
            assert inspected["reworkTask"]["status"] == "COMPLETED"
            assert inspected["issueStatus"] == "RESOLVED" and inspected["review"] is None
            assert inspected["inspection"]["result"] == "PASSED"
            assert (
                inspected["inspection"]["processingRevision"]
                == failed_check["inspection"]["processingRevision"]
            )
            inspection_history = _json(await java.get(
                f"/api/tasks/{_TASK}/reworks/{first}/inspections", params={"limit": 2},
            ))["data"]
            assert inspection_history["records"] == [failed_check["inspection"], inspected["inspection"]]

            review, review_card = await preview(
                "SUBMIT_REWORK_REVIEW", first, status="REWORK_REQUIRED", review_comment="还需检查范围",
            )
            assert review_card["bound_materials"]["inspection"] == inspected["inspection"]
            assert (await confirm(review))["outcome"] == "SUCCEEDED"
            returned = await detail(first)
            assert returned["review"]["status"] == "REWORK_REQUIRED"
            assert returned["issueStatus"] == "OPEN"
            next_path, next_card = await preview("CREATE_NEXT_REWORK", first, reason="第二轮检查范围")
            assert next_card["previous_review"] == returned["review"]
            next_result = await confirm(next_path)
            assert next_result["outcome"] == "SUCCEEDED"
            next_id = next_result["next_rework_task_id"]
            assert isinstance(next_id, str) and next_id != first
            successor = await detail(next_id)
            assert successor["roundNumber"] == 2 and successor["previousReworkTaskId"] == first
            assert successor["reworkTask"]["status"] == "PENDING"
            assert (await detail(first))["review"] == returned["review"]
            assert (await detail(other, task=_OTHER_TASK))["taskVersion"] == 1
            assert len(transport.writes) == 10 and len(transport.lookups) == 1
            assert _json(await java.get(golden_path))["data"] == golden
    finally:
        try:
            if created:
                await admin.execute(f'DROP DATABASE "{_AGENT_DATABASE}"')
        finally:
            await admin.close()
