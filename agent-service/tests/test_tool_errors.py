import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode, ToolException
from app.settings import Settings


class OrderData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str = Field(alias="orderId")
    status: str


def error_response(
    status_code: int,
    upstream_code: str,
    *,
    message: str = "safe business error",
    trace_id: str = "trace-error-001",
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": False,
            "code": upstream_code,
            "message": message,
            "data": None,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


async def call_with_response(response: httpx.Response) -> ToolException:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ToolException) as caught:
            await client.get("/api/orders/ORDER-003", OrderData, trace_id="trace-error-001")
        return caught.value
    finally:
        await client.aclose()


@pytest.mark.unit
def test_tool_error_code_defines_the_complete_m13_vocabulary() -> None:
    assert {code.value for code in ToolErrorCode} == {
        "PARAM_VALIDATION_ERROR",
        "RESOURCE_NOT_FOUND",
        "PERMISSION_DENIED",
        "BUSINESS_CONFLICT",
        "TOOL_TIMEOUT",
        "UPSTREAM_UNAVAILABLE",
        "RESPONSE_VALIDATION_ERROR",
        "DUPLICATE_CALL",
        "UNKNOWN_TOOL_ERROR",
    }


@pytest.mark.unit
def test_tool_exception_exposes_machine_fields_without_losing_the_message() -> None:
    error = ToolException(
        code=ToolErrorCode.RESOURCE_NOT_FOUND,
        message="order not found: ORDER-999",
        retryable=False,
        trace_id="trace-error-001",
        status_code=404,
    )

    assert error.code is ToolErrorCode.RESOURCE_NOT_FOUND
    assert error.message == "order not found: ORDER-999"
    assert error.retryable is False
    assert error.trace_id == "trace-error-001"
    assert error.status_code == 404
    assert str(error) == "RESOURCE_NOT_FOUND: order not found: ORDER-999"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "upstream_code", "expected_code"),
    [
        (400, "PARAM_VALIDATION_ERROR", ToolErrorCode.PARAM_VALIDATION_ERROR),
        (401, "PERMISSION_DENIED", ToolErrorCode.PERMISSION_DENIED),
        (403, "PERMISSION_DENIED", ToolErrorCode.PERMISSION_DENIED),
        (404, "RESOURCE_NOT_FOUND", ToolErrorCode.RESOURCE_NOT_FOUND),
        (409, "BUSINESS_CONFLICT", ToolErrorCode.BUSINESS_CONFLICT),
        (500, "INTERNAL_SERVER_ERROR", ToolErrorCode.UPSTREAM_UNAVAILABLE),
    ],
    ids=["400", "401", "403", "404", "409", "500"],
)
async def test_java_error_envelope_maps_to_standard_tool_error(
    status_code: int,
    upstream_code: str,
    expected_code: ToolErrorCode,
) -> None:
    error = await call_with_response(
        error_response(status_code, upstream_code, message=f"safe-{status_code}")
    )

    assert error.code is expected_code
    assert error.message == f"safe-{status_code}"
    assert error.retryable is False
    assert error.trace_id == "trace-error-001"
    assert error.status_code == status_code


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout_type",
    [
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
async def test_all_httpx_timeouts_map_to_retryable_tool_timeout(
    timeout_type: type[httpx.TimeoutException],
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise timeout_type("simulated timeout", request=request)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ToolException) as caught:
            await client.get(
                "/api/orders/ORDER-003",
                OrderData,
                trace_id="trace-timeout-001",
            )
    finally:
        await client.aclose()

    assert caught.value.code is ToolErrorCode.TOOL_TIMEOUT
    assert caught.value.retryable is True
    assert caught.value.trace_id == "trace-timeout-001"
    assert caught.value.status_code is None
    assert isinstance(caught.value.__cause__, timeout_type)
    assert calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_network_failure_maps_to_retryable_upstream_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private network detail", request=request)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ToolException) as caught:
            await client.get(
                "/api/orders/ORDER-003",
                OrderData,
                trace_id="trace-network-001",
            )
    finally:
        await client.aclose()

    assert caught.value.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert caught.value.message == "business service is unavailable"
    assert "private network detail" not in str(caught.value)
    assert caught.value.retryable is True
    assert caught.value.trace_id == "trace-network-001"
    assert isinstance(caught.value.__cause__, httpx.ConnectError)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json", headers={"X-Trace-Id": "trace-error-001"}),
        httpx.Response(
            200,
            headers={"X-Trace-Id": "trace-error-001"},
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "success",
                "trace_id": "trace-error-001",
                "retryable": False,
            },
        ),
        httpx.Response(
            200,
            headers={"X-Trace-Id": "trace-error-001"},
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "success",
                "data": {"orderId": "ORDER-003"},
                "trace_id": "trace-error-001",
                "retryable": False,
            },
        ),
        error_response(404, "BUSINESS_CONFLICT"),
        error_response(404, "RESOURCE_NOT_FOUND", trace_id="trace-body"),
    ],
    ids=[
        "invalid-json",
        "missing-data",
        "invalid-data-schema",
        "status-code-mismatch",
        "trace-mismatch",
    ],
)
async def test_invalid_java_response_maps_to_non_retryable_validation_error(
    response: httpx.Response,
) -> None:
    if response.headers.get("X-Trace-Id") == "trace-body":
        response.headers["X-Trace-Id"] = "trace-header"

    error = await call_with_response(response)

    assert error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert error.message == "business service returned an invalid response"
    assert error.retryable is False
    assert error.status_code == response.status_code
    assert "not-json" not in str(error)
