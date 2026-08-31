import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl, SecretStr, ValidationError

from app.main import create_app
from app.schemas.model_capabilities import ModelCapabilitiesResponse
from app.services.model_capabilities import ModelCapabilityService
from app.settings import Settings


@pytest.mark.unit
def test_unconfigured_capabilities_hide_inactive_model_identity() -> None:
    capabilities = ModelCapabilityService(Settings(environment="test")).get()

    assert capabilities == ModelCapabilitiesResponse(
        configured=False,
        provider=None,
        model_name=None,
    )


@pytest.mark.unit
def test_configured_capabilities_only_include_safe_model_identity() -> None:
    settings = Settings(
        environment="test",
        model_name="test-chat-model",
        model_base_url=AnyHttpUrl("https://model.example.test/v1"),
        model_api_key=SecretStr("must-not-leak"),
    )

    payload = ModelCapabilityService(settings).get().model_dump()

    assert payload == {
        "configured": True,
        "provider": "openai_compatible",
        "model_name": "test-chat-model",
    }
    assert "must-not-leak" not in repr(payload)
    assert "model.example.test" not in repr(payload)


@pytest.mark.unit
def test_capabilities_schema_rejects_inconsistent_state() -> None:
    with pytest.raises(ValidationError, match="require provider and model_name"):
        ModelCapabilitiesResponse(
            configured=True,
            provider=None,
            model_name=None,
        )

    with pytest.raises(ValidationError, match="must not expose model identity"):
        ModelCapabilitiesResponse(
            configured=False,
            provider="openai_compatible",
            model_name="test-chat-model",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_capabilities_endpoint_returns_configured_state_without_secrets() -> None:
    application = create_app(
        Settings(
            environment="test",
            model_name="test-chat-model",
            model_base_url=AnyHttpUrl("https://model.example.test/v1"),
            model_api_key=SecretStr("must-not-leak"),
        )
    )

    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/agent/capabilities/model")

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "provider": "openai_compatible",
        "model_name": "test-chat-model",
    }
    assert "must-not-leak" not in response.text
    assert "model.example.test" not in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_capabilities_endpoint_reports_disabled_model_honestly() -> None:
    application = create_app(Settings(environment="test"))

    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/agent/capabilities/model")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "provider": None,
        "model_name": None,
    }
