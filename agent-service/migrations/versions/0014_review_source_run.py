"""为Review和返工Run增加可追溯来源Run。

Revision ID: 0014_review_source_run
Revises: 0013_llm_step_observability
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_review_source_run"
down_revision: str | None = "0013_llm_step_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只保存来源身份; 删除来源Run时保留当前Run并把关联置空。"""

    op.add_column("agent_runs", sa.Column("source_run_id", sa.String(128), nullable=True))
    op.create_foreign_key(
        "fk_agent_runs_source_run_id",
        "agent_runs",
        "agent_runs",
        ["source_run_id"],
        ["run_id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_source_run_id", "agent_runs", ["source_run_id"])


def downgrade() -> None:
    """移除来源Run关联。"""

    op.drop_index("ix_agent_runs_source_run_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_source_run_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "source_run_id")
