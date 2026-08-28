"""创建人工确认写操作审计日志表。

Revision ID: 0010_operation_logs
Revises: 0009_approval_execution_result
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_operation_logs"
down_revision: str | None = "0009_approval_execution_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保存每个Approval唯一的受控操作前后证据。"""

    op.create_table(
        "agent_operation_logs",
        sa.Column("operation_log_id", sa.String(length=128), nullable=False),  # 日志自己的唯一标识
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("target_version", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.String(length=128), nullable=False),
        sa.Column("before_summary", sa.JSON(), nullable=False),
        sa.Column("after_summary", sa.JSON(), nullable=False),
        sa.Column("user_modification_diff", sa.JSON(), nullable=False),
        sa.Column("java_trace_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(operation_log_id) > 0",
            name="ck_agent_operation_logs_id_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(target_id) > 0",
            name="ck_agent_operation_logs_target_not_blank",
        ),
        sa.CheckConstraint(
            "target_version >= 0",
            name="ck_agent_operation_logs_target_version_nonnegative",
        ),
        sa.CheckConstraint(
            "operation_type IN ('SUBMIT_REVIEW', 'CREATE_REWORK')",
            name="ck_agent_operation_logs_operation_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('SUCCEEDED', 'FAILED', 'STALE')",
            name="ck_agent_operation_logs_outcome",
        ),
        sa.CheckConstraint(
            "java_trace_id IS NULL OR char_length(java_trace_id) > 0",
            name="ck_agent_operation_logs_java_trace_not_blank",
        ),
        sa.CheckConstraint(
            "outcome <> 'SUCCEEDED' OR java_trace_id IS NOT NULL",
            name="ck_agent_operation_logs_success_trace_required",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_records.approval_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_log_id"),
        sa.UniqueConstraint("approval_id", name="uq_agent_operation_logs_approval"),
    )
    op.create_index(
        "ix_agent_operation_logs_target_created",
        "agent_operation_logs",
        ["target_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """移除人工确认写操作日志。"""

    op.drop_index(
        "ix_agent_operation_logs_target_created",
        table_name="agent_operation_logs",
    )
    op.drop_table("agent_operation_logs")
