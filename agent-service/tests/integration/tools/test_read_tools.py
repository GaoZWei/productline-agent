from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode
from app.schemas.business import BusinessIdentity
from app.settings import Settings
from app.tools import READ_TOOL_NAMES, ToolContext, create_read_tool_registry


@dataclass(frozen=True, slots=True)
class ReadToolCase:
    name: str
    input_field: str
    input_value: str
    permission: str
    path: str
    response_data: dict[str, Any]
    missing_field: str
    mismatch_path: tuple[str | int, ...]
    empty_collection_field: str | None = None

    @property
    def tool_input(self) -> dict[str, object]:
        return {self.input_field: self.input_value}


READ_TOOL_CASES = (
    ReadToolCase(
        name="get_order_detail",
        input_field="order_id",
        input_value="ORDER-003",
        permission="ORDER_READ",
        path="/api/orders/ORDER-003",
        response_data={
            "orderId": "ORDER-003",
            "productType": "DOM",
            "status": "QUALITY_CHECKING",
        },
        missing_field="status",
        mismatch_path=("orderId",),
    ),
    ReadToolCase(
        name="get_related_tasks",
        input_field="order_id",
        input_value="ORDER-003",
        permission="ORDER_READ",
        path="/api/orders/ORDER-003/tasks",
        response_data={
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
        missing_field="tasks",
        mismatch_path=("tasks", 0, "orderId"),
        empty_collection_field="tasks",
    ),
    ReadToolCase(
        name="get_task_detail",
        input_field="task_id",
        input_value="TASK-003",
        permission="TASK_READ",
        path="/api/tasks/TASK-003",
        response_data={
            "taskId": "TASK-003",
            "orderId": "ORDER-003",
            "status": "COMPLETED",
            "version": 0,
        },
        missing_field="version",
        mismatch_path=("taskId",),
    ),
    ReadToolCase(
        name="get_production_progress",
        input_field="task_id",
        input_value="TASK-003",
        permission="TASK_READ",
        path="/api/tasks/TASK-003/progress",
        response_data={
            "taskId": "TASK-003",
            "steps": [
                {
                    "stepId": "STEP-003-01",
                    "taskId": "TASK-003",
                    "stepName": "DOM 生产处理",
                    "sequenceNumber": 1,
                    "status": "COMPLETED",
                }
            ],
        },
        missing_field="steps",
        mismatch_path=("steps", 0, "taskId"),
        empty_collection_field="steps",
    ),
    ReadToolCase(
        name="get_quality_issues",
        input_field="task_id",
        input_value="TASK-003",
        permission="QUALITY_ISSUE_READ",
        path="/api/tasks/TASK-003/quality-issues",
        response_data={
            "taskId": "TASK-003",
            "issues": [
                {
                    "issueId": "ISSUE-001",
                    "taskId": "TASK-003",
                    "issueType": "COORDINATE_SYSTEM",
                    "status": "OPEN",
                    # 固定业务响应原文不能为了静态检查改变标点。
                    "description": "成果坐标系与生产规范要求不一致，问题尚未处理。",  # noqa: RUF001
                }
            ],
        },
        missing_field="issues",
        mismatch_path=("issues", 0, "taskId"),
        empty_collection_field="issues",
    ),
    ReadToolCase(
        name="get_review_result",
        input_field="task_id",
        input_value="TASK-003",
        permission="REVIEW_READ",
        path="/api/tasks/TASK-003/review",
        response_data={
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
        missing_field="reviews",
        mismatch_path=("taskId",),
        empty_collection_field="reviews",
    ),
    ReadToolCase(
        name="get_delivery_status",
        input_field="order_id",
        input_value="ORDER-003",
        permission="DELIVERY_READ",
        path="/api/orders/ORDER-003/delivery-status",
        response_data={
            "orderId": "ORDER-003",
            "records": [
                {
                    "deliveryId": "DELIVERY-003",
                    "orderId": "ORDER-003",
                    "status": "BLOCKED",
                }
            ],
        },
        missing_field="records",
        mismatch_path=("records", 0, "orderId"),
        empty_collection_field="records",
    ),
)


def success_response(data: object, trace_id: str = "trace-read-tool-001") -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "success",
            "data": data,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


def error_response(
    status_code: int,
    code: str,
    trace_id: str = "trace-read-tool-001",
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": False,
            "code": code,
            "message": "safe business error",
            "data": None,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


def tool_context(permission: str | None) -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="agent-user-001", role="REVIEWER"),
        permissions=frozenset() if permission is None else frozenset({permission}),
        trace_id="trace-read-tool-001",
        run_id="run-read-tool-001",
    )


def replace_nested_value(
    source: dict[str, Any],
    path: tuple[str | int, ...],
    value: object,
) -> dict[str, Any]:
    copied = copy.deepcopy(source)
    target: Any = copied
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    return copied


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
async def test_each_read_tool_calls_the_exact_java_endpoint_and_validates_output(
    case: ReadToolCase,
) -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return success_response(case.response_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert captured_request is not None
    assert captured_request.method == "GET"
    assert captured_request.url.path == case.path
    assert captured_request.headers["X-User-Id"] == "agent-user-001"
    assert captured_request.headers["X-User-Role"] == "REVIEWER"
    assert captured_request.headers["X-Trace-Id"] == "trace-read-tool-001"
    assert result.success is True
    assert result.data is not None
    assert result.data.model_dump(by_alias=True) == case.response_data


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    ("invalid_value", "case_id"),
    [("", "empty"), ("../invalid", "malformed")],
    ids=lambda value: value,
)
async def test_each_read_tool_rejects_empty_and_malformed_identifiers_before_http(
    case: ReadToolCase,
    invalid_value: str,
    case_id: str,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return success_response(case.response_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(
            {case.input_field: invalid_value},
            tool_context(case.permission),
        )
    finally:
        await client.aclose()

    assert case_id in {"empty", "malformed"}
    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.PARAM_VALIDATION_ERROR
    assert calls == 0


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
async def test_each_read_tool_rejects_missing_permission_before_http(
    case: ReadToolCase,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return success_response(case.response_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(None))
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.PERMISSION_DENIED
    assert calls == 0


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (error_response(404, "RESOURCE_NOT_FOUND"), ToolErrorCode.RESOURCE_NOT_FOUND),
        (error_response(500, "INTERNAL_SERVER_ERROR"), ToolErrorCode.UPSTREAM_UNAVAILABLE),
    ],
    ids=["not-found", "java-500"],
)
async def test_each_read_tool_maps_java_errors_without_retrying(
    case: ReadToolCase,
    response: httpx.Response,
    expected_code: ToolErrorCode,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is expected_code
    assert calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
async def test_each_read_tool_retries_java_timeout_once(case: ReadToolCase) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("simulated timeout", request=request)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_TIMEOUT
    assert result.error.retryable is True
    assert calls == 2


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
async def test_each_read_tool_rejects_java_data_with_missing_fields(
    case: ReadToolCase,
) -> None:
    incomplete_data = copy.deepcopy(case.response_data)
    incomplete_data.pop(case.missing_field)

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return success_response(incomplete_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
async def test_each_read_tool_rejects_structurally_valid_but_mismatched_resources(
    case: ReadToolCase,
) -> None:
    mismatched_data = replace_nested_value(
        case.response_data,
        case.mismatch_path,
        "ORDER-999" if case.input_field == "order_id" else "TASK-999",
    )

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return success_response(mismatched_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert result.error.retryable is False
    assert calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_TOOL_CASES, ids=lambda case: case.name)
async def test_each_read_tool_retries_connection_failure_then_succeeds(
    case: ReadToolCase,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("simulated connection failure", request=request)
        return success_response(case.response_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert result.success is True
    assert result.data is not None
    assert calls == 2


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [case for case in READ_TOOL_CASES if case.empty_collection_field is not None],
    ids=lambda case: case.name,
)
async def test_collection_read_tools_preserve_empty_lists_as_success(
    case: ReadToolCase,
) -> None:
    empty_data = copy.deepcopy(case.response_data)
    assert case.empty_collection_field is not None
    empty_data[case.empty_collection_field] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return success_response(empty_data)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        tool = create_read_tool_registry(client).get(case.name)
        result = await tool.execute(case.tool_input, tool_context(case.permission))
    finally:
        await client.aclose()

    assert result.success is True
    assert result.data is not None
    assert result.data.model_dump(by_alias=True)[case.empty_collection_field] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_contains_exactly_the_seven_planned_read_tools() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("registry creation must not perform HTTP requests")

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        registry = create_read_tool_registry(client)
    finally:
        await client.aclose()

    assert registry.names == tuple(sorted(READ_TOOL_NAMES))
    assert len(registry) == 7
