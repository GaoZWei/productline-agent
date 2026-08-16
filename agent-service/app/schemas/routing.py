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

    USER_MESSAGE = "USER_MESSAGE"  # 用户本轮明确输入
    # 用户之前已经确认并保存在 SessionContext 中。
    CONFIRMED_SESSION = "CONFIRMED_SESSION"
    PAGE_CONTEXT = "PAGE_CONTEXT"  # 当前页面展示的订单、任务等
    SESSION_CANDIDATE = "SESSION_CANDIDATE"  # 上一轮留下的未确认候选对象


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

# 实体提取结果表示模型从本轮用户消息中明确提取到了什么。
class EntityExtractionResult(RoutingSchema):
    """模型从本轮用户消息提取的实体, 不包含页面或会话候选值。"""

    entities: RouterEntities

# 来源化实体 一个已经过字段校验且带可信来源的实体值
class SourcedEntity(RoutingSchema):
    """一个已经过字段校验且带可信来源的实体值。"""

    value: RoutingEntityText
    source: EntitySourceValue

# 合并参数时, 冲突模型保留同一字段出现的不同候选值。
class EntityConflict(RoutingSchema):
    """同一字段出现不同候选值时保留的可审查冲突。"""

    field: RoutingEntityNameValue
    selected: SourcedEntity | None
    candidates: tuple[SourcedEntity, ...]
    resolved_by_priority: bool

# 合并结果 参数合并后的来源化实体、冲突和未解析字段
class EntityMergeResult(RoutingSchema):
    """参数合并后的来源化实体、冲突和未解析字段。"""

    # 已经成功选择的字段。
    entities: dict[RoutingEntityNameValue, SourcedEntity] = Field(default_factory=dict)
    conflicts: tuple[EntityConflict, ...] = ()  # 发现过哪些不同值的字段。
    unresolved_fields: tuple[RoutingEntityNameValue, ...] = ()  # 未解析字段。

    @property
    def has_unresolved_conflicts(self) -> bool: # 方便后续 M3.6 判断是否需要向用户追问冲突
        """表示至少一个同优先级冲突仍需要后续澄清。"""

        return bool(self.unresolved_fields)

    def to_router_entities(self) -> RouterEntities:
        """去除来源元数据, 生成后续 RouterResult 可复用的实体契约。"""

        return RouterEntities.model_validate(
            {
                field.value: sourced.value
                for field, sourced in self.entities.items()
            }
        )

# 置信度等级
class ConfidenceLevel(StrEnum):
    """M3.6 固定置信度分级。"""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

# 路由决策状态 （是否可以进入业务分发）
class RoutingDecisionStatus(StrEnum):
    """路由决策是否已经具备进入业务分发的条件。"""

    READY = "READY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

# 澄清原因
class ClarificationReason(StrEnum):
    """服务端生成澄清问题时使用的稳定原因。"""

    UNKNOWN_INTENT = "UNKNOWN_INTENT"  # 无法识别支持的意图
    ENTITY_CONFLICT = "ENTITY_CONFLICT"  # 同一最高优先级存在多个候选值
    MISSING_PARAMETER = "MISSING_PARAMETER"  # 缺少订单号或任务号
    LOW_CONFIDENCE = "LOW_CONFIDENCE"  # 置信度低于 0.60
    CONFIRM_INTENT = "CONFIRM_INTENT"  # 中置信度，需要确认意图
    MODEL_REQUEST = "MODEL_REQUEST"  # 模型在参数完整时仍认为请求有歧义


ConfidenceLevelValue = Annotated[ConfidenceLevel, Field(strict=False)]
RoutingDecisionStatusValue = Annotated[RoutingDecisionStatus, Field(strict=False)]
ClarificationReasonValue = Annotated[ClarificationReason, Field(strict=False)]

# 澄清请求模型
class ClarificationRequest(RoutingSchema):
    """可直接交给前端展示的确定性澄清问题和候选项。"""

    reason: ClarificationReasonValue
    question: Annotated[str, Field(min_length=1, max_length=512)]
    field: RoutingEntityNameValue | None = None
    options: tuple[SourcedEntity, ...] = ()

    @model_validator(mode="after")
    def validate_reason_payload(self) -> Self:
        """保证字段类澄清带目标字段且候选冲突至少有两个选项。"""

        if self.reason is ClarificationReason.ENTITY_CONFLICT:  # 同一最高优先级存在多个候选值
            if self.field is None or len(self.options) < 2:
                raise ValueError("entity conflict clarification requires field and options")
        elif self.reason is ClarificationReason.MISSING_PARAMETER:  # 缺少订单号或任务号
            if self.field is None or self.options:
                raise ValueError("missing parameter clarification requires only field")
        elif self.field is not None or self.options:  # 非实体澄清不能带字段或选项
            raise ValueError("non-entity clarification must not contain field or options")
        return self

# 用户输入模型
class EntitySelection(RoutingSchema):
    """用户针对缺参或候选冲突提交的明确字段选择。"""

    field: RoutingEntityNameValue
    value: RoutingEntityText

# 最终 RoutingDecision （模型路由和可信实体合并后的最终路由决策）
class RoutingDecision(RoutingSchema):
    """合并模型路由和可信实体后的最终内部路由决策。"""

    intent: IntentValue
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence_level: ConfidenceLevelValue
    entities: EntityMergeResult
    missing_fields: tuple[RoutingParameterValue, ...]
    status: RoutingDecisionStatusValue
    clarification: ClarificationRequest | None = None
    intent_confirmed: bool = False
    model_requested_clarification: bool = False
    # 还要再次校验决策是否符合合同要求
    @model_validator(mode="after")
    def validate_decision_contract(self) -> Self:
        """防止手工构造的决策绕过缺参、冲突和置信度门禁。"""
        # 不会完全相信 build_routing_decision()，而是再次验证一次决策是否符合合同要求
        merged = self.entities.to_router_entities()
        # 从意图目录重新计算缺失字段
        expected_missing = tuple(
            parameter
            for parameter in required_parameters_for(self.intent)
            if not merged.contains(parameter)
        )
        if self.missing_fields != expected_missing:
            raise ValueError("decision missing_fields must match merged entities")
        if self.status is RoutingDecisionStatus.NEEDS_CLARIFICATION:
            if self.clarification is None:
                raise ValueError("pending decision requires clarification payload")
            return self
        if self.clarification is not None:
            raise ValueError("ready decision must not contain clarification")
        if self.intent is Intent.UNKNOWN or skill_for_intent(self.intent) is None:
            raise ValueError("UNKNOWN or unmapped intent cannot be ready")
        if self.missing_fields or self.entities.has_unresolved_conflicts:
            raise ValueError("incomplete or conflicted decision cannot be ready")
        if self.confidence_level is ConfidenceLevel.LOW:
            raise ValueError("low confidence decision cannot be ready")
        if (
            self.confidence_level is ConfidenceLevel.MEDIUM
            and not self.intent_confirmed
        ):
            raise ValueError("medium confidence decision requires intent confirmation")
        if self.model_requested_clarification:
            raise ValueError("model-requested clarification cannot be ready")
        return self

    @property
    def can_dispatch(self) -> bool:
        """表示所有确定性门禁均通过, 仍不代表Java业务事实已验证。"""

        return self.status is RoutingDecisionStatus.READY


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
