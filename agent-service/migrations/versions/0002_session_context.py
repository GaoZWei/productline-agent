"""为Agent会话增加最小上下文与滑动过期时间。

Revision ID: 0002_session_context
Revises: 0001_agent_runtime_base
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_session_context"
down_revision: str | None = "0001_agent_runtime_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保存Agent最小会话指代，不复制Java业务事实。"""

    op.add_column(
        "agent_sessions",
        sa.Column("context", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP + INTERVAL '30 minutes'"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_sessions_expires_at",
        "agent_sessions",
        ["expires_at"],
        unique=False,
    )
    op.alter_column("agent_sessions", "context", server_default=None)
    op.alter_column("agent_sessions", "expires_at", server_default=None)


def downgrade() -> None:
    """移除M3.2会话上下文字段，保留M2运行表。"""

    op.drop_index("ix_agent_sessions_expires_at", table_name="agent_sessions")
    op.drop_column("agent_sessions", "expires_at")
    op.drop_column("agent_sessions", "context")
