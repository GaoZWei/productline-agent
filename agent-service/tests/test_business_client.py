import json

import httpx
import pytest
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.clients.business import BusinessHttpClient, BusinessResponseValidationError
from app.main import create_app
from app.observability import reset_trace_id, set_trace_id
from app.schemas.business import BusinessIdentity
from app.settings import Settings


class OrderData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str = Field(alias="orderId")
    status: str


def success_response(data: object, trace_id: str = "trace-java-001") -> httpx.Response:
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


@pytest.mark.unit
def test_business_client_settings_validate_url_and_timeouts() -> None:
    settings = Settings(
        environment="test",
        business_service_url=AnyHttpUrl("https://business.example/api-root"),
        business_connect_timeout_seconds=1.5,
        business_read_timeout_seconds=4.0,
        business_write_timeout_seconds=2.5,
        business_pool_timeout_seconds=0.5,
    )

    assert str(settings.business_service_url) == "https://business.example/api-root"
    assert settings.business_connect_timeout_seconds == 1.5
    assert settings.business_read_timeout_seconds == 4.0
    assert settings.business_write_timeout_seconds == 2.5
    assert settings.business_pool_timeout_seconds == 0.5

    with pytest.raises(ValidationError):
        Settings(environment="test", business_read_timeout_seconds=0)

    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            business_service_url=AnyHttpUrl("ftp://business.example"),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fastapi_lifespan_owns_business_client() -> None:
    app = create_app(Settings(environment="test"))

    async with app.router.lifespan_context(app):
        client = app.state.business_client
        assert isinstance(client, BusinessHttpClient)
        assert client.is_closed is False

    assert client.is_closed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_forwards_identity_trace_and_query_parameters() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return success_response(
            {"orderId": "ORDER-003", "status": "QUALITY_CHECKING"},
            trace_id="trace-client-003",
        )

    client = BusinessHttpClient(
        Settings(
            environment="test",
            business_service_url=AnyHttpUrl("http://business.test"),
        ),
        transport=httpx.MockTransport(handler),
    )
    identity = BusinessIdentity(
        user_id="agent-user-001",
        role="REVIEWER",
        token=SecretStr("access-token-001"),
    )
    trace_token = set_trace_id("trace-client-003")
    try:
        response = await client.get(
            "/api/orders/ORDER-003",
            OrderData,
            identity=identity,
            params={"include": "tasks"},
        )
    finally:
        reset_trace_id(trace_token)
        await client.aclose()

    assert captured_request is not None
    assert captured_request.method == "GET"
    assert captured_request.url.path == "/api/orders/ORDER-003"
    assert captured_request.url.params["include"] == "tasks"
    assert captured_request.headers["X-User-Id"] == "agent-user-001"
    assert captured_request.headers["X-User-Role"] == "REVIEWER"
    assert captured_request.headers["Authorization"] == "Bearer access-token-001"
    assert captured_request.headers["X-Trace-Id"] == "trace-client-003"
    assert response.data.order_id == "ORDER-003"
    assert response.data.status == "QUALITY_CHECKING"
    assert response.trace_id == "trace-client-003"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_forwards_json_identity_trace_and_idempotency_key() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return success_response(
            {"orderId": "ORDER-003", "status": "REVIEWING"},
            trace_id="trace-write-003",
        )

    client = BusinessHttpClient(
        Settings(
            environment="test",
            business_service_url=AnyHttpUrl("http://business.test"),
        ),
        transport=httpx.MockTransport(handler),
    )
    response = await client.post(
        "/api/tasks/TASK-003/review",
        OrderData,
        json_body={"issueId": "ISSUE-001", "expectedVersion": 0},
        identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
        trace_id="trace-write-003",
        idempotency_key="review-order-003-v0",
    )
    await client.aclose()

    assert captured_request is not None
    assert captured_request.method == "POST"
    assert json.loads(captured_request.content) == {
        "issueId": "ISSUE-001",
        "expectedVersion": 0,
    }
    assert captured_request.headers["X-User-Id"] == "reviewer-001"
    assert captured_request.headers["X-User-Role"] == "REVIEWER"
    assert captured_request.headers["X-Trace-Id"] == "trace-write-003"
    assert captured_request.headers["Idempotency-Key"] == "review-order-003-v0"
    assert "Authorization" not in captured_request.headers
    assert response.data.status == "REVIEWING"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_builds_separate_httpx_timeouts() -> None:
    client = BusinessHttpClient(
        Settings(
            environment="test",
            business_connect_timeout_seconds=1.0,
            business_read_timeout_seconds=2.0,
            business_write_timeout_seconds=3.0,
            business_pool_timeout_seconds=4.0,
        )
    )

    assert client.timeout.connect == 1.0
    assert client.timeout.read == 2.0
    assert client.timeout.write == 3.0
    assert client.timeout.pool == 4.0
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_httpx_timeout_remains_available_for_m13_error_mapping() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout", request=request)

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(httpx.ReadTimeout):
        await client.get("/api/orders/ORDER-003", OrderData)

    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response"),
    [
        httpx.Response(200, content=b"not-json", headers={"X-Trace-Id": "trace-invalid"}),
        httpx.Response(
            200,
            headers={"X-Trace-Id": "trace-invalid"},
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "success",
                "trace_id": "trace-invalid",
                "retryable": False,
            },
        ),
        success_response({"orderId": "ORDER-003"}, trace_id="trace-invalid"),
        success_response(
            {"orderId": "ORDER-003", "status": "QUALITY_CHECKING"},
            trace_id="trace-body",
        ),
    ],
    ids=["invalid-json", "missing-data", "invalid-data-schema", "trace-mismatch"],
)
async def test_invalid_java_response_is_rejected(response: httpx.Response) -> None:
    if response.headers.get("X-Trace-Id") == "trace-body":
        response.headers["X-Trace-Id"] = "trace-header"

    async def handler(request: httpx.Request) -> httpx.Response:
        return response

    client = BusinessHttpClient(
        Settings(environment="test"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(BusinessResponseValidationError):
        await client.get("/api/orders/ORDER-003", OrderData)

    await client.aclose()
