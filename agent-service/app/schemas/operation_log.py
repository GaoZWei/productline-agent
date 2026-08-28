"""人工确认写操作的受控审计摘要和详情接口契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ApprovalStatus, OperationType
from app.schemas.approval import Conclusion, ReworkType
from app.schemas.tools import BusinessIdentifier, TaskIdentifier
from app.schemas.workflow import StableCode
from app.schemas.write_tools import ApprovalIdentifier, JavaTraceIdentifier

OperationLogIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
OperationDiffValue = str | bool | tuple[str, ...] | None

# 日志Schema
class OperationLogSchema(BaseModel):
    """日志契约禁止额外字段并保持创建后不可变。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


# 操作前摘要 要回答 真正交给写Tool的内容是什么？
class OperationBeforeSummary(OperationLogSchema):
    """写入前由Approval授权的最小业务与草稿摘要。"""

    task_id: TaskIdentifier
    issue_id: BusinessIdentifier
    task_version: Annotated[int, Field(ge=0)]
    conclusion: Annotated[Conclusion, Field(strict=False)]
    problem_summary: Annotated[str, Field(min_length=1, max_length=2048)]
    review_comment: Annotated[str, Field(min_length=1, max_length=1000)]
    rework_required: bool
    rework_type: Annotated[ReworkType, Field(strict=False)] | None
    specification_sources: tuple[str, ...]

    @field_validator("specification_sources", mode="before")
    @classmethod
    def normalize_sources(cls, value: object) -> object:
        """把数据库JSON数组恢复为不可变来源身份序列。"""

        return tuple(value) if isinstance(value, list) else value


class OperationFieldChange(OperationLogSchema):
    """用户相对模型原始草稿修改的一个受控字段。"""

    field_path: Annotated[str, Field(min_length=1, max_length=128)]
    before: OperationDiffValue
    after: OperationDiffValue

    @field_validator("before", "after", mode="before")
    @classmethod
    def normalize_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

# 只需要机器可以判断的信息
class OperationFailureSummary(OperationLogSchema):
    """失败日志只保存机器字段; 不复制上游内部错误正文。"""

    code: StableCode
    status_code: Annotated[int, Field(ge=400, le=599)]
    retryable: bool


class ReviewOperationResultSummary(OperationLogSchema):
    """Java复核写入成功后的业务结果摘要。"""

    operation_type: Literal[OperationType.SUBMIT_REVIEW]
    task_id: TaskIdentifier
    issue_id: BusinessIdentifier
    review_id: BusinessIdentifier
    status: Annotated[Conclusion, Field(strict=False)]
    review_comment: Annotated[str, Field(min_length=1, max_length=1000)]
    task_version: Annotated[int, Field(ge=0)]


class ReworkOperationResultSummary(OperationLogSchema):
    """Java返工创建成功后的业务结果摘要。"""

    operation_type: Literal[OperationType.CREATE_REWORK]
    task_id: TaskIdentifier
    source_issue_id: BusinessIdentifier
    rework_task_id: BusinessIdentifier
    rework_type: Annotated[ReworkType, Field(strict=False)]
    status: Literal["PENDING"]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    task_version: Annotated[int, Field(ge=0)]


OperationResultSummary = ReviewOperationResultSummary | ReworkOperationResultSummary

# 操作后摘要如何区分成功和失败的
class OperationAfterSummary(OperationLogSchema):
    """把成功业务结果与失败机器摘要收敛为互斥结构。"""
    # 三者是互斥的
    outcome: Annotated[ApprovalStatus, Field(strict=False)]
    result: OperationResultSummary | None
    failure: OperationFailureSummary | None
    # 互斥校验位置
    @model_validator(mode="after")
    def validate_outcome_payload(self) -> Self:
        success = self.outcome is ApprovalStatus.SUCCEEDED
        if success != (self.result is not None):
            raise ValueError("successful operation log must contain exactly one result")
        if success == (self.failure is not None):
            raise ValueError("failed operation log must contain exactly one failure")
        if self.outcome not in {
            ApprovalStatus.SUCCEEDED,
            ApprovalStatus.FAILED,
            ApprovalStatus.STALE,
        }:
            raise ValueError("operation log outcome must be terminal after write execution")
        return self


class OperationLogDetail(OperationLogSchema):
    """按Approval查询的一次人工授权业务操作详情。"""

    operation_log_id: OperationLogIdentifier
    approval_id: ApprovalIdentifier
    operation_type: Annotated[OperationType, Field(strict=False)]
    target_id: TaskIdentifier
    target_version: Annotated[int, Field(ge=0)]
    confirmed_by_user_id: Annotated[str, Field(min_length=1, max_length=128)]
    before_summary: OperationBeforeSummary
    after_summary: OperationAfterSummary
    user_modification_diff: tuple[OperationFieldChange, ...]
    java_trace_id: JavaTraceIdentifier | None
    created_at: datetime

    @field_validator("user_modification_diff", mode="before")
    @classmethod
    def normalize_diff(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value
