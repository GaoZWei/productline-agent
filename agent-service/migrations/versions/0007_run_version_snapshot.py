"""为 Agent Run 增加不可变组件版本快照。

Revision ID: 0007_run_version_snapshot
Revises: 0006_vector_search
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_run_version_snapshot"
down_revision: str | None = "0006_vector_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_SNAPSHOT = (
    '{"schema_version":"run-version-snapshot-v1",'
    '"capture_status":"UNAVAILABLE_LEGACY",'
    '"router_prompt_version":null,'
    '"agent_prompt_version":null,'
    '"model":null,'
    '"tool_schema":null,'
    '"rag_strategy":null}'
)


def upgrade() -> None:
    """回填诚实的历史占位后移除默认值, 使新代码必须显式提供快照。"""

    op.add_column(
        "agent_runs",
        sa.Column("version_snapshot", sa.JSON(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE agent_runs "
            "SET version_snapshot = CAST(:legacy_snapshot AS JSON) "
            "WHERE version_snapshot IS NULL"
        ).bindparams(legacy_snapshot=_LEGACY_SNAPSHOT)
    )
    op.alter_column(
        "agent_runs",
        "version_snapshot",
        existing_type=sa.JSON(),
        nullable=False,
    )


def downgrade() -> None:
    """移除 Run 版本快照字段。"""

    op.drop_column("agent_runs", "version_snapshot")
