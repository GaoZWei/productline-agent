"""T821离线契约用例，MockTransport不代替真实Java、数据库或Approval验收。"""

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import AnyHttpUrl, ValidationError

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity, BusinessResponse
from app.schemas.rework import (
    MAX_SAFE_INTEGER,
    CreateLifecycleReworkRequest,
    EffectiveReworkReviews,
    RegisterReworkInspectionRequest,
    RegisterReworkResultRequest,
    ReworkDetail,
    ReworkHistoryPage,
    ReworkInspection,
    ReworkPageQuery,
    ReworkProcessing,
    ReworkReasonRequest,
    ReworkReview,
    ReworkVersionRequest,
    ReworkWriteReceipt,
    SubmitReworkReviewRequest,
)
from app.schemas.rework_delivery import DeliveryConditions
from app.schemas.write_tools import ReworkWriteResponseData
from app.settings import Settings

pytestmark = pytest.mark.unit
TRACE = "trace-m8-001"
TASK = "TASK-M8-A"
REWORK = "REWORK-M8-A"
IDENTITY = BusinessIdentity(user_id="reviewer-test", role="REVIEWER")


def task_data(status: str = "PENDING") -> dict[str, object]:
    """构造原ReworkTaskDto全部字段。"""

    return {
        "reworkTaskId": REWORK,
        "taskId": TASK,
        "sourceIssueId": "ISSUE-M8-A",
        "status": status,
        "reason": "  原始创建原因🚀  ",
    }


def processing(revision: int = 1) -> dict[str, object]:
    """保留处理说明、成果版本和引用的原始文本。"""

    return {
        "processingRevision": revision,
        "artifact": {"artifactId": "成果-A", "artifactVersion": "release-A"},
        "processingComment": "  人工修正说明🚀  ",
        "evidenceReferences": ["report:Case-A"],
        "registeredBy": "handler-test",
        "registeredAt": "2026-11-11T00:01:00.123456789Z",
    }


def item(result: str = "PASSED") -> dict[str, object]:
    """构造四字段人工检查项。"""

    return {
        "checkItem": "  坐标系  ",
        "result": result,
        "comment": "  检查说明  ",
        "evidenceReferences": ["report:check-A"],
    }


def inspection(sequence: int = 1, result: str = "PASSED") -> dict[str, object]:
    """构造八字段当前检查。"""

    return {
        "inspectionId": "CHECK-M8-A" if sequence == 1 else f"CHECK-M8-{sequence}",
        "inspectionSequence": sequence,
        "roundNumber": 1,
        "processingRevision": 1,
        "inspectorId": "inspector-test",
        "inspectedAt": "2026-11-11T00:02:00Z",
        "result": result,
        "items": [item(result)],
    }


def review(sequence: int = 1, status: str = "APPROVED") -> dict[str, object]:
    """构造九字段受控最终复核。"""

    return {
        "reviewId": "REVIEW-M8-A" if sequence == 1 else f"REVIEW-M8-{sequence}",
        "reviewSequence": sequence,
        "roundNumber": 1,
        "processingRevision": 1,
        "inspectionId": "CHECK-M8-A",
        "status": status,
        "reviewComment": "  复核说明🚀  ",
        "reviewedBy": "reviewer-test",
        "reviewedAt": "2026-11-11T00:03:00Z",
    }


def detail() -> dict[str, object]:
    """构造尚未开始的受控首轮详情，缺材料保持显式null。"""

    return {
        "reworkTask": task_data(),
        "issueStatus": "OPEN",
        "roundNumber": 1,
        "previousReworkTaskId": None,
        "allowedActions": ["START_REWORK"],
        "taskVersion": 4,
        "processing": None,
        "inspection": None,
        "review": None,
    }


def effective() -> dict[str, object]:
    """构造无材料的新轮当前绑定。"""

    return {
        "taskId": TASK,
        "taskVersion": 4,
        "issues": [
            {
                "issueId": "ISSUE-M8-A",
                "reworkTaskId": REWORK,
                "roundNumber": 1,
                "processingRevision": None,
                "inspectionId": None,
                "review": None,
                "legacyReviews": [],
            }
        ],
    }


