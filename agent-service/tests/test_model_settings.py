"""M7.6-A模型配置的启用条件和敏感字段边界测试。"""

import pytest
from pydantic import AnyHttpUrl, ValidationError

from app.settings import Settings


@pytest.mark.unit
def test_empty_model_name_keeps_model_unconfigured_and_normalizes_legacy_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("MODEL_NAME", "  ")
    monkeypatch.setenv("MODEL_BASE_URL", "")
    monkeypatch.setenv("MODEL_API_KEY", "")

    settings = Settings(environment="test")

    assert settings.model_provider == "openai_compatible"
    assert settings.model_name is None
    assert settings.model_base_url is None
    assert settings.model_api_key is None
    assert settings.model_configured is False


@pytest.mark.unit
def test_configured_model_requires_address_but_allows_local_gateway_without_key() -> None:
    settings = Settings(
        environment="test",
        model_name="  local-structured-model  ",
        model_base_url=AnyHttpUrl("http://localhost:11434/v1"),
        model_api_key=None,
    )

    assert settings.model_provider == "openai_compatible"
    assert settings.model_name == "local-structured-model"
    assert str(settings.model_base_url) == "http://localhost:11434/v1"
    assert settings.model_api_key is None
    assert settings.model_configured is True


@pytest.mark.unit
def test_model_configuration_reads_environment_and_masks_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("MODEL_NAME", "decision-model-v2")
    monkeypatch.setenv("MODEL_BASE_URL", "https://models.example.test/v1")
    monkeypatch.setenv("MODEL_API_KEY", "model-secret-value")

    settings = Settings(environment="test")

    assert settings.model_provider == "openai_compatible"
    assert settings.model_name == "decision-model-v2"
    assert str(settings.model_base_url) == "https://models.example.test/v1"
    assert settings.model_api_key is not None
    assert settings.model_api_key.get_secret_value() == "model-secret-value"
    assert "model-secret-value" not in repr(settings)


@pytest.mark.unit
def test_model_name_without_base_url_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="MODEL_BASE_URL is required when MODEL_NAME is configured",
    ):
        Settings(
            environment="test",
            model_name="decision-model-v2",
        )


@pytest.mark.unit
def test_unsupported_model_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "unsupported-provider")
    monkeypatch.setenv("MODEL_NAME", "")

    with pytest.raises(ValidationError, match="openai_compatible"):
        Settings(environment="test")


@pytest.mark.unit
def test_model_retry_backoff_and_timeout_are_bounded() -> None:
    settings = Settings(
        environment="test",
        model_timeout_seconds=12.5,
        model_max_retries=3,
        model_initial_backoff_seconds=0.5,
        model_max_backoff_seconds=1.0,
    )

    assert settings.model_timeout_seconds == 12.5
    assert settings.model_max_retries == 3

    with pytest.raises(ValidationError, match="must not be smaller"):
        Settings(
            environment="test",
            model_initial_backoff_seconds=2.0,
            model_max_backoff_seconds=1.0,
        )
