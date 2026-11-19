"""九类返工动作的状态审计，与旧版Approval外键及动作枚举隔离。"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReworkOperationLog(Base):
    """每个审查修订只追加一条白名单摘要，不复制人工材料或完整回执。"""

    __tablename__ = "rework_operation_logs"
    __table_args__ = (CheckConstraint("revision >= 0", name="ck_rol_revision"),)

    approval_id: Mapped[str] = mapped_column(
        ForeignKey("rework_confirmation_records.approval_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.run_id", ondelete="SET NULL"), index=True
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[dict[str, str | int | None]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
