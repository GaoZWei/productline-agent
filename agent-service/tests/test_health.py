import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_preserves_safe_trace_id() -> None:
    app = create_app(Settings(environment="test"))

    async with app.router.lifespan_context(app):
        # 直接在测试进程中调用 FastAPI 应用。测试不监听真实端口。
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health", headers={"X-Trace-Id": "trace-test-001"})

    assert response.status_code == 200
    assert response.json() == {"service": "agent-service", "status": "UP"}
    assert response.headers["X-Trace-Id"] == "trace-test-001"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_replaces_unsafe_trace_id() -> None:
    app = create_app(Settings(environment="test"))

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health", headers={"X-Trace-Id": "unsafe trace id"})

    trace_id = response.headers["X-Trace-Id"]
    assert trace_id.startswith("trace-")
    assert trace_id != "unsafe trace id"
