"""意图目录的稳定定义; 具体模型供应商和动态执行由后续阶段实现。"""

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
