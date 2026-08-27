"""人工确认记录及其稳定状态、操作和待执行 Tool 契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.agent_runtime import AgentRun

# 确认状态
class ApprovalStatus(StrEnum):
    """人工确认从草稿到唯一终态的稳定状态集合。"""

    DRAFT = "DRAFT"  # Agent草稿刚保存，还没有正式展示给用户
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"  # 已展示给用户，允许用户修改或确认
    CONFIRMED = "CONFIRMED"  # 用户已经确认，但还没有调用Java写Tool
    EXECUTING = "EXECUTING"  # 正在调用写Tool，等待结果
    SUCCEEDED = "SUCCEEDED"  # Java写操作成功
    FAILED = "FAILED"  # 写Tool调用失败
    CANCELLED = "CANCELLED"  # 用户取消
    EXPIRED = "EXPIRED"  # 确认请求超时
    STALE = "STALE"  # 目标业务对象版本已经变化，原确认失效

# 操作类型
class OperationType(StrEnum):
    """与 Java 业务写操作语义一致的审批操作类型。"""

    SUBMIT_REVIEW = "SUBMIT_REVIEW"  # 提交复核结果
    CREATE_REWORK = "CREATE_REWORK"  # 创建返工任务

# 描述确认后准备调用哪个具体 Tool
class PendingToolName(StrEnum):
    """Approval确认后唯一允许进入执行阶段的写Tool名称。"""

    WRITE_REVIEW_RESULT = "write_review_result"
    CREATE_REWORK_TASK = "create_rework_task"


def _enum_column(enum_type: type[StrEnum], constraint_name: str, length: int) -> Enum:
    """使用字符串Check Constraint保存枚举, 便于后续显式迁移。"""

    return Enum(
        enum_type,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=length,
    )

# ApprovalRecord 数据表
class ApprovalRecord(Base):
    """保存原始/修改草稿、待调用Tool和确认事实, 不直接保存Java业务事实。"""

    __tablename__ = "approval_records"
    __table_args__ = (
        CheckConstraint(
            "char_length(approval_id) > 0",
            name="ck_approval_records_id_not_blank",
        ),
        CheckConstraint(
            "char_length(target_id) > 0",
            name="ck_approval_records_target_not_blank",
        ),
        CheckConstraint(
            "target_version >= 0",
            name="ck_approval_records_target_version_nonnegative",
        ),
        CheckConstraint(
            "((confirmed_by_user_id IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL))",
            name="ck_approval_records_confirmation_pair",
        ),
        CheckConstraint(
            "((operation_type = 'SUBMIT_REVIEW' AND "
            "pending_tool_name = 'write_review_result') OR "
            "(operation_type = 'CREATE_REWORK' AND "
            "pending_tool_name = 'create_rework_task'))",
            name="ck_approval_records_operation_tool_match",
        ),
        CheckConstraint(
            "execution_result IS NULL OR status IN ('EXECUTING', 'SUCCEEDED')",
            name="ck_approval_records_execution_result_status",
        ),
        Index("ix_approval_records_status_created", "status", "created_at"),
        Index("ix_approval_records_run", "run_id"),
    )
    # 当前确认单的唯一ID
    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 这个确认单由哪个Agent Run生成 
    # 删除Run时保留Approval审查证据, 只解除来源关联。
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        _enum_column(ApprovalStatus, "ck_approval_records_status", 32),
        default=ApprovalStatus.DRAFT,
        server_default=ApprovalStatus.DRAFT.value,
        nullable=False,
    )
    # 确认单要做什么的操作类型
    operation_type: Mapped[OperationType] = mapped_column(
        _enum_column(OperationType, "ck_approval_records_operation_type", 32),
        nullable=False,
    )
    # Agent最初生成的内容
    original_draft: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # 用户修改后的草稿内容
    user_modified_draft: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 后续应该调用哪个Tool名称
    pending_tool_name: Mapped[PendingToolName] = mapped_column(
        _enum_column(PendingToolName, "ck_approval_records_pending_tool", 64),
        nullable=False,
    )
    # 目标对象和版本
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 确认事实（要求两个字段同时存在或同时不存在）
    confirmed_by_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Java成功响应的强类型摘要; 具体审计日志由M6.7单独保存。
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    run: Mapped[AgentRun | None] = relationship(back_populates="approvals")
