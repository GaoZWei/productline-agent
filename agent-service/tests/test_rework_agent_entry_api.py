"""统一Agent入口的只读返工路由及业务边界。"""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.api.agent_messages import router
from app.clients.rework import ReworkHttpClient
from app.database import Database
from app.models import AgentRun, ReworkConfirmationRecord
from app.observability import TraceIdMiddleware
from app.services.rework_agent_entry import ReworkAgentEntry, parse_rework_entry
from app.settings import Settings
from app.tools.readonly import create_read_tool_registry
from app.versioning import build_run_version_snapshot
from tests.integration.tools.test_rework_write_tools import REWORK, TASK
from tests.test_agent_persistence import migrated_database_url as migrated_database_url
from tests.test_rework_draft_workflow import ORDER, TRACE, nested
from tests.test_rework_execution_persistence import ExecutionHarness


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("帮我查询返工状态 task-t823-a", (None, TASK, True)),
        ("请开始返工 TASK-T823-A REWORK-T823-A", ("START_REWORK", TASK, True)),
        ("查看返工 TASK-T823-A TASK-OTHER", (None, None, False)),
        ("登记成果 TASK-T823-A 自动编造证据", ("REGISTER_REWORK_RESULT", None, False)),
        ("查询订单 ORDER-003", None),
    ],
)
def test_rework_agent_entry_parser(
    text: str, expected: tuple[str | None, str | None, bool] | None
) -> None:
    command = parse_rework_entry(text)
    result = (command.operation, command.task_id, command.valid) if command is not None else None
    assert result == expected


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected", "reads"),
    [
        (f"查询返工 {TASK} {REWORK}", "READY", 2),
        (f"请开始返工 {TASK} {REWORK}", "READY", 2),
        (f"再次复核 {TASK} {REWORK}", "ACTION_UNAVAILABLE", 2),
        ("查询返工 ORDER-OTHER", "NEEDS_INPUT", 0),
        ("查询返工 TASK-OTHER", "NOT_FOUND", 1),
        ("查询返工", "CHOOSE_TARGET", 1),
    ],
)
async def test_rework_agent_entry_through_unified_http(
    migrated_database_url: str,
    message: str,
    expected: str,
    reads: int,
) -> None:
    database, java = Database(migrated_database_url), ExecutionHarness()
    model, skills = AsyncMock(), AsyncMock()
    try:
        if expected == "CHOOSE_TARGET":
            task = nested(java.data[1], "tasks", 0)
            active = task["activeReworks"]
            assert isinstance(active, list)
            active.append({**nested(active, 0), "reworkTaskId": "REWORK-SECOND"})
        app = FastAPI()
        app.include_router(router)
        app.add_middleware(TraceIdMiddleware)
        settings = Settings(_env_file=None, environment="test")
        app.state.database = database
        app.state.settings = settings
        app.state.model_client = model
        app.state.agent_skill_dispatcher = skills
        app.state.rework_entry = ReworkAgentEntry(ReworkHttpClient(java.http))
        app.state.run_version_snapshot = build_run_version_snapshot(
            settings, create_read_tool_registry(java.http)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://agent.test"
        ) as client:
            response = await client.post(
                "/api/agent/messages",
                headers={
                    "X-User-Id": "reviewer-test",
                    "X-User-Role": "REVIEWER",
                    "X-Trace-Id": TRACE,
                },
                json={
                    "message": message,
                    "page_context": {
                        "current_system": "production-system",
                        "current_page": "order-detail",
                        "order_id": ORDER,
                        "user_role": "REVIEWER",
                    },
                },
            )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["kind"] == "REWORK_GUIDANCE" and result["state"] == expected
        if expected == "CHOOSE_TARGET":
            assert {item["rework_task_id"] for item in result["candidates"]} == {
                REWORK,
                "REWORK-SECOND",
            }
            assert result["status"] is None
        elif expected == "READY":
            assert result["candidates"] == [{"task_id": TASK, "rework_task_id": REWORK}]
            assert result["status"] == "PENDING"
        assert len(java.calls) == reads and not java.writes and not java.lookups
        model.complete_structured.assert_not_called()
        skills.dispatch.assert_not_called()
        async with database.session() as session:
            assert (
                await session.scalar(select(func.count()).select_from(ReworkConfirmationRecord))
                == 0
            )
            run = await session.scalar(select(AgentRun))
            assert run is not None and run.tool_call_count == reads and run.final_result == result
    finally:
        await java.shared.aclose()
        await java.close()
        await database.dispose()
