"""创建 Agent 会话、消息、Run 和 Step 基础表。

Revision ID: 0001_agent_runtime_base
Revises:
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_agent_runtime_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只创建 Agent 自有运行元数据，不映射 Java 业务表。"""

    op.create_table(
        "agent_sessions",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(session_id) > 0", name="ck_agent_sessions_id_not_blank"
        ),
        sa.CheckConstraint("char_length(user_id) > 0", name="ck_agent_sessions_user_not_blank"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_agent_sessions_user_created",
        "agent_sessions",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "agent_messages",
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "USER",
                "ASSISTANT",
                name="ck_agent_messages_role",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("char_length(message_id) > 0", name="ck_agent_messages_id_not_blank"),
        sa.CheckConstraint(
            "sequence_number > 0", name="ck_agent_messages_sequence_positive"
        ),
        sa.CheckConstraint(
            "char_length(content) > 0", name="ck_agent_messages_content_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint(
            "session_id", "sequence_number", name="uq_agent_messages_session_sequence"
        ),
    )

    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("request_message_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "WAITING_APPROVAL",
                "CANCELLED",
                name="ck_agent_runs_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("final_result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_step", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(run_id) > 0", name="ck_agent_runs_id_not_blank"),
        sa.ForeignKeyConstraint(
            ["request_message_id"], ["agent_messages.message_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_agent_runs_session_created",
        "agent_runs",
        ["session_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "agent_steps",
        sa.Column("step_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "step_type",
            sa.Enum(
                "CONTEXT",
                "TOOL",
                "RULE",
                "LLM",
                name="ck_agent_steps_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("step_name", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                name="ck_agent_steps_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(step_id) > 0", name="ck_agent_steps_id_not_blank"),
        sa.CheckConstraint("sequence_number > 0", name="ck_agent_steps_sequence_positive"),
        sa.CheckConstraint("char_length(step_name) > 0", name="ck_agent_steps_name_not_blank"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_steps_duration_nonnegative"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("step_id"),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_agent_steps_run_sequence"),
    )


def downgrade() -> None:
    """按外键依赖的逆序移除 M2.1 表。"""

    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_session_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_sessions_user_created", table_name="agent_sessions")
    op.drop_table("agent_sessions")
