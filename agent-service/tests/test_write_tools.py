"""M6.5复核回写与返工创建Tool的安全映射和持久化测试。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import AnyHttpUrl, ValidationError

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode
from app.models import ApprovalStatus, PendingToolName
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.write_tools import (
    CreateReworkTaskInput,
    CreateReworkTaskOutput,
    WriteReviewResultInput,
    WriteReviewResultOutput,
)
from app.services.approval_execution_store import ApprovalExecutionSnapshot
from app.settings import Settings
from app.tools import (
    CreateReworkTaskTool,
    ToolContext,
    ToolRiskLevel,
    WriteReviewResultTool,
    create_write_tool_registry,
)


class _FakeExecutionStore:
    def __init__(self, snapshot: ApprovalExecutionSnapshot | None) -> None:
        self.snapshot = snapshot
        self.requested: list[str] = []
        self.saved: list[tuple[str, dict[str, Any]]] = []
        self.allow_save = True

    async def get_execution_snapshot(
        self,
        approval_id: str,
    ) -> ApprovalExecutionSnapshot | None:
        self.requested.append(approval_id)
        return self.snapshot

    async def save_execution_result(
        self,
        approval_id: str,
        *,
        result: dict[str, Any],
    ) -> bool:
        self.saved.append((approval_id, result))
        return self.allow_save


def _draft(**changes: object) -> ReviewDraft:
    values: dict[str, object] = {
        "task_id": "TASK-003",
        "issue_id": "ISSUE-001",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": "建议完成坐标系统处理后重新提交复核",
        "specification_references": [],
        "suggested_rework": {
            "required": True,
            "type": "COORDINATE_SYSTEM_FIX",
        },
    }
    values.update(changes)
    return ReviewDraft.model_validate(values)


def _snapshot(
    *,
    pending_tool_name: PendingToolName = PendingToolName.WRITE_REVIEW_RESULT,
    status: ApprovalStatus = ApprovalStatus.EXECUTING,
    confirmed_by_user_id: str | None = "reviewer-001",
    draft: ReviewDraft | None = None,
) -> ApprovalExecutionSnapshot:
    return ApprovalExecutionSnapshot(
        approval_id="approval-write-003",
        status=status,
        pending_tool_name=pending_tool_name,
        target_id="TASK-003",
        target_version=7,
        confirmed_by_user_id=confirmed_by_user_id,
        draft=draft or _draft(),
    )


def _context(*, user_id: str = "reviewer-001", permission: str) -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id=user_id, role="REVIEWER"),
        permissions=frozenset({permission}),
        trace_id="trace-write-003",
        run_id="run-write-003",
    )


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://agent:agent@localhost:5432/agent",
        business_service_url=AnyHttpUrl("http://business.test"),
    )


def _success(data: dict[str, Any], *, trace_id: str = "trace-java-write") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": data,
            "trace_id": trace_id,
            "retryable": False,
        },
        headers={"X-Trace-Id": trace_id},
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("schema", "values"),
    [
        (WriteReviewResultInput, {"approval_id": " ", "idempotency_key": "write-003"}),
        (CreateReworkTaskInput, {"approval_id": "approval-003", "idempotency_key": "bad key"}),
        (
            WriteReviewResultInput,
            {"approval_id": "approval-003", "idempotency_key": "write-003", "task_id": "TASK-004"},
        ),
    ],
)
def test_write_tool_input_schemas_reject_invalid_or_unapproved_parameters(
    schema: type[WriteReviewResultInput] | type[CreateReworkTaskInput],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(values)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_tool_is_high_risk_non_retrying_and_requires_static_permission() -> None:
    client = BusinessHttpClient(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("Java write must not be called"))
        ),
    )
    store = _FakeExecutionStore(_snapshot())
    tool = WriteReviewResultTool(client, store)
    context = ToolContext(
        identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
        permissions=frozenset(),
        trace_id="trace-write-003",
        run_id="run-write-003",
    )
    try:
        result = await tool.execute(
            {"approval_id": "approval-write-003", "idempotency_key": "approval:write:003"},
            context,
        )
    finally:
        await client.aclose()

    assert tool.risk_level is ToolRiskLevel.HIGH
    assert tool.max_retries == 0
    assert tool.required_permissions == frozenset({"REVIEW_WRITE"})
    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.PERMISSION_DENIED
    assert store.requested == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_tools_use_a_dedicated_registry() -> None:
    client = BusinessHttpClient(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("Java write must not be called"))
        ),
    )
    try:
        registry = create_write_tool_registry(client, _FakeExecutionStore(_snapshot()))

        assert registry.names == ("create_rework_task", "write_review_result")
    finally:
        await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_review_result_maps_confirmed_approval_and_persists_java_result() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/api/tasks/TASK-003/review"
        assert request.headers["X-User-Id"] == "reviewer-001"
        assert request.headers["X-User-Role"] == "REVIEWER"
        assert request.headers["Idempotency-Key"] == "approval:write:003"
        assert json.loads(request.content) == {
            "issueId": "ISSUE-001",
            "status": "REWORK_REQUIRED",
            "reviewComment": "建议完成坐标系统处理后重新提交复核",
            "expectedVersion": 7,
        }
        return _success(
            {
                "review": {
                    "reviewId": "REVIEW-WRITE-003",
                    "issueId": "ISSUE-001",
                    "status": "REWORK_REQUIRED",
                    "reviewComment": "建议完成坐标系统处理后重新提交复核",
                },
                "taskVersion": 8,
            }
        )

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    store = _FakeExecutionStore(_snapshot())
    tool = WriteReviewResultTool(client, store)
    try:
        result = await tool.execute(
            {
                "approval_id": "approval-write-003",
                "idempotency_key": "approval:write:003",
            },
            _context(permission="REVIEW_WRITE"),
        )
    finally:
        await client.aclose()

    assert result.success is True
    assert isinstance(result.data, WriteReviewResultOutput)
    assert result.data.review_id == "REVIEW-WRITE-003"
    assert result.data.task_version == 8
    assert result.data.java_trace_id == "trace-java-write"
    assert len(calls) == 1
    assert store.saved == [
        (
            "approval-write-003",
            result.data.model_dump(mode="json"),
        )
    ]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("snapshot", "user_id", "expected_code"),
    [
        (None, "reviewer-001", ToolErrorCode.RESOURCE_NOT_FOUND),
        (
            _snapshot(status=ApprovalStatus.CONFIRMED),
            "reviewer-001",
            ToolErrorCode.BUSINESS_CONFLICT,
        ),
        (_snapshot(), "reviewer-other", ToolErrorCode.PERMISSION_DENIED),
        (
            _snapshot(pending_tool_name=PendingToolName.CREATE_REWORK_TASK),
            "reviewer-001",
            ToolErrorCode.BUSINESS_CONFLICT,
        ),
    ],
)
async def test_write_review_result_rejects_missing_unlocked_wrong_user_or_wrong_tool(
    snapshot: ApprovalExecutionSnapshot | None,
    user_id: str,
    expected_code: ToolErrorCode,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("Java write must not be called")

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    store = _FakeExecutionStore(snapshot)
    tool = WriteReviewResultTool(client, store)
    try:
        result = await tool.execute(
            {"approval_id": "approval-write-003", "idempotency_key": "approval:write:003"},
            _context(user_id=user_id, permission="REVIEW_WRITE"),
        )
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is expected_code
    assert calls == 0
    assert store.saved == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_rework_task_validates_type_calls_java_and_saves_new_task_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tasks/TASK-003/rework"
        assert request.headers["Idempotency-Key"] == "approval:rework:003"
        assert json.loads(request.content) == {
            "sourceIssueId": "ISSUE-001",
            "reason": "建议完成坐标系统处理后重新提交复核",
            "expectedVersion": 7,
        }
        return _success(
            {
                "reworkTask": {
                    "reworkTaskId": "REWORK-WRITE-003",
                    "taskId": "TASK-003",
                    "sourceIssueId": "ISSUE-001",
                    "status": "PENDING",
                    "reason": "建议完成坐标系统处理后重新提交复核",
                },
                "taskVersion": 8,
            }
        )

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    store = _FakeExecutionStore(
        _snapshot(pending_tool_name=PendingToolName.CREATE_REWORK_TASK)
    )
    tool = CreateReworkTaskTool(client, store)
    try:
        result = await tool.execute(
            {
                "approval_id": "approval-write-003",
                "idempotency_key": "approval:rework:003",
            },
            _context(permission="REWORK_WRITE"),
        )
    finally:
        await client.aclose()

    assert result.success is True
    assert isinstance(result.data, CreateReworkTaskOutput)
    assert result.data.rework_task_id == "REWORK-WRITE-003"
    assert result.data.source_issue_id == "ISSUE-001"
    assert result.data.rework_type.value == "COORDINATE_SYSTEM_FIX"
    assert store.saved[0][1]["rework_task_id"] == "REWORK-WRITE-003"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_rework_task_rejects_approval_without_coordinate_rework() -> None:
    draft = _draft(
        conclusion="APPROVED",
        suggested_rework={"required": False, "type": None},
    )
    client = BusinessHttpClient(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("Java write must not be called"))
        ),
    )
    store = _FakeExecutionStore(
        _snapshot(
            pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
            draft=draft,
        )
    )
    tool = CreateReworkTaskTool(client, store)
    try:
        result = await tool.execute(
            {"approval_id": "approval-write-003", "idempotency_key": "approval:rework:003"},
            _context(permission="REWORK_WRITE"),
        )
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.BUSINESS_CONFLICT
    assert store.saved == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_tool_rejects_mismatched_java_response_without_persisting() -> None:
    client = BusinessHttpClient(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: _success(
                {
                    "review": {
                        "reviewId": "REVIEW-WRITE-003",
                        "issueId": "ISSUE-OTHER",
                        "status": "REWORK_REQUIRED",
                        "reviewComment": "建议完成坐标系统处理后重新提交复核",
                    },
                    "taskVersion": 8,
                }
            )
        ),
    )
    store = _FakeExecutionStore(_snapshot())
    tool = WriteReviewResultTool(client, store)
    try:
        result = await tool.execute(
            {"approval_id": "approval-write-003", "idempotency_key": "approval:write:003"},
            _context(permission="REVIEW_WRITE"),
        )
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert store.saved == []
