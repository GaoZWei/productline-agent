"""为Agent Run增加完整运行上下文和用量字段。

Revision ID: 0011_run_observability
Revises: 0010_operation_logs
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_run_observability"
down_revision: str | None = "0010_operation_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增安全快照、计数、总耗时和终止原因, 历史Run不补造运行事实。"""

    op.add_column("agent_runs", sa.Column("page_context_snapshot", sa.JSON(), nullable=True))
    op.add_column("agent_runs", sa.Column("router_result", sa.JSON(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("input_token_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("output_token_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("total_token_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("tool_call_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("agent_runs", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("termination_reason", sa.String(64), nullable=True))
    op.create_check_constraint(
        "ck_agent_runs_token_counts",
        "agent_runs",
        "input_token_count >= 0 AND output_token_count >= 0 "
        "AND total_token_count = input_token_count + output_token_count",
    )
    op.create_check_constraint(
        "ck_agent_runs_tool_call_count_nonnegative",
        "agent_runs",
        "tool_call_count >= 0",
    )
    op.create_check_constraint(
        "ck_agent_runs_duration_nonnegative",
        "agent_runs",
        "duration_ms IS NULL OR duration_ms >= 0",
    )
    op.create_check_constraint(
        "ck_agent_runs_termination_not_blank",
        "agent_runs",
        "termination_reason IS NULL OR char_length(termination_reason) > 0",
    )


def downgrade() -> None:
    """按约束依赖逆序移除M7.1字段。"""

    op.drop_constraint(
        "ck_agent_runs_termination_not_blank",
        "agent_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_runs_duration_nonnegative",
        "agent_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_runs_tool_call_count_nonnegative",
        "agent_runs",
        type_="check",
    )
    op.drop_constraint("ck_agent_runs_token_counts", "agent_runs", type_="check")
    op.drop_column("agent_runs", "termination_reason")
    op.drop_column("agent_runs", "duration_ms")
    op.drop_column("agent_runs", "tool_call_count")
    op.drop_column("agent_runs", "total_token_count")
    op.drop_column("agent_runs", "output_token_count")
    op.drop_column("agent_runs", "input_token_count")
    op.drop_column("agent_runs", "router_result")
    op.drop_column("agent_runs", "page_context_snapshot")
