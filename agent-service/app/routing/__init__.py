"""意图路由的稳定定义; 模型 Prompt 和动态执行由后续阶段实现。"""

from app.routing.intent_catalog import (
    INTENT_DEFINITIONS,
    BusinessSkill,
    Intent,
    IntentDefinition,
    RoutingParameter,
    definition_for,
    required_parameters_for,
    skill_for_intent,
)

__all__ = [
    "INTENT_DEFINITIONS",
    "BusinessSkill",
    "Intent",
    "IntentDefinition",
    "RoutingParameter",
    "definition_for",
    "required_parameters_for",
    "skill_for_intent",
]
