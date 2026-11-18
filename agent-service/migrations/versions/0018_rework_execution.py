"""M8唯一执行键与成功状态，保留0017原审查记录。

Revision ID: 0018_rework_execution
Revises: 0017_rework_confirmation
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_rework_execution"
down_revision: str | None = "0017_rework_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只扩展Agent审查表，Java幂等和业务表保持。"""

    op.add_column("rework_confirmation_records", sa.Column("execution_key", sa.String(128)))
    op.drop_constraint("ck_rcr_status", "rework_confirmation_records", type_="check")
    op.create_check_constraint(
        "ck_rcr_status",
        "rework_confirmation_records",
        "status IN ('WAITING_CONFIRMATION','CONFIRMED','CANCELLED','EXPIRED','STALE',"
        "'EXECUTING','SUCCEEDED')",
    )
    op.create_check_constraint(
        "ck_rcr_execution_key",
        "rework_confirmation_records",
        "(status IN ('EXECUTING','SUCCEEDED')) = (execution_key IS NOT NULL)",
    )
    op.create_index(
        "uq_rcr_execution_key", "rework_confirmation_records", ["execution_key"], unique=True
    )


def downgrade() -> None:
    """已有执行证据时拒绝降级，不删键或伪造回到待确认状态。"""

    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM rework_confirmation_records WHERE execution_key IS NOT NULL)
        THEN RAISE EXCEPTION 'cannot downgrade persisted rework executions'; END IF;
        END $$""")
    op.drop_index("uq_rcr_execution_key", table_name="rework_confirmation_records")
    op.drop_constraint("ck_rcr_execution_key", "rework_confirmation_records", type_="check")
    op.drop_constraint("ck_rcr_status", "rework_confirmation_records", type_="check")
    op.create_check_constraint(
        "ck_rcr_status",
        "rework_confirmation_records",
        "status IN ('WAITING_CONFIRMATION','CONFIRMED','CANCELLED','EXPIRED','STALE')",
    )
    op.drop_column("rework_confirmation_records", "execution_key")
