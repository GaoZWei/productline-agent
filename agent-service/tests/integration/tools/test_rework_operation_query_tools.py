"""T824只读结果核对与错误矩阵。FakeStore和MockTransport不代表生产确认恢复。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.models import ApprovalStatus
from app.schemas.rework_operation_query import (
    ReworkOperationQueryRequest,
    ReworkOperationResolution,
)
from app.tools.base import ToolRiskLevel
from app.tools.retry import RetryPolicy
from app.tools.rework_operation_query import (
    QueryReworkOperationTool,
    create_rework_operation_query_tool_registry,
)
from app.tools.rework_write import create_rework_write_tool_registry
from tests.integration.tools.test_rework_write_tools import (
    APPROVAL,
    CASES,
    INPUT,
    KEY,
    START,
    TASK,
    TRACE,
    Case,
    FakeStore,
    context,
    receipt,
    response,
    shared,
    snapshot,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
PATH = f"/api/tasks/{TASK}/reworks/operations/query"


def found(case: Case = START) -> dict[str, object]:
    """Java响应只携带首次原回执，不添加当前业务状态。"""

    return {"found": True, "receipt": receipt(case)}


async def test_independent_registry_construction_does_not_query_or_authorize_writes() -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(found())

    client = shared(httpx.MockTransport(handler))
    try:
        registry = create_rework_operation_query_tool_registry(ReworkHttpClient(client), store)
        assert frozenset(registry.names) == {"query_rework_operation"}
        tool = registry.get("query_rework_operation")
        assert tool.timeout == 5.0 and tool.max_retries == 1
        assert calls == [] and store.reads == [] and store.saved == []
    finally:
        await client.aclose()


async def test_maximum_task_id_is_allowed_by_only_the_exact_query_path() -> None:
    task = "TASK-" + "A" * 59
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == f"/api/tasks/{task}/reworks/operations/query"
        return response({"found": False, "receipt": None})

    client = shared(httpx.MockTransport(handler))
    try:
        result = await ReworkHttpClient(client).query_operation(
            task,
            ReworkOperationQueryRequest(idempotency_key=KEY),
            identity=context().identity,
            trace_id=TRACE,
        )
        assert not result.data.found and result.data.receipt is None and len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.operation)
async def test_nine_operations_match_original_receipt_without_any_store_write(case: Case) -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot(case))

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST" and request.url.path == PATH
        assert json.loads(request.content) == {"idempotencyKey": KEY}
        assert not request.url.query and "Idempotency-Key" not in request.headers
        assert request.headers["X-User-Id"] == "reviewer-test"
        assert request.headers["X-User-Role"] == "REVIEWER"
        assert request.headers["X-Trace-Id"] == TRACE
        return response(found(case))

    client = shared(httpx.MockTransport(handler))
    try:
        tool = QueryReworkOperationTool(ReworkHttpClient(client), store)
        assert tool.risk_level is ToolRiskLevel.LOW
        assert tool.required_permissions == frozenset({"REWORK_READ"})
        result = await tool.execute(INPUT, context("REWORK_READ"))
        assert result.success and result.data is not None
        assert result.data.outcome == "MATCHED_RECEIPT"
        assert result.data.receipt is not None
        assert result.data.receipt.model_dump(mode="json", by_alias=True) == receipt(case)
        assert result.data.java_trace_id == TRACE and len(calls) == 1
        assert store.saved == [] and store.reads == [APPROVAL, APPROVAL]
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "path",
    [
        "/api/tasks/TASK-A/reworks/start",
        "/api/tasks/TASK-A/reworks/operations/query/extra",
        "/api/tasks/TASK-A/reworks/operations/query?x=1",
        "/api/tasks/TASK-A/reworks/operations/query#x",
        "/api/tasks/TASK-A/../TASK-B/reworks/operations/query",
        "/api/tasks/task-a/reworks/operations/query",
        "/api/tasks/TASK-" + "A" * 60 + "/reworks/operations/query",
        "/api/tasks/TASK-A/rework",
        "/api/tasks/TASK-A%2FB/reworks/operations/query",
        "/api/tasks/TASK-A/reworks/operations/query\n",
    ],
)
async def test_readonly_post_whitelist_rejects_other_paths_without_http(path: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response({"found": False, "receipt": None})

    client = shared(httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="approved read-only POST"):
            await client.post_readonly(
                path, ReworkOperationResolution, json_body={}, identity=context().identity
            )
        assert calls == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("task,key", [("TASK_bad", KEY), ("TASK-A/other", KEY), (TASK, "x\n")])
async def test_client_rejects_bad_parameters_before_http(task: str, key: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response({"found": False, "receipt": None})

    client = shared(httpx.MockTransport(handler))
    try:
        with pytest.raises(ToolException) as caught:
            await ReworkHttpClient(client).query_operation(
                task,
                ReworkOperationQueryRequest.model_construct(idempotency_key=key),
                identity=context().identity,
                trace_id=TRACE,
            )
        assert caught.value.code is ToolErrorCode.PARAM_VALIDATION_ERROR
        assert calls == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("field", ["task_id", "confirmed", "operation", "request", "user_id"])
async def test_extra_input_cannot_choose_query_scope_or_authority(field: str) -> None:
    store = FakeStore(snapshot())
    client = shared(httpx.MockTransport(lambda _: response(found())))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            {**INPUT, field: "untrusted"}, context("REWORK_READ")
        )
        assert (
            result.error is not None and result.error.code is ToolErrorCode.PARAM_VALIDATION_ERROR
        )
        assert store.reads == [] and store.saved == []
    finally:
        await client.aclose()


async def test_permission_gate_precedes_store_and_invalid_key_precedes_fingerprint() -> None:
    store = FakeStore(snapshot())
    client = shared(httpx.MockTransport(lambda _: response(found())))
    try:
        tool = QueryReworkOperationTool(ReworkHttpClient(client), store)
        denied = await tool.execute(INPUT, context("REWORK_WRITE"))
        assert denied.error is not None and denied.error.code is ToolErrorCode.PERMISSION_DENIED
        invalid = await tool.execute({**INPUT, "idempotency_key": "x\n"}, context("REWORK_READ"))
        assert (
            invalid.error is not None and invalid.error.code is ToolErrorCode.PARAM_VALIDATION_ERROR
        )
        assert store.reads == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", ToolErrorCode.RESOURCE_NOT_FOUND),
        ("owner", ToolErrorCode.PERMISSION_DENIED),
        ("run", ToolErrorCode.PERMISSION_DENIED),
        ("confirmer", ToolErrorCode.PERMISSION_DENIED),
        ("approval", ToolErrorCode.RESPONSE_VALIDATION_ERROR),
        ("version", ToolErrorCode.RESPONSE_VALIDATION_ERROR),
        ("key", ToolErrorCode.BUSINESS_CONFLICT),
        ("unconfirmed", ToolErrorCode.BUSINESS_CONFLICT),
        ("future", ToolErrorCode.BUSINESS_CONFLICT),
    ],
)
async def test_confirmation_gate_blocks_untrusted_lookup_before_http(
    kind: str, code: ToolErrorCode
) -> None:
    value = snapshot()
    changes: dict[str, dict[str, object]] = {
        "owner": {"owner_user_id": "other"},
        "run": {"run_id": "other"},
        "confirmer": {"confirmed_by_user_id": "other"},
        "approval": {"approval_id": "other"},
        "version": {"task_version": 100},
        "key": {"idempotency_key": "other"},
        "unconfirmed": {"confirmed_at": None},
        "future": {"confirmed_at": datetime.now(UTC) + timedelta(days=1)},
    }
    if kind != "missing":
        value = value.model_copy(update=changes[kind])
    store = FakeStore(None if kind == "missing" else value)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(found())

    client = shared(httpx.MockTransport(handler))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        assert result.error is not None and result.error.code is code and not result.error.retryable
        assert calls == [] and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status",
    [
        s
        for s in ApprovalStatus
        if s not in {ApprovalStatus.EXECUTING, ApprovalStatus.SUCCEEDED, ApprovalStatus.FAILED}
    ],
)
async def test_unexecuted_confirmation_states_cannot_be_used_for_lookup(
    status: ApprovalStatus,
) -> None:
    store = FakeStore(snapshot().model_copy(update={"status": status}))
    client = shared(httpx.MockTransport(lambda _: response(found())))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        assert result.error is not None and result.error.code is ToolErrorCode.BUSINESS_CONFLICT
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status", [ApprovalStatus.EXECUTING, ApprovalStatus.SUCCEEDED, ApprovalStatus.FAILED]
)
async def test_expired_but_previously_confirmed_snapshot_allows_only_read_lookup(
    status: ApprovalStatus,
) -> None:
    value = snapshot().model_copy(
        update={
            "status": status,
            "confirmed_at": datetime.now(UTC) - timedelta(days=2),
            "expires_at": datetime.now(UTC) - timedelta(days=1),
        }
    )
    store = FakeStore(value)
    client = shared(httpx.MockTransport(lambda _: response(found())))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        assert (
            result.success and result.data is not None and result.data.outcome == "MATCHED_RECEIPT"
        )
        assert store.snapshot == value and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status,code",
    [
        (400, ToolErrorCode.PARAM_VALIDATION_ERROR),
        (401, ToolErrorCode.PERMISSION_DENIED),
        (403, ToolErrorCode.PERMISSION_DENIED),
        (404, ToolErrorCode.RESOURCE_NOT_FOUND),
        (409, ToolErrorCode.BUSINESS_CONFLICT),
        (500, ToolErrorCode.UPSTREAM_UNAVAILABLE),
    ],
)
async def test_java_errors_are_not_disguised_as_unknown_or_retried(
    status: int, code: ToolErrorCode
) -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status,
            headers={"X-Trace-Id": TRACE},
            json={
                "success": False,
                "code": "INTERNAL_SERVER_ERROR" if status == 500 else code.value,
                "message": "rejected",
                "data": None,
                "trace_id": TRACE,
                "retryable": False,
            },
        )

    client = shared(httpx.MockTransport(handler))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        assert result.error is not None and result.error.code is code and not result.error.retryable
        assert result.data is None and len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "RESUME_REWORK"),
        ("taskId", "TASK-OTHER"),
        ("reworkTaskId", "REWORK-OTHER"),
        ("taskVersion", 6),
        ("status", "COMPLETED"),
        ("issueStatus", "CLOSED"),
        ("roundNumber", 2),
        ("processingRevision", 1),
    ],
)
async def test_mismatched_original_receipt_never_becomes_a_success_fact(
    field: str, value: object
) -> None:
    raw = receipt()
    raw[field] = value
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response({"found": True, "receipt": raw})

    client = shared(httpx.MockTransport(handler))
    store = FakeStore(snapshot())
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        assert (
            result.error is not None
            and result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
        )
        assert len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


async def test_unknown_does_not_poll_or_rewrite_and_only_explicit_refresh_queries_again() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response({"found": False, "receipt": None} if len(calls) == 1 else found())

    client = shared(httpx.MockTransport(handler))
    store = FakeStore(snapshot())
    try:
        tool, ctx = (
            QueryReworkOperationTool(ReworkHttpClient(client), store),
            context("REWORK_READ"),
        )
        unknown = await tool.execute(INPUT, ctx)
        assert unknown.success and unknown.data is not None
        assert (
            unknown.data.outcome == "UNKNOWN" and unknown.data.receipt is None and len(calls) == 1
        )
        duplicate = await tool.execute(INPUT, ctx)
        assert duplicate.error is not None and duplicate.error.code is ToolErrorCode.DUPLICATE_CALL
        matched = await tool.execute(INPUT, ctx, force_refresh=True)
        assert matched.data is not None and matched.data.outcome == "MATCHED_RECEIPT"
        assert len(calls) == 2 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("failure", ["timeout-after-commit", "save-conflict-after-commit"])
async def test_uncertain_write_is_never_resent_and_read_query_recovers_only_original_fact(
    failure: str,
) -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())
    store.allow_save = failure != "save-conflict-after-commit"

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == PATH:
            return response(found())
        assert request.url.path.endswith("/start") and request.headers["Idempotency-Key"] == KEY
        if failure == "timeout-after-commit":
            raise httpx.ReadTimeout("simulated lost committed response", request=request)
        return response(receipt())

    client = shared(httpx.MockTransport(handler))
    try:
        adapter = ReworkHttpClient(client)
        failed = (
            await create_rework_write_tool_registry(adapter, store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert failed.error is not None and not failed.error.retryable
        assert failed.error.code is (
            ToolErrorCode.TOOL_TIMEOUT
            if failure == "timeout-after-commit"
            else ToolErrorCode.BUSINESS_CONFLICT
        )
        result = await QueryReworkOperationTool(adapter, store).execute(
            INPUT, context("REWORK_READ")
        )
        assert result.data is not None and result.data.outcome == "MATCHED_RECEIPT"
        assert len(calls) == 2 and store.saved == []
        assert store.snapshot is not None and store.snapshot.status is ApprovalStatus.EXECUTING
    finally:
        await client.aclose()


@pytest.mark.parametrize("always_fail", [False, True])
async def test_only_read_transient_failure_can_retry_once(always_fail: bool) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if always_fail or len(calls) == 1:
            raise httpx.ReadTimeout("query timeout", request=request)
        return response(found())

    client = shared(httpx.MockTransport(handler))
    store = FakeStore(snapshot())
    try:
        result = await QueryReworkOperationTool(
            ReworkHttpClient(client),
            store,
            retry_policy=RetryPolicy(max_retries=1, initial_backoff_seconds=0.001),
        ).execute(INPUT, context("REWORK_READ"))
        assert len(calls) == 2 and all(r.url.path == PATH for r in calls)
        if always_fail:
            assert result.error is not None and result.error.code is ToolErrorCode.TOOL_TIMEOUT
        else:
            assert result.data is not None and result.data.outcome == "MATCHED_RECEIPT"
        assert store.saved == []
    finally:
        await client.aclose()


async def test_confirmation_changed_during_lookup_rejects_late_result() -> None:
    store = FakeStore(snapshot())

    def handler(_: httpx.Request) -> httpx.Response:
        assert store.snapshot is not None
        store.snapshot = store.snapshot.model_copy(update={"status": ApprovalStatus.SUCCEEDED})
        return response(found())

    client = shared(httpx.MockTransport(handler))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        assert result.error is not None and result.error.code is ToolErrorCode.BUSINESS_CONFLICT
        assert store.saved == []
    finally:
        await client.aclose()


async def test_total_budget_and_external_cancellation_do_not_spawn_background_queries() -> None:
    calls: list[httpx.Request] = []
    entered = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()
        return response(found())

    client = shared(httpx.MockTransport(handler))
    store = FakeStore(snapshot())
    try:
        tool = QueryReworkOperationTool(ReworkHttpClient(client), store, timeout=0.02)
        result = await tool.execute(INPUT, context("REWORK_READ"))
        assert result.error is not None and result.error.code is ToolErrorCode.TOOL_TIMEOUT
        assert len(calls) == 1
        entered.clear()
        task = asyncio.create_task(tool.execute(INPUT, context("REWORK_READ")))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 2 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("kind", ["bad-trace", "bad-schema", "lost-snapshot"])
async def test_lookup_integrity_errors_never_return_unknown(kind: str) -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if kind == "lost-snapshot":
            store.snapshot = None
        result = response({"found": True, "receipt": None} if kind == "bad-schema" else found())
        if kind == "bad-trace":
            raw = json.loads(result.content)
            raw["trace_id"] = "trace-other"
            return httpx.Response(200, headers={"X-Trace-Id": "trace-other"}, json=raw)
        return result

    client = shared(httpx.MockTransport(handler))
    try:
        result = await QueryReworkOperationTool(ReworkHttpClient(client), store).execute(
            INPUT, context("REWORK_READ")
        )
        expected = (
            ToolErrorCode.RESOURCE_NOT_FOUND
            if kind == "lost-snapshot"
            else ToolErrorCode.RESPONSE_VALIDATION_ERROR
        )
        assert result.error is not None and result.error.code is expected and result.data is None
        assert len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "outcome,raw", [("MATCHED_RECEIPT", None), ("UNKNOWN", receipt()), ("FAILED", None)]
)
async def test_resolution_schema_cannot_invent_failure_or_contradict_receipt(
    outcome: str, raw: object
) -> None:
    with pytest.raises(ValidationError):
        ReworkOperationResolution.model_validate(
            {"approval_id": APPROVAL, "outcome": outcome, "receipt": raw, "java_trace_id": TRACE}
        )
