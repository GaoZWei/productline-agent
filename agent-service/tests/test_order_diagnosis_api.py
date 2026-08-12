"""M2.8 诊断 API 契约、Run 持久化和 Workflow 异常集成测试。"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl, ValidationError

from app.clients.business import BusinessHttpClient
from app.main import create_app
from app.models import AgentMessage, AgentRunStatus, AgentSession, AgentStepStatus
from app.repositories import AgentRunRepository, AgentStepRepository
from app.schemas import OrderDiagnosisRequest
from app.settings import Settings
from app.tools import create_read_tool_registry
from app.workflows import OrderDiagnosisWorkflow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL_ENV = "AGENT_PERSISTENCE_TEST_DATABASE_URL"


def _configured_database_url() -> str:
    database_url = os.getenv(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(f"需要通过 {TEST_DATABASE_URL_ENV} 提供隔离 PostgreSQL")
    return database_url


def _run_alembic(database_url: str) -> None:
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


@pytest_asyncio.fixture
async def diagnosis_application() -> AsyncIterator[tuple[FastAPI, BusinessHttpClient]]:
    database_url = _configured_database_url()
    _run_alembic(database_url)
    settings = Settings(
        environment="test",
        database_url=database_url,
        business_service_url=AnyHttpUrl("http://business.test"),
    )
    application = create_app(settings)
    mock_client = BusinessHttpClient(settings, transport=_golden_transport())
    async with application.router.lifespan_context(application):
        application.state.tool_registry = create_read_tool_registry(mock_client)
        yield application, mock_client
    await mock_client.aclose()


def _success(data: object, trace_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": data,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


def _golden_transport(*, fail_quality: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        trace_id = request.headers["X-Trace-Id"]
        if fail_quality and request.url.path == "/api/tasks/TASK-003/quality-issues":
            return httpx.Response(
                404,
                headers={"X-Trace-Id": trace_id},
                json={
                    "success": False,
                    "code": "RESOURCE_NOT_FOUND",
                    "message": "quality issues were not found",
                    "data": None,
                    "trace_id": trace_id,
                    "retryable": False,
                },
            )
        responses: dict[str, object] = {
            "/api/orders/ORDER-003": {
                "orderId": "ORDER-003",
                "productType": "DOM",
                "status": "QUALITY_CHECKING",
            },
            "/api/orders/ORDER-003/tasks": {
                "orderId": "ORDER-003",
                "tasks": [
                    {
                        "taskId": "TASK-003",
                        "orderId": "ORDER-003",
                        "status": "COMPLETED",
                        "version": 0,
                    }
                ],
            },
            "/api/tasks/TASK-003/progress": {
                "taskId": "TASK-003",
                "steps": [
                    {
                        "stepId": "STEP-003-01",
                        "taskId": "TASK-003",
                        "stepName": "DOM production",
                        "sequenceNumber": 1,
                        "status": "COMPLETED",
                    }
                ],
            },
            "/api/tasks/TASK-003/quality-issues": {
                "taskId": "TASK-003",
                "issues": [
                    {
                        "issueId": "ISSUE-001",
                        "taskId": "TASK-003",
                        "issueType": "COORDINATE_SYSTEM",
                        "status": "OPEN",
                        "description": "coordinate system mismatch",
                    }
                ],
            },
            "/api/tasks/TASK-003/review": {
                "taskId": "TASK-003",
                "reviews": [
                    {
                        "reviewId": "REVIEW-003",
                        "issueId": "ISSUE-001",
                        "status": "PENDING",
                        "reviewComment": None,
                    }
                ],
            },
            "/api/orders/ORDER-003/delivery-status": {
                "orderId": "ORDER-003",
                "records": [
                    {
                        "deliveryId": "DELIVERY-003",
                        "orderId": "ORDER-003",
                        "status": "BLOCKED",
                    }
                ],
            },
        }
        return _success(responses[request.url.path], trace_id)

    return httpx.MockTransport(handler)


def _request_body() -> dict[str, str]:
    return {
        "order_id": "ORDER-003",
        "user_message": "这个订单为什么还没有交付?",
    }


def _headers(trace_id: str = "trace-diagnosis-api-003") -> dict[str, str]:
    return {
        "X-Trace-Id": trace_id,
        "X-User-Id": "reviewer-001",
        "X-User-Role": "REVIEWER",
    }


@pytest.mark.unit
def test_order_diagnosis_api_request_schema_is_strict() -> None:
    request = OrderDiagnosisRequest.model_validate(_request_body())

    assert request.order_id == "ORDER-003"
    with pytest.raises(ValidationError):
        OrderDiagnosisRequest.model_validate({**_request_body(), "unsupported": True})
    with pytest.raises(ValidationError):
        OrderDiagnosisRequest(order_id="ORDER-003", user_message=" ")


@pytest.mark.integration
def test_order_diagnosis_api_is_registered_with_declared_contract() -> None:
    application = create_app(Settings(environment="test"))
    openapi = application.openapi()

    operation = openapi["paths"]["/api/agent/order-diagnosis"]["post"]
    assert operation["summary"] == "诊断订单阻塞原因"
    assert operation["requestBody"]["required"] is True
    assert "OrderDiagnosisResponse" in openapi["components"]["schemas"]
    assert "OrderDiagnosisErrorResponse" in openapi["components"]["schemas"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_rejects_missing_identity_before_creating_run() -> None:
    application = create_app(Settings(environment="test"))
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=_request_body(),
            headers={"X-Trace-Id": "trace-missing-identity"},
        )

    assert response.status_code == 401
    assert response.json() == {
        "run_id": None,
        "trace_id": "trace-missing-identity",
        "code": "PERMISSION_DENIED",
        "message": "authenticated user identity is required",
        "retryable": False,
        "error_step": None,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_persists_successful_run_and_returns_golden_result(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=_request_body(),
            headers=_headers(),
        )

    payload = response.json()
    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "trace-diagnosis-api-003"
    assert payload["trace_id"] == "trace-diagnosis-api-003"
    assert payload["diagnosis"]["blocking_stage"] == "QUALITY_REVIEW"
    assert [item["code"] for item in payload["diagnosis"]["root_causes"]] == [
        "OPEN_COORDINATE_SYSTEM_ISSUE",
        "REVIEW_PENDING",
    ]

    database = application.state.database
    async with database.session() as session:
        run = await AgentRunRepository(session).get(payload["run_id"])
        steps = await AgentStepRepository(session).list_by_run(payload["run_id"])
        assert run is not None
        assert run.status is AgentRunStatus.SUCCEEDED
        assert run.final_result == payload["diagnosis"]
        assert run.request_message_id is not None
        message = await session.get(AgentMessage, run.request_message_id)
        assert message is not None
        assert message.content == _request_body()["user_message"]
        agent_session = await session.get(AgentSession, run.session_id)
        assert agent_session is not None
        assert agent_session.user_id == "reviewer-001"
        assert [step.sequence_number for step in steps] == list(range(1, 10))
        assert all(step.status is AgentStepStatus.SUCCEEDED for step in steps)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_marks_tool_failure_and_returns_safe_error(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, original_client = diagnosis_application
    settings = application.state.settings
    failing_client = BusinessHttpClient(settings, transport=_golden_transport(fail_quality=True))
    application.state.tool_registry = create_read_tool_registry(failing_client)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/agent/order-diagnosis",
                json=_request_body(),
                headers=_headers("trace-diagnosis-api-failed"),
            )
    finally:
        await failing_client.aclose()
        application.state.tool_registry = create_read_tool_registry(original_client)

    payload = response.json()
    assert response.status_code == 404
    assert payload["code"] == "RESOURCE_NOT_FOUND"
    assert payload["error_step"] == "load_quality"
    assert payload["retryable"] is False
    assert "coordinate system mismatch" not in response.text

    database = application.state.database
    async with database.session() as session:
        run = await AgentRunRepository(session).get(payload["run_id"])
        steps = await AgentStepRepository(session).list_by_run(payload["run_id"])
        assert run is not None
        assert run.status is AgentRunStatus.FAILED
        assert run.error_code == "RESOURCE_NOT_FOUND"
        assert run.error_step == "load_quality"
        assert run.final_result is None
        assert steps[-1].status is AgentStepStatus.FAILED
        assert steps[-1].step_name == "load_quality"
        assert all(step.step_name != "load_review" for step in steps)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_marks_unexpected_workflow_exception(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, _ = diagnosis_application

    async def raise_unexpected(
        self: OrderDiagnosisWorkflow,
        order_id: str,
    ) -> object:
        raise RuntimeError("sensitive workflow details")

    monkeypatch.setattr(OrderDiagnosisWorkflow, "ainvoke", raise_unexpected)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=_request_body(),
            headers=_headers("trace-diagnosis-api-exception"),
        )

    payload = response.json()
    assert response.status_code == 500
    assert payload["code"] == "WORKFLOW_EXECUTION_ERROR"
    assert payload["error_step"] == "order_diagnosis_workflow"
    assert "sensitive workflow details" not in response.text

    database = application.state.database
    async with database.session() as session:
        run = await AgentRunRepository(session).get(payload["run_id"])
        assert run is not None
        assert run.status is AgentRunStatus.FAILED
        assert run.error_code == "WORKFLOW_EXECUTION_ERROR"
        assert run.error_step == "order_diagnosis_workflow"
