"""返工页面HTTP与真实Agent持久化，Java边界由可控HTTP夹具提供。"""

import asyncio
import json
from functools import partial
from typing import NoReturn

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.api.rework_actions import router
from app.database import Database
from app.models import AgentRun, ReworkConfirmationRecord, ReworkOperationLog
from app.observability import TraceIdMiddleware
from app.services.observed_rework import ObservedReworkService
from app.services.rework_confirmation import ReworkConfirmationError
from app.settings import Settings
from app.tools.readonly import create_read_tool_registry
from app.versioning import build_run_version_snapshot
from tests.integration.tools.test_rework_write_tools import CASES, REWORK, TASK, Case
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_rework_draft_workflow import ORDER, TRACE, command, nested
from tests.test_rework_execution_persistence import ExecutionHarness

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_PATH = "/api/agent/rework-actions"
_HEADERS = {"X-User-Id": "reviewer-test", "X-User-Role": "REVIEWER", "X-Trace-Id": TRACE}


def page_client(database: Database, java: ExecutionHarness) -> httpx.AsyncClient:
    """仅装配页面路由，使用真实Wire格式、数据库和Tool链。"""

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(TraceIdMiddleware)
    settings = Settings(_env_file=None, environment="test")
    app.state.database = database
    app.state.business_client = java.http
    app.state.settings = settings
    app.state.run_version_snapshot = build_run_version_snapshot(
        settings, create_read_tool_registry(java.http)
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://agent.test", headers=_HEADERS
    )


async def preview(client: httpx.AsyncClient, case: Case) -> str:
    """取得实际审批地址，同时验证公开响应只含审查信息。"""

    result = await client.post(f"{_PATH}/preview", json={"order_id": ORDER, "command": command(case)})
    assert result.status_code == 200, result.text
    payload = result.json()
    fields = {"run_id", "approval_id", "order_id", "expires_at", "review"}
    if case.operation in {"REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW"}:
        fields.add("bound_materials")
    if case.operation == "CREATE_NEXT_REWORK":
        fields.add("previous_review")
        assert payload["previous_review"]["status"] == "REWORK_REQUIRED"
    assert set(payload) == fields
    assert payload["review"]["draft"]["operation"] == case.operation
    return f"{_PATH}/{payload['run_id']}/{payload['approval_id']}"


