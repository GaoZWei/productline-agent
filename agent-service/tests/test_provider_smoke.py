"""只读Provider烟测的单次预算、严格校验、脱敏和命令行契约。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr

from app.cli import provider_smoke
from app.cli.provider_smoke import run_smoke
from app.settings import Settings

SECRET = "smoke-test-secret"


@pytest.fixture(autouse=True)
def _isolate_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """避免开发机导出的模型变量覆盖测试输入, 更不能误连真实网关。"""

    for key in tuple(os.environ):
        if key.startswith(("MODEL_", "EMBEDDING_")):
            monkeypatch.delenv(key)


def _settings() -> Settings:
    """隔离本地环境文件, 使用不会指向真实服务的测试配置。"""

    return Settings(
        _env_file=None,
        model_name="chat-smoke",
        model_base_url=AnyHttpUrl("https://chat.example.test/v1"),
        model_api_key=SecretStr(SECRET),
        model_max_retries=3,
        embedding_model="embedding-smoke",
        embedding_base_url=AnyHttpUrl("https://embedding.example.test/v1"),
        embedding_api_key=SecretStr(SECRET),
        embedding_max_retries=3,
    )


def _chat_response(content: str = '{"status":"ok"}') -> httpx.Response:
    """供应商可返回版本别名, 烟测只报告差异而不误判为协议错误。"""

    return httpx.Response(200, json={
        "id": "chat-test",
        "object": "chat.completion",
        "created": 1,
        "model": "chat-smoke-version",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    })


def _embedding_response(
    *, dimension: int = 1536, model: str = "embedding-smoke", input_tokens: int | None = 9,
) -> httpx.Response:
    """提供已知向量与统计, 可制造缺失用量和模型不匹配反例。"""

    usage = {"total_tokens": 9}
    if input_tokens is not None:
        usage["prompt_tokens"] = input_tokens
    return httpx.Response(200, json={
        "object": "list",
        "model": model,
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] * dimension}],
        "usage": usage,
    })


@pytest.mark.unit
@pytest.mark.asyncio
async def test_smoke_uses_existing_clients_once_and_only_returns_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("completions"):
            return _chat_response()
        return _embedding_response()

    report = await run_smoke(
        _settings(),
        chat_transport=httpx.MockTransport(handler),
        embedding_transport=httpx.MockTransport(handler),
    )

    assert report["success"] is True
    assert len(requests) == 2
    chat_body = json.loads(requests[0].content)
    assert chat_body["max_tokens"] == 64
    assert "tools" not in chat_body
    assert json.loads(requests[1].content)["dimensions"] == 1536
    assert len(json.loads(requests[1].content)["input"]) == 1
    checks = report["checks"]
    assert isinstance(checks, list)
    assert checks[0]["total_tokens"] == 12
    assert checks[0]["model_matches"] is False
    assert checks[1]["dimension"] == 1536
    assert checks[1]["input_tokens"] == 9
    serialized = json.dumps(report)
    for forbidden in (SECRET, "example.test", "坐标系", "embedding\": [", "messages"):
        assert forbidden not in serialized


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["chat", "embedding"])
@pytest.mark.parametrize("failure", ["auth", "rate_limit", "upstream", "timeout", "invalid"])
async def test_smoke_reports_stable_errors_without_retry_or_response_leak(
    target: provider_smoke.SmokeTarget, failure: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout(f"{SECRET} https://private.example", request=request)
        if failure == "invalid":
            return (
                _chat_response(f'{{"status":"{SECRET}"}}')
                if target == "chat" else _embedding_response(dimension=3)
            )
        status = {"auth": 401, "rate_limit": 429, "upstream": 503}[failure]
        return httpx.Response(status, text=f"{SECRET} https://private.example")

    report = await run_smoke(
        _settings(), target=target,
        chat_transport=httpx.MockTransport(handler),
        embedding_transport=httpx.MockTransport(handler),
    )

    assert report["success"] is False
    assert calls == 1
    checks = report["checks"]
    assert isinstance(checks, list)
    assert len(checks) == 1
    suffix = {
        "auth": "AUTHENTICATION_ERROR", "rate_limit": "RATE_LIMITED",
        "upstream": "UPSTREAM_UNAVAILABLE", "timeout": "TIMEOUT",
        "invalid": "OUTPUT_VALIDATION_ERROR" if target == "chat" else "RESPONSE_VALIDATION_ERROR",
    }[failure]
    prefix = "MODEL" if target == "chat" else "EMBEDDING"
    assert checks[0]["error_code"] == f"{prefix}_{suffix}"
    assert SECRET not in json.dumps(report)
    assert "private.example" not in json.dumps(report)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_chat_configuration_does_not_skip_embedding() -> None:
    settings = _settings().model_copy(update={"model_name": None})
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _embedding_response(input_tokens=None)

    report = await run_smoke(settings, embedding_transport=httpx.MockTransport(handler))
    checks = report["checks"]
    assert isinstance(checks, list)
    assert report["success"] is False
    assert checks[0]["error_code"] == "MODEL_NOT_CONFIGURED"
    assert checks[1]["status"] == "passed"
    assert checks[1]["input_tokens"] is None
    assert checks[1]["total_tokens"] == 9
    assert calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_embedding_key_fails_without_external_request() -> None:
    settings = _settings().model_copy(update={"embedding_api_key": None})
    report = await run_smoke(settings, target="embedding")
    checks = report["checks"]
    assert isinstance(checks, list)
    assert report["success"] is False
    assert checks[0]["error_code"] == "PROVIDER_CONFIGURATION_ERROR"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embedding_model_mismatch_is_not_marked_as_passed() -> None:
    report = await run_smoke(
        _settings(), target="embedding",
        embedding_transport=httpx.MockTransport(lambda _: _embedding_response(model="other")),
    )
    checks = report["checks"]
    assert isinstance(checks, list)
    assert report["success"] is False
    assert checks[0]["error_code"] == "EMBEDDING_MODEL_MISMATCH"


@pytest.mark.unit
@pytest.mark.parametrize("failure", [False, True])
def test_cli_loads_default_root_env_and_returns_json_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: bool,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"EMBEDDING_MODEL=embedding-smoke\nEMBEDDING_API_KEY={SECRET}\n"
        "EMBEDDING_BASE_URL=https://embedding.example.test/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(provider_smoke, "DEFAULT_ENV_FILE", env_file)
    calls = 0

    async def handle(
        self: httpx.AsyncHTTPTransport, request: httpx.Request,
    ) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text=SECRET) if failure else _embedding_response()

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    previous_disable = logging.root.manager.disable
    try:
        exit_code = provider_smoke.main(["--target", "embedding"])
    finally:
        logging.disable(previous_disable)
    captured = capsys.readouterr()
    assert exit_code == (3 if failure else 0)
    assert json.loads(captured.out)["success"] is (not failure)
    assert SECRET not in captured.out + captured.err
    assert captured.err == ""
    assert calls == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "env_content", [None, "MODEL_NAME=test\nMODEL_BASE_URL=invalid-secret-url\n"],
)
def test_cli_missing_or_invalid_env_has_safe_configuration_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], env_content: str | None,
) -> None:
    env_file = tmp_path / "invalid.env"
    if env_content is not None:
        env_file.write_text(env_content, encoding="utf-8")
    previous_disable = logging.root.manager.disable
    try:
        exit_code = provider_smoke.main(["--env-file", str(env_file)])
    finally:
        logging.disable(previous_disable)
    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out) == {
        "success": False, "error_code": "PROVIDER_CONFIGURATION_ERROR",
    }
    assert "invalid-secret-url" not in captured.out + captured.err
