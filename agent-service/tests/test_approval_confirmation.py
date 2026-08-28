"""M6.6确认前重新校验、执行锁和终态裁决测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.errors import ToolErrorCode
from app.models import ApprovalStatus, OperationType, PendingToolName
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.operation_log import OperationLogDetail
from app.schemas.tools import QualityIssueList, TaskDetail
from app.schemas.write_tools import WriteReviewResultOutput
from app.services.approval_confirmation import (
    ApprovalConfirmationError,
    ApprovalConfirmationService,
    ApprovalConfirmationSnapshot,
)
from app.tools import ToolContext, ToolError, ToolResult

_NOW = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


def _draft(**changes: object) -> ReviewDraft:
    values: dict[str, object] = {
        "task_id": "TASK-003",
        "issue_id": "ISSUE-001",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": "完成坐标系统处理后重新提交复核",
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
    status: ApprovalStatus = ApprovalStatus.WAITING_CONFIRMATION,
    target_version: int = 7,
    confirmed_by_user_id: str | None = None,
    created_at: datetime = _NOW - timedelta(minutes=1),
    draft: ReviewDraft | None = None,
    execution_result: dict[str, Any] | None = None,
) -> ApprovalConfirmationSnapshot:
    return ApprovalConfirmationSnapshot(
        approval_id="approval-confirm-003",
        status=status,
        pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
        operation_type=OperationType.SUBMIT_REVIEW,
        target_id="TASK-003",
        target_version=target_version,
        confirmed_by_user_id=confirmed_by_user_id,
        created_at=created_at,
        original_draft=_draft(),
        draft=draft or _draft(),
        execution_result=execution_result,
    )


def _task(*, version: int = 7, status: str = "COMPLETED") -> TaskDetail:
    return TaskDetail.model_validate(
        {
            "taskId": "TASK-003",
            "orderId": "ORDER-003",
            "status": status,
            "version": version,
        }
    )


def _issues(*, status: str = "OPEN", issue_type: str = "COORDINATE_SYSTEM") -> QualityIssueList:
    return QualityIssueList.model_validate(
        {
            "taskId": "TASK-003",
            "issues": [
                {
                    "issueId": "ISSUE-001",
                    "taskId": "TASK-003",
                    "issueType": issue_type,
                    "status": status,
                    "description": "成果坐标参考系与任务要求不一致",
                }
            ],
        }
    )


def _write_output() -> WriteReviewResultOutput:
    return WriteReviewResultOutput(
        approval_id="approval-confirm-003",
        task_id="TASK-003",
        issue_id="ISSUE-001",
        review_id="REVIEW-WRITE-003",
        status="REWORK_REQUIRED",
        review_comment="完成坐标系统处理后重新提交复核",
        task_version=8,
        java_trace_id="trace-java-write",
    )


class _FakeStore:
    def __init__(self, snapshot: ApprovalConfirmationSnapshot | None) -> None:
        self.snapshot = snapshot
        self.transitions: list[tuple[ApprovalStatus, ApprovalStatus]] = []
        self.confirm_calls = 0
        self.execution_result_on_success: dict[str, Any] | None = None
        self.operation_logs: list[OperationLogDetail] = []
        self._lock = asyncio.Lock()

    async def get_snapshot(self, approval_id: str) -> ApprovalConfirmationSnapshot | None:
        assert approval_id == "approval-confirm-003"
        return self.snapshot

    async def confirm_waiting(
        self,
        approval_id: str,
        *,
        draft: ReviewDraft,
        confirmed_by_user_id: str,
        confirmed_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        self.confirm_calls += 1
        async with self._lock:
            current = self.snapshot
            if current is None or current.status is not ApprovalStatus.WAITING_CONFIRMATION:
                return None
            self.snapshot = ApprovalConfirmationSnapshot(
                approval_id=current.approval_id,
                status=ApprovalStatus.CONFIRMED,
                pending_tool_name=current.pending_tool_name,
                operation_type=current.operation_type,
                target_id=current.target_id,
                target_version=current.target_version,
                confirmed_by_user_id=confirmed_by_user_id,
                created_at=current.created_at,
                original_draft=current.original_draft,
                draft=draft,
                execution_result=current.execution_result,
            )
            return self.snapshot

    async def transition(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        target_status: ApprovalStatus,
        updated_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        async with self._lock:
            current = self.snapshot
            if current is None or current.status is not expected_status:
                return None
            self.transitions.append((expected_status, target_status))
            self.snapshot = ApprovalConfirmationSnapshot(
                approval_id=current.approval_id,
                status=target_status,
                pending_tool_name=current.pending_tool_name,
                operation_type=current.operation_type,
                target_id=current.target_id,
                target_version=current.target_version,
                confirmed_by_user_id=current.confirmed_by_user_id,
                created_at=current.created_at,
                original_draft=current.original_draft,
                draft=current.draft,
                execution_result=(
                    self.execution_result_on_success
                    if target_status is ApprovalStatus.SUCCEEDED
                    else current.execution_result
                ),
            )
            return self.snapshot

    async def finish_with_operation_log(
        self,
        approval_id: str,
        *,
        target_status: ApprovalStatus,
        detail: OperationLogDetail,
        updated_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        async with self._lock:
            current = self.snapshot
            if current is None or current.status is not ApprovalStatus.EXECUTING:
                return None
            self.transitions.append((ApprovalStatus.EXECUTING, target_status))
            self.operation_logs.append(detail)
            self.snapshot = ApprovalConfirmationSnapshot(
                approval_id=current.approval_id,
                status=target_status,
                pending_tool_name=current.pending_tool_name,
                operation_type=current.operation_type,
                target_id=current.target_id,
                target_version=current.target_version,
                confirmed_by_user_id=current.confirmed_by_user_id,
                created_at=current.created_at,
                original_draft=current.original_draft,
                draft=current.draft,
                execution_result=(
                    self.execution_result_on_success
                    if target_status is ApprovalStatus.SUCCEEDED
                    else current.execution_result
                ),
            )
            return self.snapshot


class _FakeTool:
    def __init__(self, result: ToolResult[Any]) -> None:
        self.result = result
        self.calls: list[tuple[dict[str, object], ToolContext, bool]] = []

    async def execute(
        self,
        raw_input: Mapping[str, object],
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> ToolResult[Any]:
        self.calls.append((dict(raw_input), context, force_refresh))
        return self.result


class _FakeRegistry:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self.tools = tools

    def get(self, name: str) -> _FakeTool:
        return self.tools[name]


def _service(
    store: _FakeStore,
    *,
    task: TaskDetail | None = None,
    issues: QualityIssueList | None = None,
    task_result: ToolResult[Any] | None = None,
    write_result: ToolResult[Any] | None = None,
) -> tuple[ApprovalConfirmationService, _FakeTool, _FakeTool, _FakeTool]:
    task_tool = _FakeTool(task_result or ToolResult(success=True, data=task or _task()))
    issue_tool = _FakeTool(ToolResult(success=True, data=issues or _issues()))
    write_tool = _FakeTool(
        write_result or ToolResult(success=True, data=_write_output())
    )
    if write_tool.result.success and write_tool.result.data is not None:
        store.execution_result_on_success = write_tool.result.data.model_dump(mode="json")
    service = ApprovalConfirmationService(
        store,
        _FakeRegistry(
            {
                "get_task_detail": task_tool,
                "get_quality_issues": issue_tool,
            }
        ),
        _FakeRegistry({"write_review_result": write_tool}),
        approval_ttl_seconds=900,
        now=lambda: _NOW,
    )
    return service, task_tool, issue_tool, write_tool


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmation_refreshes_facts_locks_executes_and_marks_succeeded() -> None:
    store = _FakeStore(_snapshot())
    service, task_tool, issue_tool, write_tool = _service(store)

    execution = await service.confirm_and_execute(
        approval_id="approval-confirm-003",
        draft=_draft(review_comment="  完成坐标系统处理后重新提交复核  "),
        identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
        trace_id="trace-confirm-003",
    )

    assert execution.status is ApprovalStatus.SUCCEEDED
    assert isinstance(execution.result, WriteReviewResultOutput)
    assert execution.result.review_id == "REVIEW-WRITE-003"
    assert store.confirm_calls == 1
    assert store.transitions == [
        (ApprovalStatus.CONFIRMED, ApprovalStatus.EXECUTING),
        (ApprovalStatus.EXECUTING, ApprovalStatus.SUCCEEDED),
    ]
    assert task_tool.calls[0][0] == {"task_id": "TASK-003"}
    assert issue_tool.calls[0][0] == {"task_id": "TASK-003"}
    assert task_tool.calls[0][2] is True
    assert write_tool.calls[0][0]["approval_id"] == "approval-confirm-003"
    assert str(write_tool.calls[0][0]["idempotency_key"]).startswith(
        "approval:write_review_result:"
    )
    assert len(store.operation_logs) == 1
    assert store.operation_logs[0].after_summary.outcome is ApprovalStatus.SUCCEEDED
    assert store.operation_logs[0].java_trace_id == "trace-java-write"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expired_approval_is_terminal_before_java_reads() -> None:
    store = _FakeStore(_snapshot(created_at=_NOW - timedelta(minutes=16)))
    service, task_tool, issue_tool, write_tool = _service(store)

    with pytest.raises(ApprovalConfirmationError) as expired:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
            trace_id="trace-expired",
        )

    assert expired.value.code == "APPROVAL_EXPIRED"
    assert expired.value.status_code == 410
    assert store.snapshot is not None
    assert store.snapshot.status is ApprovalStatus.EXPIRED
    assert task_tool.calls == issue_tool.calls == write_tool.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmation_rejects_non_reviewer_before_reading_approval() -> None:
    store = _FakeStore(_snapshot())
    service, task_tool, issue_tool, write_tool = _service(store)

    with pytest.raises(ApprovalConfirmationError) as denied:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="operator-001", role="OPERATOR"),
            trace_id="trace-denied",
        )

    assert denied.value.code == ToolErrorCode.PERMISSION_DENIED.value
    assert denied.value.status_code == 403
    assert store.confirm_calls == 0
    assert task_tool.calls == issue_tool.calls == write_tool.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task", "issues"),
    [
        (_task(version=8), _issues()),
        (_task(status="RUNNING"), _issues()),
        (_task(), _issues(status="CLOSED")),
        (_task(), _issues(issue_type="RADIOMETRIC")),
    ],
)
async def test_changed_business_fact_marks_approval_stale_without_writing(
    task: TaskDetail,
    issues: QualityIssueList,
) -> None:
    store = _FakeStore(_snapshot())
    service, _, _, write_tool = _service(store, task=task, issues=issues)

    with pytest.raises(ApprovalConfirmationError) as stale:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
            trace_id="trace-stale",
        )

    assert stale.value.code == "APPROVAL_STALE"
    assert store.snapshot is not None
    assert store.snapshot.status is ApprovalStatus.STALE
    assert write_tool.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_succeeded_duplicate_returns_stored_result_without_java_call() -> None:
    output = _write_output()
    store = _FakeStore(
        _snapshot(
            status=ApprovalStatus.SUCCEEDED,
            confirmed_by_user_id="reviewer-001",
            execution_result=output.model_dump(mode="json"),
        )
    )
    service, task_tool, issue_tool, write_tool = _service(store)

    execution = await service.confirm_and_execute(
        approval_id="approval-confirm-003",
        draft=_draft(),
        identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
        trace_id="trace-duplicate",
    )

    assert execution.status is ApprovalStatus.SUCCEEDED
    assert execution.result == output
    assert task_tool.calls == issue_tool.calls == write_tool.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_failure_keeps_confirmed_approval_retryable_without_writing() -> None:
    read_error = ToolError(
        code=ToolErrorCode.UPSTREAM_UNAVAILABLE,
        message="business service is unavailable",
        retryable=True,
        trace_id="trace-read-unavailable",
        status_code=502,
    )
    store = _FakeStore(_snapshot())
    service, _, issue_tool, write_tool = _service(
        store,
        task_result=ToolResult(success=False, error=read_error),
    )

    with pytest.raises(ApprovalConfirmationError) as unavailable:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
            trace_id="trace-read-failure",
        )

    assert unavailable.value.code == ToolErrorCode.UPSTREAM_UNAVAILABLE.value
    assert unavailable.value.retryable is True
    assert store.snapshot is not None
    assert store.snapshot.status is ApprovalStatus.CONFIRMED
    assert issue_tool.calls == write_tool.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmed_approval_rejects_another_user_and_changed_draft() -> None:
    store = _FakeStore(
        _snapshot(
            status=ApprovalStatus.CONFIRMED,
            confirmed_by_user_id="reviewer-001",
        )
    )
    service, task_tool, issue_tool, write_tool = _service(store)

    with pytest.raises(ApprovalConfirmationError) as wrong_user:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="reviewer-002", role="REVIEWER"),
            trace_id="trace-wrong-user",
        )
    with pytest.raises(ApprovalConfirmationError) as changed_draft:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(review_comment="另一份意见"),
            identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
            trace_id="trace-changed-draft",
        )

    assert wrong_user.value.code == ToolErrorCode.PERMISSION_DENIED.value
    assert changed_draft.value.code == ToolErrorCode.BUSINESS_CONFLICT.value
    assert task_tool.calls == issue_tool.calls == write_tool.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_conflict_marks_locked_approval_stale() -> None:
    error = ToolError(
        code=ToolErrorCode.BUSINESS_CONFLICT,
        message="task version conflict",
        retryable=False,
        trace_id="trace-java-conflict",
        status_code=409,
    )
    store = _FakeStore(_snapshot())
    service, _, _, _ = _service(
        store,
        write_result=ToolResult(success=False, error=error),
    )

    with pytest.raises(ApprovalConfirmationError) as conflict:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
            trace_id="trace-conflict",
        )

    assert conflict.value.code == ToolErrorCode.BUSINESS_CONFLICT.value
    assert store.snapshot is not None
    assert store.snapshot.status is ApprovalStatus.STALE
    assert store.operation_logs[0].after_summary.failure is not None
    assert store.operation_logs[0].after_summary.failure.code == "BUSINESS_CONFLICT"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_conflict_write_failure_marks_locked_approval_failed() -> None:
    error = ToolError(
        code=ToolErrorCode.UPSTREAM_UNAVAILABLE,
        message="business service is unavailable",
        retryable=True,
        trace_id="trace-java-unavailable",
        status_code=502,
    )
    store = _FakeStore(_snapshot())
    service, _, _, _ = _service(
        store,
        write_result=ToolResult(success=False, error=error),
    )

    with pytest.raises(ApprovalConfirmationError) as unavailable:
        await service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
            trace_id="trace-write-unavailable",
        )

    assert unavailable.value.code == ToolErrorCode.UPSTREAM_UNAVAILABLE.value
    assert store.snapshot is not None
    assert store.snapshot.status is ApprovalStatus.FAILED
    assert store.operation_logs[0].after_summary.failure is not None
    assert store.operation_logs[0].after_summary.failure.retryable is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_confirmation_allows_only_one_write_execution() -> None:
    store = _FakeStore(_snapshot())
    service, _, _, write_tool = _service(store)
    identity = BusinessIdentity(user_id="reviewer-001", role="REVIEWER")

    results = await asyncio.gather(
        service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=identity,
            trace_id="trace-concurrent-1",
        ),
        service.confirm_and_execute(
            approval_id="approval-confirm-003",
            draft=_draft(),
            identity=identity,
            trace_id="trace-concurrent-2",
        ),
        return_exceptions=True,
    )

    assert len(write_tool.calls) == 1
    assert all(
        not isinstance(result, Exception)
        or (
            isinstance(result, ApprovalConfirmationError)
            and result.code == "APPROVAL_EXECUTION_IN_PROGRESS"
        )
        for result in results
    )
    assert any(not isinstance(result, Exception) for result in results)
