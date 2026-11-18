"""新增隔离的M8审查与确认记录，不扩展旧确认执行分支。

Revision ID: 0017_rework_confirmation
Revises: 0016_managed_knowledge_state
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_rework_confirmation"
down_revision: str | None = "0016_managed_knowledge_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只创建Agent自有审查表，不访问Java、种子或运行环境数据。"""

    op.create_table(
        "rework_confirmation_records",
        sa.Column("approval_id", sa.String(128), primary_key=True),
        sa.Column(
            "run_id", sa.String(128), sa.ForeignKey("agent_runs.run_id", ondelete="SET NULL")
        ),
        sa.Column("owner_user_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(approval_id) > 0 AND char_length(owner_user_id) > 0",
            name="ck_rcr_identity",
        ),
        sa.CheckConstraint(
            "revision >= 0 AND revision <= 9007199254740991", name="ck_rcr_revision"
        ),
        sa.CheckConstraint(
            "status IN ('WAITING_CONFIRMATION','CONFIRMED','CANCELLED','EXPIRED','STALE')",
            name="ck_rcr_status",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_rcr_lifetime"),
    )
    op.create_index("ix_rcr_run", "rework_confirmation_records", ["run_id"])
    op.create_index("ix_rcr_status_expiry", "rework_confirmation_records", ["status", "expires_at"])


def downgrade() -> None:
    """只移除本版新增审查表，不改变既有确认记录。"""

    op.drop_table("rework_confirmation_records")
