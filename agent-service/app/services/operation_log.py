"""构建和读取人工确认写操作的受控审计详情。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.database import Database
from app.models import ApprovalStatus, OperationLogRecord, OperationType
from app.repositories import OperationLogRepository
from app.schemas import ReviewDraft
from app.schemas.approval import Conclusion
from app.schemas.business import BusinessIdentity
from app.schemas.operation_log import (
    OperationAfterSummary,
    OperationBeforeSummary,
    OperationFailureSummary,
    OperationFieldChange,
    OperationLogDetail,
    ReviewOperationResultSummary,
    ReworkOperationResultSummary,
)
from app.schemas.write_tools import CreateReworkTaskOutput, WriteReviewResultOutput

type OperationWriteResult = WriteReviewResultOutput | CreateReworkTaskOutput


@dataclass(frozen=True, slots=True)
class OperationFailure:
    """写Tool失败时允许进入日志的机器字段。"""

    code: str
    status_code: int
    retryable: bool


class OperationLogAccessError(Exception):
    """操作日志不存在或当前身份无权读取。"""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

# 权限检查流程：只有确认人才能读取操作日志
class DatabaseOperationLogService:
    """读取Agent日志; 并把原确认人作为当前最小访问边界。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_by_approval(
        self,
        approval_id: str,
        *,
        identity: BusinessIdentity,
    ) -> OperationLogDetail:
        # 当前角色必须是REVIEWER才能读取操作日志
        if identity.role != "REVIEWER":
            raise OperationLogAccessError(
                code="PERMISSION_DENIED",
                message="reviewer permission is required",
                status_code=403,
            )
        async with self._database.session() as session:
            # 查询approval_id对应日志记录
            record = await OperationLogRepository(session).get_by_approval(approval_id)
        # 日志必须存在
        if record is None:
            raise OperationLogAccessError(
                code="RESOURCE_NOT_FOUND",
                message="operation log was not found",
                status_code=404,
            )
        detail = detail_from_record(record)
        # confirmed_by_user_id必须等于当前user_id才能读取操作日志
        if detail.confirmed_by_user_id != identity.user_id:
            raise OperationLogAccessError(
                code="PERMISSION_DENIED",
                message="operation log belongs to another confirmer",
                status_code=403,
            )
        return detail

# Agent侧操作日志：记录的是Agent授权和编排过程
def build_operation_log_detail(
    *,
    approval_id: str,
    operation_type: OperationType,
    target_id: str,
    target_version: int,
    confirmed_by_user_id: str,
    original_draft: ReviewDraft,
    effective_draft: ReviewDraft,
    outcome: ApprovalStatus,
    result: OperationWriteResult | None,
    failure: OperationFailure | None,
    created_at: datetime,
) -> OperationLogDetail:
    """把Approval、最终草稿和写结果转换为不含长篇引用正文的日志。"""

    result_summary = _result_summary(result) if result is not None else None
    failure_summary = (
        OperationFailureSummary(
            code=failure.code,
            status_code=failure.status_code,
            retryable=failure.retryable,
        )
        if failure is not None
        else None
    )
    return OperationLogDetail(
        operation_log_id=_operation_log_id(approval_id),
        approval_id=approval_id,
        operation_type=operation_type,
        target_id=target_id,
        target_version=target_version,
        confirmed_by_user_id=confirmed_by_user_id,
        before_summary=_before_summary(effective_draft, target_version=target_version),
        after_summary=OperationAfterSummary(
            outcome=outcome,
            result=result_summary,
            failure=failure_summary,
        ),
        user_modification_diff=_draft_diff(original_draft, effective_draft),
        java_trace_id=result.java_trace_id if result is not None else None,
        created_at=created_at,
    )

