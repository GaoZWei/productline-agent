"""返工状态审计，不改变Java业务表或原确认材料。

Revision ID: 0019_rework_observability
Revises: 0018_rework_execution
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_rework_observability"
down_revision: str | None = "0018_rework_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅新增Agent自有审计表，复用现有Run/Step。"""

    op.create_table(
        "rework_operation_logs",
        sa.Column("approval_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=True),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("approval_id", "revision"),
        sa.CheckConstraint("revision >= 0", name="ck_rol_revision"),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["rework_confirmation_records.approval_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.run_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_rework_operation_logs_run_id", "rework_operation_logs", ["run_id"])


def downgrade() -> None:
    """已有审计证据时拒绝降级，避免静默丢失操作记录。"""

    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM rework_operation_logs)
        THEN RAISE EXCEPTION 'cannot downgrade persisted rework operation logs'; END IF;
        END $$""")
    op.drop_index("ix_rework_operation_logs_run_id", table_name="rework_operation_logs")
    op.drop_table("rework_operation_logs")
