"""M6.6真实HTTP、Agent数据库、写Tool和Java确认回写验收。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.database import Database
from app.main import create_app
from app.models import (
    AgentSession,
    ApprovalStatus,
    OperationType,
    PendingToolName,
)
from app.repositories import AgentRunRepository, ApprovalRecordRepository
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.tools import QualityIssueList, ReviewResult, TaskDetail
from app.services import ApprovalLifecycleService, RunLifecycleService
from app.settings import Settings
from app.tools import create_read_tool_registry
from app.versioning import build_run_version_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL_ENV = "AGENT_E2E_DATABASE_URL"
BUSINESS_URL_ENV = "AGENT_E2E_BUSINESS_URL"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def confirmation_settings() -> Settings:
    database_url = os.getenv(DATABASE_URL_ENV)
    business_url = os.getenv(BUSINESS_URL_ENV)
    if database_url is None or business_url is None:
        pytest.skip(
            f"需要通过 {DATABASE_URL_ENV} 和 {BUSINESS_URL_ENV} 提供隔离E2E服务"
        )
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        ["uv", "run", "--frozen", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return Settings(
        environment="test",
        database_url=database_url,
        business_service_url=AnyHttpUrl(business_url),
        approval_ttl_seconds=900,
    )


@pytest.mark.asyncio
async def test_confirmation_api_revalidates_writes_once_and_replays_result(
    confirmation_settings: Settings,
) -> None:
    database = Database(confirmation_settings.async_database_url)
    business_client = BusinessHttpClient(confirmation_settings)
    identity = BusinessIdentity(user_id="reviewer-001", role="REVIEWER")
    try:
        task = (
            await business_client.get(
                "/api/tasks/TASK-003",
                TaskDetail,
                identity=identity,
                trace_id="trace-e2e-confirm-read-task",
            )
        ).data
        issues = (
            await business_client.get(
                "/api/tasks/TASK-003/quality-issues",
                QualityIssueList,
                identity=identity,
                trace_id="trace-e2e-confirm-read-issues",
            )
        ).data
        reviews_before = (
            await business_client.get(
                "/api/tasks/TASK-003/review",
                ReviewResult,
                identity=identity,
                trace_id="trace-e2e-confirm-reviews-before",
            )
        ).data
        issue = next(
            item
            for item in issues.issues
            if item.issue_type == "COORDINATE_SYSTEM" and item.status == "OPEN"
        )
        draft = ReviewDraft.model_validate(
            {
                "task_id": task.task_id,
                "issue_id": issue.issue_id,
                "conclusion": "REWORK_REQUIRED",
                "problem_summary": "存在未关闭的坐标系质量问题",
                "review_comment": "确认后完成坐标系统处理并重新提交复核",
                "specification_references": [],
                "suggested_rework": {
                    "required": True,
                    "type": "COORDINATE_SYSTEM_FIX",
                },
            }
        )
        version_snapshot = build_run_version_snapshot(
            confirmation_settings,
            create_read_tool_registry(business_client),
        )
        async with database.session() as session, session.begin():
            session.add(
                AgentSession(
                    session_id="session-e2e-confirm",
                    user_id="reviewer-001",
                )
            )
            await RunLifecycleService(AgentRunRepository(session)).create_run(
                run_id="run-e2e-confirm",
                session_id="session-e2e-confirm",
                version_snapshot=version_snapshot,
            )
            lifecycle = ApprovalLifecycleService(ApprovalRecordRepository(session))
            approval = await lifecycle.create_draft(
                approval_id="approval-e2e-confirm",
                run_id="run-e2e-confirm",
                operation_type=OperationType.SUBMIT_REVIEW,
                original_draft=draft,
                pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
                target_id=task.task_id,
                target_version=task.version,
            )
            await lifecycle.mark_waiting_confirmation(approval.approval_id)

        application = create_app(confirmation_settings)
        async with application.router.lifespan_context(application):
            async with AsyncClient(
                transport=ASGITransport(app=application),
                base_url="http://test",
            ) as client:
                first = await client.post(
                    "/api/agent/approvals/approval-e2e-confirm/confirm",
                    json={"draft": draft.model_dump(mode="json")},
                    headers=_headers("trace-e2e-confirm-first"),
                )
                replay = await client.post(
                    "/api/agent/approvals/approval-e2e-confirm/confirm",
                    json={"draft": draft.model_dump(mode="json")},
                    headers=_headers("trace-e2e-confirm-replay"),
                )

        assert first.status_code == 200
        assert replay.status_code == 200
        assert first.json()["status"] == "SUCCEEDED"
        assert replay.json()["result"] == first.json()["result"]
        assert first.json()["result"]["task_version"] == task.version + 1

        reviews_after = (
            await business_client.get(
                "/api/tasks/TASK-003/review",
                ReviewResult,
                identity=identity,
                trace_id="trace-e2e-confirm-reviews-after",
            )
        ).data
        assert len(reviews_after.reviews) == len(reviews_before.reviews) + 1
        async with database.session() as session:
            stored = await ApprovalRecordRepository(session).get("approval-e2e-confirm")
            assert stored is not None
            assert stored.status is ApprovalStatus.SUCCEEDED
            assert stored.confirmed_by_user_id == "reviewer-001"
            assert stored.execution_result == first.json()["result"]
    finally:
        await business_client.aclose()
        await database.dispose()


def _headers(trace_id: str) -> dict[str, str]:
    return {
        "X-Trace-Id": trace_id,
        "X-User-Id": "reviewer-001",
        "X-User-Role": "REVIEWER",
    }
