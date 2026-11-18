"""T827确定性草稿取证，实际只读Tool/Client经MockTransport，不代表真实Java或确认验收。"""

import asyncio
from collections.abc import Callable
from copy import deepcopy

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity
from app.schemas.tools import TaskDetail, TaskIdInput
from app.settings import Settings
from app.tools.base import BaseTool, ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.readonly import create_read_tool_registry
from app.tools.registry import ToolRegistry
from app.tools.rework_readonly import create_rework_read_tool_registry
from app.workflows.rework_draft import ReworkDraftWorkflow
from tests.integration.tools.test_rework_write_tools import CASES, ISSUE, REWORK, TASK, Case
from tests.test_rework_approval_schemas import draft_values

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]
ORDER, TRACE = "ORDER-T827-A", "trace-t827"
PERMISSIONS = frozenset({"TASK_READ", "REWORK_READ", "REWORK_WRITE", "REVIEW_WRITE"})


def command(case: Case) -> dict[str, object]:
    """用户只提供选择与本次人工材料，移除测试旧快照中的所有服务端字段。"""

    raw = draft_values(case)
    request = raw["request"]
    assert isinstance(request, dict)
    result: dict[str, object] = {"operation": case.operation, "task_id": TASK}
    if case.operation == "CREATE_LIFECYCLE_REWORK":
        result["source_issue_id"] = ISSUE
    else:
        result["rework_task_id"] = REWORK
    aliases = {"processingComment": "processing_comment", "evidenceReferences": "evidence_references",
               "reviewComment": "review_comment"}
    for field in ("reason", "artifact", "processingComment", "evidenceReferences", "items", "status", "reviewComment"):
        if field in request:
            result[aliases.get(field, field)] = deepcopy(request[field])
    return result


def facts(case: Case) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """独立Java事实夹具使用新修订2，不能沿用旧命令快照的修订1。"""

    operation = case.operation
    first = operation == "CREATE_LIFECYCLE_REWORK"
    status, issue_status = {
        "CREATE_LIFECYCLE_REWORK": ("PENDING", "OPEN"),
        "START_REWORK": ("PENDING", "OPEN"),
        "BLOCK_REWORK": ("RUNNING", "PROCESSING"),
        "FAIL_REWORK": ("RUNNING", "PROCESSING"),
        "RESUME_REWORK": ("FAILED", "PROCESSING"),
        "REGISTER_REWORK_RESULT": ("RUNNING", "PROCESSING"),
        "REGISTER_REWORK_INSPECTION": ("RUNNING", "PROCESSING"),
        "SUBMIT_REWORK_REVIEW": ("COMPLETED", "RESOLVED"),
        "CREATE_NEXT_REWORK": ("COMPLETED", "OPEN"),
    }[operation]
    task: dict[str, object] = {"taskId": TASK, "orderId": ORDER, "status": "COMPLETED", "version": 4}
    rework = {"reworkTaskId": REWORK, "taskId": TASK, "sourceIssueId": ISSUE,
              "status": status, "reason": "  真实创建原因  "}
    processing = None if first or operation == "START_REWORK" else {
        "processingRevision": 2,
        "artifact": {"artifactId": "真实成果", "artifactVersion": "Release-2"},
        "processingComment": "  Java登记的原处理说明🚀  ",
        "evidenceReferences": ["report:actual-processing"],
        "registeredBy": "handler-test", "registeredAt": "2026-11-18T00:01:00Z",
    }
    inspection = None if processing is None else {
        "inspectionId": "CHECK-T827-CURRENT", "inspectionSequence": 3, "roundNumber": 1,
        "processingRevision": 2, "result": "PASSED", "inspectorId": "inspector-test",
        "inspectedAt": "2026-11-18T00:02:00Z", "items": [{
            "checkItem": "坐标系", "result": "PASSED", "comment": "实际登记检查",
            "evidenceReferences": ["report:actual-check"],
        }],
    }
    review = None if operation != "CREATE_NEXT_REWORK" else {
        "reviewId": "REVIEW-T827-RETURN", "reviewSequence": 2, "roundNumber": 1,
        "processingRevision": 2, "inspectionId": "CHECK-T827-CURRENT", "status": "REWORK_REQUIRED",
        "reviewComment": "原退回意见", "reviewedBy": "reviewer-test", "reviewedAt": "2026-11-18T00:03:00Z",
    }
    effective = {
        "issueId": ISSUE, "reworkTaskId": None if first else REWORK,
        "roundNumber": None if first else 1,
        "processingRevision": None if processing is None else 2,
        "inspectionId": None if inspection is None else "CHECK-T827-CURRENT",
        "review": review, "legacyReviews": [],
    }
    conditions: dict[str, object] = {
        "order": {"orderId": ORDER, "productType": "DOM", "status": "QUALITY_CHECKING"},
        "tasks": [{
            "taskId": TASK, "taskVersion": 4, "productionStatus": "COMPLETED",
            "steps": [{"stepId": "STEP-T827-A", "taskId": TASK, "stepName": "生产",
                       "sequenceNumber": 1, "status": "COMPLETED"}],
            "issues": [{"issue": {"issueId": ISSUE, "taskId": TASK, "issueType": "COORDINATE_SYSTEM",
                                  "status": issue_status, "description": "真实来源问题"},
                        "effectiveReview": effective}],
            "activeReworks": [rework] if not first and status != "COMPLETED" else [],
        }],
        "deliveryRecords": [{"deliveryId": "DELIVERY-T827-A", "orderId": ORDER, "status": "BLOCKED"}],
        "blockers": [{"code": "DELIVERY_NOT_READY", "taskId": None,
                      "resourceId": "DELIVERY-T827-A", "status": "BLOCKED"}],
        "hasBlockers": True,
    }
    detail: dict[str, object] = {
        "reworkTask": rework, "issueStatus": issue_status, "roundNumber": 1,
        "previousReworkTaskId": None, "allowedActions": [] if first else [operation],
        "taskVersion": 4, "processing": processing, "inspection": inspection, "review": review,
    }
    return task, conditions, detail


