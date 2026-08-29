"""人工确认后刷新Java事实、抢占执行锁并调用唯一写Tool。"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, Protocol

from pydantic import JsonValue, ValidationError

from app.database import Database
from app.errors import ToolErrorCode
from app.eventing import RunEventSink
from app.models import ApprovalRecord, ApprovalStatus, OperationType, PendingToolName
from app.repositories import ApprovalRecordRepository, OperationLogRepository
from app.schemas import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.events import RunEventType
from app.schemas.operation_log import OperationLogDetail
from app.schemas.tools import QualityIssue, QualityIssueList, TaskDetail
from app.schemas.write_tools import (
    CreateReworkTaskOutput,
    WriteReviewResultOutput,
)
from app.services.approval_lifecycle import (
    ApprovalLifecycleError,
    ApprovalLifecycleService,
)
from app.services.operation_log import (
    OperationFailure,
    build_operation_log_detail,
    record_from_detail,
)
from app.tools import ToolContext, ToolResult

type ApprovalWriteResult = WriteReviewResultOutput | CreateReworkTaskOutput

# 从数据库Approval提取出来的最小执行快照
@dataclass(frozen=True, slots=True)
class ApprovalConfirmationSnapshot:
    """确认执行链需要的最小不可变Approval快照。"""

    approval_id: str
    status: ApprovalStatus
    pending_tool_name: PendingToolName
    operation_type: OperationType
    target_id: str
    target_version: int
    confirmed_by_user_id: str | None
    created_at: datetime
    original_draft: ReviewDraft
    draft: ReviewDraft
    execution_result: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ApprovalConfirmationExecution:
    """确认执行完成后返回终态和Java业务结果。"""

    approval_id: str
    status: ApprovalStatus
    result: ApprovalWriteResult


class ApprovalConfirmationStore(Protocol):
    """隔离确认服务与数据库事务和比较更新细节。"""

    def get_snapshot(
        self,
        approval_id: str,
    ) -> Awaitable[ApprovalConfirmationSnapshot | None]: ...

    def confirm_waiting(
        self,
        approval_id: str,
        *,
        draft: ReviewDraft,
        confirmed_by_user_id: str,
        confirmed_at: datetime,
    ) -> Awaitable[ApprovalConfirmationSnapshot | None]: ...

    def transition(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        target_status: ApprovalStatus,
        updated_at: datetime,
    ) -> Awaitable[ApprovalConfirmationSnapshot | None]: ...

    def finish_with_operation_log(
        self,
        approval_id: str,
        *,
        target_status: ApprovalStatus,
        detail: OperationLogDetail,
        updated_at: datetime,
    ) -> Awaitable[ApprovalConfirmationSnapshot | None]: ...


class ConfirmationTool(Protocol):
    """确认执行链只依赖Tool的统一执行入口。"""

    def execute(
        self,
        raw_input: Mapping[str, object],
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> Awaitable[ToolResult[Any]]: ...


class ConfirmationToolRegistry(Protocol):
    """按稳定名称提供确认阶段所需的只读或写Tool。"""

    def get(self, name: str) -> ConfirmationTool: ...


class ApprovalConfirmationError(Exception):
    """确认、重校验或写入无法安全完成。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        retryable: bool = False,
        approval_status: ApprovalStatus | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.approval_status = approval_status
        super().__init__(message)