def delivery() -> dict[str, object]:
    """构造T820已知条件均满足但订单仍保持原状态的响应。"""

    return {
        "order": {"orderId": "ORDER-M8-A", "productType": "DOM", "status": "QUALITY_CHECKING"},
        "tasks": [
            {
                "taskId": TASK,
                "taskVersion": 4,
                "productionStatus": "COMPLETED",
                "steps": [
                    {
                        "stepId": "STEP-M8-A",
                        "taskId": TASK,
                        "stepName": "生产处理",
                        "sequenceNumber": 1,
                        "status": "COMPLETED",
                    }
                ],
                "issues": [],
                "activeReworks": [],
            }
        ],
        "deliveryRecords": [
            {"deliveryId": "DELIVERY-M8-A", "orderId": "ORDER-M8-A", "status": "READY"}
        ],
        "blockers": [],
        "hasBlockers": False,
    }


def receipt(operation: str) -> dict[str, object]:
    """构造固定十二字段原成功回执。"""

    raw: dict[str, object] = {
        "operation": operation,
        "operationId": "OPERATION-M8-A",
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
    if operation in ("CREATE_LIFECYCLE_REWORK", "CREATE_NEXT_REWORK"):
        raw.update(reworkTaskId="REWORK-M8-NEW", status="PENDING", issueStatus="OPEN")
        if operation == "CREATE_NEXT_REWORK":
            raw.update(roundNumber=2, previousReworkTaskId=REWORK)
    elif operation == "BLOCK_REWORK":
        raw["status"] = "BLOCKED"
    elif operation == "FAIL_REWORK":
        raw["status"] = "FAILED"
    elif operation == "REGISTER_REWORK_RESULT":
        raw["processingRevision"] = 2
    elif operation == "REGISTER_REWORK_INSPECTION":
        raw.update(
            status="COMPLETED",
            issueStatus="RESOLVED",
            processingRevision=1,
            inspectionId="CHECK-M8-A",
        )
    elif operation == "SUBMIT_REWORK_REVIEW":
        raw.update(
            status="COMPLETED",
            issueStatus="CLOSED",
            processingRevision=1,
            inspectionId="CHECK-M8-A",
            reviewId="REVIEW-M8-A",
        )
    return raw


def success(data: object, trace: str = TRACE) -> httpx.Response:
    """构造与Java公共层一致的六字段成功信封。"""

    return httpx.Response(
        200,
        headers={"X-Trace-Id": trace},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "success",
            "data": data,
            "trace_id": trace,
            "retryable": False,
        },
    )


