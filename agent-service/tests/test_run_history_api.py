"""M7.5 Run列表API的身份、分页和安全摘要契约测试。"""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import runs as runs_api
from app.main import create_app
from app.models import AgentRunStatus, AgentStepStatus, AgentStepType
from app.schemas.business import BusinessIdentity
from app.schemas.run_history import (
    RunDetailResponse,
    RunListResponse,
    RunSummary,
    StepListResponse,
    StepSummary,
)
from app.services.run_history import RunHistoryAccessError
from app.settings import Settings


def _response() -> RunListResponse:
    return RunListResponse(
        items=(
            RunSummary(
                run_id="run-history-002",
                session_id="session-history-001",
                status=AgentRunStatus.FAILED,
                order_id="ORDER-003",
                task_id="TASK-003",
                tool_call_count=4,
                total_token_count=0,
                duration_ms=320,
                termination_reason="EXECUTION_ERROR",
                error_code="RESOURCE_NOT_FOUND",
                error_step="load_quality",
                created_at=datetime(2026, 8, 30, 2, 0, tzinfo=UTC),
                started_at=datetime(2026, 8, 30, 2, 0, tzinfo=UTC),
                finished_at=datetime(2026, 8, 30, 2, 0, 0, 320000, tzinfo=UTC),
            ),
        ),
        page=2,
        page_size=1,
        total=3,
    )


class _FakeRunHistoryService:
    def __init__(
        self,
        outcome: RunListResponse | RunDetailResponse | StepListResponse | Exception,
    ) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def list_runs(
        self,
        *,
        identity: BusinessIdentity,
        page: int,
        page_size: int,
    ) -> RunListResponse:
        self.calls.append({"identity": identity, "page": page, "page_size": page_size})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, RunListResponse)
        return self.outcome

    async def get_run_detail(
        self,
        *,
        identity: BusinessIdentity,
        run_id: str,
    ) -> RunDetailResponse:
        self.calls.append({"identity": identity, "run_id": run_id, "operation": "detail"})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, RunDetailResponse)
        return self.outcome

    async def list_steps(
        self,
        *,
        identity: BusinessIdentity,
        run_id: str,
    ) -> StepListResponse:
        self.calls.append({"identity": identity, "run_id": run_id, "operation": "steps"})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, StepListResponse)
        return self.outcome


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_list_api_requires_identity_and_returns_paginated_safe_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeRunHistoryService(_response())
    monkeypatch.setattr(runs_api, "_service", lambda _: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        missing_identity = await client.get("/api/agent/runs")
        success = await client.get(
            "/api/agent/runs?page=2&page_size=1",
            headers={
                "X-User-Id": "reviewer-001",
                "X-User-Role": "REVIEWER",
                "X-Trace-Id": "trace-run-list",
            },
        )

    assert missing_identity.status_code == 401
    assert success.status_code == 200
    assert success.json()["page"] == 2
    assert success.json()["total"] == 3
    assert success.json()["items"][0] == {
        "run_id": "run-history-002",
        "session_id": "session-history-001",
        "status": "FAILED",
        "order_id": "ORDER-003",
        "task_id": "TASK-003",
        "tool_call_count": 4,
        "total_token_count": 0,
        "duration_ms": 320,
        "termination_reason": "EXECUTION_ERROR",
        "error_code": "RESOURCE_NOT_FOUND",
        "error_step": "load_quality",
        "created_at": "2026-08-30T02:00:00Z",
        "started_at": "2026-08-30T02:00:00Z",
        "finished_at": "2026-08-30T02:00:00.320000Z",
    }
    assert service.calls[0]["identity"].user_id == "reviewer-001"
    assert service.calls[0]["page"] == 2
    assert service.calls[0]["page_size"] == 1
    assert "final_result" not in success.json()["items"][0]
    assert "page_context_snapshot" not in success.json()["items"][0]
    assert "version_snapshot" not in success.json()["items"][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_list_api_maps_permission_error_and_rejects_invalid_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeRunHistoryService(
        RunHistoryAccessError(
            code="PERMISSION_DENIED",
            message="reviewer permission is required",
            status_code=403,
        )
    )
    monkeypatch.setattr(runs_api, "_service", lambda _: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        forbidden = await client.get(
            "/api/agent/runs",
            headers={"X-User-Id": "operator-001", "X-User-Role": "OPERATOR"},
        )
        invalid_page = await client.get(
            "/api/agent/runs?page=0&page_size=101",
            headers={"X-User-Id": "reviewer-001", "X-User-Role": "REVIEWER"},
        )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"
    assert invalid_page.status_code == 422
    assert len(service.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_detail_and_steps_require_identity_and_return_safe_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail_service = _FakeRunHistoryService(
        RunDetailResponse(
            run=_response().items[0],
            input_token_count=10,
            output_token_count=4,
            result=None,
            approvals=(),
        )
    )
    monkeypatch.setattr(runs_api, "_service", lambda _: detail_service)
    application = create_app(Settings(environment="test"))
    headers = {"X-User-Id": "reviewer-001", "X-User-Role": "REVIEWER"}

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        missing = await client.get("/api/agent/runs/run-history-002")
        detail = await client.get("/api/agent/runs/run-history-002", headers=headers)

    assert missing.status_code == 401
    assert detail.status_code == 200
    assert detail.json()["run"]["run_id"] == "run-history-002"
    assert detail.json()["input_token_count"] == 10
    assert "page_context_snapshot" not in detail.json()

    step_service = _FakeRunHistoryService(
        StepListResponse(
            run_id="run-history-002",
            items=(
                StepSummary(
                    step_id="step-history-001",
                    sequence_number=1,
                    step_type=AgentStepType.TOOL,
                    step_name="get_order",
                    status=AgentStepStatus.FAILED,
                    input_summary="order_id=ORDER-003",
                    output_summary="code=RESOURCE_NOT_FOUND",
                    error_code="RESOURCE_NOT_FOUND",
                    duration_ms=8,
                    created_at=datetime(2026, 8, 30, 2, 0, tzinfo=UTC),
                ),
            ),
        )
    )
    monkeypatch.setattr(runs_api, "_service", lambda _: step_service)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        steps = await client.get("/api/agent/runs/run-history-002/steps", headers=headers)

    assert steps.status_code == 200
    assert steps.json()["items"][0]["input_summary"] == "order_id=ORDER-003"
    assert steps.json()["items"][0]["error_code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_detail_hides_missing_and_foreign_runs_with_same_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeRunHistoryService(
        RunHistoryAccessError(
            code="RUN_NOT_FOUND",
            message="run was not found",
            status_code=404,
        )
    )
    monkeypatch.setattr(runs_api, "_service", lambda _: service)
    application = create_app(Settings(environment="test"))

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/agent/runs/run-other-user",
            headers={"X-User-Id": "reviewer-001", "X-User-Role": "REVIEWER"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"
