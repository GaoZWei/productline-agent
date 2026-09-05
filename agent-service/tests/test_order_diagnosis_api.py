"""M2.8-M3.3 诊断API、上下文防伪和Run持久化集成测试。"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy import select

from app.clients.business import BusinessHttpClient
from app.main import create_app
from app.models import (
    AgentMessage,
    AgentRunStatus,
    AgentSession,
    AgentStepStatus,
    AgentStepType,
)
from app.repositories import AgentRunRepository, AgentSessionRepository, AgentStepRepository
from app.routing import Intent
from app.schemas import (
    OrderDiagnosisRequest,
    PendingActionContext,
    SessionContext,
)
from app.schemas.business import BusinessIdentity
from app.services import RunEventService, SessionContextService
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


def _page_context() -> dict[str, object]:
    return {
        "current_system": "production-system",
        "current_page": "order-detail",
        "order_id": "ORDER-003",
        "task_id": None,
        "issue_id": None,
        "batch_id": None,
        "product_type": "DOM",
        "satellite_type": None,
        "user_role": "REVIEWER",
    }


def _request_body() -> dict[str, object]:
    return {
        "order_id": "ORDER-003",
        "user_message": "这个订单为什么还没有交付?",
        "page_context": _page_context(),
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
    assert request.page_context is not None
    assert request.page_context.order_id == request.order_id
    inherited = OrderDiagnosisRequest.model_validate(
        {"session_id": "session-order-003", "user_message": "继续诊断"}
    )
    assert inherited.order_id is None
    assert inherited.page_context is None
    with pytest.raises(ValidationError):
        OrderDiagnosisRequest.model_validate({**_request_body(), "unsupported": True})
    with pytest.raises(ValidationError):
        OrderDiagnosisRequest.model_validate(
            {**_request_body(), "user_message": " "}
        )


@pytest.mark.integration
def test_order_diagnosis_api_is_registered_with_declared_contract() -> None:
    application = create_app(Settings(environment="test"))
    openapi = application.openapi()

    operation = openapi["paths"]["/api/agent/order-diagnosis"]["post"]
    assert operation["summary"] == "诊断订单阻塞原因"
    assert operation["requestBody"]["required"] is True
    assert "OrderDiagnosisResponse" in openapi["components"]["schemas"]
    assert "OrderDiagnosisErrorResponse" in openapi["components"]["schemas"]
    assert "PageContext" in openapi["components"]["schemas"]
    assert "SessionContext" in openapi["components"]["schemas"]
    assert "/api/agent/sessions" in openapi["paths"]


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
async def test_order_diagnosis_api_rejects_role_without_permission_before_run() -> None:
    application = create_app(Settings(environment="test"))
    body = _request_body()
    page_context = _page_context()
    page_context["user_role"] = "VIEWER"
    body["page_context"] = page_context
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=body,
            headers={
                "X-Trace-Id": "trace-viewer-denied",
                "X-User-Id": "viewer-001",
                "X-User-Role": "VIEWER",
            },
        )

    assert response.status_code == 403
    assert response.json()["run_id"] is None
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_rejects_forged_context_role_before_run() -> None:
    application = create_app(Settings(environment="test"))
    body = _request_body()
    page_context = _page_context()
    page_context["user_role"] = "ADMIN"
    body["page_context"] = page_context
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=body,
            headers=_headers("trace-forged-role"),
        )

    assert response.status_code == 403
    assert response.json()["run_id"] is None
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_api_creates_reads_isolates_and_clears_context(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/agent/sessions",
            json={"page_context": _page_context()},
            headers=_headers("trace-session-create"),
        )
        session_id = created.json()["session_id"]
        loaded = await client.get(
            f"/api/agent/sessions/{session_id}",
            headers=_headers("trace-session-get"),
        )
        denied = await client.get(
            f"/api/agent/sessions/{session_id}",
            headers={
                "X-Trace-Id": "trace-session-denied",
                "X-User-Id": "reviewer-002",
                "X-User-Role": "REVIEWER",
            },
        )
        denied_diagnosis = await client.post(
            "/api/agent/order-diagnosis",
            json={"session_id": session_id, "user_message": "继续诊断"},
            headers={
                "X-Trace-Id": "trace-session-diagnosis-denied",
                "X-User-Id": "reviewer-002",
                "X-User-Role": "REVIEWER",
            },
        )
        deleted = await client.delete(
            f"/api/agent/sessions/{session_id}",
            headers=_headers("trace-session-delete"),
        )
        missing = await client.get(
            f"/api/agent/sessions/{session_id}",
            headers=_headers("trace-session-missing"),
        )

    assert created.status_code == 201
    assert created.json()["context"]["current_order_id"] == "ORDER-003"
    assert loaded.status_code == 200
    assert loaded.json()["context"]["confirmed_entities"] == {
        "order_id": "ORDER-003"
    }
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"
    assert denied_diagnosis.status_code == 403
    assert denied_diagnosis.json()["run_id"] is None
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["code"] == "SESSION_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_service_saves_routing_fields_and_enforces_expiration(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    identity = BusinessIdentity(user_id="reviewer-001", role="REVIEWER")
    service = SessionContextService(
        application.state.database,
        ttl_seconds=1800,
    )
    created = await service.create(identity=identity)
    context = SessionContext(
        current_order_id="ORDER-003",
        current_task_id="TASK-003",
        previous_intent=Intent.TASK_TRACKING,
        confirmed_entities={"order_id": "ORDER-003", "task_id": "TASK-003"},
        candidate_entities={"task_id": ["TASK-003", "TASK-004"]},
        recent_diagnosis_run_id="run-order-003",
        pending_action=PendingActionContext(
            action_type="RESUBMIT_REVIEW",
            parameters={"task_id": "TASK-003"},
            source_run_id="run-order-003",
        ),
    )

    updated = await service.replace_context(
        session_id=created.session_id,
        identity=identity,
        context=context,
    )

    assert updated.context == context
    database = application.state.database
    async with database.session() as session, session.begin():
        stored = await AgentSessionRepository(session).get(created.session_id)
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        expired = await client.get(
            f"/api/agent/sessions/{created.session_id}",
            headers=_headers("trace-session-expired"),
        )
        expired_diagnosis = await client.post(
            "/api/agent/order-diagnosis",
            json={"session_id": created.session_id, "user_message": "继续诊断"},
            headers=_headers("trace-session-diagnosis-expired"),
        )
        cleared = await client.delete(
            f"/api/agent/sessions/{created.session_id}",
            headers=_headers("trace-session-clear-expired"),
        )

    assert expired.status_code == 410
    assert expired.json()["code"] == "SESSION_EXPIRED"
    assert expired_diagnosis.status_code == 410
    assert expired_diagnosis.json()["run_id"] is None
    assert cleared.status_code == 204


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
        assert run.version_snapshot["capture_status"] == "CAPTURED"
        assert run.version_snapshot["router_prompt_version"] == "router-v3"
        assert run.version_snapshot["agent_prompt_version"] == "action-decision-v1"
        assert run.version_snapshot["model"]["configured"] is False
        assert run.version_snapshot["tool_schema"]["tool_names"] == [
            "get_delivery_status",
            "get_order_detail",
            "get_production_progress",
            "get_quality_issues",
            "get_related_tasks",
            "get_review_result",
            "get_task_detail",
        ]
        assert run.version_snapshot["rag_strategy"]["version"] == "hybrid-rrf-rerank-v2"
        assert run.page_context_snapshot == _page_context()
        assert run.router_result is None
        assert run.input_token_count == 0
        assert run.output_token_count == 0
        assert run.total_token_count == 0
        assert run.tool_call_count == sum(
            step.step_type is AgentStepType.TOOL for step in steps
        )
        assert run.duration_ms is not None and run.duration_ms >= 0
        assert run.termination_reason == "COMPLETED"
        assert run.request_message_id is not None
        message = await session.get(AgentMessage, run.request_message_id)
        assert message is not None
        assert message.content == _request_body()["user_message"]
        agent_session = await session.get(AgentSession, run.session_id)
        assert agent_session is not None
        assert agent_session.user_id == "reviewer-001"
        assert [step.sequence_number for step in steps] == list(range(1, 11))
        assert all(step.status is AgentStepStatus.SUCCEEDED for step in steps)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_publishes_ordered_sse_progress_without_raw_facts(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    stream_id = "stream-diagnosis-003"
    event_service: RunEventService = application.state.run_event_service
    await event_service.open_stream(stream_id, owner_user_id="reviewer-001")

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        diagnosis = await client.post(
            "/api/agent/order-diagnosis",
            json=_request_body(),
            headers={
                **_headers("trace-diagnosis-events-003"),
                "X-Event-Stream-Id": stream_id,
            },
        )
        event_stream = await client.get(
            f"/api/agent/events/{stream_id}",
            headers=_headers("trace-diagnosis-events-subscribe-003"),
        )

    assert diagnosis.status_code == 200
    assert event_stream.status_code == 200
    event_names = [
        line.removeprefix("event: ")
        for line in event_stream.text.splitlines()
        if line.startswith("event: ")
    ]
    assert event_names == [
        "run_started",
        "context_loaded",
        *[name for _ in range(6) for name in ("tool_started", "tool_completed")],
        "diagnosis_generated",
        "run_completed",
    ]
    assert "coordinate system mismatch" not in event_stream.text
    user_message = _request_body()["user_message"]
    assert isinstance(user_message, str)
    assert user_message not in event_stream.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_inherits_context_and_appends_to_session(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    first_body = _request_body()
    task_page_context = _page_context()
    task_page_context.update(current_page="task-detail", task_id="TASK-003")
    first_body["page_context"] = task_page_context
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/api/agent/order-diagnosis",
            json=first_body,
            headers=_headers("trace-session-first"),
        )
        second = await client.post(
            "/api/agent/order-diagnosis",
            json={
                "session_id": first.json()["session_id"],
                "user_message": "继续检查这个订单",
            },
            headers=_headers("trace-session-second"),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert second_payload["session_id"] == first_payload["session_id"]
    assert second_payload["run_id"] != first_payload["run_id"]
    assert second_payload["diagnosis"]["order_id"] == "ORDER-003"

    database = application.state.database
    async with database.session() as session:
        stored_session = await AgentSessionRepository(session).get(
            first_payload["session_id"]
        )
        assert stored_session is not None
        context = SessionContext.model_validate(stored_session.context)
        messages = list(
            (
                await session.scalars(
                    select(AgentMessage)
                    .where(AgentMessage.session_id == first_payload["session_id"])
                    .order_by(AgentMessage.sequence_number)
                )
            ).all()
        )
        runs = await AgentRunRepository(session).list_by_session(
            first_payload["session_id"]
        )

    assert context.current_order_id == "ORDER-003"
    assert context.current_task_id == "TASK-003"
    assert context.previous_intent == "ORDER_DIAGNOSIS"
    assert context.recent_diagnosis_run_id == second_payload["run_id"]
    assert [message.sequence_number for message in messages] == [1, 2]
    assert [run.run_id for run in runs] == [
        first_payload["run_id"],
        second_payload["run_id"],
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_rejects_forged_order_context_before_tools(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    body = _request_body()
    page_context = _page_context()
    page_context["order_id"] = "ORDER-004"
    body["page_context"] = page_context
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=body,
            headers=_headers("trace-forged-order"),
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["code"] == "PARAM_VALIDATION_ERROR"
    assert payload["error_step"] == "load_context"

    database = application.state.database
    async with database.session() as session:
        run = await AgentRunRepository(session).get(payload["run_id"])
        steps = await AgentStepRepository(session).list_by_run(payload["run_id"])
        assert run is not None
        assert run.status is AgentRunStatus.FAILED
        assert [(step.step_name, step.status) for step in steps] == [
            ("load_context", AgentStepStatus.FAILED)
        ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_diagnosis_api_revalidates_task_against_java_facts(
    diagnosis_application: tuple[FastAPI, BusinessHttpClient],
) -> None:
    application, _ = diagnosis_application
    body = _request_body()
    page_context = _page_context()
    page_context.update(current_page="task-detail", task_id="TASK-999")
    body["page_context"] = page_context
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/agent/order-diagnosis",
            json=body,
            headers=_headers("trace-forged-task"),
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["code"] == "PARAM_VALIDATION_ERROR"
    assert payload["error_step"] == "validate_page_context"

    database = application.state.database
    async with database.session() as session:
        run = await AgentRunRepository(session).get(payload["run_id"])
        steps = await AgentStepRepository(session).list_by_run(payload["run_id"])
        assert run is not None
        assert run.status is AgentRunStatus.FAILED
        assert steps[-1].step_name == "validate_page_context"
        assert steps[-1].status is AgentStepStatus.FAILED
        assert all(step.step_name != "diagnose_by_rules" for step in steps)


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
        *,
        page_context: object,
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