def nested(value: object, *path: str | int) -> dict[str, object]:
    """只用于修改明确的JSON夹具，不忽略Schema的运行时校验。"""

    for key in path:
        if isinstance(key, int):
            assert isinstance(value, list)
            value = value[key]
        else:
            assert isinstance(value, dict)
            value = value[key]
    assert isinstance(value, dict)
    return value


def context(permissions: frozenset[str] = PERMISSIONS) -> ToolContext:
    """权限从可信服务端上下文模拟提供，不放入命令。"""

    return ToolContext(identity=BusinessIdentity(user_id="reviewer-test", role="REVIEWER"),
                       permissions=permissions, trace_id=TRACE, run_id="run-t827")


def response(data: object) -> httpx.Response:
    """保持现有Java信封，不构造假确认或执行成功回执。"""

    return httpx.Response(200, headers={"X-Trace-Id": TRACE}, json={"success": True,
        "code": "SUCCESS", "message": "success", "data": data, "trace_id": TRACE, "retryable": False})


def workflow(shared: BusinessHttpClient, timeout: float = 15.0) -> ReworkDraftWorkflow:
    """真实只读Tool及Client，不提供任何Store或写Tool依赖。"""

    return ReworkDraftWorkflow(task_tools=create_read_tool_registry(shared),
        rework_tools=create_rework_read_tool_registry(ReworkHttpClient(shared)), timeout_seconds=timeout)


def client(transport: httpx.MockTransport) -> BusinessHttpClient:
    """显式MockTransport，不访问Java或数据库。"""

    return BusinessHttpClient(Settings(environment="test", business_service_url=AnyHttpUrl("http://business.test")), transport=transport)


