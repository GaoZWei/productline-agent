"""M3.3 意图、必填参数与业务 Skill 的稳定目录。"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

# 限制模型只能选择有限意图
class Intent(StrEnum):
    """第一批可路由业务意图; UNKNOWN 是安全回退而非业务动作。"""

    ORDER_QUERY = "ORDER_QUERY"
    ORDER_DIAGNOSIS = "ORDER_DIAGNOSIS"
    TASK_TRACKING = "TASK_TRACKING"
    SPEC_QA = "SPEC_QA"
    REVIEW_GENERATION = "REVIEW_GENERATION"
    UNKNOWN = "UNKNOWN"

# 定义分发前必须确认的参数
class RoutingParameter(StrEnum):
    """当前意图在进入业务 Skill 前可能要求确认的参数。"""

    ORDER_ID = "order_id"
    TASK_ID = "task_id"

# 限定允许分发的能力名称
class BusinessSkill(StrEnum):
    """规划中的四个单主 Agent 业务 Skill 稳定名称。"""

    ORDER_STATUS = "OrderStatusSkill"
    DIAGNOSIS = "DiagnosisSkill"
    SPECIFICATION = "SpecificationSkill"
    REVIEW = "ReviewSkill"

# 把意图、必填参数、Skill 绑定起来
@dataclass(frozen=True, slots=True)
class IntentDefinition:
    """描述一个意图的执行目标和进入目标前必须具备的参数。"""

    required_parameters: tuple[RoutingParameter, ...]  # 进入对应 Skill 前必须已经确认的参数列表
    skill: BusinessSkill | None = None  # 该意图未来应该交给哪个 Skill | None 表示 明确没有可执行 Skill

# 完整的只读意图目录(意图映射)
INTENT_DEFINITIONS: Final[Mapping[Intent, IntentDefinition]] = MappingProxyType(
    {
        Intent.ORDER_QUERY: IntentDefinition(
            required_parameters=(RoutingParameter.ORDER_ID,),
            skill=BusinessSkill.ORDER_STATUS,
        ),
        Intent.ORDER_DIAGNOSIS: IntentDefinition(
            required_parameters=(RoutingParameter.ORDER_ID,),
            skill=BusinessSkill.DIAGNOSIS,
        ),
        Intent.TASK_TRACKING: IntentDefinition(
            required_parameters=(RoutingParameter.TASK_ID,),
            skill=BusinessSkill.ORDER_STATUS,
        ),
        # 规范问题本身就是后续 RAG 的检索输入, 产品等页面元数据是可选过滤条件。
        Intent.SPEC_QA: IntentDefinition(
            required_parameters=(),
            skill=BusinessSkill.SPECIFICATION,
        ),
        # M6 的复核草稿以任务为聚合根, 质检问题由 Java 最新事实重新加载。
        Intent.REVIEW_GENERATION: IntentDefinition(
            required_parameters=(RoutingParameter.TASK_ID,),
            skill=BusinessSkill.REVIEW,
        ),
        Intent.UNKNOWN: IntentDefinition(required_parameters=(), skill=None),
    }
)
# 完整性检查: 每个意图必须有对应的定义
if set(INTENT_DEFINITIONS) != set(Intent):
    raise RuntimeError("intent catalog must define every Intent exactly once")


def definition_for(intent: Intent) -> IntentDefinition:
    """返回一个完整且只读的意图定义。"""

    return INTENT_DEFINITIONS[intent]


def required_parameters_for(intent: Intent) -> tuple[RoutingParameter, ...]:
    """返回稳定顺序的必填参数, 供 Schema 和后续参数合并器复用。"""

    return definition_for(intent).required_parameters


def skill_for_intent(intent: Intent) -> BusinessSkill | None:
    """返回目标业务 Skill; UNKNOWN 明确返回 None。"""

    return definition_for(intent).skill
