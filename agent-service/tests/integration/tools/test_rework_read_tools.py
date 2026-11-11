"""T822 Tool→T821 Client→MockTransport用例，不代替真实Java及数据库验收。"""

import asyncio
import copy
from dataclasses import dataclass

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode
from app.schemas.business import BusinessIdentity
from app.settings import Settings
from app.tools import READ_TOOL_NAMES, create_read_tool_registry
from app.tools.base import ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.registry import DuplicateToolRegistrationError, ToolNotRegisteredError
from app.tools.retry import RetryPolicy
from app.tools.rework_readonly import (
    REWORK_READ_TOOL_NAMES,
    create_rework_read_tool_registry,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
TASK = "TASK-T822-A"
REWORK = "REWORK-T822-A"
TRACE = "trace-t822"
RESOURCE: dict[str, object] = {"task_id": TASK, "rework_task_id": REWORK}
BASE = f"/api/tasks/{TASK}/reworks/{REWORK}"


@dataclass(frozen=True, slots=True)
class ReadCase:
    """每个Tool的独立输入、Java路径和完整返回样例。"""

    name: str
    tool_input: dict[str, object]
    path: str
    data: dict[str, object]


def processing(revision: int = 1) -> dict[str, object]:
    """说明和引用保持大小写与首尾空白的既有语义。"""

    return {
        "processingRevision": revision,
        "artifact": {"artifactId": "成果-A", "artifactVersion": "release-A"},
        "processingComment": "  人工修正说明🚀  ",
        "evidenceReferences": ["report:Case-A"],
        "registeredBy": "handler-test",
        "registeredAt": "2026-11-11T00:01:00.123456789Z",
    }


def page(record: dict[str, object]) -> dict[str, object]:
    """单页末尾显式null，不自动补出空游标或其他记录。"""

    return {"taskId": TASK, "reworkTaskId": REWORK, "records": [record], "nextCursor": None}


CASES = (
    ReadCase(
        "get_rework_detail",
        RESOURCE,
        BASE,
        {
            "reworkTask": {
                "reworkTaskId": REWORK,
                "taskId": TASK,
                "sourceIssueId": "ISSUE-T822-A",
                "status": "PENDING",
                "reason": "  原始创建原因🚀  ",
            },
            "issueStatus": "OPEN",
            "roundNumber": 1,
            "previousReworkTaskId": None,
            "allowedActions": ["START_REWORK"],
            "taskVersion": 4,
            "processing": None,
            "inspection": None,
            "review": None,
        },
    ),
    ReadCase("get_rework_results", RESOURCE, BASE + "/results", page(processing())),
    ReadCase(
        "get_rework_inspections",
        RESOURCE,
        BASE + "/inspections",
        page(
            {
                "inspectionId": "CHECK-T822-A",
                "inspectionSequence": 1,
                "roundNumber": 1,
                "processingRevision": 1,
                "inspectorId": "inspector-test",
                "inspectedAt": "2026-11-11T00:02:00Z",
                "result": "FAILED",
                "items": [
                    {
                        "checkItem": "坐标系",
                        "result": "FAILED",
                        "comment": "保留失败说明",
                        "evidenceReferences": ["report:failed-check"],
                    }
                ],
            }
        ),
    ),
    ReadCase(
        "get_rework_reviews",
        RESOURCE,
        BASE + "/reviews",
        page(
            {
                "reviewId": "REVIEW-T822-A",
                "reviewSequence": 1,
                "roundNumber": 1,
                "processingRevision": 1,
                "inspectionId": "CHECK-T822-PASS",
                "status": "REWORK_REQUIRED",
                "reviewComment": "  保留退回意见  ",
                "reviewedBy": "reviewer-test",
                "reviewedAt": "2026-11-11T00:03:00Z",
            }
        ),
    ),
    ReadCase(
        "get_effective_rework_reviews",
        {"task_id": TASK},
        f"/api/tasks/{TASK}/effective-reviews",
        {
            "taskId": TASK,
            "taskVersion": 4,
            "issues": [
                {
                    "issueId": "ISSUE-T822-A",
                    "reworkTaskId": REWORK,
                    "roundNumber": 1,
                    "processingRevision": None,
                    "inspectionId": None,
                    "review": None,
                    "legacyReviews": [],
                }
            ],
        },
    ),
    ReadCase(
        "get_delivery_conditions",
        {"order_id": "ORDER-T822-A"},
        "/api/orders/ORDER-T822-A/delivery-conditions",
        {
            "order": {
                "orderId": "ORDER-T822-A",
                "productType": "DOM",
                "status": "CREATED",
            },
            "tasks": [],
            "deliveryRecords": [],
            "blockers": [
                {
                    "code": "MISSING_PRODUCTION_TASKS",
                    "taskId": None,
                    "resourceId": "ORDER-T822-A",
                    "status": None,
                },
                {
                    "code": "MISSING_DELIVERY_RECORDS",
                    "taskId": None,
                    "resourceId": "ORDER-T822-A",
                    "status": None,
                },
            ],
            "hasBlockers": True,
        },
    ),
)


def context(
    permissions: frozenset[str] = frozenset({"REWORK_READ"}),
    role: str = "REVIEWER",
) -> ToolContext:
    """模拟服务端上下文，不从Tool参数获取角色、权限或令牌。"""

    return ToolContext(
        identity=BusinessIdentity(
            user_id="reviewer-test",
            role=role,
            token=SecretStr("synthetic-test-token"),
        ),
        permissions=permissions,
        trace_id=TRACE,
        run_id="run-t822",
    )


def shared_client(transport: httpx.MockTransport) -> BusinessHttpClient:
    """显式使用MockTransport，不连接Java。"""

    return BusinessHttpClient(
        Settings(environment="test", business_service_url=AnyHttpUrl("http://business.test")),
        transport=transport,
    )


def success(data: object) -> httpx.Response:
    """Java六字段成功信封和响应Header使用同一Trace。"""

    return httpx.Response(
        200,
        headers={"X-Trace-Id": TRACE},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "success",
            "data": data,
            "trace_id": TRACE,
            "retryable": False,
        },
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_six_tools_use_get_context_identity_and_original_java_facts(case: ReadCase) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """保留真实HTTP层请求供断言，而不是只模拟Client方法。"""

        captured.append(request)
        return success(case.data)

    shared = shared_client(httpx.MockTransport(handler))
    try:
        registry = create_rework_read_tool_registry(ReworkHttpClient(shared))
        result = await registry.get(case.name).execute(case.tool_input, context())
        assert result.success and result.data is not None
        assert result.data.model_dump(mode="json", by_alias=True) == case.data
        assert not shared.is_closed
    finally:
        await shared.aclose()
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET" and request.url.path == case.path
    assert request.headers["X-User-Id"] == "reviewer-test"
    assert request.headers["X-User-Role"] == "REVIEWER"
    assert request.headers["Authorization"] == "Bearer synthetic-test-token"
    assert request.headers["X-Trace-Id"] == TRACE
    assert "Idempotency-Key" not in request.headers and request.content == b""
    if "/results" in case.path or "/inspections" in case.path or "/reviews" in case.path:
        assert dict(request.url.params) == {"limit": "20"}
    else:
        assert not request.url.params


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_missing_permission_is_rejected_before_input_and_http(case: ReadCase) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """没有权限时不应到达此边界。"""

        captured.append(request)
        return success(case.data)

    shared = shared_client(httpx.MockTransport(handler))
    denied_context = context(frozenset({"TASK_READ", "REVIEW_READ"}))
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get(case.name)
        result = await tool.execute(
            {"role": "REVIEWER", "permissions": ["REWORK_READ"]}, denied_context
        )
        assert not result.success and result.error is not None
        assert result.error.code == ToolErrorCode.PERMISSION_DENIED
        assert not result.error.retryable and captured == []
        assert denied_context.tool_call_ledger.recorded_call_count == 0
    finally:
        await shared.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_unknown_self_reported_fields_are_rejected_without_http(case: ReadCase) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """合法身份不能让调用参数携带额外权限或业务结论。"""

        captured.append(request)
        return success(case.data)

    shared = shared_client(httpx.MockTransport(handler))
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get(case.name)
        for field in ("role", "permissions", "confirmed", "status", "expectedVersion"):
            result = await tool.execute({**case.tool_input, field: "self-reported"}, context())
            assert result.error is not None
            assert result.error.code == ToolErrorCode.PARAM_VALIDATION_ERROR
        assert captured == []
    finally:
        await shared.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_same_run_duplicate_is_blocked_and_explicit_refresh_reads_again(
    case: ReadCase,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """每次实际GET均返回相同合法结构。"""

        nonlocal calls
        calls += 1
        return success(case.data)

    shared = shared_client(httpx.MockTransport(handler))
    run = context()
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get(case.name)
        first = await tool.execute(case.tool_input, run)
        duplicate = await tool.execute(case.tool_input, run)
        refreshed = await tool.execute(case.tool_input, run, force_refresh=True)
        assert first.success and refreshed.success
        assert duplicate.error is not None and duplicate.error.code == ToolErrorCode.DUPLICATE_CALL
        assert calls == 2 and run.tool_call_ledger.recorded_call_count == 2
    finally:
        await shared.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("failure", ["network", "timeout"])
async def test_transient_error_retries_one_get_inside_the_same_run(
    case: ReadCase, failure: str
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """首个瞬时错误可恢复，第二次才返回有效事实。"""

        captured.append(request)
        if len(captured) == 1:
            if failure == "network":
                raise httpx.ConnectError("forced transient failure", request=request)
            raise httpx.ReadTimeout("forced transient timeout", request=request)
        return success(case.data)

    shared = shared_client(httpx.MockTransport(handler))
    run = context()
    policy = RetryPolicy(max_retries=1, initial_backoff_seconds=0.001)
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared), retry_policy=policy).get(
            case.name
        )
        result = await tool.execute(case.tool_input, run)
        assert result.success and len(captured) == 2
        assert run.tool_call_ledger.recorded_call_count == 1
        assert captured[0].url == captured[1].url
        assert captured[0].headers == captured[1].headers
    finally:
        await shared.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    "status,code",
    [
        (400, "PARAM_VALIDATION_ERROR"),
        (403, "PERMISSION_DENIED"),
        (404, "RESOURCE_NOT_FOUND"),
        (409, "BUSINESS_CONFLICT"),
        (500, "INTERNAL_SERVER_ERROR"),
    ],
)
async def test_java_rejections_are_not_retried(case: ReadCase, status: int, code: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """Java明确retryable=false，不能凭500就自动重试。"""

        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            headers={"X-Trace-Id": TRACE},
            json={
                "success": False,
                "code": code,
                "message": "safe rejection",
                "data": None,
                "trace_id": TRACE,
                "retryable": False,
            },
        )

    shared = shared_client(httpx.MockTransport(handler))
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get(case.name)
        result = await tool.execute(case.tool_input, context(role="VIEWER"))
        assert result.error is not None and not result.error.retryable
        expected = ToolErrorCode.UPSTREAM_UNAVAILABLE.value if status == 500 else code
        assert result.error.code.value == expected
        assert result.error.status_code == status and calls == 1
    finally:
        await shared.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("failure", ["schema", "resource", "trace"])
