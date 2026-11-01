"""验证知识授权查询的严格契约、请求绑定、有限重试和失败阻断。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge import PermissionScope
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeAuthorizationResponse,
    KnowledgeManagementAction,
)
from app.settings import Settings
from app.tools.retry import RetryPolicy

_IDENTITY = BusinessIdentity(user_id="reviewer-001", role="REVIEWER")
_TRACE = "trace-knowledge-client-001"
type Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def _data(action: str = "READ", user_id: str = "reviewer-001") -> dict[str, object]:
    """构造与Java一致的授权响应数据。"""

    return {
        "userId": user_id,
        "action": action,
        "permissionScope": "INTERNAL_REVIEWER",
        "confirmationRequired": action != "READ",
    }


def _success(
    data: dict[str, object] | None = None, *, trace_id: str = _TRACE
) -> httpx.Response:
    """构造带一致Trace ID的Java成功信封。"""

    return httpx.Response(
        200,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "success",
            "data": _data() if data is None else data,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


@asynccontextmanager
async def _client(
    handler: Handler,
    *,
    timeout_seconds: float = 5.0,
    retry_policy: RetryPolicy | None = None,
) -> AsyncIterator[KnowledgeAuthorizationClient]:
    """创建独立MockTransport，始终由外层关闭共享业务Client。"""

    async def dispatch(request: httpx.Request) -> httpx.Response:
        """兼容同步与异步测试响应。"""

        result = handler(request)
        return await result if isinstance(result, Awaitable) else result

    business_client = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(dispatch)
    )
    try:
        yield KnowledgeAuthorizationClient(
            business_client, timeout_seconds=timeout_seconds, retry_policy=retry_policy
        )
    finally:
        await business_client.aclose()


@pytest.mark.parametrize("action", list(KnowledgeManagementAction))
@pytest.mark.asyncio
async def test_authorization_forwards_only_action_and_binds_java_result(
    action: KnowledgeManagementAction,
) -> None:
    """五类动作只发起授权查询，身份凭据和Trace透传但不进入请求体。"""

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _success(_data(action.value))

    identity = _IDENTITY.model_copy(update={"token": SecretStr("test-access-token")})
    async with _client(handler) as client:
        response = await client.authorize(
            KnowledgeAuthorizationRequest(action=action), identity=identity, trace_id=_TRACE
        )
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST" and request.url.path == "/api/knowledge/authorize"
    assert request.content == f'{{"action":"{action.value}"}}'.encode()
    assert request.headers["X-User-Id"] == identity.user_id
    assert request.headers["X-User-Role"] == identity.role
    assert request.headers["Authorization"] == "Bearer test-access-token"
    assert request.headers["X-Trace-Id"] == _TRACE
    assert "Idempotency-Key" not in request.headers
    assert response.data.action is action
    assert response.data.permission_scope is PermissionScope.INTERNAL_REVIEWER
    assert response.data.confirmation_required is (action is not KnowledgeManagementAction.READ)
    assert response.trace_id == _TRACE


@pytest.mark.parametrize(
    "raw_input",
    [
        {}, {"action": None}, {"action": 0}, {"action": True}, {"action": []},
        {"action": "read"}, {"action": "DELETE"}, {"action": " READ "},
        {"action": "PUBLISH", "confirmed": True},
        {"action": "READ", "permissionScope": "INTERNAL_REVIEWER"},
        {"action": "PUBLISH", "expectedVersion": 1},
    ],
)
@pytest.mark.asyncio
async def test_invalid_input_never_sends_http(raw_input: dict[str, object]) -> None:
    """参数错误在HTTP前阻断，不能携带客户端自报的确认或权限。"""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    async with _client(handler) as client:
        with pytest.raises(ToolException) as caught:
            await client.authorize(raw_input, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is ToolErrorCode.PARAM_VALIDATION_ERROR
    assert caught.value.retryable is False
    assert calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"userId": ""}, {"userId": "bad\nactor"}, {"userId": 123},
        {"action": "DELETE"}, {"action": 0}, {"permissionScope": "PUBLIC"},
        {"confirmationRequired": "false"}, {"confirmationRequired": 0},
        {"confirmationRequired": True}, {"confirmed": True},
    ],
)
def test_response_schema_rejects_unsafe_values(changes: dict[str, object]) -> None:
    """严格类型、范围和策略不匹配均不能成为有效授权结果。"""

    with pytest.raises(ValidationError):
        KnowledgeAuthorizationResponse.model_validate(_data() | changes)


@pytest.mark.parametrize(
    "data",
    [
        _data("PUBLISH", "another-user"), _data("READ"),
        _data("PUBLISH") | {"confirmationRequired": False},
        {"action": "PUBLISH", "permissionScope": "INTERNAL_REVIEWER"},
    ],
)
@pytest.mark.asyncio
async def test_mismatched_or_incomplete_authorization_is_not_retried(
    data: dict[str, object],
) -> None:
    """格式合法但属于另一用户/动作的响应也必须停止执行。"""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success(data)

    async with _client(handler) as client:
        with pytest.raises(ToolException) as caught:
            await client.authorize({"action": "PUBLISH"}, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert caught.value.retryable is False and calls == 1


@pytest.mark.parametrize(
    ("status", "java_code", "expected"),
    [
        (400, "PARAM_VALIDATION_ERROR", ToolErrorCode.PARAM_VALIDATION_ERROR),
        (401, "PERMISSION_DENIED", ToolErrorCode.PERMISSION_DENIED),
        (403, "PERMISSION_DENIED", ToolErrorCode.PERMISSION_DENIED),
        (404, "RESOURCE_NOT_FOUND", ToolErrorCode.RESOURCE_NOT_FOUND),
        (409, "BUSINESS_CONFLICT", ToolErrorCode.BUSINESS_CONFLICT),
        (500, "INTERNAL_SERVER_ERROR", ToolErrorCode.UPSTREAM_UNAVAILABLE),
    ],
)
@pytest.mark.asyncio
async def test_java_errors_keep_existing_mapping_without_retry(
    status: int, java_code: str, expected: ToolErrorCode,
) -> None:
    """错误信封不可重试时，即使是500也不能扩大调用次数。"""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            headers={"X-Trace-Id": _TRACE},
            json={
                "success": False, "code": java_code, "message": "request denied",
                "data": None, "trace_id": _TRACE, "retryable": False,
            },
        )

    async with _client(handler) as client:
        with pytest.raises(ToolException) as caught:
            await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is expected and caught.value.retryable is False
    assert caught.value.status_code == status and calls == 1


@pytest.mark.parametrize(
    "fault", ["invalid-json", "trace-mismatch", "request-trace-mismatch", "redirect", "bad-error"]
)
@pytest.mark.asyncio
async def test_protocol_errors_fail_closed_without_retry(fault: str) -> None:
    """错误正文、重定向和Trace冲突都不能静默放行或泄露原文。"""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if fault == "invalid-json":
            return httpx.Response(200, text="sensitive-invalid-payload")
        if fault == "trace-mismatch":
            result = _success()
            result.headers["X-Trace-Id"] = "trace-other"
            return result
        if fault == "request-trace-mismatch":
            return _success(trace_id="trace-other")
        return httpx.Response(302 if fault == "redirect" else 503, text="sensitive-invalid-payload")

    async with _client(handler) as client:
        with pytest.raises(ToolException) as caught:
            await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert caught.value.retryable is False and calls == 1
    assert "sensitive-invalid-payload" not in str(caught.value)


@pytest.mark.parametrize("fault", [httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.asyncio
async def test_transient_failure_retries_once_with_stable_trace_and_safe_logs(
    fault: type[httpx.RequestError], caplog: pytest.LogCaptureFixture,
) -> None:
    """默认仅重试一次，所有HTTP尝试属于同一授权查询与Trace。"""

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if len(captured) == 1:
            raise fault("sensitive-network-detail", request=request)
        return _success(trace_id=request.headers["X-Trace-Id"])

    with caplog.at_level(logging.WARNING, logger="agent-service.knowledge-authorization"):
        async with _client(handler) as client:
            response = await client.authorize({"action": "READ"}, identity=_IDENTITY)
    assert len(captured) == 2
    assert captured[0].content == captured[1].content
    assert (
        captured[0].headers["X-Trace-Id"]
        == captured[1].headers["X-Trace-Id"]
        == response.trace_id
    )
    assert "sensitive-network-detail" not in caplog.text and _IDENTITY.user_id not in caplog.text
    retries = [r for r in caplog.records if r.message == "knowledge_authorization_retry_scheduled"]
    assert len(retries) == 1


@pytest.mark.parametrize(
    ("fault", "code"),
    [(httpx.ReadTimeout, ToolErrorCode.TOOL_TIMEOUT),
     (httpx.ConnectError, ToolErrorCode.UPSTREAM_UNAVAILABLE)],
)
@pytest.mark.asyncio
async def test_repeated_transient_failure_stops_after_two_attempts(
    fault: type[httpx.RequestError], code: ToolErrorCode,
) -> None:
    """重试耗尽后保留错误类型，不返回空授权或缓存结果。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise fault("network failure", request=request)

    async with _client(handler) as client:
        with pytest.raises(ToolException) as caught:
            await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is code and calls == 2


