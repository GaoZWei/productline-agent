"""M6.7操作日志详情HTTP身份和响应契约测试。"""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import approvals as approvals_api
from app.main import create_app
from app.models import ApprovalStatus, OperationType
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.operation_log import OperationLogDetail
from app.schemas.write_tools import WriteReviewResultOutput
from app.services import OperationLogAccessError, build_operation_log_detail
from app.settings import Settings


def _detail() -> OperationLogDetail:
    draft = ReviewDraft.model_validate(
        {
            "task_id": "TASK-003",
            "issue_id": "ISSUE-001",
            "conclusion": "REWORK_REQUIRED",
            "problem_summary": "存在坐标系质量问题",
            "review_comment": "处理后重新提交复核",
            "specification_references": [],
            "suggested_rework": {
                "required": True,
                "type": "COORDINATE_SYSTEM_FIX",
            },
        }
    )
    return build_operation_log_detail(
        approval_id="approval-log-api",
        operation_type=OperationType.SUBMIT_REVIEW,
        target_id="TASK-003",
        target_version=7,
        confirmed_by_user_id="reviewer-001",
        original_draft=draft,
        effective_draft=draft,
        outcome=ApprovalStatus.SUCCEEDED,
        result=WriteReviewResultOutput(
            approval_id="approval-log-api",
            task_id="TASK-003",
            issue_id="ISSUE-001",
            review_id="REVIEW-LOG-API",
            status="REWORK_REQUIRED",
            review_comment="处理后重新提交复核",
            task_version=8,
            java_trace_id="trace-java-log-api",
        ),
        failure=None,
        created_at=datetime(2026, 8, 27, 13, 0, tzinfo=UTC),
    )


class _FakeOperationLogService:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def get_by_approval(
        self,
        approval_id: str,
        *,
        identity: BusinessIdentity,
    ) -> OperationLogDetail:
        self.calls.append({"approval_id": approval_id, "identity": identity})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, OperationLogDetail)
        return self.outcome


@pytest.mark.unit
@pytest.mark.asyncio
async def test_operation_log_api_requires_identity_and_returns_strict_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeOperationLogService(_detail())
    monkeypatch.setattr(approvals_api, "_operation_log_service", lambda _: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        missing_identity = await client.get(
            "/api/agent/approvals/approval-log-api/operation-log"
        )
        success = await client.get(
            "/api/agent/approvals/approval-log-api/operation-log",
            headers={
                "X-User-Id": "reviewer-001",
                "X-User-Role": "REVIEWER",
                "X-Trace-Id": "trace-log-api",
            },
        )

    assert missing_identity.status_code == 401
    assert success.status_code == 200
    assert success.json()["approval_id"] == "approval-log-api"
    assert success.json()["after_summary"]["outcome"] == "SUCCEEDED"
    assert success.json()["java_trace_id"] == "trace-java-log-api"
    assert len(service.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_operation_log_api_maps_access_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeOperationLogService(
        OperationLogAccessError(
            code="PERMISSION_DENIED",
            message="operation log belongs to another confirmer",
            status_code=403,
        )
    )
    monkeypatch.setattr(approvals_api, "_operation_log_service", lambda _: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/agent/approvals/approval-log-api/operation-log",
            headers={"X-User-Id": "reviewer-002", "X-User-Role": "REVIEWER"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"