async def test_malformed_or_unrelated_facts_fail_without_retry(
    case: ReadCase, failure: str
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """合法信封不能掩盖错资源、错Trace或不完整业务结构。"""

        nonlocal calls
        calls += 1
        raw = copy.deepcopy(case.data)
        if failure == "schema":
            return success({"privateEvidence": "must-not-leak"})
        if failure == "resource":
            if case.name == "get_rework_detail":
                nested = raw["reworkTask"]
                assert isinstance(nested, dict)
                nested["taskId"] = "TASK-OTHER"
            elif case.name == "get_delivery_conditions":
                nested = raw["order"]
                assert isinstance(nested, dict)
                nested["orderId"] = "ORDER-OTHER"
            else:
                raw["taskId"] = "TASK-OTHER"
            return success(raw)
        return httpx.Response(
            200,
            headers={"X-Trace-Id": "trace-other"},
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "success",
                "data": raw,
                "trace_id": "trace-other",
                "retryable": False,
            },
        )

    shared = shared_client(httpx.MockTransport(handler))
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get(case.name)
        result = await tool.execute(case.tool_input, context())
        assert result.error is not None and not result.error.retryable
        assert result.error.code == ToolErrorCode.RESPONSE_VALIDATION_ERROR and calls == 1
        assert "privateEvidence" not in result.error.message
    finally:
        await shared.aclose()


