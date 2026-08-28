"""Agent侧人工确认写操作审计日志。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.approval import ApprovalRecord


class OperationLogRecord(Base):
    """保存受控前后摘要、用户差异和Java Trace; 不复制完整业务对象。"""

    # Java已占用公共Schema的operation_logs; Agent使用显式前缀隔离审计职责。
    __tablename__ = "agent_operation_logs"
    __table_args__ = (
        CheckConstraint(
            "char_length(operation_log_id) > 0",
            name="ck_agent_operation_logs_id_not_blank",
        ),
        CheckConstraint(
            "char_length(target_id) > 0",
            name="ck_agent_operation_logs_target_not_blank",
        ),
        CheckConstraint(
            "target_version >= 0",
            name="ck_agent_operation_logs_target_version_nonnegative",
        ),
        CheckConstraint(
            "operation_type IN ('SUBMIT_REVIEW', 'CREATE_REWORK')",
            name="ck_agent_operation_logs_operation_type",
        ),
        CheckConstraint(
            "outcome IN ('SUCCEEDED', 'FAILED', 'STALE')",
            name="ck_agent_operation_logs_outcome",
        ),
        CheckConstraint(
            "java_trace_id IS NULL OR char_length(java_trace_id) > 0",
            name="ck_agent_operation_logs_java_trace_not_blank",
        ),
        CheckConstraint(
            "outcome <> 'SUCCEEDED' OR java_trace_id IS NOT NULL",
            name="ck_agent_operation_logs_success_trace_required",
        ),
        Index("ix_agent_operation_logs_target_created", "target_id", "created_at"),
    )

    operation_log_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    approval_id: Mapped[str] = mapped_column(
        ForeignKey("approval_records.approval_id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    before_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    user_modification_diff: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    java_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    approval: Mapped[ApprovalRecord] = relationship(back_populates="operation_log")