def clients(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[BusinessHttpClient, ReworkHttpClient]:
    """使用显式MockTransport，借用外层连接池而不修改应用装配。"""

    shared = BusinessHttpClient(
        Settings(environment="test", business_service_url=AnyHttpUrl("http://business.test")),
        transport=httpx.MockTransport(handler),
    )
    return shared, ReworkHttpClient(shared)


def result_request() -> RegisterReworkResultRequest:
    """成果请求只含冻结的四字段。"""

    return RegisterReworkResultRequest.model_validate(
        {
            "expectedVersion": 4,
            "artifact": {"artifactId": "成果-A", "artifactVersion": "release-A"},
            "processingComment": "  人工修正说明🚀  ",
            "evidenceReferences": ["report:Case-A"],
        }
    )


async def write(
    client: ReworkHttpClient, operation: str, key: str = "m8-write"
) -> BusinessResponse[ReworkWriteReceipt]:
    """显式调用各公开方法，验证它们映射到不同Java动作而非旧端点。"""

    # 公共参数显式传递，避免宽泛kwargs绕过各方法的静态类型契约。
    if operation == "CREATE_LIFECYCLE_REWORK":
        return await client.create_first(
            TASK,
            CreateLifecycleReworkRequest.model_validate(
                {"sourceIssueId": "ISSUE-M8-A", "expectedVersion": 4, "reason": "  本次原因🚀  "}
            ),
            identity=IDENTITY,
            idempotency_key=key,
            trace_id=TRACE,
        )
    if operation == "START_REWORK":
        return await client.start(
            TASK,
            REWORK,
            ReworkVersionRequest(expected_version=4),
            identity=IDENTITY,
            idempotency_key=key,
            trace_id=TRACE,
        )
    reason = ReworkReasonRequest(expected_version=4, reason="  本次原因🚀  ")
    if operation == "BLOCK_REWORK":
        return await client.block(
            TASK, REWORK, reason, identity=IDENTITY, idempotency_key=key, trace_id=TRACE
        )
    if operation == "FAIL_REWORK":
        return await client.fail(
            TASK, REWORK, reason, identity=IDENTITY, idempotency_key=key, trace_id=TRACE
        )
    if operation == "RESUME_REWORK":
        return await client.resume(
            TASK, REWORK, reason, identity=IDENTITY, idempotency_key=key, trace_id=TRACE
        )
    if operation == "REGISTER_REWORK_RESULT":
        return await client.register_result(
            TASK, REWORK, result_request(), identity=IDENTITY, idempotency_key=key, trace_id=TRACE
        )
    if operation == "REGISTER_REWORK_INSPECTION":
        request = RegisterReworkInspectionRequest.model_validate(
            {"expectedVersion": 4, "processingRevision": 1, "items": [item()]}
        )
        return await client.register_inspection(
            TASK, REWORK, request, identity=IDENTITY, idempotency_key=key, trace_id=TRACE
        )
    if operation == "SUBMIT_REWORK_REVIEW":
        review_request = SubmitReworkReviewRequest.model_validate(
            {
                "expectedVersion": 4,
                "processingRevision": 1,
                "inspectionId": "CHECK-M8-A",
                "status": "APPROVED",
                "reviewComment": "  复核说明🚀  ",
            }
        )
        return await client.submit_review(
            TASK, REWORK, review_request, identity=IDENTITY, idempotency_key=key, trace_id=TRACE
        )
    assert operation == "CREATE_NEXT_REWORK"
    return await client.create_next(
        TASK, REWORK, reason, identity=IDENTITY, idempotency_key=key, trace_id=TRACE
    )


@pytest.mark.parametrize("version", [True, "4", 4.0, -1, MAX_SAFE_INTEGER + 1, None])
def test_versions_are_strict_safe_json_integers(version: object) -> None:
    with pytest.raises(ValidationError):
        ReworkVersionRequest.model_validate({"expectedVersion": version})
    assert (
        ReworkVersionRequest(expected_version=MAX_SAFE_INTEGER).expected_version == MAX_SAFE_INTEGER
    )


@pytest.mark.parametrize(
    "extra", ["confirmed", "approval_id", "role", "roundNumber", "registeredBy"]
)
def test_requests_reject_self_reported_confirmation_and_server_facts(extra: str) -> None:
    with pytest.raises(ValidationError):
        ReworkReasonRequest.model_validate(
            {"expectedVersion": 4, "reason": "本次原因", extra: True}
        )


@pytest.mark.parametrize("text", ["", " \t\u3000", "\0", "\ud800", "🚀" * 501])
def test_comment_validation_rejects_blank_unsafe_or_overlong_utf16(text: str) -> None:
    with pytest.raises(ValidationError):
        ReworkReasonRequest(expected_version=4, reason=text)


def test_original_whitespace_case_non_bmp_and_java_blank_semantics_are_preserved() -> None:
    request = result_request()
    assert request.model_dump(by_alias=True)["processingComment"] == "  人工修正说明🚀  "
    assert request.evidence_references == ["report:Case-A"]
    assert ReworkReasonRequest(expected_version=4, reason="🚀" * 500).reason == "🚀" * 500
    assert ReworkReasonRequest(expected_version=4, reason="\u00a0").reason == "\u00a0"
    assert (
        ReworkProcessing.model_validate(processing()).registered_at
        == "2026-11-11T00:01:00.123456789Z"
    )
    raw = request.model_dump(by_alias=True)
    raw["evidenceReferences"] = [" report:Case-A"]
    with pytest.raises(ValidationError):
        RegisterReworkResultRequest.model_validate(raw)


def test_inspection_and_review_require_real_complete_materials() -> None:
    changes: tuple[dict[str, object], ...] = (
        {"items": []},
        {"items": [item("UNKNOWN")]},
        {"processingRevision": 0},
    )
    for changed in changes:
        raw: dict[str, object] = {"expectedVersion": 4, "processingRevision": 1, "items": [item()]}
        raw.update(changed)
        with pytest.raises(ValidationError):
            RegisterReworkInspectionRequest.model_validate(raw)
    raw_inspection = inspection()
    raw_inspection["result"] = "FAILED"
    with pytest.raises(ValidationError):
        ReworkInspection.model_validate(raw_inspection)
    raw_review = review()
    raw_review["status"] = "PENDING"
    with pytest.raises(ValidationError):
        ReworkReview.model_validate(raw_review)


def test_legacy_detail_and_nullable_history_are_not_fabricated() -> None:
    raw = detail()
    raw.update(roundNumber=None, allowedActions=[])
    old = ReworkDetail.model_validate(raw)
    assert old.round_number is None and old.processing is None
    page = ReworkHistoryPage[ReworkProcessing].model_validate(
        {"taskId": TASK, "reworkTaskId": REWORK, "records": [], "nextCursor": None}
    )
    assert page.records == [] and page.next_cursor is None
    with pytest.raises(ValidationError):
        ReworkHistoryPage[ReworkProcessing].model_validate(
            {"taskId": TASK, "reworkTaskId": REWORK, "records": []}
        )
    raw["processing"] = processing()
    with pytest.raises(ValidationError):
        ReworkDetail.model_validate(raw)


def test_detail_rejects_cross_revision_review_and_unbound_inspection() -> None:
    raw = detail()
    raw.update(processing=processing(), inspection=inspection(), review=review())
    assert ReworkDetail.model_validate(raw).review is not None
    wrong = review()
    wrong["inspectionId"] = "CHECK-OTHER"
    raw["review"] = wrong
    with pytest.raises(ValidationError):
        ReworkDetail.model_validate(raw)
    raw.update(processing=None, review=None)
    with pytest.raises(ValidationError):
        ReworkDetail.model_validate(raw)


def test_effective_reviews_keep_legacy_pending_and_null_comment_separate() -> None:
    old: dict[str, object] = {
        "issueId": "ISSUE-M8-A",
        "reworkTaskId": None,
        "roundNumber": None,
        "processingRevision": None,
        "inspectionId": None,
        "review": None,
        "legacyReviews": [
            {
                "reviewId": "REVIEW-OLD",
                "issueId": "ISSUE-M8-A",
                "status": "PENDING",
                "reviewComment": None,
            }
        ],
    }
    raw = effective()
    raw["issues"] = [old]
    assert (
        EffectiveReworkReviews.model_validate(raw).issues[0].legacy_reviews[0].review_comment
        is None
    )
    old["roundNumber"] = 1
    with pytest.raises(ValidationError):
        EffectiveReworkReviews.model_validate(raw)
    old["roundNumber"] = None
    old["inspectionId"] = "CHECK-UNBOUND"
    with pytest.raises(ValidationError):
        EffectiveReworkReviews.model_validate(raw)


def test_new_receipt_does_not_relax_old_pending_only_creation_response() -> None:
    assert ReworkWriteReceipt.model_validate(receipt("START_REWORK")).status == "RUNNING"
    with pytest.raises(ValidationError):
        ReworkWriteResponseData.model_validate(
            {"reworkTask": task_data("RUNNING"), "taskVersion": 5}
        )


def test_delivery_flags_and_nested_resource_ownership_are_checked() -> None:
    raw = delivery()
    assert DeliveryConditions.model_validate(raw).has_blockers is False
    raw["hasBlockers"] = True
    with pytest.raises(ValidationError):
        DeliveryConditions.model_validate(raw)
    raw = delivery()
    raw["deliveryRecords"] = [
        {"deliveryId": "DELIVERY-M8-A", "orderId": "ORDER-OTHER", "status": "READY"}
    ]
    with pytest.raises(ValidationError):
        DeliveryConditions.model_validate(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,suffix",
    [
        ("CREATE_LIFECYCLE_REWORK", ""),
        ("START_REWORK", "/start"),
        ("BLOCK_REWORK", "/block"),
        ("FAIL_REWORK", "/fail"),
        ("RESUME_REWORK", "/resume"),
        ("REGISTER_REWORK_RESULT", "/results"),
        ("REGISTER_REWORK_INSPECTION", "/inspections"),
        ("SUBMIT_REWORK_REVIEW", "/review"),
        ("CREATE_NEXT_REWORK", "/next-round"),
    ],
)
async def test_all_write_routes_send_only_explicit_java_contract(
    operation: str, suffix: str
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """记录实际HTTP请求并提供该动作的固定原成功回执。"""
        captured.append(request)
        return success(receipt(operation))

    shared, client = clients(handler)
    try:
        response = await write(client, operation)
        assert response.data.operation == operation
        assert shared.is_closed is False
    finally:
        await shared.aclose()
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == f"/api/tasks/{TASK}/reworks" + (
        f"/{REWORK}{suffix}" if suffix else ""
    )
    assert (
        request.headers["X-User-Id"] == IDENTITY.user_id
        and request.headers["X-User-Role"] == "REVIEWER"
    )
    assert (
        request.headers["X-Trace-Id"] == TRACE and request.headers["Idempotency-Key"] == "m8-write"
    )
    body = json.loads(request.content)
    assert body["expectedVersion"] == 4
    assert not {"confirmed", "approval_id", "operation", "taskId", "roundNumber"}.intersection(body)
    if "reason" in body:
        assert body["reason"] == "  本次原因🚀  "
    if operation == "REGISTER_REWORK_RESULT":
        assert body["processingComment"] == "  人工修正说明🚀  "


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["detail", "results", "inspections", "reviews", "effective", "delivery"]
)
async def test_read_routes_bind_parent_and_keep_empty_pages_without_automatic_paging(
    kind: str,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """根据场景返回单个真实传输结构。"""
        captured.append(request)
        data: object = (
            detail()
            if kind == "detail"
            else effective()
            if kind == "effective"
            else delivery()
            if kind == "delivery"
            else {"taskId": TASK, "reworkTaskId": REWORK, "records": [], "nextCursor": None}
        )
        return success(data)

    shared, client = clients(handler)
    try:
        if kind == "detail":
            await client.get_detail(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
        elif kind == "effective":
            await client.get_effective_reviews(TASK, identity=IDENTITY, trace_id=TRACE)
        elif kind == "delivery":
            await client.get_delivery_conditions("ORDER-M8-A", identity=IDENTITY, trace_id=TRACE)
        elif kind == "results":
            await client.get_results(
                TASK,
                REWORK,
                identity=IDENTITY,
                page=ReworkPageQuery(limit=1, cursor="opaque:Cursor-A"),
                trace_id=TRACE,
            )
        elif kind == "inspections":
            await client.get_inspections(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
        else:
            await client.get_reviews(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
    finally:
        await shared.aclose()
    assert len(captured) == 1 and captured[0].method == "GET"
    assert "Idempotency-Key" not in captured[0].headers
    expected = f"/api/tasks/{TASK}/reworks/{REWORK}"
    assert captured[0].url.path == (
        expected
        if kind == "detail"
        else f"/api/tasks/{TASK}/effective-reviews"
        if kind == "effective"
        else "/api/orders/ORDER-M8-A/delivery-conditions"
        if kind == "delivery"
        else f"{expected}/{kind}"
    )
    if kind == "results":
        assert dict(captured[0].url.params) == {"limit": "1", "cursor": "opaque:Cursor-A"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("taskId", "TASK-OTHER"),
        ("reworkTaskId", "REWORK-OTHER"),
        ("operation", "BLOCK_REWORK"),
        ("taskVersion", 6),
        ("status", "COMPLETED"),
        ("issueStatus", "CLOSED"),
    ],
)
async def test_structurally_valid_but_wrong_write_receipt_is_rejected(
    field: str, value: object
) -> None:
    raw = receipt("START_REWORK")
    raw[field] = value
    shared, client = clients(lambda _: success(raw))
    try:
        with pytest.raises(ToolException) as caught:
            await write(client, "START_REWORK")
        assert (
            caught.value.code == ToolErrorCode.RESPONSE_VALIDATION_ERROR
            and not caught.value.retryable
        )
    finally:
        await shared.aclose()


@pytest.mark.asyncio
async def test_unrelated_successful_trace_is_rejected_even_when_header_and_envelope_match() -> None:
    shared, client = clients(lambda _: success(detail(), trace="trace-unrelated"))
    try:
        with pytest.raises(ToolException) as caught:
            await client.get_detail(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
        assert caught.value.code == ToolErrorCode.RESPONSE_VALIDATION_ERROR
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_id",
    ["task-lower", "TASK-A/../../admin", "http://other.test", "TASK-A\n", "TASK-" + "A" * 60],
)
async def test_invalid_paths_never_reach_the_shared_http_client(bad_id: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """任何调用都表示输入门禁失效。"""
        nonlocal calls
        calls += 1
        return success(detail())

    shared, client = clients(handler)
    try:
        with pytest.raises(ToolException) as caught:
            await client.get_detail(bad_id, REWORK, identity=IDENTITY, trace_id=TRACE)
        assert caught.value.code == ToolErrorCode.PARAM_VALIDATION_ERROR and calls == 0
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", "contains spaces", "key\n", "x" * 129])
async def test_invalid_write_keys_never_reach_java(key: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """只有通过参数门禁后才会调用。"""
        nonlocal calls
        calls += 1
        return success(receipt("START_REWORK"))

    shared, client = clients(handler)
    try:
        with pytest.raises(ToolException) as caught:
            await write(client, "START_REWORK", key)
        assert caught.value.code == ToolErrorCode.PARAM_VALIDATION_ERROR and calls == 0
    finally:
        await shared.aclose()


@pytest.mark.asyncio
async def test_mutated_nested_request_is_revalidated_before_any_write() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """不可信列表不能通过已构造模型绕过再次校验。"""
        nonlocal calls
        calls += 1
        return success(receipt("REGISTER_REWORK_RESULT"))

    request = result_request()
    request.evidence_references.append("  ")
    shared, client = clients(handler)
    try:
        with pytest.raises(ToolException) as caught:
            await client.register_result(
                TASK,
                REWORK,
                request,
                identity=IDENTITY,
                idempotency_key="mutated-request",
                trace_id=TRACE,
            )
        assert caught.value.code == ToolErrorCode.PARAM_VALIDATION_ERROR and calls == 0
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["duplicate", "reverse", "too-many", "same-cursor", "wrong-parent"]
)
async def test_history_rejects_invalid_order_page_size_cursor_and_parent(kind: str) -> None:
    raw: dict[str, object] = {
        "taskId": TASK,
        "reworkTaskId": REWORK,
        "records": [processing(1), processing(2)],
        "nextCursor": None,
    }
    if kind == "duplicate":
        raw["records"] = [processing(1), processing(1)]
    elif kind == "reverse":
        raw["records"] = [processing(2), processing(1)]
    elif kind == "same-cursor":
        raw["nextCursor"] = "cursor-A"
    elif kind == "wrong-parent":
        raw["reworkTaskId"] = "REWORK-OTHER"
    shared, client = clients(lambda _: success(raw))
    try:
        with pytest.raises(ToolException) as caught:
            await client.get_results(
                TASK,
                REWORK,
                identity=IDENTITY,
                page=ReworkPageQuery(limit=1 if kind == "too-many" else 2, cursor="cursor-A"),
                trace_id=TRACE,
            )
        assert caught.value.code == ToolErrorCode.RESPONSE_VALIDATION_ERROR
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("write_call", [False, True])
@pytest.mark.parametrize("failure", ["timeout", "network", "invalid-schema", "server"])
async def test_one_request_only_and_write_failures_are_never_auto_retryable(
    write_call: bool, failure: str
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """显式制造传输、信封或Java失败，不访问外部服务。"""
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("forced", request=request)
        if failure == "network":
            raise httpx.ConnectError("forced", request=request)
        if failure == "invalid-schema":
            return success({"rawSensitiveEvidence": "must not leak"})
        return httpx.Response(
            500,
            headers={"X-Trace-Id": TRACE},
            json={
                "success": False,
                "code": "INTERNAL_SERVER_ERROR",
                "message": "safe failure",
                "data": None,
                "trace_id": TRACE,
                "retryable": False,
            },
        )

    shared, client = clients(handler)
    try:
        with pytest.raises(ToolException) as caught:
            if write_call:
                await write(client, "START_REWORK")
            else:
                await client.get_detail(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
        assert calls == 1 and "rawSensitiveEvidence" not in str(caught.value)
        assert (
            caught.value.code
            == {
                "timeout": ToolErrorCode.TOOL_TIMEOUT,
                "network": ToolErrorCode.UPSTREAM_UNAVAILABLE,
                "invalid-schema": ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "server": ToolErrorCode.UPSTREAM_UNAVAILABLE,
            }[failure]
        )
        if write_call:
            assert caught.value.retryable is False
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["results", "inspections", "reviews"])
async def test_populated_history_preserves_original_sequences_and_next_cursor(kind: str) -> None:
    raw: dict[str, object] = {"taskId": TASK, "reworkTaskId": REWORK, "nextCursor": "opaque:Next-A"}
    raw["records"] = {
        "results": [processing(2), processing(5)],
        "inspections": [inspection(2, "FAILED"), inspection(5)],
        "reviews": [review(2, "REWORK_REQUIRED"), review(5)],
    }[kind]
    shared, client = clients(lambda _: success(raw))
    try:
        if kind == "results":
            response = await client.get_results(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
            assert [row.processing_revision for row in response.data.records] == [2, 5]
            assert response.data.records[0].processing_comment == "  人工修正说明🚀  "
            assert response.data.next_cursor == "opaque:Next-A"
        elif kind == "inspections":
            checked = await client.get_inspections(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
            assert [row.inspection_sequence for row in checked.data.records] == [2, 5]
            assert [row.result for row in checked.data.records] == ["FAILED", "PASSED"]
            assert checked.data.next_cursor == "opaque:Next-A"
        else:
            reviewed = await client.get_reviews(TASK, REWORK, identity=IDENTITY, trace_id=TRACE)
            assert [row.review_sequence for row in reviewed.data.records] == [2, 5]
            assert [row.status for row in reviewed.data.records] == ["REWORK_REQUIRED", "APPROVED"]
            assert reviewed.data.next_cursor == "opaque:Next-A"
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (400, "PARAM_VALIDATION_ERROR"),
        (401, "PERMISSION_DENIED"),
        (403, "PERMISSION_DENIED"),
        (404, "RESOURCE_NOT_FOUND"),
        (409, "BUSINESS_CONFLICT"),
    ],
)
async def test_java_rejections_keep_existing_error_classification(status: int, code: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """业务拒绝保持机器码和非重试语义。"""
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

    shared, client = clients(handler)
    try:
        with pytest.raises(ToolException) as caught:
            await write(client, "START_REWORK")
        assert caught.value.code.value == code and caught.value.status_code == status
        assert caught.value.retryable is False and calls == 1
    finally:
        await shared.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["failed-inspection", "rejected-review", "required-review"])
async def test_nonpassing_inspection_and_returned_review_validate_their_actual_side_effects(
    kind: str,
) -> None:
    operation = (
        "REGISTER_REWORK_INSPECTION" if kind == "failed-inspection" else "SUBMIT_REWORK_REVIEW"
    )
    raw = receipt(operation)
    if kind == "failed-inspection":
        raw.update(status="RUNNING", issueStatus="PROCESSING")
    else:
        raw["issueStatus"] = "OPEN"
    shared, client = clients(lambda _: success(raw))
    try:
        if kind == "failed-inspection":
            request = RegisterReworkInspectionRequest.model_validate(
                {"expectedVersion": 4, "processingRevision": 1, "items": [item("FAILED")]}
            )
            checked = await client.register_inspection(
                TASK,
                REWORK,
                request,
                identity=IDENTITY,
                idempotency_key="failed-check",
                trace_id=TRACE,
            )
            assert checked.data.status == "RUNNING" and checked.data.issue_status == "PROCESSING"
        else:
            review_request = SubmitReworkReviewRequest.model_validate(
                {
                    "expectedVersion": 4,
                    "processingRevision": 1,
                    "inspectionId": "CHECK-M8-A",
                    "status": "REJECTED" if kind == "rejected-review" else "REWORK_REQUIRED",
                    "reviewComment": "退回意见",
                }
            )
            returned = await client.submit_review(
                TASK,
                REWORK,
                review_request,
                identity=IDENTITY,
                idempotency_key="return-review",
                trace_id=TRACE,
            )
            assert returned.data.status == "COMPLETED" and returned.data.issue_status == "OPEN"
    finally:
        await shared.aclose()