@pytest.mark.parametrize("cursor", ["", "\ud800", "\0", "cursor\n", "cursor\r"])
async def test_unsafe_cursor_is_rejected_before_the_call_fingerprint(cursor: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """不能让无损UTF-8编码错误逃出BaseTool的结果边界。"""

        nonlocal calls
        calls += 1
        return success(page(processing()))

    shared = shared_client(httpx.MockTransport(handler))
    run = context()
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get("get_rework_results")
        result = await tool.execute({**RESOURCE, "cursor": cursor}, run)
        assert (
            result.error is not None and result.error.code == ToolErrorCode.PARAM_VALIDATION_ERROR
        )
        assert calls == 0 and run.tool_call_ledger.recorded_call_count == 0
    finally:
        await shared.aclose()


@pytest.mark.parametrize("limit", [0, 101, True, "20", 20.0, None])
async def test_page_limit_is_strict_and_bounded(limit: object) -> None:
    shared = shared_client(httpx.MockTransport(lambda _: success(page(processing()))))
    run = context()
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get("get_rework_results")
        result = await tool.execute({**RESOURCE, "limit": limit}, run)
        assert (
            result.error is not None and result.error.code == ToolErrorCode.PARAM_VALIDATION_ERROR
        )
        assert run.tool_call_ledger.recorded_call_count == 0
    finally:
        await shared.aclose()


async def test_history_pages_are_explicit_distinct_calls_and_defaults_share_one_fingerprint() -> (
    None
):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """游标原值参与翻页和指纹，不从Tool内部自动翻到末页。"""

        captured.append(request)
        raw = page(processing(1 if request.url.params.get("cursor") is None else 2))
        raw["nextCursor"] = "opaque.Cursor-A" if len(captured) == 1 else None
        return success(raw)

    shared = shared_client(httpx.MockTransport(handler))
    run = context()
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get("get_rework_results")
        first = await tool.execute(RESOURCE, run)
        duplicate = await tool.execute(
            {"taskId": TASK, "reworkTaskId": REWORK, "limit": 20, "cursor": None}, run
        )
        second = await tool.execute({**RESOURCE, "cursor": "opaque.Cursor-A"}, run)
        assert first.success and second.success
        assert first.data is not None and first.data.next_cursor == "opaque.Cursor-A"
        assert second.data is not None and second.data.next_cursor is None
        assert duplicate.error is not None and duplicate.error.code == ToolErrorCode.DUPLICATE_CALL
        assert len(captured) == 2
        assert dict(captured[1].url.params) == {"limit": "20", "cursor": "opaque.Cursor-A"}
    finally:
        await shared.aclose()


@pytest.mark.parametrize(
    "name", ["get_rework_results", "get_rework_inspections", "get_rework_reviews"]
)
async def test_empty_history_preserves_explicit_null_end_cursor(name: str) -> None:
    raw: dict[str, object] = {
        "taskId": TASK,
        "reworkTaskId": REWORK,
        "records": [],
        "nextCursor": None,
    }
    shared = shared_client(httpx.MockTransport(lambda _: success(raw)))
    try:
        tool = create_rework_read_tool_registry(ReworkHttpClient(shared)).get(name)
        result = await tool.execute(RESOURCE, context())
        assert result.success and result.data is not None
        assert result.data.records == [] and result.data.next_cursor is None
    finally:
        await shared.aclose()


async def test_legacy_detail_and_pending_review_are_returned_without_inventing_bindings() -> None:
    legacy = copy.deepcopy(CASES[0].data)
    legacy.update(roundNumber=None, allowedActions=[])
    current: dict[str, object] = {
        "taskId": TASK,
        "taskVersion": 4,
        "issues": [
            {
                "issueId": "ISSUE-T822-A",
                "reworkTaskId": None,
                "roundNumber": None,
                "processingRevision": None,
                "inspectionId": None,
                "review": None,
                "legacyReviews": [
                    {
                        "reviewId": "REVIEW-T822-OLD",
                        "issueId": "ISSUE-T822-A",
                        "status": "PENDING",
                        "reviewComment": None,
                    }
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        """两种查询独立返回，不在Tool内拼接成同一快照。"""

        return success(current if request.url.path.endswith("effective-reviews") else legacy)

    shared = shared_client(httpx.MockTransport(handler))
    try:
        registry = create_rework_read_tool_registry(ReworkHttpClient(shared))
        detail = await registry.get("get_rework_detail").execute(RESOURCE, context())
        effective = await registry.get("get_effective_rework_reviews").execute(
            {"task_id": TASK}, context()
        )
        assert detail.success and detail.data is not None
        assert detail.data.model_dump(mode="json", by_alias=True) == legacy
        assert effective.success and effective.data is not None
        assert effective.data.model_dump(mode="json", by_alias=True) == current
    finally:
        await shared.aclose()


async def test_retries_stop_at_two_attempts_and_can_be_disabled() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """持续瞬时失败也不能无限重试。"""

        nonlocal calls
        calls += 1
        raise httpx.ConnectError("forced failure", request=request)

    shared = shared_client(httpx.MockTransport(handler))
    try:
        client = ReworkHttpClient(shared)
        retrying = create_rework_read_tool_registry(
            client,
            retry_policy=RetryPolicy(max_retries=1, initial_backoff_seconds=0.001),
        ).get("get_rework_detail")
        failed = await retrying.execute(RESOURCE, context())
        assert failed.error is not None and failed.error.code == ToolErrorCode.UPSTREAM_UNAVAILABLE
        assert calls == 2
        once = create_rework_read_tool_registry(client, retry_policy=RetryPolicy(max_retries=0))
        assert not (await once.get("get_rework_detail").execute(RESOURCE, context())).success
        assert calls == 3
    finally:
        await shared.aclose()


async def test_total_timeout_includes_retry_backoff() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """退避长于总预算，不能等退避后又执行新HTTP。"""

        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("forced timeout", request=request)

    shared = shared_client(httpx.MockTransport(handler))
    try:
        registry = create_rework_read_tool_registry(
            ReworkHttpClient(shared),
            timeout=0.02,
            retry_policy=RetryPolicy(max_retries=1, initial_backoff_seconds=1.0),
        )
        result = await asyncio.wait_for(
            registry.get("get_rework_detail").execute(RESOURCE, context()), 2.0
        )
        assert result.error is not None and result.error.code == ToolErrorCode.TOOL_TIMEOUT
        assert calls == 1
    finally:
        await shared.aclose()


async def test_cancellation_propagates_without_retry_or_background_request() -> None:
    entered = asyncio.Event()
    hold = asyncio.Event()
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        """显式屏障确保取消发生在真实MockTransport请求内部。"""

        nonlocal calls
        calls += 1
        entered.set()
        await hold.wait()
        return success(CASES[0].data)

    shared = shared_client(httpx.MockTransport(handler))
    registry = create_rework_read_tool_registry(ReworkHttpClient(shared))
    pending = asyncio.create_task(registry.get("get_rework_detail").execute(RESOURCE, context()))
    try:
        await asyncio.wait_for(entered.wait(), 2.0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert calls == 1
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await shared.aclose()


async def test_registry_is_explicit_low_risk_and_does_not_change_old_seven_tools() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """构造、注册和枚举都不能访问Java。"""

        nonlocal calls
        calls += 1
        return success(CASES[0].data)

    shared = shared_client(httpx.MockTransport(handler))
    try:
        registry = create_rework_read_tool_registry(ReworkHttpClient(shared))
        assert registry.names == tuple(sorted(REWORK_READ_TOOL_NAMES)) and len(registry) == 6
        for name in registry.names:
            tool = registry.get(name)
            assert tool.risk_level == ToolRiskLevel.LOW
            assert tool.required_permissions == frozenset({"REWORK_READ"})
            assert tool.max_retries == 1 and tool.timeout == 5.0
        old = create_read_tool_registry(shared)
        assert old.names == tuple(sorted(READ_TOOL_NAMES)) and len(old) == 7
        assert not set(old.names).intersection(registry.names)
        with pytest.raises(ToolNotRegisteredError):
            registry.get("start_rework")
        with pytest.raises(DuplicateToolRegistrationError):
            registry.register(registry.get("get_rework_detail"))
        with pytest.raises(ValueError):
            create_rework_read_tool_registry(
                ReworkHttpClient(shared), retry_policy=RetryPolicy(max_retries=2)
            )
        assert calls == 0
    finally:
        await shared.aclose()
