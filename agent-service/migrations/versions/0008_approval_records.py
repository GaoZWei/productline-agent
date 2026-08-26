"""创建人工确认记录表。

Revision ID: 0008_approval_records
Revises: 0007_run_version_snapshot
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_approval_records"
down_revision: str | None = "0007_run_version_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保存Approval草稿、执行目标、确认人和状态。"""

    op.create_table(
        "approval_records",
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "WAITING_CONFIRMATION",
                "CONFIRMED",
                "EXECUTING",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "EXPIRED",
                "STALE",
                name="ck_approval_records_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column(
            "operation_type",
            sa.Enum(
                "SUBMIT_REVIEW",
                "CREATE_REWORK",
                name="ck_approval_records_operation_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("original_draft", sa.JSON(), nullable=False),
        sa.Column("user_modified_draft", sa.JSON(), nullable=True),
        sa.Column(
            "pending_tool_name",
            sa.Enum(
                "write_review_result",
                "create_rework_task",
                name="ck_approval_records_pending_tool",
                native_enum=False,
                create_constraint=True,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("target_version", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.String(length=128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(approval_id) > 0",
            name="ck_approval_records_id_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(target_id) > 0",
            name="ck_approval_records_target_not_blank",
        ),
        sa.CheckConstraint(
            "target_version >= 0",
            name="ck_approval_records_target_version_nonnegative",
        ),
        sa.CheckConstraint(
            "((confirmed_by_user_id IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL))",
            name="ck_approval_records_confirmation_pair",
        ),
        sa.CheckConstraint(
            "((operation_type = 'SUBMIT_REVIEW' AND "
            "pending_tool_name = 'write_review_result') OR "
            "(operation_type = 'CREATE_REWORK' AND "
            "pending_tool_name = 'create_rework_task'))",
            name="ck_approval_records_operation_tool_match",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.run_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_approval_records_status_created",
        "approval_records",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_approval_records_run",
        "approval_records",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    """移除人工确认记录表。"""

    op.drop_index("ix_approval_records_run", table_name="approval_records")
    op.drop_index("ix_approval_records_status_created", table_name="approval_records")
    op.drop_table("approval_records")
