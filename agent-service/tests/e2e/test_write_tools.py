"""M6.5真实Java、PostgreSQL与两个高风险写Tool的端到端验收。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.database import Database
from app.models import AgentSession, OperationType, PendingToolName
from app.repositories import AgentRunRepository, ApprovalRecordRepository
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.tools import QualityIssueList, TaskDetail
from app.schemas.versioning import RunVersionSnapshot
from app.services import (
    ApprovalLifecycleService,
    DatabaseApprovalExecutionStore,
    RunLifecycleService,
)
from app.settings import Settings
from app.tools import (
    CreateReworkTaskTool,
    ToolContext,
    WriteReviewResultTool,
    create_read_tool_registry,
)
from app.versioning import build_run_version_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL_ENV = "AGENT_E2E_DATABASE_URL"
BUSINESS_URL_ENV = "AGENT_E2E_BUSINESS_URL"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def write_settings() -> Settings:
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
    )


@pytest.mark.asyncio
async def test_confirmed_review_and_rework_tools_write_once_and_persist_results(
    write_settings: Settings,
) -> None:
    database = Database(write_settings.async_database_url)
    client = BusinessHttpClient(write_settings)
    identity = BusinessIdentity(user_id="reviewer-001", role="REVIEWER")
    store = DatabaseApprovalExecutionStore(database)
    version_snapshot = build_run_version_snapshot(
        write_settings,
        create_read_tool_registry(client),
    )
    try:
        task = (
            await client.get(
                "/api/tasks/TASK-003",
                TaskDetail,
                identity=identity,
                trace_id="trace-e2e-write-read-task",
            )
        ).data
        issues = (
            await client.get(
                "/api/tasks/TASK-003/quality-issues",
                QualityIssueList,
                identity=identity,
                trace_id="trace-e2e-write-read-issues",
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
                "review_comment": "完成坐标系统处理后重新提交复核",
                "specification_references": [],
                "suggested_rework": {
                    "required": True,
                    "type": "COORDINATE_SYSTEM_FIX",
                },
            }
        )

        await _prepare_executing_approval(
            database,
            approval_id="approval-e2e-review",
            run_id="run-e2e-review",
            operation_type=OperationType.SUBMIT_REVIEW,
            pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
            draft=draft,
            target_version=task.version,
            create_session=True,
            version_snapshot=version_snapshot,
        )
        review_tool = WriteReviewResultTool(client, store)
        review_result = await review_tool.execute(
            {
                "approval_id": "approval-e2e-review",
                "idempotency_key": "approval:e2e:review",
            },
            _context("run-tool-e2e-review", "REVIEW_WRITE"),
        )
        assert review_result.success is True
        assert review_result.data is not None
        assert review_result.data.issue_id == issue.issue_id
        assert review_result.data.task_version == task.version + 1

        # 使用新ToolContext模拟网络重放; Java沿用幂等键返回同一复核记录。
        replay = await review_tool.execute(
            {
                "approval_id": "approval-e2e-review",
                "idempotency_key": "approval:e2e:review",
            },
            _context("run-tool-e2e-review-replay", "REVIEW_WRITE"),
        )
        assert replay.success is True
        assert replay.data is not None
        assert replay.data.review_id == review_result.data.review_id
        assert replay.data.task_version == review_result.data.task_version

        await _prepare_executing_approval(
            database,
            approval_id="approval-e2e-rework",
            run_id="run-e2e-rework",
            operation_type=OperationType.CREATE_REWORK,
            pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
            draft=draft,
            target_version=review_result.data.task_version,
            create_session=False,
            version_snapshot=version_snapshot,
        )
        rework_result = await CreateReworkTaskTool(client, store).execute(
            {
                "approval_id": "approval-e2e-rework",
                "idempotency_key": "approval:e2e:rework",
            },
            _context("run-tool-e2e-rework", "REWORK_WRITE"),
        )
        assert rework_result.success is True
        assert rework_result.data is not None
        assert rework_result.data.rework_task_id.startswith("REWORK-WRITE-")
        assert rework_result.data.source_issue_id == issue.issue_id
        assert rework_result.data.task_version == task.version + 2

        async with database.session() as session:
            review_approval = await ApprovalRecordRepository(session).get(
                "approval-e2e-review"
            )
            rework_approval = await ApprovalRecordRepository(session).get(
                "approval-e2e-rework"
            )
            assert review_approval is not None
            assert rework_approval is not None
            assert review_approval.execution_result == review_result.data.model_dump(mode="json")
            assert rework_approval.execution_result == rework_result.data.model_dump(mode="json")
    finally:
        await client.aclose()
        await database.dispose()


async def _prepare_executing_approval(
    database: Database,
    *,
    approval_id: str,
    run_id: str,
    operation_type: OperationType,
    pending_tool_name: PendingToolName,
    draft: ReviewDraft,
    target_version: int,
    create_session: bool,
    version_snapshot: RunVersionSnapshot,
) -> None:
    async with database.session() as session, session.begin():
        if create_session:
            session.add(AgentSession(session_id="session-e2e-write", user_id="reviewer-001"))
        await RunLifecycleService(AgentRunRepository(session)).create_run(
            run_id=run_id,
            session_id="session-e2e-write",
            version_snapshot=version_snapshot,
        )
        lifecycle = ApprovalLifecycleService(ApprovalRecordRepository(session))
        approval = await lifecycle.create_draft(
            approval_id=approval_id,
            run_id=run_id,
            operation_type=operation_type,
            original_draft=draft,
            pending_tool_name=pending_tool_name,
            target_id=draft.task_id,
            target_version=target_version,
        )
        await lifecycle.mark_waiting_confirmation(approval.approval_id)
        await lifecycle.confirm(
            approval.approval_id,
            confirmed_by_user_id="reviewer-001",
        )
        await lifecycle.mark_executing(approval.approval_id)


def _context(run_id: str, permission: str) -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
        permissions=frozenset({permission}),
        trace_id=f"trace-{run_id}",
        run_id=run_id,
    )