@pytest.mark.parametrize("trace_id", [None, "-", ".invalid", ":invalid", "bad\ntrace", "x" * 129])
@pytest.mark.asyncio
async def test_trace_is_normalized_to_java_contract_once(trace_id: str | None) -> None:
    """缺省或非法Trace只生成一次安全标识，并与Java回显绑定。"""

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        actual_trace = request.headers["X-Trace-Id"]
        assert actual_trace.startswith("trace-")
        return _success(trace_id=actual_trace)

    async with _client(handler) as client:
        result = await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=trace_id)
    assert result.trace_id == captured[0].headers["X-Trace-Id"]


@pytest.mark.parametrize("during_backoff", [False, True])
@pytest.mark.asyncio
async def test_total_budget_includes_request_and_backoff(during_backoff: bool) -> None:
    """请求或退避超时都在同一预算内终止，不再发第二次请求。"""

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if during_backoff:
            raise httpx.ReadTimeout("retryable timeout", request=request)
        await asyncio.sleep(1)
        return _success()

    async with _client(handler, timeout_seconds=0.03) as client:
        with pytest.raises(ToolException) as caught:
            await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is ToolErrorCode.TOOL_TIMEOUT
    assert caught.value.retryable is False and calls == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry() -> None:
    """调用方取消不能被吞掉或转换成新的HTTP重试。"""

    started = asyncio.Event()
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
        return _success()

    async with _client(handler) as client:
        task = asyncio.create_task(client.authorize({"action": "READ"}, identity=_IDENTITY))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls == 1


