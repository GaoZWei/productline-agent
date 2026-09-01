"""为LLM Step增加模型身份、Token和实际重试次数字段。

Revision ID: 0013_llm_step_observability
Revises: 0012_step_types
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_llm_step_observability"
down_revision: str | None = "0012_step_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增可空字段，历史LLM Step不补造供应商调用指标。"""

    op.add_column("agent_steps", sa.Column("llm_model_name", sa.String(128), nullable=True))
    op.add_column("agent_steps", sa.Column("llm_input_token_count", sa.Integer(), nullable=True))
    op.add_column("agent_steps", sa.Column("llm_output_token_count", sa.Integer(), nullable=True))
    op.add_column("agent_steps", sa.Column("llm_total_token_count", sa.Integer(), nullable=True))
    op.add_column("agent_steps", sa.Column("llm_retry_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_agent_steps_llm_token_counts",
        "agent_steps",
        "(llm_input_token_count IS NULL AND llm_output_token_count IS NULL AND "
        "llm_total_token_count IS NULL) OR ("
        "llm_input_token_count >= 0 AND llm_output_token_count >= 0 AND "
        "llm_total_token_count = llm_input_token_count + llm_output_token_count)",
    )
    op.create_check_constraint(
        "ck_agent_steps_llm_retry_count_nonnegative",
        "agent_steps",
        "llm_retry_count IS NULL OR llm_retry_count >= 0",
    )
    op.create_check_constraint(
        "ck_agent_steps_llm_model_not_blank",
        "agent_steps",
        "llm_model_name IS NULL OR char_length(llm_model_name) > 0",
    )


def downgrade() -> None:
    """移除本阶段新增的LLM观测字段。"""

    op.drop_constraint(
        "ck_agent_steps_llm_model_not_blank", "agent_steps", type_="check"
    )
    op.drop_constraint(
        "ck_agent_steps_llm_retry_count_nonnegative", "agent_steps", type_="check"
    )
    op.drop_constraint("ck_agent_steps_llm_token_counts", "agent_steps", type_="check")
    op.drop_column("agent_steps", "llm_retry_count")
    op.drop_column("agent_steps", "llm_total_token_count")
    op.drop_column("agent_steps", "llm_output_token_count")
    op.drop_column("agent_steps", "llm_input_token_count")
    op.drop_column("agent_steps", "llm_model_name")
