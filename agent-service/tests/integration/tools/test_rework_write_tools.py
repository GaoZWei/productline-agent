"""T823写Tool→Client→MockTransport验收，确认快照来自显式Fake，不代表生产确认接线。"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode
from app.models import ApprovalStatus
from app.schemas.business import BusinessIdentity
from app.schemas.rework import RegisterReworkResultRequest, ReworkOperation
from app.schemas.rework_write_tools import (
    ReworkExecutionSnapshot,
    ReworkWriteInput,
    ReworkWriteOutput,
    ReworkWriteRequest,
)
from app.settings import Settings
from app.tools.base import ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.rework_readonly import REWORK_READ_TOOL_NAMES
from app.tools.rework_write import REWORK_WRITE_TOOL_NAMES, create_rework_write_tool_registry
from app.tools.write import WRITE_TOOL_NAMES

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
TASK, REWORK, ISSUE = "TASK-T823-A", "REWORK-T823-A", "ISSUE-T823-A"
TRACE, RUN, APPROVAL, KEY = "trace-t823", "run-t823", "approval-t823", "key-t823"


@dataclass(frozen=True)
class Case:
    """独立列出冻结的Java路径和操作，不从被测注册表推导预期值。"""

    name: str
    operation: ReworkOperation
    suffix: str


CASES = (
    Case("create_lifecycle_rework", "CREATE_LIFECYCLE_REWORK", ""),
    Case("start_rework", "START_REWORK", "start"),
    Case("block_rework", "BLOCK_REWORK", "block"),
    Case("fail_rework", "FAIL_REWORK", "fail"),
    Case("resume_rework", "RESUME_REWORK", "resume"),
    Case("register_rework_result", "REGISTER_REWORK_RESULT", "results"),
    Case("register_rework_inspection", "REGISTER_REWORK_INSPECTION", "inspections"),
    Case("submit_rework_review", "SUBMIT_REWORK_REVIEW", "review"),
    Case("create_next_rework", "CREATE_NEXT_REWORK", "next-round"),
)
START, RESULT, INSPECT, REVIEW, NEXT = CASES[1], CASES[5], CASES[6], CASES[7], CASES[8]


def snapshot(case: Case = START) -> ReworkExecutionSnapshot:
    """仅作为测试夹具显式构造已确认执行数据，不提供真实或生产确认生成器。"""

    body: dict[str, object] = {"expectedVersion": 4}
    processing: int | None = None
    inspection: str | None = None
    if case.operation == "CREATE_LIFECYCLE_REWORK":
        body.update(sourceIssueId=ISSUE, reason="  独立确认首轮🚀  ")
    elif case.operation in {"BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK", "CREATE_NEXT_REWORK"}:
        body["reason"] = "  独立确认的原样说明🚀  "
    elif case.operation == "REGISTER_REWORK_RESULT":
        processing = 1
        body.update(
            artifact={"artifactId": "成果-A", "artifactVersion": "Release-2"},
            processingComment="  原样处理说明🚀  ",
            evidenceReferences=["report:Case-A"],
        )
    elif case.operation == "REGISTER_REWORK_INSPECTION":
        processing, inspection = 1, "CHECK-T823-OLD"
        body.update(
            processingRevision=1,
            items=[
                {
                    "checkItem": "坐标系",
                    "result": "PASSED",
                    "comment": "人工检查",
                    "evidenceReferences": ["report:manual"],
                }
            ],
        )
    elif case.operation == "SUBMIT_REWORK_REVIEW":
        processing, inspection = 1, "CHECK-T823-A"
        body.update(
            processingRevision=1,
            inspectionId=inspection,
            status="APPROVED",
            reviewComment="  人工复核🚀  ",
        )
    first = case.operation == "CREATE_LIFECYCLE_REWORK"
    return ReworkExecutionSnapshot(
        approval_id=APPROVAL,
        run_id=RUN,
        owner_user_id="reviewer-test",
        confirmed_by_user_id="reviewer-test",
        confirmed_at=datetime.now(UTC) - timedelta(minutes=1),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        status=ApprovalStatus.EXECUTING,
        operation=case.operation,
        idempotency_key=KEY,
        task_id=TASK,
        task_version=4,
        source_issue_id=ISSUE,
        rework_task_id=None if first else REWORK,
        round_number=None if first else 1,
        previous_rework_task_id=None,
        processing_revision=processing,
        inspection_id=inspection,
        review_id=None,
        request=TypeAdapter(ReworkWriteRequest).validate_python(body),
    )


def receipt(case: Case = START) -> dict[str, object]:
    """固定十二字段回执夹具。只表示这次Java结果，不模拟当前GET事实。"""

    raw: dict[str, object] = {
        "operation": case.operation,
        "operationId": "OPERATION-T823-A",
        "taskId": TASK,
        "reworkTaskId": REWORK,
        "taskVersion": 5,
        "status": "RUNNING",
        "issueStatus": "PROCESSING",
        "roundNumber": 1,
        "previousReworkTaskId": None,
        "processingRevision": None,
        "inspectionId": None,
        "reviewId": None,
    }
    if case.operation in {"CREATE_LIFECYCLE_REWORK", "CREATE_NEXT_REWORK"}:
        raw.update(reworkTaskId="REWORK-T823-NEW", status="PENDING", issueStatus="OPEN")
        if case is NEXT:
            raw.update(roundNumber=2, previousReworkTaskId=REWORK)
    elif case.operation == "BLOCK_REWORK":
        raw["status"] = "BLOCKED"
    elif case.operation == "FAIL_REWORK":
        raw["status"] = "FAILED"
    elif case is RESULT:
        raw["processingRevision"] = 2
    elif case is INSPECT:
        raw.update(
            status="COMPLETED",
            issueStatus="RESOLVED",
            processingRevision=1,
            inspectionId="CHECK-T823-A",
        )
    elif case is REVIEW:
        raw.update(
            status="COMPLETED",
            issueStatus="CLOSED",
            processingRevision=1,
            inspectionId="CHECK-T823-A",
            reviewId="REVIEW-T823-A",
        )
    return raw


class FakeStore:
    """测试受信Store协议及CAS冲突，不是可部署的Approval存储。"""

    def __init__(self, value: ReworkExecutionSnapshot | None) -> None:
        self.snapshot = value
        self.reads: list[str] = []
        self.saved: list[ReworkWriteOutput] = []
        self.allow_save = True

    async def get_execution_snapshot(self, approval_id: str) -> ReworkExecutionSnapshot | None:
        self.reads.append(approval_id)
        return self.snapshot

    async def save_execution_result(
        self, expected: ReworkExecutionSnapshot, result: ReworkWriteOutput
    ) -> bool:
        if not self.allow_save or self.snapshot != expected:
            return False
        if self.saved:
            return self.saved[0].receipt == result.receipt
        self.saved.append(result)
        return True


def context(
    permission: str = "REWORK_WRITE", *, user: str = "reviewer-test", run: str = RUN
) -> ToolContext:
    """身份和权限仅来自服务端上下文。"""

    return ToolContext(
        identity=BusinessIdentity(user_id=user, role="REVIEWER"),
        permissions=frozenset({permission}),
        trace_id=TRACE,
        run_id=run,
    )


def shared(transport: httpx.MockTransport) -> BusinessHttpClient:
    """只使用MockTransport，不连接业务库或真实Java。"""

    return BusinessHttpClient(
        Settings(environment="test", business_service_url=AnyHttpUrl("http://business.test")),
        transport=transport,
    )


def response(raw: dict[str, object]) -> httpx.Response:
    """使用Java六字段信封及同一Trace。"""

    return httpx.Response(
        200,
        headers={"X-Trace-Id": TRACE},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": raw,
            "trace_id": TRACE,
            "retryable": False,
        },
    )


def recording(
    calls: list[httpx.Request], raw: dict[str, object]
) -> Callable[[httpx.Request], httpx.Response]:
    """记录HTTP副作用，避免把无返回值的append伪装成响应表达式。"""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(raw)

    return handler


INPUT = {"approval_id": APPROVAL, "idempotency_key": KEY}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_each_operation_only_posts_confirmed_request_and_saves_original_receipt(
    case: Case,
) -> None:
    store = FakeStore(snapshot(case))
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response(receipt(case))

    client = shared(httpx.MockTransport(handler))
    try:
        registry = create_rework_write_tool_registry(ReworkHttpClient(client), store)
        tool = registry.get(case.name)
        permission = "REVIEW_WRITE" if case is REVIEW else "REWORK_WRITE"
        result = await tool.execute(INPUT, context(permission))
        assert result.success and result.data is not None
        assert result.data.receipt.model_dump(mode="json", by_alias=True) == receipt(case)
        assert store.saved == [result.data] and store.reads == [APPROVAL]
        assert len(captured) == 1 and captured[0].method == "POST"
        expected = f"/api/tasks/{TASK}/reworks" + (
            f"/{REWORK}/{case.suffix}" if case.suffix else ""
        )
        assert captured[0].url.path == expected
        assert store.snapshot is not None
        assert json.loads(captured[0].content) == store.snapshot.request.model_dump(
            mode="json", by_alias=True
        )
        assert (
            captured[0].headers["X-User-Id"] == "reviewer-test"
            and captured[0].headers["X-User-Role"] == "REVIEWER"
        )
        assert (
            captured[0].headers["X-Trace-Id"] == TRACE
            and captured[0].headers["Idempotency-Key"] == KEY
        )
        assert (
            tool.risk_level is ToolRiskLevel.HIGH
            and tool.max_retries == 0
            and tool.retry_policy is None
        )
        assert tool.required_permissions == frozenset({permission})
        assert len(registry.names) == 9 and REWORK_WRITE_TOOL_NAMES == frozenset(registry.names)
        assert not REWORK_WRITE_TOOL_NAMES.intersection(WRITE_TOOL_NAMES | REWORK_READ_TOOL_NAMES)
    finally:
        await client.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_permission_denied_before_store_and_no_constructor_http(case: Case) -> None:
    store = FakeStore(snapshot(case))
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, receipt(case))))
    try:
        tool = create_rework_write_tool_registry(ReworkHttpClient(client), store).get(case.name)
        assert calls == []
        result = await tool.execute(INPUT, context("REWORK_READ"))
        assert result.error is not None and result.error.code is ToolErrorCode.PERMISSION_DENIED
        assert calls == [] and store.reads == [] and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "extra", ["task_id", "operation", "expectedVersion", "request", "confirmed", "role"]
)
async def test_caller_cannot_supply_business_or_confirmation_fields(extra: str) -> None:
    store = FakeStore(snapshot())
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, receipt())))
    try:
        tool = create_rework_write_tool_registry(ReworkHttpClient(client), store).get(START.name)
        result = await tool.execute({**INPUT, extra: "spoof"}, context())
        assert (
            result.error is not None and result.error.code is ToolErrorCode.PARAM_VALIDATION_ERROR
        )
        assert calls == [] and store.reads == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "identity",
        "owner",
        "run",
        "confirmer",
        "confirmed-at",
        "expired",
        "future",
        "operation",
        "key",
        "version",
        "request",
    ],
)
async def test_invalid_confirmation_never_posts_or_saves(kind: str) -> None:
    approved = snapshot()
    changes: dict[str, object] = {
        "identity": {"approval_id": "another-approval"},
        "owner": {"owner_user_id": "another-user"},
        "run": {"run_id": "another-run"},
        "confirmer": {"confirmed_by_user_id": None},
        "confirmed-at": {"confirmed_at": None},
        "expired": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        "future": {"confirmed_at": datetime.now(UTC) + timedelta(minutes=1)},
        "operation": None,
        "key": {"idempotency_key": "other-key"},
        "version": {"task_version": 9},
        "request": {"request": snapshot(RESULT).request},
    }
    if kind == "operation":
        approved = snapshot(CASES[2])
    elif kind != "missing":
        approved = approved.model_copy(update=cast(dict[str, object], changes[kind]))
    store = FakeStore(None if kind == "missing" else approved)
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, receipt())))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert not result.success and result.error is not None and not result.error.retryable
        expected = {
            "missing": ToolErrorCode.RESOURCE_NOT_FOUND,
            "identity": ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            "owner": ToolErrorCode.PERMISSION_DENIED,
            "run": ToolErrorCode.PERMISSION_DENIED,
            "confirmer": ToolErrorCode.PERMISSION_DENIED,
            "version": ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            "request": ToolErrorCode.RESPONSE_VALIDATION_ERROR,
        }.get(kind, ToolErrorCode.BUSINESS_CONFLICT)
        assert result.error.code is expected
        assert calls == [] and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status", [status for status in ApprovalStatus if status is not ApprovalStatus.EXECUTING]
)
async def test_only_executing_claim_is_accepted(status: ApprovalStatus) -> None:
    store = FakeStore(snapshot().model_copy(update={"status": status}))
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, receipt())))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert result.error is not None and result.error.code is ToolErrorCode.BUSINESS_CONFLICT
        assert calls == [] and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "case,field,value",
    [
        (START, "roundNumber", 2),
        (START, "previousReworkTaskId", "REWORK-OTHER"),
        (START, "processingRevision", 1),
        (RESULT, "processingRevision", 3),
        (INSPECT, "inspectionId", "CHECK-T823-OLD"),
        (NEXT, "roundNumber", 3),
        (REVIEW, "inspectionId", "CHECK-OTHER"),
        (REVIEW, "taskVersion", 6),
        (START, "taskId", "TASK-OTHER"),
        (START, "reworkTaskId", "REWORK-OTHER"),
        (START, "operation", "RESUME_REWORK"),
    ],
)
async def test_receipt_must_match_confirmed_material_round_and_java_operation(
    case: Case, field: str, value: object
) -> None:
    raw = receipt(case)
    raw[field] = value
    store = FakeStore(snapshot(case))
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, raw)))
    try:
        tool = create_rework_write_tool_registry(ReworkHttpClient(client), store).get(case.name)
        result = await tool.execute(
            INPUT, context("REVIEW_WRITE" if case is REVIEW else "REWORK_WRITE")
        )
        assert (
            result.error is not None
            and result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
        )
        assert not result.error.retryable and len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "code,http_status,retryable",
    [
        ("PARAM_VALIDATION_ERROR", 400, False),
        ("PERMISSION_DENIED", 403, False),
        ("RESOURCE_NOT_FOUND", 404, False),
        ("BUSINESS_CONFLICT", 409, False),
        ("INTERNAL_SERVER_ERROR", 500, False),
    ],
)
async def test_java_errors_are_not_retried_or_saved(
    code: str, http_status: int, retryable: bool
) -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        return httpx.Response(
            http_status,
            headers={"X-Trace-Id": TRACE},
            json={
                "success": False,
                "code": code,
                "message": "拒绝本次请求",
                "data": None,
                "trace_id": TRACE,
                "retryable": retryable,
            },
        )

    client = shared(httpx.MockTransport(handler))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert not result.success and result.error is not None and not result.error.retryable
        assert len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("outer", [True, False])
async def test_client_and_outer_timeouts_never_automatically_repeat_a_write(outer: bool) -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())

    async def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        if not outer:
            raise httpx.ReadTimeout("synthetic timeout", request=r)
        await asyncio.sleep(1)
        return response(receipt())

    client = shared(httpx.MockTransport(handler))
    try:
        tool = create_rework_write_tool_registry(
            ReworkHttpClient(client), store, timeout=0.01 if outer else 1
        ).get(START.name)
        result = await tool.execute(INPUT, context())
        assert result.error is not None and not result.error.retryable and len(calls) == 1
        assert (
            store.saved == []
            and store.snapshot is not None
            and store.snapshot.status is ApprovalStatus.EXECUTING
        )
    finally:
        await client.aclose()


async def test_store_conflict_after_java_success_does_not_retry_or_claim_failure() -> None:
    store = FakeStore(snapshot())
    store.allow_save = False
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, receipt())))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert (
            result.error is not None
            and result.error.code is ToolErrorCode.BUSINESS_CONFLICT
            and not result.error.retryable
        )
        assert (
            len(calls) == 1
            and store.saved == []
            and store.snapshot is not None
            and store.snapshot.status is ApprovalStatus.EXECUTING
        )
    finally:
        await client.aclose()


async def test_materials_are_copied_before_http_and_save_cas_catches_changed_confirmation() -> None:
    store = FakeStore(snapshot(RESULT))
    captured: list[dict[str, object]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        captured.append(json.loads(r.content))
        assert store.snapshot is not None
        assert isinstance(store.snapshot.request, RegisterReworkResultRequest)
        store.snapshot.request.evidence_references.append("report:unconfirmed")
        return response(receipt(RESULT))

    client = shared(httpx.MockTransport(handler))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(RESULT.name)
            .execute(INPUT, context())
        )
        assert result.error is not None and result.error.code is ToolErrorCode.BUSINESS_CONFLICT
        assert captured[0]["evidenceReferences"] == ["report:Case-A"] and store.saved == []
    finally:
        await client.aclose()


async def test_refresh_keeps_original_key_and_receipt_while_default_duplicate_is_blocked() -> None:
    store = FakeStore(snapshot())
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, receipt())))
    try:
        tool = create_rework_write_tool_registry(ReworkHttpClient(client), store).get(START.name)
        ctx = context()
        first = await tool.execute(INPUT, ctx)
        duplicate = await tool.execute(INPUT, ctx)
        replay = await tool.execute(INPUT, ctx, force_refresh=True)
        assert first.success and replay.data == first.data
        assert duplicate.error is not None and duplicate.error.code is ToolErrorCode.DUPLICATE_CALL
        assert len(calls) == 2 and len(store.saved) == 1
        assert all(r.headers["Idempotency-Key"] == KEY for r in calls)
    finally:
        await client.aclose()


async def test_cancellation_propagates_without_saving_or_resubmitting() -> None:
    entered = asyncio.Event()
    store = FakeStore(snapshot())
    calls: list[httpx.Request] = []

    async def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        entered.set()
        await asyncio.Event().wait()
        return response(receipt())

    client = shared(httpx.MockTransport(handler))
    try:
        tool = create_rework_write_tool_registry(ReworkHttpClient(client), store).get(START.name)
        task = asyncio.create_task(tool.execute(INPUT, context()))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("kind", ["inspection-failed", "review-rejected", "review-rework"])
async def test_manual_failure_or_rejection_is_returned_as_java_fact_without_inventing_success(
    kind: str,
) -> None:
    case = INSPECT if kind == "inspection-failed" else REVIEW
    value = snapshot(case)
    raw_request = value.request.model_dump(mode="python")
    raw_receipt = receipt(case)
    if kind == "inspection-failed":
        raw_request["items"] = [
            {
                "checkItem": "坐标系",
                "result": "FAILED",
                "comment": "实际未通过",
                "evidenceReferences": ["report:failed"],
            }
        ]
        raw_receipt.update(status="RUNNING", issueStatus="PROCESSING")
    else:
        raw_request["status"] = "REJECTED" if kind == "review-rejected" else "REWORK_REQUIRED"
        raw_receipt["issueStatus"] = "OPEN"
    value = value.model_copy(
        update={"request": TypeAdapter(ReworkWriteRequest).validate_python(raw_request)}
    )
    store = FakeStore(value)
    calls: list[httpx.Request] = []
    client = shared(httpx.MockTransport(recording(calls, raw_receipt)))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(case.name)
            .execute(INPUT, context("REWORK_WRITE" if case is INSPECT else "REVIEW_WRITE"))
        )
        assert result.success and result.data is not None
        assert result.data.receipt.model_dump(mode="json", by_alias=True) == raw_receipt
        assert len(calls) == 1 and store.saved == [result.data]
    finally:
        await client.aclose()


async def test_existing_later_round_keeps_its_confirmed_predecessor() -> None:
    value = snapshot().model_copy(
        update={"round_number": 2, "previous_rework_task_id": "REWORK-T823-PREV"}
    )
    store = FakeStore(value)
    raw = receipt()
    raw.update(roundNumber=2, previousReworkTaskId="REWORK-T823-PREV")
    client = shared(httpx.MockTransport(lambda _: response(raw)))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert result.success and result.data is not None and result.data.receipt.round_number == 2
        assert result.data.receipt.previous_rework_task_id == "REWORK-T823-PREV"
    finally:
        await client.aclose()


async def test_trace_mismatch_is_not_saved_or_retried() -> None:
    calls: list[httpx.Request] = []
    store = FakeStore(snapshot())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            headers={"X-Trace-Id": "trace-other"},
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "ok",
                "data": receipt(),
                "trace_id": "trace-other",
                "retryable": False,
            },
        )

    client = shared(httpx.MockTransport(handler))
    try:
        result = (
            await create_rework_write_tool_registry(ReworkHttpClient(client), store)
            .get(START.name)
            .execute(INPUT, context())
        )
        assert (
            result.error is not None
            and result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
        )
        assert len(calls) == 1 and store.saved == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_version", 5),
        ("round_number", 2),
        ("processing_revision", 1),
        ("source_issue_id", "ISSUE-OTHER"),
    ],
)
async def test_schema_refuses_inconsistent_confirmed_bindings(field: str, value: object) -> None:
    raw = snapshot(CASES[0]).model_dump(mode="python")
    raw[field] = value
    with pytest.raises(ValidationError):
        ReworkExecutionSnapshot.model_validate(raw)
    with pytest.raises(ValidationError):
        ReworkWriteInput.model_validate({**INPUT, "expected_version": 4})