def fact_handler(
    data: tuple[dict[str, object], dict[str, object], dict[str, object]], calls: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    """按实际固定路径响应，任何写入或额外端点都失败。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """记录实际HTTP边界，不能只用假Workflow返回值冒充取证。"""

        calls.append(request)
        assert request.method == "GET"
        assert request.headers["X-User-Id"] == "reviewer-test"
        assert request.headers["X-Trace-Id"] == TRACE
        if request.url.path == f"/api/tasks/{TASK}":
            return response(data[0])
        if request.url.path == f"/api/orders/{ORDER}/delivery-conditions":
            return response(data[1])
        assert request.url.path == f"/api/tasks/{TASK}/reworks/{REWORK}"
        return response(data[2])
    return handler


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.operation)
async def test_nine_actions_read_fresh_java_facts_and_only_prepare_a_review(case: Case) -> None:
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(facts(case), calls)))
    try:
        prepared = await workflow(shared).ainvoke(command(case), context=context())
        assert prepared.review.draft.operation == case.operation
        assert prepared.review.draft.target.task_version == 4
        assert prepared.review.pending_tool == case.name
        assert prepared.review.effect_semantics == "EXPECTED_IF_JAVA_ACCEPTS"
        assert prepared.review.draft.request.expected_version == 4
        assert len(calls) == (2 if case.operation == "CREATE_LIFECYCLE_REWORK" else 3)
        assert prepared.current_task.production_status == "COMPLETED"
        assert prepared.order_id == ORDER
        assert "approval_id" not in prepared.model_dump()
        if case.operation in {"REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW", "CREATE_NEXT_REWORK"}:
            assert prepared.review.draft.target.processing_revision == 2
            assert prepared.current_rework is not None and prepared.current_rework.processing is not None
            assert prepared.current_rework.processing.evidence_references == ["report:actual-processing"]
            assert prepared.current_rework.processing.processing_comment == "  Java登记的原处理说明🚀  "
        if case.operation == "SUBMIT_REWORK_REVIEW":
            assert prepared.review.draft.target.inspection_id == "CHECK-T827-CURRENT"
        assert all(call.method == "GET" for call in calls)
    finally:
        await shared.aclose()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.operation)
async def test_write_permission_is_checked_before_any_fact_read(case: Case) -> None:
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(facts(case), calls)))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared).ainvoke(command(case), context=context(frozenset({"TASK_READ", "REWORK_READ"})))
        assert error.value.code == ToolErrorCode.PERMISSION_DENIED and calls == []
    finally:
        await shared.aclose()


@pytest.mark.parametrize("field", ["expectedVersion", "task_version", "target", "confirmed", "approval_id", "processing_revision", "inspection_id"])
async def test_user_cannot_submit_server_facts_or_confirmation(field: str) -> None:
    raw = command(CASES[7])
    raw[field] = "self-reported"
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(facts(CASES[7]), calls)))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared).ainvoke(raw, context=context())
        assert error.value.code == ToolErrorCode.PARAM_VALIDATION_ERROR and calls == []
    finally:
        await shared.aclose()


@pytest.mark.parametrize("kind", ["task-version", "detail-version", "processing", "round", "no-action", "no-issue", "legacy", "failed-inspection", "not-completed"])
async def test_changed_incomplete_or_disallowed_facts_stop_without_a_draft(kind: str) -> None:
    case = CASES[7]
    data = facts(case)
    if kind == "task-version": nested(data[1], "tasks", 0)["taskVersion"] = 5
    elif kind == "detail-version": data[2]["taskVersion"] = 5
    elif kind == "processing": nested(data[1], "tasks", 0, "issues", 0, "effectiveReview")["processingRevision"] = 1
    elif kind == "round": nested(data[1], "tasks", 0, "issues", 0, "effectiveReview").update(reworkTaskId="REWORK-NEW", roundNumber=2)
    elif kind == "no-action": data[2]["allowedActions"] = []
    elif kind == "no-issue": nested(data[1], "tasks", 0)["issues"] = []
    elif kind == "legacy": data[2].update(roundNumber=None, allowedActions=[], processing=None, inspection=None)
    elif kind == "failed-inspection":
        nested(data[2], "inspection")["result"] = "FAILED"
        nested(data[2], "inspection", "items", 0)["result"] = "FAILED"
    else:
        data[0]["status"] = "RUNNING"
        nested(data[1], "tasks", 0)["productionStatus"] = "RUNNING"
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(data, calls)))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared).ainvoke(command(case), context=context())
        assert error.value.code in {ToolErrorCode.BUSINESS_CONFLICT, ToolErrorCode.RESOURCE_NOT_FOUND}
        assert all(call.method == "GET" for call in calls)
    finally:
        await shared.aclose()


@pytest.mark.parametrize("first", [True, False])
async def test_active_rework_prevents_creation_and_existing_chain_cannot_be_recreated(first: bool) -> None:
    case = CASES[0] if first else CASES[8]
    data = facts(case)
    nested(data[1], "tasks", 0)["activeReworks"] = [{
        "reworkTaskId": "REWORK-OTHER-ACTIVE", "taskId": TASK, "sourceIssueId": ISSUE,
        "status": "PENDING", "reason": "另有活动返工",
    }]
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(data, calls)))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared).ainvoke(command(case), context=context())
        assert error.value.code == ToolErrorCode.BUSINESS_CONFLICT
    finally:
        await shared.aclose()


async def test_first_creation_cannot_restart_a_completed_controlled_chain() -> None:
    data = facts(CASES[0])
    nested(data[1], "tasks", 0, "issues", 0, "effectiveReview").update(
        reworkTaskId=REWORK, roundNumber=1,
    )
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(data, calls)))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared).ainvoke(command(CASES[0]), context=context())
        assert error.value.code == ToolErrorCode.BUSINESS_CONFLICT
        assert len(calls) == 2
    finally:
        await shared.aclose()


@pytest.mark.parametrize("status", ["REJECTED", "REWORK_REQUIRED"])
async def test_review_return_does_not_automatically_create_the_next_round(status: str) -> None:
    case = CASES[7]
    raw = command(case)
    raw["status"] = status
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(facts(case), calls)))
    try:
        result = await workflow(shared).ainvoke(raw, context=context())
        assert result.review.expected_effects.issue_status_after == "OPEN"
        assert result.review.expected_effects.rework_status_after == "COMPLETED"
        assert len(calls) == 3 and all(call.method == "GET" for call in calls)
    finally:
        await shared.aclose()


async def test_failed_human_check_keeps_running_and_input_evidence_is_copied() -> None:
    case = CASES[6]
    raw = command(case)
    nested(raw, "items", 0)["result"] = "FAILED"
    calls: list[httpx.Request] = []
    base = fact_handler(facts(case), calls)
    def handler(request: httpx.Request) -> httpx.Response:
        """取证期间修改调用方原对象，不能改动已解析命令。"""
        result = base(request)
        nested(raw, "items", 0)["comment"] = "调用方迟到修改"
        return result
    shared = client(httpx.MockTransport(handler))
    try:
        prepared = await workflow(shared).ainvoke(raw, context=context())
        assert prepared.review.expected_effects.rework_status_after == "RUNNING"
        assert prepared.review.expected_effects.issue_status_after == "PROCESSING"
        assert "调用方迟到修改" not in prepared.model_dump_json()
    finally:
        await shared.aclose()


async def test_unavailable_java_facts_do_not_fall_back_to_user_snapshots() -> None:
    calls = 0
    def handler(_: httpx.Request) -> httpx.Response:
        """明确Java拒绝不得从历史或命令补事实。"""
        nonlocal calls
        calls += 1
        return httpx.Response(403, headers={"X-Trace-Id": TRACE}, json={
            "success": False, "code": "PERMISSION_DENIED", "message": "safe denial",
            "data": None, "trace_id": TRACE, "retryable": False,
        })
    shared = client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared).ainvoke(command(CASES[1]), context=context())
        assert error.value.code == ToolErrorCode.PERMISSION_DENIED and calls == 1
    finally:
        await shared.aclose()


async def test_misconfigured_high_risk_tool_is_never_executed() -> None:
    class UnsafeTaskTool(BaseTool[TaskIdInput, TaskDetail]):
        """模拟服务端误装配，固定读取名称也不能绕过只读元数据门禁。"""

        def __init__(self) -> None:
            """声明HIGH风险，执行计数必须始终为零。"""
            super().__init__(name="get_task_detail", description="misconfigured tool",
                input_model=TaskIdInput, output_model=TaskDetail,
                risk_level=ToolRiskLevel.HIGH, required_permissions=frozenset(),
                timeout=5.0, max_retries=0)
            self.calls = 0

        async def _execute(self, tool_input: TaskIdInput, context: ToolContext) -> TaskDetail:
            """若被调用即代表Workflow未在执行前拒绝误配置。"""
            self.calls += 1
            return TaskDetail.model_validate(facts(CASES[1])[0])

    unsafe = UnsafeTaskTool()
    tasks = ToolRegistry()
    tasks.register(unsafe)
    calls: list[httpx.Request] = []
    shared = client(httpx.MockTransport(fact_handler(facts(CASES[1]), calls)))
    try:
        prepare = ReworkDraftWorkflow(task_tools=tasks,
            rework_tools=create_rework_read_tool_registry(ReworkHttpClient(shared)))
        with pytest.raises(ToolException) as error:
            await prepare.ainvoke(command(CASES[1]), context=context())
        assert error.value.code == ToolErrorCode.UNKNOWN_TOOL_ERROR
        assert unsafe.calls == 0 and calls == []
    finally:
        await shared.aclose()


async def test_whole_workflow_budget_stops_fact_reading_without_background_write() -> None:
    started, hold = asyncio.Event(), asyncio.Event()
    calls = 0
    async def handler(_: httpx.Request) -> httpx.Response:
        """挂起第一条只读请求以触发Workflow总预算。"""
        nonlocal calls
        calls += 1
        started.set()
        await hold.wait()
        return response(facts(CASES[1])[0])
    shared = client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ToolException) as error:
            await workflow(shared, timeout=0.02).ainvoke(command(CASES[1]), context=context())
        assert error.value.code == ToolErrorCode.TOOL_TIMEOUT
        assert not error.value.retryable and started.is_set() and calls == 1
    finally:
        await shared.aclose()
