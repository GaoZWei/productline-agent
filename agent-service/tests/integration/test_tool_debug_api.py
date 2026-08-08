from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

from app.api.tool_debug import ToolDebugInvokeRequest, ToolDebugRunContextStore
from app.main import create_app
from app.settings import Settings
from app.tools import BaseTool, ToolContext, ToolRegistry, ToolRiskLevel


class DebugEchoInput(BaseModel):
    """调试接口测试使用的严格输入。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    value: str


class DebugEchoOutput(BaseModel):
    """记录调试 Tool 收到的上下文。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    value: str
    user_id: str
    trace_id: str
    invocation: int


class DebugEchoTool(BaseTool[DebugEchoInput, DebugEchoOutput]):
    """通过返回上下文字段验证 HTTP 请求到 Tool 的映射。"""

    def __init__(self) -> None:
        super().__init__(
            name="debug_echo",
            description="返回调试输入和上下文字段",
            input_model=DebugEchoInput,
            output_model=DebugEchoOutput,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=frozenset({"ORDER_READ"}),
            timeout=1.0,
            max_retries=0,
        )
        self.calls = 0

    async def _execute(
        self,
        tool_input: DebugEchoInput,
        context: ToolContext,
    ) -> DebugEchoOutput | Mapping[str, object]:
        self.calls += 1
        return DebugEchoOutput(
            value=tool_input.value,
            user_id=context.identity.user_id,
            trace_id=context.trace_id,
            invocation=self.calls,
        )


def debug_request(
    *,
    value: str = "ORDER-003",
    permissions: list[str] | None = None,
    run_id: str = "debug-run-001",
    force_refresh: bool = False,
) -> dict[str, Any]:
    return {
        "arguments": {"value": value},
        "identity": {"user_id": "debug-user-001", "role": "REVIEWER"},
        "permissions": permissions if permissions is not None else ["ORDER_READ"],
        "run_id": run_id,
        "force_refresh": force_refresh,
    }


@pytest.mark.unit
@pytest.mark.parametrize("capacity", [True, 0, -1])
def test_tool_debug_run_context_store_rejects_invalid_capacity(capacity: object) -> None:
    with pytest.raises(ValueError, match="capacity"):
        ToolDebugRunContextStore(capacity=capacity)  # type: ignore[arg-type]


@pytest.mark.unit
def test_tool_debug_run_context_store_evicts_the_oldest_run() -> None:
    store = ToolDebugRunContextStore(capacity=2)
    first_request = ToolDebugInvokeRequest.model_validate(debug_request(run_id="debug-run-001"))
    second_request = ToolDebugInvokeRequest.model_validate(debug_request(run_id="debug-run-002"))
    third_request = ToolDebugInvokeRequest.model_validate(debug_request(run_id="debug-run-003"))

    first = store.resolve(first_request, trace_id="trace-debug-001")
    store.resolve(second_request, trace_id="trace-debug-002")
    store.resolve(third_request, trace_id="trace-debug-003")
    recreated_first = store.resolve(first_request, trace_id="trace-debug-004")

    assert store.size == 2
    assert recreated_first.tool_call_ledger is not first.tool_call_ledger


@asynccontextmanager
async def development_client(
    tool: DebugEchoTool,
) -> AsyncIterator[tuple[AsyncClient, DebugEchoTool]]:
    application = create_app(Settings(environment="development"))
    async with application.router.lifespan_context(application):
        registry = ToolRegistry()
        registry.register(tool)
        application.state.tool_registry = registry
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            yield client, tool


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["test", "production"])
async def test_tool_debug_route_is_not_registered_outside_development(
    environment: str,
) -> None:
    application = create_app(Settings(environment=environment))  # type: ignore[arg-type]

    assert "/internal/tools/{tool_name}/invoke" not in application.openapi()["paths"]
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(),
        )

    assert response.status_code == 404


@pytest.mark.integration
def test_tool_debug_openapi_contains_request_and_response_examples() -> None:
    application = create_app(Settings(environment="development"))

    openapi = application.openapi()
    operation = openapi["paths"]["/internal/tools/{tool_name}/invoke"]["post"]
    request_schema = openapi["components"]["schemas"]["ToolDebugInvokeRequest"]

    assert operation["tags"] == ["internal-tools"]
    assert operation["summary"] == "调试调用只读 Tool"
    assert request_schema["examples"][0]["arguments"] == {"order_id": "ORDER-003"}
    result_examples = operation["responses"]["200"]["content"]["application/json"]["examples"]
    assert result_examples["success"]["value"]["data"] == {
        "orderId": "ORDER-003",
        "productType": "DOM",
        "status": "QUALITY_CHECKING",
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_debug_endpoint_maps_request_to_standard_success_result() -> None:
    async with development_client(DebugEchoTool()) as (client, tool):
        response = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(),
            headers={"X-Trace-Id": "trace-debug-001"},
        )

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "trace-debug-001"
    assert response.json() == {
        "success": True,
        "data": {
            "value": "ORDER-003",
            "user_id": "debug-user-001",
            "trace_id": "trace-debug-001",
            "invocation": 1,
        },
        "error": None,
    }
    assert tool.calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_debug_endpoint_returns_standard_tool_failure_with_http_200() -> None:
    async with development_client(DebugEchoTool()) as (client, tool):
        response = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(value="", permissions=[]),
            headers={"X-Trace-Id": "trace-debug-error-001"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "PERMISSION_DENIED"
    assert payload["error"]["retryable"] is False
    assert payload["error"]["trace_id"] == "trace-debug-error-001"
    assert tool.calls == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_debug_endpoint_keeps_one_context_for_repeated_run_calls() -> None:
    async with development_client(DebugEchoTool()) as (client, tool):
        first = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(),
            headers={"X-Trace-Id": "trace-debug-first"},
        )
        duplicate = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(),
            headers={"X-Trace-Id": "trace-debug-second"},
        )

    assert first.json()["success"] is True
    assert duplicate.status_code == 200
    assert duplicate.json()["error"]["code"] == "DUPLICATE_CALL"
    assert duplicate.json()["error"]["trace_id"] == "trace-debug-second"
    assert tool.calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_debug_endpoint_allows_explicit_force_refresh() -> None:
    async with development_client(DebugEchoTool()) as (client, tool):
        first = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(),
        )
        refreshed = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(force_refresh=True),
        )

    assert first.json()["success"] is True
    assert refreshed.json()["success"] is True
    assert refreshed.json()["data"]["invocation"] == 2
    assert tool.calls == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_debug_endpoint_rejects_unknown_tool_and_run_context_changes() -> None:
    async with development_client(DebugEchoTool()) as (client, tool):
        unknown = await client.post(
            "/internal/tools/not_registered/invoke",
            json=debug_request(),
        )
        first = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=debug_request(),
        )
        changed_context = debug_request()
        changed_context["identity"] = {"user_id": "other-user", "role": "REVIEWER"}
        conflict = await client.post(
            "/internal/tools/debug_echo/invoke",
            json=changed_context,
        )

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "tool is not registered"}
    assert first.json()["success"] is True
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "run context does not match its first invocation"}
    assert tool.calls == 1
