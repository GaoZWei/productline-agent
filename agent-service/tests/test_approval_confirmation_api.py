"""M6.6人工确认执行HTTP契约和错误映射测试。"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.approvals as approvals_api
from app.main import create_app
from app.models import AgentRunStatus, ApprovalStatus, OperationType
from app.schemas import ReviewDraft
from app.schemas.agent_messages import ApprovalAgentResult
from app.schemas.business import BusinessIdentity
from app.schemas.write_tools import WriteReviewResultOutput
from app.services import (
    ApprovalConfirmationError,
    ApprovalConfirmationExecution,
)
from app.services.approval_orchestration import (
    ApprovalCancellation,
    ReworkApprovalCreation,
)
from app.settings import Settings


def _draft() -> dict[str, Any]:
    return {
        "task_id": "TASK-003",
        "issue_id": "ISSUE-001",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": "完成坐标系统处理后重新提交复核",
        "specification_references": [],
        "suggested_rework": {
            "required": True,
            "type": "COORDINATE_SYSTEM_FIX",
        },
    }


class _FakeConfirmationService:
    def __init__(
        self,
        result: ApprovalConfirmationExecution | ApprovalConfirmationError,
    ) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def confirm_and_execute(self, **values: object) -> ApprovalConfirmationExecution:
        self.calls.append(values)
        if isinstance(self.result, ApprovalConfirmationError):
            raise self.result
        return self.result


class _FakeOrchestrationService:
    def __init__(self) -> None:
        self.cancel_calls: list[dict[str, object]] = []
        self.rework_calls: list[dict[str, object]] = []

    async def cancel(self, approval_id: str, **values: object) -> ApprovalCancellation:
        self.cancel_calls.append({"approval_id": approval_id, **values})
        return ApprovalCancellation(
            approval_id=approval_id,
            run_id="run-review-003",
            status=ApprovalStatus.CANCELLED,
            run_status=AgentRunStatus.CANCELLED,
        )

    async def create_rework(
        self,
        approval_id: str,
        **values: object,
    ) -> ReworkApprovalCreation:
        self.rework_calls.append({"approval_id": approval_id, **values})
        result = ApprovalAgentResult(
            approval_id="approval-rework-003",
            run_id="run-rework-003",
            source_run_id="run-review-003",
            status=ApprovalStatus.WAITING_CONFIRMATION,
            operation_type=OperationType.CREATE_REWORK,
            target_id="TASK-003",
            target_version=8,
            draft=ReviewDraft.model_validate(_draft()),
        )
        return ReworkApprovalCreation(run_id=result.run_id, result=result)


def _execution() -> ApprovalConfirmationExecution:
    return ApprovalConfirmationExecution(
        approval_id="approval-confirm-003",
        status=ApprovalStatus.SUCCEEDED,
        result=WriteReviewResultOutput(
            approval_id="approval-confirm-003",
            task_id="TASK-003",
            issue_id="ISSUE-001",
            review_id="REVIEW-WRITE-003",
            status="REWORK_REQUIRED",
            review_comment="完成坐标系统处理后重新提交复核",
            task_version=8,
            java_trace_id="trace-java-write",
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirm_api_requires_identity_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeConfirmationService(_execution())
    monkeypatch.setattr(approvals_api, "_service", lambda _, **__: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/approvals/approval-confirm-003/confirm",
            json={"draft": _draft()},
            headers={"X-Trace-Id": "trace-confirm-missing-identity"},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "PERMISSION_DENIED"
    assert service.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirm_api_returns_strict_success_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeConfirmationService(_execution())
    monkeypatch.setattr(approvals_api, "_service", lambda _, **__: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/approvals/approval-confirm-003/confirm",
            json={"draft": _draft()},
            headers={
                "X-Trace-Id": "trace-confirm-success",
                "X-User-Id": "reviewer-001",
                "X-User-Role": "REVIEWER",
            },
        )

    assert response.status_code == 200
    assert response.json()["approval_id"] == "approval-confirm-003"
    assert response.json()["status"] == "SUCCEEDED"
    assert response.json()["result"]["review_id"] == "REVIEW-WRITE-003"
    assert response.json()["trace_id"] == "trace-confirm-success"
    assert len(service.calls) == 1
    assert isinstance(service.calls[0]["identity"], BusinessIdentity)
    assert service.calls[0]["identity"].user_id == "reviewer-001"
    assert isinstance(service.calls[0]["draft"], ReviewDraft)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirm_api_maps_expired_and_rejects_extra_request_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeConfirmationService(
        ApprovalConfirmationError(
            code="APPROVAL_EXPIRED",
            message="approval confirmation window has expired",
            status_code=410,
            approval_status=ApprovalStatus.EXPIRED,
        )
    )
    monkeypatch.setattr(approvals_api, "_service", lambda _, **__: service)
    application = create_app(Settings(environment="test"))
    headers = {
        "X-Trace-Id": "trace-confirm-expired",
        "X-User-Id": "reviewer-001",
        "X-User-Role": "REVIEWER",
    }

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        expired = await client.post(
            "/api/agent/approvals/approval-confirm-003/confirm",
            json={"draft": _draft()},
            headers=headers,
        )
        invalid = await client.post(
            "/api/agent/approvals/approval-confirm-003/confirm",
            json={"draft": _draft(), "task_id": "TASK-OTHER"},
            headers=headers,
        )

    assert expired.status_code == 410
    assert expired.json()["code"] == "APPROVAL_EXPIRED"
    assert expired.json()["status"] == "EXPIRED"
    assert invalid.status_code == 422


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_and_rework_api_return_independent_run_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeOrchestrationService()
    monkeypatch.setattr(approvals_api, "_orchestration_service", lambda _: service)
    application = create_app(Settings(environment="test"))
    headers = {
        "X-Trace-Id": "trace-orchestration",
        "X-User-Id": "reviewer-001",
        "X-User-Role": "REVIEWER",
    }

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        cancelled = await client.post(
            "/api/agent/approvals/approval-review-003/cancel",
            headers=headers,
        )
        rework = await client.post(
            "/api/agent/approvals/approval-review-003/rework",
            headers=headers,
        )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["run_status"] == "CANCELLED"
    assert rework.status_code == 200
    assert rework.json()["run_id"] == "run-rework-003"
    assert rework.json()["result"]["operation_type"] == "CREATE_REWORK"
    assert rework.json()["result"]["status"] == "WAITING_CONFIRMATION"
    assert len(service.cancel_calls) == len(service.rework_calls) == 1
