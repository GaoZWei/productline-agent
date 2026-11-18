"""M8独立审查记录，与旧ReviewDraft确认表隔离，不存Java业务事实表。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReworkConfirmationRecord(Base):
    """原始审查快照不可编辑，状态转换通过完整快照及revision比较。"""

    __tablename__ = "rework_confirmation_records"
    __table_args__ = (
        CheckConstraint(
            "char_length(approval_id) > 0 AND char_length(owner_user_id) > 0",
            name="ck_rcr_identity",
        ),
        CheckConstraint("revision >= 0 AND revision <= 9007199254740991", name="ck_rcr_revision"),
        CheckConstraint(
            "status IN ('WAITING_CONFIRMATION','CONFIRMED','CANCELLED','EXPIRED','STALE',"
            "'EXECUTING','SUCCEEDED')",
            name="ck_rcr_status",
        ),
        CheckConstraint(
            "(status IN ('EXECUTING','SUCCEEDED')) = (execution_key IS NOT NULL)",
            name="ck_rcr_execution_key",
        ),
        CheckConstraint("expires_at > created_at", name="ck_rcr_lifetime"),
        Index("ix_rcr_run", "run_id"),
        Index("ix_rcr_status_expiry", "status", "expires_at"),
        Index("uq_rcr_execution_key", "execution_key", unique=True),
    )

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.run_id", ondelete="SET NULL"))
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
