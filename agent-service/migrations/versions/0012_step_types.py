"""扩展Agent Step类型并将历史RULE统一为WORKFLOW。

Revision ID: 0012_step_types
Revises: 0011_run_observability
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_step_types"
down_revision: str | None = "0011_run_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPLETE_STEP_TYPES = (
    "CONTEXT",
    "ROUTER",
    "WORKFLOW",
    "AGENT",
    "TOOL",
    "RAG",
    "LLM",
    "APPROVAL",
    "WRITEBACK",
)
_LEGACY_STEP_TYPES = ("CONTEXT", "TOOL", "RULE", "LLM")


def _type_constraint(values: tuple[str, ...]) -> str:
    """生成只包含稳定枚举值的Check Constraint表达式。"""

    allowed_values = ", ".join(f"'{value}'" for value in values)
    return f"step_type IN ({allowed_values})"


def upgrade() -> None:
    """先放开旧约束转换历史数据, 再锁定九种完整类型。"""

    op.drop_constraint("ck_agent_steps_type", "agent_steps", type_="check")
    op.execute("UPDATE agent_steps SET step_type = 'WORKFLOW' WHERE step_type = 'RULE'")
    op.create_check_constraint(
        "ck_agent_steps_type",
        "agent_steps",
        _type_constraint(_COMPLETE_STEP_TYPES),
    )


def downgrade() -> None:
    """将新类型收敛为旧RULE分类, 保证降级前数据符合旧约束。"""

    op.drop_constraint("ck_agent_steps_type", "agent_steps", type_="check")
    op.execute(
        "UPDATE agent_steps SET step_type = 'RULE' "
        "WHERE step_type NOT IN ('CONTEXT', 'TOOL', 'LLM')"
    )
    op.create_check_constraint(
        "ck_agent_steps_type",
        "agent_steps",
        _type_constraint(_LEGACY_STEP_TYPES),
    )