# 日志转换为数据库记录
def record_from_detail(detail: OperationLogDetail) -> OperationLogRecord:
    """把严格详情转换为ORM记录; JSON字段保持受控Schema形状。"""

    return OperationLogRecord(
        operation_log_id=detail.operation_log_id,
        approval_id=detail.approval_id,
        operation_type=detail.operation_type.value,
        outcome=detail.after_summary.outcome.value,
        target_id=detail.target_id,
        target_version=detail.target_version,
        confirmed_by_user_id=detail.confirmed_by_user_id,
        before_summary=detail.before_summary.model_dump(mode="json"),
        after_summary=detail.after_summary.model_dump(mode="json"),
        user_modification_diff=[
            change.model_dump(mode="json") for change in detail.user_modification_diff
        ],
        java_trace_id=detail.java_trace_id,
        created_at=detail.created_at,
    )


def detail_from_record(record: OperationLogRecord) -> OperationLogDetail:
    """读取数据库JSON后重新执行严格响应校验。"""

    return OperationLogDetail.model_validate(
        {
            "operation_log_id": record.operation_log_id,
            "approval_id": record.approval_id,
            "operation_type": record.operation_type,
            "target_id": record.target_id,
            "target_version": record.target_version,
            "confirmed_by_user_id": record.confirmed_by_user_id,
            "before_summary": record.before_summary,
            "after_summary": record.after_summary,
            "user_modification_diff": record.user_modification_diff,
            "java_trace_id": record.java_trace_id,
            "created_at": record.created_at,
        }
    )


def _before_summary(draft: ReviewDraft, *, target_version: int) -> OperationBeforeSummary:
    return OperationBeforeSummary(
        task_id=draft.task_id,
        issue_id=draft.issue_id,
        task_version=target_version,
        conclusion=draft.conclusion,
        problem_summary=draft.problem_summary,
        review_comment=draft.review_comment,
        rework_required=draft.suggested_rework.required,
        rework_type=draft.suggested_rework.type,
        specification_sources=_specification_sources(draft),
    )

# 成功结果摘要计算逻辑
def _result_summary(
    result: OperationWriteResult,
) -> ReviewOperationResultSummary | ReworkOperationResultSummary:
    if isinstance(result, WriteReviewResultOutput):
        # 复核结果摘要
        return ReviewOperationResultSummary(
            operation_type=OperationType.SUBMIT_REVIEW,
            task_id=result.task_id,
            issue_id=result.issue_id,
            review_id=result.review_id,
            status=Conclusion(result.status),
            review_comment=result.review_comment,
            task_version=result.task_version,
        )
        # 返工结果摘要
    return ReworkOperationResultSummary(
        operation_type=OperationType.CREATE_REWORK,
        task_id=result.task_id,
        source_issue_id=result.source_issue_id,
        rework_task_id=result.rework_task_id,
        rework_type=result.rework_type,
        status=result.status,
        reason=result.reason,
        task_version=result.task_version,
    )

# 用户修改差异计算逻辑
def _draft_diff(
    original: ReviewDraft,  # 模型生成的原始草稿
    effective: ReviewDraft,  # 用户最终确认的草稿
) -> tuple[OperationFieldChange, ...]:
    # 把允许比较的字段转换成稳定字典
    original_values = _diff_values(original)
    effective_values = _diff_values(effective)
    return tuple(
        OperationFieldChange(
            field_path=field_path,
            before=original_values[field_path],
            after=effective_values[field_path],
        )
        # 逐字段比较是否有差异
        for field_path in original_values
        if original_values[field_path] != effective_values[field_path]
    )


def _diff_values(draft: ReviewDraft) -> dict[str, str | bool | tuple[str, ...] | None]:
    return {
        "conclusion": draft.conclusion.value,
        "problem_summary": draft.problem_summary,
        "review_comment": draft.review_comment,
        "specification_references": _specification_sources(draft),
        "suggested_rework.required": draft.suggested_rework.required,
        "suggested_rework.type": (
            draft.suggested_rework.type.value
            if draft.suggested_rework.type is not None
            else None
        ),
    }

# 转换为操作前摘要的specification_sources格式
def _specification_sources(draft: ReviewDraft) -> tuple[str, ...]:
    return tuple(
        f"{citation.document_id}@{citation.document_version}#{chunk_id}"
        for citation in draft.specification_references
        for chunk_id in citation.chunk_ids
    )


def _operation_log_id(approval_id: str) -> str:
    digest = hashlib.sha256(approval_id.encode()).hexdigest()[:32]
    return f"operation-log-{digest}"
