"""意图路由、实体来源和参数合并的严格结构化契约。"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing.intent_catalog import (
    Intent,
    RoutingParameter,
    required_parameters_for,
    skill_for_intent,
)
from app.schemas.tools import BusinessIdentifier, OrderIdentifier, TaskIdentifier

IntentValue = Annotated[Intent, Field(strict=False)]
RoutingParameterValue = Annotated[RoutingParameter, Field(strict=False)]
RoutingEntityText = Annotated[str, Field(min_length=1, max_length=128)]

# 实体字段白名单 明确规定哪些字段允许进入参数合并
class RoutingEntityName(StrEnum):
    """允许参与路由合并的稳定实体字段名。"""

    ORDER_ID = "order_id"
    TASK_ID = "task_id"
    ISSUE_ID = "issue_id"
    BATCH_ID = "batch_id"
    PRODUCT_TYPE = "product_type"
    SATELLITE_TYPE = "satellite_type"

# 四种参数来源
class EntitySource(StrEnum):
    """实体候选值的可信来源, 枚举顺序不代表合并优先级。"""

    USER_MESSAGE = "USER_MESSAGE" # 用户本轮明确输入
    CONFIRMED_SESSION = "CONFIRMED_SESSION" # 用户之前已经确认，保存在 SessionContext 中
    PAGE_CONTEXT = "PAGE_CONTEXT" # 当前页面展示的订单、任务等
    SESSION_CANDIDATE = "SESSION_CANDIDATE" # 上一轮留下但还没有确认的候选对象


RoutingEntityNameValue = Annotated[RoutingEntityName, Field(strict=False)]
EntitySourceValue = Annotated[EntitySource, Field(strict=False)]


class RoutingSchema(BaseModel):
    """禁止额外字段和隐式标量转换的路由共同契约。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


# 模型允许提取的“业务指代”, 用于后续业务Skill调用。
class RouterEntities(RoutingSchema):
    """路由阶段允许提取的最小业务实体, 不承载 Java 事实快照。"""

    order_id: OrderIdentifier | None = None
    task_id: TaskIdentifier | None = None
    issue_id: BusinessIdentifier | None = None
    batch_id: BusinessIdentifier | None = None
    product_type: RoutingEntityText | None = None
    satellite_type: RoutingEntityText | None = None

    # 判断必填参数有没有值
    def contains(self, parameter: RoutingParameter) -> bool:
        """判断必填参数是否已经获得一个经过格式校验的值。"""

        if parameter is RoutingParameter.ORDER_ID:
            return self.order_id is not None
        return self.task_id is not None

# 实体提取结果 模型从本轮用户消息中明确提取到了什么（模型提取的实体）
class EntityExtractionResult(RoutingSchema):
    """模型从本轮用户消息提取的实体, 不包含页面或会话候选值。"""

    entities: RouterEntities

# 来源化实体 一个已经过字段校验且带可信来源的实体值
class SourcedEntity(RoutingSchema):
    """一个已经过字段校验且带可信来源的实体值。"""

    value: RoutingEntityText
    source: EntitySourceValue

# 冲突模型 合并参数时，同一字段出现不同候选值时保留的可审查冲突
class EntityConflict(RoutingSchema):
    """同一字段出现不同候选值时保留的可审查冲突。"""

    field: RoutingEntityNameValue
    selected: SourcedEntity | None
    candidates: tuple[SourcedEntity, ...]
    resolved_by_priority: bool

# 合并结果 参数合并后的来源化实体、冲突和未解析字段
class EntityMergeResult(RoutingSchema):
    """参数合并后的来源化实体、冲突和未解析字段。"""

    entities: dict[RoutingEntityNameValue, SourcedEntity] = Field(default_factory=dict) # 已经成功选择的字段
    conflicts: tuple[EntityConflict, ...] = () # 发现过哪些不同值的字段
    unresolved_fields: tuple[RoutingEntityNameValue, ...] = () # 未解析的字段

    @property
    def has_unresolved_conflicts(self) -> bool: # 方便后续 M3.6 判断是否需要向用户追问冲突
        """表示至少一个同优先级冲突仍需要后续澄清。"""

        return bool(self.unresolved_fields)

    def to_router_entities(self) -> RouterEntities: # 去掉来源信息, 转换成后续 RouterResult 或 Skill 可以使用的结构
        """去除来源元数据, 生成后续 RouterResult 可复用的实体契约。"""

        return RouterEntities.model_validate(
            {
                field.value: sourced.value
                for field, sourced in self.entities.items()
            }
        )


# 模型必须返回什么内容
class RouterResult(RoutingSchema):
    """模型或规则路由器必须产出的自洽机器结果。"""

    intent: IntentValue  # 选择的意图
    # 置信度范围包含0和1; 分级策略由M3.6实现。
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    entities: RouterEntities
    missing_fields: list[RoutingParameterValue]
    need_clarification: bool

    # 确保缺参列表准确, 并阻止UNKNOWN被当作可执行意图。
    @model_validator(mode="after")
    def validate_route_contract(self) -> Self:
        """确保缺参列表准确, 并阻止 UNKNOWN 被当作可执行意图。"""
        # 禁止重复缺参参数
        if len(set(self.missing_fields)) != len(self.missing_fields):
            raise ValueError("missing_fields must not contain duplicates")
        # 服务端独立计算真实缺参参数
        expected_missing = tuple(
            parameter
            for parameter in required_parameters_for(self.intent)
            if not self.entities.contains(parameter)
        )
        # 对照模型声明的 missing_fields 是否准确
        if tuple(self.missing_fields) != expected_missing:
            raise ValueError("missing_fields must exactly match unresolved required parameters")
        # 缺参必须澄清用户提问
        if expected_missing and not self.need_clarification:
            raise ValueError("missing required parameters must request clarification")
        # UNKNOWN 必须澄清用户提问
        if self.intent is Intent.UNKNOWN and not self.need_clarification:
            raise ValueError("UNKNOWN intent must request clarification")
        return self

    # 当前结果是否具备分发条件
    @property
    def can_dispatch(self) -> bool:
        """表示结构化结果已满足安全分发条件, 不包含后续置信度策略。"""

        return (
            skill_for_intent(self.intent) is not None  # 该意图存在允许执行的 Skill。
            and not self.missing_fields  # 模型声称当前缺少哪些必填参数为空
            and not self.need_clarification  # 当前不需要用户澄清。
        )