class DatabaseApprovalConfirmationStore:
    """用短事务保存确认事实并对每次状态变化执行数据库CAS。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_snapshot(
        self,
        approval_id: str,
    ) -> ApprovalConfirmationSnapshot | None:
        async with self._database.session() as session:
            approval = await ApprovalRecordRepository(session).get(approval_id)
            return None if approval is None else _snapshot_from_record(approval)

    async def confirm_waiting(
        self,
        approval_id: str,
        *,
        draft: ReviewDraft,
        confirmed_by_user_id: str,
        confirmed_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        try:
            async with self._database.session() as session, session.begin():
                lifecycle = ApprovalLifecycleService(
                    ApprovalRecordRepository(session),
                    now=lambda: confirmed_at,
                )
                # 保存数据库记录中的用户修改草稿
                await lifecycle.save_user_modification(
                    approval_id,
                    modified_draft=draft,
                )
                # 确认Approval
                confirmed = await lifecycle.confirm(
                    approval_id,
                    confirmed_by_user_id=confirmed_by_user_id,
                )
                return _snapshot_from_record(confirmed)
        except ApprovalLifecycleError:
            # 修改草稿和确认必须同成同败; 异常离开事务后再转换为并发冲突。
            return None

    async def transition(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        target_status: ApprovalStatus,
        updated_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        async with self._database.session() as session, session.begin():
            transitioned = await ApprovalRecordRepository(session).transition_status(
                approval_id,
                expected_status=expected_status,
                target_status=target_status,
                changes={"updated_at": updated_at},
            )
            return None if transitioned is None else _snapshot_from_record(transitioned)

    async def finish_with_operation_log(
        self,
        approval_id: str,
        *,
        target_status: ApprovalStatus,
        detail: OperationLogDetail,
        updated_at: datetime,
    ) -> ApprovalConfirmationSnapshot | None:
        if detail.approval_id != approval_id or detail.after_summary.outcome is not target_status:
            raise ValueError("operation log must match the terminal approval transition")
        async with self._database.session() as session, session.begin():
            transitioned = await ApprovalRecordRepository(session).transition_status(
                approval_id,
                expected_status=ApprovalStatus.EXECUTING,
                target_status=target_status,
                changes={"updated_at": updated_at},
            )
            if transitioned is None:
                return None
            await OperationLogRepository(session).create(record_from_detail(detail))
            return _snapshot_from_record(transitioned)


class ApprovalConfirmationService:
    """把人工确认、最新事实校验和唯一写执行编排为确定性流程。"""

    def __init__(
        self,
        store: ApprovalConfirmationStore,
        read_tools: ConfirmationToolRegistry,
        write_tools: ConfirmationToolRegistry,
        *,
        approval_ttl_seconds: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        event_sink: RunEventSink | None = None,
    ) -> None:
        if approval_ttl_seconds < 60 or approval_ttl_seconds > 86400:
            raise ValueError("approval_ttl_seconds must be between 60 and 86400")
        self._store = store
        self._read_tools = read_tools
        self._write_tools = write_tools
        self._ttl = timedelta(seconds=approval_ttl_seconds)
        self._now = now
        self._event_sink = event_sink
    # 主流程
    async def confirm_and_execute(
        self,
        *,
        approval_id: str,
        draft: ReviewDraft,
        identity: BusinessIdentity,
        trace_id: str,
    ) -> ApprovalConfirmationExecution:
        """保存用户确认并在全部重新校验通过后执行唯一写Tool。"""
        # 权限检查
        permissions = self._permissions(identity)
        snapshot = await self._require_snapshot(approval_id)
        run_id = _confirmation_run_id(approval_id)
        # 根据当前状态决定如何处理
        if snapshot.status is ApprovalStatus.SUCCEEDED:
            # 校验确认人和草稿,直接返回历史 execution_result
            execution = self._completed_replay(snapshot, draft=draft, identity=identity)
            await self._publish_event(
                RunEventType.WRITEBACK_COMPLETED,
                run_id=run_id,
                data={
                    "approval_id": snapshot.approval_id,
                    "status": snapshot.status.value,
                    "replayed": True,
                },
            )
            return execution
        if snapshot.status is ApprovalStatus.WAITING_CONFIRMATION:
            # 检查过期、保存最终草稿、保存确认人、改为Confirmed
            await self._expire_if_needed(snapshot)
            confirmed = await self._store.confirm_waiting(
                approval_id,
                draft=draft,
                confirmed_by_user_id=identity.user_id,
                confirmed_at=self._timestamp(),
            )
            if confirmed is None:
                self._raise_current_conflict(await self._require_snapshot(approval_id))
            snapshot = confirmed
        elif snapshot.status is ApprovalStatus.CONFIRMED:
            # 校验是不是同一个确认人、同一份草稿; 继续重新校验
            self._require_same_confirmation(snapshot, draft=draft, identity=identity)
        else:
            # 返回 APPROVAL_EXECUTION_IN_PROGRESS
            self._raise_current_conflict(snapshot)

        self._require_same_confirmation(snapshot, draft=draft, identity=identity)
        await self._expire_if_needed(snapshot)
        context = ToolContext(
            identity=identity,
            permissions=permissions,
            trace_id=trace_id,
            run_id=_confirmation_run_id(approval_id),
        )
        task = await self._read_task(snapshot.target_id, context)
        issues = await self._read_issues(snapshot.target_id, context)
        stale_reason = _stale_reason(snapshot, task=task, issues=issues)
        if stale_reason is not None:
            await self._mark_stale(snapshot)
            raise ApprovalConfirmationError(
                code="APPROVAL_STALE",
                message=stale_reason,
                status_code=409,
                approval_status=ApprovalStatus.STALE,
            )
        await self._expire_if_needed(snapshot)
        # 执行锁
        locked = await self._store.transition(
            snapshot.approval_id,
            expected_status=ApprovalStatus.CONFIRMED,
            target_status=ApprovalStatus.EXECUTING,
            updated_at=self._timestamp(),
        )
        if locked is None:
            raise ApprovalConfirmationError(
                code="APPROVAL_EXECUTION_IN_PROGRESS",
                message="approval execution was already claimed",
                status_code=409,
                approval_status=(await self._require_snapshot(approval_id)).status,
            )

        await self._publish_event(
            RunEventType.WRITEBACK_STARTED,
            run_id=run_id,
            data={
                "approval_id": locked.approval_id,
                "tool_name": locked.pending_tool_name.value,
                "target_id": locked.target_id,
            },
        )
        write_result = await self._execute_write(locked, context)
        # 处理写入失败
        if not write_result.success:
            assert write_result.error is not None
            target_status = (
                ApprovalStatus.STALE
                if write_result.error.code is ToolErrorCode.BUSINESS_CONFLICT
                and write_result.error.status_code == 409
                else ApprovalStatus.FAILED
            )
            failure_status_code = _error_status_code(write_result.error.status_code)
            # 保存失败日志
            await self._finish_locked(
                locked,
                target_status,
                result=None,
                failure=OperationFailure(
                    code=write_result.error.code.value,
                    status_code=failure_status_code,
                    retryable=write_result.error.retryable,
                ),
            )
            await self._publish_event(
                RunEventType.WRITEBACK_COMPLETED,
                run_id=run_id,
                data={
                    "approval_id": locked.approval_id,
                    "status": target_status.value,
                    "error_code": write_result.error.code.value,
                    "replayed": False,
                },
            )
            raise ApprovalConfirmationError(
                code=write_result.error.code.value,
                message=write_result.error.message,
                status_code=failure_status_code,
                retryable=write_result.error.retryable,
                approval_status=target_status,
            )

        output = _parse_write_result(locked.pending_tool_name, write_result.data)
        # 解析成严格写结果
        await self._finish_locked(
            locked,
            ApprovalStatus.SUCCEEDED,
            result=output,
            failure=None,
        )
        await self._publish_event(
            RunEventType.WRITEBACK_COMPLETED,
            run_id=run_id,
            data={
                "approval_id": locked.approval_id,
                "status": ApprovalStatus.SUCCEEDED.value,
                "replayed": False,
            },
        )
        return ApprovalConfirmationExecution(
            approval_id=locked.approval_id,
            status=ApprovalStatus.SUCCEEDED,
            result=output,
        )

    async def _publish_event(
        self,
        event_type: RunEventType,
        *,
        run_id: str,
        data: dict[str, JsonValue],
    ) -> None:
        """只发布确认阶段状态摘要, 不暴露草稿、幂等键或Java写结果。"""

        if self._event_sink is None:
            return
        await self._event_sink.publish(event_type, run_id=run_id, data=data)
    # 权限检查
    def _permissions(self, identity: BusinessIdentity) -> frozenset[str]:
        if identity.role != "REVIEWER":
            raise ApprovalConfirmationError(
                code=ToolErrorCode.PERMISSION_DENIED.value,
                message="reviewer permission is required",
                status_code=403,
            )
        return frozenset(
            {
                "TASK_READ",
                "QUALITY_ISSUE_READ",
                "REVIEW_WRITE",
                "REWORK_WRITE",
            }
        )
    # 读取Approval快照
    async def _require_snapshot(self, approval_id: str) -> ApprovalConfirmationSnapshot:
        snapshot = await self._store.get_snapshot(approval_id)
        # 检查Approval是否存在
        if snapshot is None:
            raise ApprovalConfirmationError(
                code=ToolErrorCode.RESOURCE_NOT_FOUND.value,
                message="approval was not found",
                status_code=404,
            )
        return snapshot
    # 校验确认人和草稿是否匹配
    def _require_same_confirmation(
        self,
        snapshot: ApprovalConfirmationSnapshot,
        *,
        draft: ReviewDraft,
        identity: BusinessIdentity,
    ) -> None:
        if snapshot.confirmed_by_user_id != identity.user_id:
            raise ApprovalConfirmationError(
                code=ToolErrorCode.PERMISSION_DENIED.value,
                message="approval was confirmed by another user",
                status_code=403,
                approval_status=snapshot.status,
            )
        if snapshot.draft != draft:
            raise ApprovalConfirmationError(
                code=ToolErrorCode.BUSINESS_CONFLICT.value,
                message="confirmed approval draft does not match this request",
                status_code=409,
                approval_status=snapshot.status,
            )
    # 检查Approval是否过期
    async def _expire_if_needed(self, snapshot: ApprovalConfirmationSnapshot) -> None:
        created_at = snapshot.created_at
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ApprovalConfirmationError(
                code=ToolErrorCode.RESPONSE_VALIDATION_ERROR.value,
                message="approval timestamp is invalid",
                status_code=500,
                approval_status=snapshot.status,
            )
        if created_at + self._ttl > self._timestamp():
            return
        expired = await self._store.transition(
            snapshot.approval_id,
            expected_status=snapshot.status,
            target_status=ApprovalStatus.EXPIRED,
            updated_at=self._timestamp(),
        )
        if expired is None:
            self._raise_current_conflict(await self._require_snapshot(snapshot.approval_id))
        raise ApprovalConfirmationError(
            code="APPROVAL_EXPIRED",
            message="approval confirmation window has expired",
            status_code=410,
            approval_status=ApprovalStatus.EXPIRED,
        )
    # 重新查询Java任务详情
    async def _read_task(self, task_id: str, context: ToolContext) -> TaskDetail:
        result = await self._read_tools.get("get_task_detail").execute(
            {"task_id": task_id},
            context,
            force_refresh=True,
        )
        return _require_tool_data(result, TaskDetail)

    async def _read_issues(self, task_id: str, context: ToolContext) -> QualityIssueList:
        result = await self._read_tools.get("get_quality_issues").execute(
            {"task_id": task_id},
            context,
            force_refresh=True,
        )
        return _require_tool_data(result, QualityIssueList)

    async def _mark_stale(self, snapshot: ApprovalConfirmationSnapshot) -> None:
        stale = await self._store.transition(
            snapshot.approval_id,
            expected_status=ApprovalStatus.CONFIRMED,
            target_status=ApprovalStatus.STALE,
            updated_at=self._timestamp(),
        )
        if stale is None:
            self._raise_current_conflict(await self._require_snapshot(snapshot.approval_id))

    async def _execute_write(
        self,
        snapshot: ApprovalConfirmationSnapshot,
        context: ToolContext,
    ) -> ToolResult[Any]:
        return await self._write_tools.get(snapshot.pending_tool_name.value).execute(
            {
                "approval_id": snapshot.approval_id,
                "idempotency_key": _idempotency_key(snapshot),
            },
            context,
        )
    # 拿到原始草稿、用户草稿和写入结果后, 构造操作日志详情并完成数据库终态保存。
    async def _finish_locked(
        self,
        snapshot: ApprovalConfirmationSnapshot,
        target_status: ApprovalStatus,
        *,
        result: ApprovalWriteResult | None,
        failure: OperationFailure | None,
    ) -> None:
        assert snapshot.confirmed_by_user_id is not None
        timestamp = self._timestamp()
        detail = build_operation_log_detail(
            approval_id=snapshot.approval_id,
            operation_type=snapshot.operation_type,
            target_id=snapshot.target_id,
            target_version=snapshot.target_version,
            confirmed_by_user_id=snapshot.confirmed_by_user_id,
            original_draft=snapshot.original_draft,
            effective_draft=snapshot.draft,
            outcome=target_status,
            result=result,
            failure=failure,
            created_at=timestamp,
        )
        finished = await self._store.finish_with_operation_log(
            snapshot.approval_id,
            target_status=target_status,
            detail=detail,
            updated_at=timestamp,
        )
        if finished is None:
            raise ApprovalConfirmationError(
                code=ToolErrorCode.BUSINESS_CONFLICT.value,
                message="approval terminal status could not be saved",
                status_code=409,
                approval_status=(await self._require_snapshot(snapshot.approval_id)).status,
            )

    def _completed_replay(
        self,
        snapshot: ApprovalConfirmationSnapshot,
        *,
        draft: ReviewDraft,
        identity: BusinessIdentity,
    ) -> ApprovalConfirmationExecution:
        self._require_same_confirmation(snapshot, draft=draft, identity=identity)
        output = _parse_write_result(
            snapshot.pending_tool_name,
            snapshot.execution_result,
        )
        return ApprovalConfirmationExecution(
            approval_id=snapshot.approval_id,
            status=ApprovalStatus.SUCCEEDED,
            result=output,
        )

    def _raise_current_conflict(
        self,
        snapshot: ApprovalConfirmationSnapshot,
    ) -> NoReturn:
        code = (
            "APPROVAL_EXECUTION_IN_PROGRESS"
            if snapshot.status is ApprovalStatus.EXECUTING
            else "APPROVAL_NOT_CONFIRMABLE"
        )
        raise ApprovalConfirmationError(
            code=code,
            message=f"approval cannot be confirmed from {snapshot.status.value}",
            status_code=409,
            approval_status=snapshot.status,
        )

    def _timestamp(self) -> datetime:
        timestamp = self._now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("confirmation clock must include timezone information")
        return timestamp

# 数据库记录转快照
def _snapshot_from_record(approval: ApprovalRecord) -> ApprovalConfirmationSnapshot:
    """把SQLAlchemy记录转换为不依赖Session的确认快照。"""

    return ApprovalConfirmationSnapshot(
        approval_id=approval.approval_id,
        status=approval.status,
        pending_tool_name=approval.pending_tool_name,
        operation_type=approval.operation_type,
        target_id=approval.target_id,
        target_version=approval.target_version,
        confirmed_by_user_id=approval.confirmed_by_user_id,
        created_at=approval.created_at,
        original_draft=ReviewDraft.model_validate(approval.original_draft),
        # 从数据库记录中提取当前有效草稿。
        draft=ApprovalLifecycleService.effective_review_draft(approval),
        execution_result=approval.execution_result,
    )


def _require_tool_data[DataT](result: ToolResult[Any], model: type[DataT]) -> DataT:
    """把只读Tool失败保持为稳定确认错误并验证成功数据类型。"""

    if not result.success:
        assert result.error is not None
        raise ApprovalConfirmationError(
            code=result.error.code.value,
            message=result.error.message,
            status_code=result.error.status_code or 500,
            retryable=result.error.retryable,
            approval_status=ApprovalStatus.CONFIRMED,
        )
    if not isinstance(result.data, model):
        raise ApprovalConfirmationError(
            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR.value,
            message="confirmation read tool returned unrecognized data",
            status_code=502,
            approval_status=ApprovalStatus.CONFIRMED,
        )
    return result.data

# 以下变化会导致STALE状态
def _stale_reason(
    snapshot: ApprovalConfirmationSnapshot,
    *,
    task: TaskDetail,
    issues: QualityIssueList,
) -> str | None:
    """比较确认快照和最新Java事实并返回第一个失效原因。"""
    # 任务版本是否变化
    if task.version != snapshot.target_version:
        return "task version changed after approval draft generation"
    # 任务不再是COMPLETED状态
    if task.status != "COMPLETED":
        return "task is no longer completed"
    issue = next(
        (
            candidate
            for candidate in issues.issues
            if candidate.issue_id == snapshot.draft.issue_id
            and candidate.task_id == snapshot.target_id
        ),
        None,
    )
    # 质检问题不存在或不属于目标任务
    if issue is None:
        return "quality issue is no longer attached to the target task"
    return _issue_stale_reason(snapshot, issue)


def _issue_stale_reason(
    snapshot: ApprovalConfirmationSnapshot,
    issue: QualityIssue,
) -> str | None:
    # 问题已经关闭
    if issue.status == "CLOSED":
        return "quality issue was closed after approval draft generation"
    # 问题未解决却要审批通过
    if snapshot.draft.conclusion.value == "APPROVED" and issue.status != "RESOLVED":
        return "only a resolved quality issue can be approved"
    # 返工类型与问题类型不一致
    if (
        snapshot.draft.suggested_rework.required
        and issue.issue_type != "COORDINATE_SYSTEM"
    ):
        return "coordinate-system rework no longer matches the quality issue type"
    return None


def _parse_write_result(
    pending_tool_name: PendingToolName,
    value: object,
) -> ApprovalWriteResult:
    """按Approval指定的唯一写Tool恢复严格执行结果。"""

    model: type[WriteReviewResultOutput] | type[CreateReworkTaskOutput] = (
        WriteReviewResultOutput
        if pending_tool_name is PendingToolName.WRITE_REVIEW_RESULT
        else CreateReworkTaskOutput
    )
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise ApprovalConfirmationError(
            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR.value,
            message="approval execution result is invalid",
            status_code=500,
            approval_status=ApprovalStatus.SUCCEEDED,
        ) from error

# 幂等键
def _idempotency_key(snapshot: ApprovalConfirmationSnapshot) -> str:
    """从Approval和唯一写Tool生成稳定且不泄露草稿内容的幂等键。"""

    digest = hashlib.sha256(snapshot.approval_id.encode()).hexdigest()[:32]
    return f"approval:{snapshot.pending_tool_name.value}:{digest}"


def _confirmation_run_id(approval_id: str) -> str:
    """生成安全有界的确认执行ToolContext标识。"""

    return f"approval-confirm-{hashlib.sha256(approval_id.encode()).hexdigest()[:32]}"


def _error_status_code(status_code: int | None) -> int:
    """日志和HTTP错误只接受真实4xx/5xx; 拒绝把异常包装成200。"""

    return status_code if status_code is not None and 400 <= status_code <= 599 else 500