@pytest.mark.parametrize("case", CASES[1:], ids=lambda case: case.operation)
async def test_rework_actions_api_preview_and_concurrent_confirmation_write_once(
    migrated_database_url: str, case: Case
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness(case)
    try:
        async with page_client(database, java) as client:
            path = await preview(client, case)
            assert not java.writes
            decision = {"decision": "CONFIRM"}
            results = await asyncio.gather(*(
                client.post(f"{path}/confirm", json=decision) for _ in range(2)
            ))
            assert sorted(res.status_code for res in results)[0] == 200
            success = [res.json() for res in results if res.status_code == 200]
            assert len(success) == 1 and success[0]["outcome"] == "SUCCEEDED"
            assert success[0]["operation_id"] == java.raw_receipt["operationId"]
            if case.operation == "CREATE_NEXT_REWORK":
                assert success[0]["next_rework_task_id"] == java.raw_receipt["reworkTaskId"]
            else:
                assert success[0]["next_rework_task_id"] is None
            assert len(java.writes) == 1
        async with database.session() as session:
            row = await session.scalar(select(ReworkConfirmationRecord))
            assert row is not None and row.status == "SUCCEEDED"
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


@pytest.mark.parametrize("action", ["cancel", "owner", "wrong-run", "stale", "unknown"])
async def test_rework_actions_api_confirmation_respects_original_binding(
    migrated_database_url: str, action: str
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness()
    try:
        async with page_client(database, java) as client:
            path = await preview(client, java.case)
            decision = {"decision": "CONFIRM"}
            headers = {}
            if action == "cancel":
                stopped = await client.post(f"{path}/cancel")
                assert stopped.status_code == 200 and stopped.json()["status"] == "CANCELLED"
            elif action == "owner":
                headers = {"X-User-Id": "another-reviewer"}
            elif action == "wrong-run":
                path = f"{_PATH}/another-run/{path.rsplit('/', 1)[1]}"
            elif action == "stale":
                java.data[0]["version"] = 5
                nested(java.data[1], "tasks", 0)["taskVersion"] = 5
                java.data[2]["taskVersion"] = 5
            else:
                java.lose_response = True
            result = await client.post(f"{path}/confirm", json=decision, headers=headers)
            if action == "unknown":
                assert result.status_code == 200 and result.json()["outcome"] == "UNKNOWN"
                assert result.json()["operation_id"] is None
                assert (await client.post(f"{path}/confirm", json=decision)).status_code == 409
                assert len(java.writes) == 1 and not java.lookups
            else:
                assert result.status_code == (409 if action == "stale" else 404)
                assert not java.writes and not java.lookups
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


async def test_rework_actions_api_rejects_bad_material_and_unavailable_operations(
    migrated_database_url: str,
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness()
    try:
        async with page_client(database, java) as client:
            valid = {"order_id": ORDER, "command": command(java.case)}
            invalid = [
                {"order_id": ORDER, "command": command(CASES[0])},
                {"order_id": ORDER, "command": {**command(CASES[5]), "evidence_references": []}},
                {"order_id": ORDER, "command": {**command(java.case), "expected_version": 4}},
            ]
            for body in invalid:
                result = await client.post(f"{_PATH}/preview", json=body)
                assert result.status_code == 400
                assert set(result.json()["detail"]) == {"code", "trace_id"}
            denied = await client.post(f"{_PATH}/preview", json=valid, headers={"X-User-Role": "VIEWER"})
            assert denied.status_code == 403 and not java.calls
            assert (await client.post(
                f"{_PATH}/preview", json={**valid, "order_id": "ORDER-OTHER"}
            )).status_code == 404
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(AgentRun)) == 1
            assert await session.scalar(select(func.count()).select_from(ReworkConfirmationRecord)) == 0
        assert not java.writes
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


@pytest.mark.parametrize(
    ("case", "disposition", "rework_status", "issue_status", "delivery"),
    [
        (CASES[6], "PASSED", "COMPLETED", "RESOLVED", "NONE"),
        (CASES[6], "FAILED", "RUNNING", "PROCESSING", "NONE"),
        (CASES[7], "APPROVED", "COMPLETED", "CLOSED", "RECHECK_ONLY"),
        (CASES[7], "REJECTED", "COMPLETED", "OPEN", "NONE"),
        (CASES[7], "REWORK_REQUIRED", "COMPLETED", "OPEN", "NONE"),
    ],
)
async def test_rework_actions_api_quality_disposition_and_binding(
    migrated_database_url: str,
    case: Case,
    disposition: str,
    rework_status: str,
    issue_status: str,
    delivery: str,
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness(case)
    try:
        body = command(case)
        if case.operation == "REGISTER_REWORK_INSPECTION":
            items = body["items"]
            assert isinstance(items, list)
            if disposition == "FAILED":
                items.append({
                    "checkItem": "范围边界",
                    "result": "FAILED",
                    "comment": "  实际失败证据  ",
                    "evidenceReferences": ["report:manual-2"],
                })
        else:
            body["status"] = disposition
        java.raw_receipt.update(status=rework_status, issueStatus=issue_status)
        async with page_client(database, java) as client:
            response = await client.post(f"{_PATH}/preview", json={"order_id": ORDER, "command": body})
            assert response.status_code == 200, response.text
            payload = response.json()
            assert not java.writes
            review = payload["review"]
            assert review["expected_effects"] == {
                "production_status_after": "COMPLETED",
                "rework_status_after": rework_status,
                "issue_status_after": issue_status,
                "delivery_effect": delivery,
            }
            draft = review["draft"]
            assert draft["target"]["processing_revision"] == 2
            assert draft["request"]["processingRevision"] == 2
            assert payload["bound_materials"]["processing"] == java.data[2]["processing"]
            if case.operation == "SUBMIT_REWORK_REVIEW":
                assert draft["request"]["inspectionId"] == "CHECK-T827-CURRENT"
                assert draft["request"]["status"] == disposition
                assert payload["bound_materials"]["inspection"] == java.data[2]["inspection"]
            else:
                assert payload["bound_materials"]["inspection"] is None
            path = f"{_PATH}/{payload['run_id']}/{payload['approval_id']}/confirm"
            result = await client.post(path, json={"decision": "CONFIRM"})
            assert result.status_code == 200 and result.json()["outcome"] == "SUCCEEDED"
            assert len(java.writes) == 1
            assert json.loads(java.writes[0].content) == draft["request"]
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


@pytest.mark.parametrize("case", CASES[6:8], ids=lambda case: case.operation)
async def test_rework_actions_api_changed_quality_evidence_invalidates_original_preview(
    migrated_database_url: str, case: Case
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness(case)
    try:
        async with page_client(database, java) as client:
            path = await preview(client, case)
            # 即使标识未变，也不能沿用已经看到的旧证据。
            if case.operation == "REGISTER_REWORK_INSPECTION":
                nested(java.data[2], "processing")["evidenceReferences"] = ["report:changed"]
            else:
                nested(java.data[2], "inspection", "items", 0)["evidenceReferences"] = ["report:changed"]
            result = await client.post(f"{path}/confirm", json={"decision": "CONFIRM"})
            assert result.status_code == 409 and result.json()["detail"]["code"] == "APPROVAL_STALE"
            assert not java.writes
        async with database.session() as session:
            row = await session.scalar(select(ReworkConfirmationRecord))
            assert row is not None and row.status == "STALE"
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


async def test_rework_actions_api_reconcile_next_round_uses_only_original_key(
    migrated_database_url: str,
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness(CASES[8])
    try:
        async with page_client(database, java) as client:
            path = await preview(client, java.case)
            target = {"order_id": ORDER, "task_id": TASK, "rework_task_id": REWORK}
            waiting = await client.post(f"{path}/reconcile", json=target)
            assert waiting.status_code == 200 and waiting.json()["outcome"] == "WAITING_CONFIRMATION"
            assert not java.writes and not java.lookups
            java.lose_response = True
            result = await client.post(f"{path}/confirm", json={"decision": "CONFIRM"})
            assert result.status_code == 200 and result.json()["outcome"] == "UNKNOWN"
            assert result.json()["error_code"] is not None
            mismatch = await client.post(f"{path}/reconcile", json={**target, "order_id": "ORDER-OTHER"})
            assert mismatch.status_code == 404 and not java.lookups
            java.found = False
            missing = await client.post(f"{path}/reconcile", json=target)
            assert missing.status_code == 200 and missing.json()["outcome"] == "UNKNOWN"
            java.found = True
            success = await client.post(f"{path}/reconcile", json=target)
            assert success.status_code == 200 and success.json()["outcome"] == "SUCCEEDED"
            assert success.json()["next_rework_task_id"] == java.raw_receipt["reworkTaskId"]
            assert success.json()["operation_id"] == java.raw_receipt["operationId"]
            repeated = await client.post(f"{path}/reconcile", json=target)
            assert repeated.json() == success.json()
            assert len(java.writes) == 1 and len(java.lookups) == 2
            key = java.writes[0].headers["Idempotency-Key"]
            assert all(json.loads(item.content)["idempotencyKey"] == key for item in java.lookups)
            assert key not in success.text
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


async def test_rework_actions_api_reconcile_cancelled_approval_never_queries_java(
    migrated_database_url: str,
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness()
    try:
        async with page_client(database, java) as client:
            path = await preview(client, java.case)
            assert (await client.post(f"{path}/cancel")).status_code == 200
            result = await client.post(
                f"{path}/reconcile", json={"order_id": ORDER, "task_id": TASK, "rework_task_id": REWORK}
            )
            assert result.status_code == 200 and result.json()["outcome"] == "NOT_SUBMITTED"
            assert not java.writes and not java.lookups
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()


@pytest.mark.parametrize("state", ["WAITING_CONFIRMATION", "CONFIRMED", "EXECUTING"])
async def test_rework_actions_api_reconcile_expired_interrupted_confirmation(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness()
    original_key: str | None = None

    async def interrupt_execution(service: ObservedReworkService, value: dict[str, str]) -> NoReturn:
        """在确认已持久化后，模拟执行领取前或领取后、提交前的中断。"""

        nonlocal original_key
        snapshot = await service.get_approval(value["approval_id"])
        assert snapshot.status == "CONFIRMED"
        if state == "EXECUTING":
            execution = await service._executor(service._context).store.claim(snapshot)
            assert execution is not None and execution.execution_key is not None
            original_key = execution.execution_key
        raise ReworkConfirmationError("UPSTREAM_UNAVAILABLE", status_code=503)

    monkeypatch.setattr(
        "app.api.rework_actions.ObservedReworkService",
        partial(ObservedReworkService, now=lambda: java.now),
    )
    monkeypatch.setattr(ObservedReworkService, "execute", interrupt_execution)
    try:
        async with page_client(database, java) as client:
            path = await preview(client, java.case)
            approval_id = path.rsplit("/", 1)[-1]
            target = {"order_id": ORDER, "task_id": TASK, "rework_task_id": REWORK}
            if state != "WAITING_CONFIRMATION":
                result = await client.post(f"{path}/confirm", json={"decision": "CONFIRM"})
                assert result.status_code == 503
            java_reads = len(java.calls)
            pending = await client.post(f"{path}/reconcile", json=target)
            expected_pending = (
                "WAITING_CONFIRMATION" if state == "WAITING_CONFIRMATION" else "IN_PROGRESS"
            )
            assert pending.status_code == 200 and pending.json()["outcome"] == expected_pending

            async with database.session() as session:
                row = await session.get(ReworkConfirmationRecord, approval_id)
                assert row is not None and row.status == state
                java.now = row.expires_at

            mismatched = await client.post(
                f"{path}/reconcile", json={**target, "order_id": "ORDER-OTHER"}
            )
            assert mismatched.status_code == 404
            async with database.session() as session:
                row = await session.get(ReworkConfirmationRecord, approval_id)
                assert row is not None and row.status == state

            checked = await asyncio.gather(
                client.post(f"{path}/reconcile", json=target),
                client.post(f"{path}/reconcile", json=target),
            )
            expected = "IN_PROGRESS" if state == "EXECUTING" else "NOT_SUBMITTED"
            assert all(result.status_code == 200 for result in checked)
            assert all(result.json()["outcome"] == expected for result in checked)
            assert len(java.calls) == java_reads and not java.writes and not java.lookups

        async with database.session() as session:
            row = await session.get(ReworkConfirmationRecord, approval_id)
            final_status = "EXECUTING" if state == "EXECUTING" else "EXPIRED"
            assert row is not None and row.status == final_status
            assert row.execution_key == original_key
            phases = await session.scalars(
                select(ReworkOperationLog.phase)
                .where(ReworkOperationLog.approval_id == row.approval_id)
                .order_by(ReworkOperationLog.revision)
            )
            expected_phases = ["WAITING_CONFIRMATION"]
            if state != "WAITING_CONFIRMATION":
                expected_phases.append("CONFIRMED")
            expected_phases.append("CLAIMED" if state == "EXECUTING" else "EXPIRED")
            assert phases.all() == expected_phases
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()