@pytest.mark.asyncio
async def test_authorization_is_never_cached_after_an_earlier_success() -> None:
    """同一用户再次查询时必须访问Java并接受新的拒绝结果。"""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _success()
        return httpx.Response(
            403, headers={"X-Trace-Id": _TRACE},
            json={"success": False, "code": "PERMISSION_DENIED", "message": "denied",
                  "data": None, "trace_id": _TRACE, "retryable": False},
        )

    async with _client(handler) as client:
        await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=_TRACE)
        with pytest.raises(ToolException) as caught:
            await client.authorize({"action": "READ"}, identity=_IDENTITY, trace_id=_TRACE)
    assert caught.value.code is ToolErrorCode.PERMISSION_DENIED and calls == 2


@pytest.mark.parametrize(
    "path", ["/api/tasks/TASK-003/review", "/api/tasks/TASK-003/rework",
             "/api/knowledge/authorize?x=1", "https://business.test/api/knowledge/authorize"],
)
@pytest.mark.asyncio
async def test_readonly_post_cannot_be_used_for_writes_or_arbitrary_paths(path: str) -> None:
    """新增只读入口不能取消既有写POST的幂等要求。"""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success()

    business = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ValueError):
            await business.post_readonly(
                path, KnowledgeAuthorizationResponse,
                json_body={"action": "READ"}, identity=_IDENTITY,
            )
        with pytest.raises(ValueError):
            await business.post(
                "/api/tasks/TASK-003/review", KnowledgeAuthorizationResponse,
                json_body={}, identity=_IDENTITY, idempotency_key="",
            )
    finally:
        await business.aclose()
    assert calls == 0


@pytest.mark.parametrize("timeout_seconds", [0, -1, True, float("nan"), float("inf")])
@pytest.mark.asyncio
async def test_client_rejects_unbounded_or_invalid_budget(timeout_seconds: float) -> None:
    """预算配置必须有限且为正，构造错误不会访问Java。"""

    business = BusinessHttpClient(Settings(environment="test"))
    try:
        with pytest.raises(ValueError):
            KnowledgeAuthorizationClient(business, timeout_seconds=timeout_seconds)
    finally:
        await business.aclose()
