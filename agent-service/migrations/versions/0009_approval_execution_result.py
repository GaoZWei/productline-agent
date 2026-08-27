"""保存Approval对应的Java写Tool成功结果。

Revision ID: 0009_approval_execution_result
Revises: 0008_approval_records
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_approval_execution_result"
down_revision: str | None = "0008_approval_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """允许执行中或成功的Approval保存Java成功响应摘要。"""

    op.add_column(
        "approval_records",
        sa.Column("execution_result", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_approval_records_execution_result_status",
        "approval_records",
        "execution_result IS NULL OR status IN ('EXECUTING', 'SUCCEEDED')",
    )


def downgrade() -> None:
    """移除Approval执行结果摘要。"""

    op.drop_constraint(
        "ck_approval_records_execution_result_status",
        "approval_records",
        type_="check",
    )
    op.drop_column("approval_records", "execution_result")
