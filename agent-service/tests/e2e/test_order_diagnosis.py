"""M2.10 真实 Java、PostgreSQL 与 Agent API 的订单诊断端到端验收。"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.main import create_app
from app.models import AgentRun, AgentRunStatus, AgentStep, AgentStepStatus, AgentStepType
from app.repositories import AgentRunRepository, AgentStepRepository
from app.schemas import OrderDiagnosisErrorResponse, OrderDiagnosisResponse
from app.settings import Settings
from app.tools import create_read_tool_registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL_ENV = "AGENT_E2E_DATABASE_URL"
BUSINESS_URL_ENV = "AGENT_E2E_BUSINESS_URL"
EXPECTED_TOOL_STEPS = [
    "load_order",
    "load_tasks",
    "load_progress",
    "load_quality",
    "load_review",
    "load_delivery",
]

pytestmark = pytest.mark.e2e


class DemoFaultTransport(httpx.AsyncBaseTransport):
    """只在E2E边界给真实Java GET请求注入已启用的演示故障。"""

    def __init__(self, fault: str) -> None:
        self._fault = fault
        self._transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.headers["X-Demo-Fault"] = self._fault
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


@pytest.fixture(scope="module")
def e2e_settings() -> Settings:
    """对隔离数据库只执行一次迁移并复用不可变E2E配置。"""

    settings = _e2e_settings()
    _run_alembic(settings.database_url)
    return settings


@pytest_asyncio.fixture
async def e2e_application(e2e_settings: Settings) -> AsyncIterator[FastAPI]:
    """在当前用例事件循环内启动并关闭Agent应用与连接池。"""

    application = create_app(e2e_settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.mark.parametrize(
    ("order_id", "expected_stage"),
    [
        pytest.param("ORDER-001", "PRODUCTION", id="production"),
        pytest.param("ORDER-002", "PRODUCTION_BLOCKED", id="production-blocked"),
        pytest.param("ORDER-003", "QUALITY_REVIEW", id="quality-review"),
        pytest.param("ORDER-004", "REVIEW", id="review"),
        pytest.param("ORDER-005", "NONE", id="none"),
    ],
)
async def test_fixed_orders_return_expected_diagnosis_and_persist_all_steps(
    e2e_application: FastAPI,
    order_id: str,
    expected_stage: str,
) -> None:
    """五个固定订单必须由真实Tool事实得到稳定阶段和完整运行记录。"""

    response = await _diagnose(e2e_application, order_id, f"请诊断{order_id}当前状态")

    assert response.status_code == 200
    payload = OrderDiagnosisResponse.model_validate_json(response.content)
    assert payload.trace_id == response.headers["X-Trace-Id"]
    assert payload.diagnosis.order_id == order_id
    assert payload.diagnosis.blocking_stage.value == expected_stage
    assert payload.diagnosis.evidence
    assert all(item.source_type == "TOOL" for item in payload.diagnosis.evidence)

    run, steps = await _load_run(e2e_application, payload.run_id)
    assert run.status is AgentRunStatus.SUCCEEDED
    assert run.final_result == payload.diagnosis.model_dump(mode="json")
    assert [step.sequence_number for step in steps] == list(range(1, len(steps) + 1))
    assert all(step.status is AgentStepStatus.SUCCEEDED for step in steps)
    assert [step.step_name for step in steps if step.step_type is AgentStepType.TOOL] == (
        EXPECTED_TOOL_STEPS
    )

    if order_id == "ORDER-003":
        assert [item.field_path for item in payload.diagnosis.evidence] == [
            "tasks[0].status",
            "issues[0].status",
            "reviews[0].status",
            "records[0].status",
        ]
        assert [item.value for item in payload.diagnosis.evidence] == [
            "COMPLETED",
            "OPEN",
            "PENDING",
            "BLOCKED",
        ]


async def test_missing_order_returns_resource_not_found_at_load_order(
    e2e_application: FastAPI,
) -> None:
    """不存在订单必须在第一个Java Tool节点失败并保存FAILED Run。"""

    response = await _diagnose(e2e_application, "ORDER-999", "请诊断不存在的订单")

    assert response.status_code == 404
    payload = OrderDiagnosisErrorResponse.model_validate_json(response.content)
    assert payload.code == "RESOURCE_NOT_FOUND"
    assert payload.retryable is False
    assert payload.error_step == "load_order"
    assert payload.run_id is not None
    await _assert_failed_run(e2e_application, payload.run_id, payload.code, "load_order")


async def test_java_timeout_is_located_at_tool_step(e2e_application: FastAPI) -> None:
    """真实Java慢响应必须映射为可重试超时并定位到Tool Step。"""

    async with _fault_registry(e2e_application, "timeout", read_timeout=0.1):
        response = await _diagnose(e2e_application, "ORDER-003", "模拟Java超时")

    assert response.status_code == 504
    payload = OrderDiagnosisErrorResponse.model_validate_json(response.content)
    assert payload.code == "TOOL_TIMEOUT"
    assert payload.retryable is True
    assert payload.error_step == "load_order"
    assert payload.run_id is not None
    await _assert_failed_run(e2e_application, payload.run_id, payload.code, "load_order")


async def test_invalid_java_response_is_rejected_at_tool_step(
    e2e_application: FastAPI,
) -> None:
    """Java HTTP 200缺字段也不得作为事实进入Workflow。"""

    async with _fault_registry(e2e_application, "invalid-response"):
        response = await _diagnose(e2e_application, "ORDER-003", "模拟Java字段错误")

    assert response.status_code == 502
    payload = OrderDiagnosisErrorResponse.model_validate_json(response.content)
    assert payload.code == "RESPONSE_VALIDATION_ERROR"
    assert payload.retryable is False
    assert payload.error_step == "load_order"
    assert payload.run_id is not None
    await _assert_failed_run(e2e_application, payload.run_id, payload.code, "load_order")


class _fault_registry:
    """临时替换Tool注册表, 并在用例结束后恢复应用原注册表。"""

    def __init__(
        self,
        application: FastAPI,
        fault: str,
        *,
        read_timeout: float | None = None,
    ) -> None:
        self._application = application
        self._original_registry = application.state.tool_registry
        settings: Settings = application.state.settings
        if read_timeout is not None:
            settings = settings.model_copy(
                update={"business_read_timeout_seconds": read_timeout}
            )
        self._client = BusinessHttpClient(settings, transport=DemoFaultTransport(fault))

    async def __aenter__(self) -> None:
        self._application.state.tool_registry = create_read_tool_registry(self._client)

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self._application.state.tool_registry = self._original_registry
        await self._client.aclose()


async def _diagnose(
    application: FastAPI,
    order_id: str,
    user_message: str,
) -> httpx.Response:
    message_fingerprint = sha256(user_message.encode()).hexdigest()[:8]
    trace_id = f"trace-e2e-{order_id.lower()}-{message_fingerprint}"
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        return await client.post(
            "/api/agent/order-diagnosis",
            json={"order_id": order_id, "user_message": user_message},
            headers={
                "X-Trace-Id": trace_id,
                "X-User-Id": "reviewer-e2e",
                "X-User-Role": "REVIEWER",
            },
        )


async def _load_run(application: FastAPI, run_id: str) -> tuple[AgentRun, list[AgentStep]]:
    database = application.state.database
    async with database.session() as session:
        run = await AgentRunRepository(session).get(run_id)
        steps = await AgentStepRepository(session).list_by_run(run_id)
    assert run is not None
    return run, steps


async def _assert_failed_run(
    application: FastAPI,
    run_id: str,
    error_code: str,
    error_step: str,
) -> None:
    run, steps = await _load_run(application, run_id)
    assert run.status is AgentRunStatus.FAILED
    assert run.error_code == error_code
    assert run.error_step == error_step
    assert run.final_result is None
    assert [step.step_name for step in steps] == ["load_context", error_step]
    assert steps[-1].step_type is AgentStepType.TOOL
    assert steps[-1].status is AgentStepStatus.FAILED
    assert steps[-1].error_code == error_code


def _e2e_settings() -> Settings:
    database_url = os.getenv(DATABASE_URL_ENV)
    business_url = os.getenv(BUSINESS_URL_ENV)
    if database_url is None or business_url is None:
        pytest.skip(
            f"需要通过 {DATABASE_URL_ENV} 和 {BUSINESS_URL_ENV} 提供隔离E2E服务"
        )
    return Settings(
        environment="test",
        database_url=database_url,
        business_service_url=AnyHttpUrl(business_url),
    )


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
