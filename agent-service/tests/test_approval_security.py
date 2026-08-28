"""M6.8人工确认写回的十条安全边界验收测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode
from app.models import ApprovalStatus, OperationType, PendingToolName
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.operation_log import OperationLogDetail
from app.schemas.tools import QualityIssueList, TaskDetail
from app.services.approval_confirmation import (
    ApprovalConfirmationError,
    ApprovalConfirmationExecution,
    ApprovalConfirmationService,
    ApprovalConfirmationSnapshot,
)
from app.services.approval_execution_store import ApprovalExecutionSnapshot
from app.settings import Settings
from app.tools import ToolContext, ToolResult, create_write_tool_registry

_NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
_IDENTITY = BusinessIdentity(user_id="reviewer-001", role="REVIEWER")


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
    created_at: datetime = _NOW - timedelta(minutes=1),
    original_draft: ReviewDraft | None = None,
) -> ApprovalConfirmationSnapshot:
    draft = original_draft or _draft()
    confirmed_by = (
        "reviewer-001"
        if status
        in {
            ApprovalStatus.CONFIRMED,
            ApprovalStatus.EXECUTING,
            ApprovalStatus.SUCCEEDED,
        }
        else None
    )
    return ApprovalConfirmationSnapshot(
        approval_id="approval-security-003",
        status=status,
        pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
        operation_type=OperationType.SUBMIT_REVIEW,
        target_id="TASK-003",
        target_version=7,
        confirmed_by_user_id=confirmed_by,
        created_at=created_at,
        original_draft=draft,
        draft=draft,
        execution_result=None,
    )


class _SecurityStore:
    """同时模拟确认事务和写Tool读取的同一份Approval记录。"""

    def __init__(self, snapshot: ApprovalConfirmationSnapshot) -> None:
        self.snapshot = snapshot
        self.operation_logs: list[OperationLogDetail] = []
        self._lock = asyncio.Lock()

    async def get_snapshot(
        self,
        approval_id: str,
    ) -> ApprovalConfirmationSnapshot | None:
        assert approval_id == self.snapshot.approval_id
        return self.snapshot

    async def confirm_waiting(
        self,
        approval_id: str,
        *,
        draft: ReviewDraft,
        confirmed_by_user_id: str,
        confirmed_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        async with self._lock:
            if (
                approval_id != self.snapshot.approval_id
                or self.snapshot.status is not ApprovalStatus.WAITING_CONFIRMATION
            ):
                return None
            self.snapshot = replace(
                self.snapshot,
                status=ApprovalStatus.CONFIRMED,
                draft=draft,
                confirmed_by_user_id=confirmed_by_user_id,
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
            if (
                approval_id != self.snapshot.approval_id
                or self.snapshot.status is not expected_status
            ):
                return None
            self.snapshot = replace(self.snapshot, status=target_status)
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
            if (
                approval_id != self.snapshot.approval_id
                or self.snapshot.status is not ApprovalStatus.EXECUTING
            ):
                return None
            self.operation_logs.append(detail)
            self.snapshot = replace(self.snapshot, status=target_status)
            return self.snapshot

    async def get_execution_snapshot(
        self,
        approval_id: str,
    ) -> ApprovalExecutionSnapshot | None:
        if approval_id != self.snapshot.approval_id:
            return None
        return ApprovalExecutionSnapshot(
            approval_id=self.snapshot.approval_id,
            status=self.snapshot.status,
            pending_tool_name=self.snapshot.pending_tool_name,
            target_id=self.snapshot.target_id,
            target_version=self.snapshot.target_version,
            confirmed_by_user_id=self.snapshot.confirmed_by_user_id,
            draft=self.snapshot.draft,
        )

    async def save_execution_result(
        self,
        approval_id: str,
        *,
        result: dict[str, Any],
    ) -> bool:
        async with self._lock:
            if (
                approval_id != self.snapshot.approval_id
                or self.snapshot.status is not ApprovalStatus.EXECUTING
            ):
                return False
            self.snapshot = replace(self.snapshot, execution_result=result)
            return True


class _FakeTool:
    def __init__(self, result: ToolResult[Any]) -> None:
        self.result = result

    async def execute(
        self,
        raw_input: Mapping[str, object],
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> ToolResult[Any]:
        return self.result


class _FakeRegistry:
    def __init__(self, task: TaskDetail, issues: QualityIssueList) -> None:
        self.tools = {
            "get_task_detail": _FakeTool(ToolResult(success=True, data=task)),
            "get_quality_issues": _FakeTool(ToolResult(success=True, data=issues)),
        }

    def get(self, name: str) -> _FakeTool:
        return self.tools[name]


class _SecurityHarness:
    def __init__(
        self,
        *,
        snapshot: ApprovalConfirmationSnapshot | None = None,
        java_status: int = 200,
        task_version: int = 7,
    ) -> None:
        self.store = _SecurityStore(snapshot or _snapshot())
        self.java_status = java_status
        self.java_requests: list[httpx.Request] = []
        self.client = BusinessHttpClient(
            Settings(
                environment="test",
                database_url="postgresql://agent:agent@localhost:5432/agent",
                business_service_url=AnyHttpUrl("http://business.test"),
            ),
            transport=httpx.MockTransport(self._handle_java),
        )
        task = TaskDetail.model_validate(
            {
                "taskId": "TASK-003",
                "orderId": "ORDER-003",
                "status": "COMPLETED",
                "version": task_version,
            }
        )
        issues = QualityIssueList.model_validate(
            {
                "taskId": "TASK-003",
                "issues": [
                    {
                        "issueId": "ISSUE-001",
                        "taskId": "TASK-003",
                        "issueType": "COORDINATE_SYSTEM",
                        "status": "OPEN",
                        "description": "成果坐标参考系与任务要求不一致",
                    }
                ],
            }
        )
        self.write_tools = create_write_tool_registry(self.client, self.store)
        self.service = ApprovalConfirmationService(
            self.store,
            _FakeRegistry(task, issues),
            self.write_tools,
            approval_ttl_seconds=900,
            now=lambda: _NOW,
        )

    def _handle_java(self, request: httpx.Request) -> httpx.Response:
        self.java_requests.append(request)
        if self.java_status != 200:
            code = (
                "BUSINESS_CONFLICT"
                if self.java_status == 409
                else "INTERNAL_SERVER_ERROR"
            )
            return httpx.Response(
                self.java_status,
                json={
                    "success": False,
                    "code": code,
                    "message": "simulated Java write failure",
                    "data": None,
                    "trace_id": f"trace-java-{self.java_status}",
                    "retryable": False,
                },
                headers={"X-Trace-Id": f"trace-java-{self.java_status}"},
            )
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": "SUCCESS",
                "message": "ok",
                "data": {
                    "review": {
                        "reviewId": "REVIEW-SECURITY-003",
                        "issueId": body["issueId"],
                        "status": body["status"],
                        "reviewComment": body["reviewComment"],
                    },
                    "taskVersion": body["expectedVersion"] + 1,
                },
                "trace_id": "trace-java-security",
                "retryable": False,
            },
            headers={"X-Trace-Id": "trace-java-security"},
        )

    async def confirm(
        self,
        *,
        draft: ReviewDraft | None = None,
        identity: BusinessIdentity = _IDENTITY,
        trace_id: str = "trace-security-confirm",
    ) -> ApprovalConfirmationExecution:
        return await self.service.confirm_and_execute(
            approval_id=self.store.snapshot.approval_id,
            draft=draft or _draft(),
            identity=identity,
            trace_id=trace_id,
        )

    async def aclose(self) -> None:
        await self.client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t661_unconfirmed_approval_cannot_call_java_write() -> None:
    harness = _SecurityHarness()
    tool = harness.write_tools.get("write_review_result")
    try:
        result = await tool.execute(
            {
                "approval_id": "approval-security-003",
                "idempotency_key": "approval:security:003",
            },
            ToolContext(
                identity=_IDENTITY,
                permissions=frozenset({"REVIEW_WRITE"}),
                trace_id="trace-security-bypass",
                run_id="run-security-bypass",
            ),
        )
    finally:
        await harness.aclose()

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.BUSINESS_CONFLICT
    assert harness.java_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t662_normal_confirmation_writes_once_and_succeeds() -> None:
    harness = _SecurityHarness()
    try:
        execution = await harness.confirm()
    finally:
        await harness.aclose()

    assert execution.status is ApprovalStatus.SUCCEEDED
    assert harness.store.snapshot.status is ApprovalStatus.SUCCEEDED
    assert len(harness.java_requests) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t663_user_modification_is_the_only_content_sent_to_java() -> None:
    original = _draft(review_comment="模型生成的原始意见")
    modified = _draft(review_comment="用户修改后的最终意见")
    harness = _SecurityHarness(snapshot=_snapshot(original_draft=original))
    try:
        await harness.confirm(draft=modified)
    finally:
        await harness.aclose()

    body = json.loads(harness.java_requests[0].content)
    assert body["reviewComment"] == "用户修改后的最终意见"
    assert harness.store.snapshot.draft.review_comment == "用户修改后的最终意见"
    assert harness.store.snapshot.original_draft.review_comment == "模型生成的原始意见"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t664_concurrent_duplicate_confirmation_writes_only_once() -> None:
    harness = _SecurityHarness()
    try:
        results = await asyncio.gather(
            harness.confirm(trace_id="trace-security-first"),
            harness.confirm(trace_id="trace-security-duplicate"),
            return_exceptions=True,
        )
    finally:
        await harness.aclose()

    assert len(harness.java_requests) == 1
    assert harness.store.snapshot.status is ApprovalStatus.SUCCEEDED
    assert any(not isinstance(result, Exception) for result in results)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t665_cancelled_approval_keeps_data_unchanged() -> None:
    harness = _SecurityHarness(snapshot=_snapshot(status=ApprovalStatus.CANCELLED))
    try:
        with pytest.raises(ApprovalConfirmationError) as cancelled:
            await harness.confirm()
    finally:
        await harness.aclose()

    assert cancelled.value.code == "APPROVAL_NOT_CONFIRMABLE"
    assert harness.store.snapshot.status is ApprovalStatus.CANCELLED
    assert harness.java_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t666_expired_approval_is_rejected_before_java_write() -> None:
    harness = _SecurityHarness(
        snapshot=_snapshot(created_at=_NOW - timedelta(minutes=16))
    )
    try:
        with pytest.raises(ApprovalConfirmationError) as expired:
            await harness.confirm()
    finally:
        await harness.aclose()

    assert expired.value.code == "APPROVAL_EXPIRED"
    assert harness.store.snapshot.status is ApprovalStatus.EXPIRED
    assert harness.java_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t667_changed_business_state_marks_stale_without_writing() -> None:
    harness = _SecurityHarness(task_version=8)
    try:
        with pytest.raises(ApprovalConfirmationError) as stale:
            await harness.confirm()
    finally:
        await harness.aclose()

    assert stale.value.code == "APPROVAL_STALE"
    assert harness.store.snapshot.status is ApprovalStatus.STALE
    assert harness.java_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t668_non_reviewer_is_denied_without_writing() -> None:
    harness = _SecurityHarness()
    try:
        with pytest.raises(ApprovalConfirmationError) as denied:
            await harness.confirm(
                identity=BusinessIdentity(user_id="operator-001", role="OPERATOR")
            )
    finally:
        await harness.aclose()

    assert denied.value.code == ToolErrorCode.PERMISSION_DENIED.value
    assert denied.value.status_code == 403
    assert harness.store.snapshot.status is ApprovalStatus.WAITING_CONFIRMATION
    assert harness.java_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t669_java_409_returns_conflict_and_marks_stale() -> None:
    harness = _SecurityHarness(java_status=409)
    try:
        with pytest.raises(ApprovalConfirmationError) as conflict:
            await harness.confirm()
    finally:
        await harness.aclose()

    assert conflict.value.code == ToolErrorCode.BUSINESS_CONFLICT.value
    assert conflict.value.status_code == 409
    assert harness.store.snapshot.status is ApprovalStatus.STALE
    assert len(harness.java_requests) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_t670_java_500_marks_approval_failed_without_retry() -> None:
    harness = _SecurityHarness(java_status=500)
    try:
        with pytest.raises(ApprovalConfirmationError) as unavailable:
            await harness.confirm()
    finally:
        await harness.aclose()

    assert unavailable.value.code == ToolErrorCode.UPSTREAM_UNAVAILABLE.value
    assert unavailable.value.status_code == 500
    assert harness.store.snapshot.status is ApprovalStatus.FAILED
    assert len(harness.java_requests) == 1
