"""M3.3 意图路由实体和结果的严格结构化契约。"""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing import (
    Intent,
    RoutingParameter,
    required_parameters_for,
    skill_for_intent,
)
from app.schemas.tools import BusinessIdentifier, OrderIdentifier, TaskIdentifier

IntentValue = Annotated[Intent, Field(strict=False)]
RoutingParameterValue = Annotated[RoutingParameter, Field(strict=False)]
RoutingEntityText = Annotated[str, Field(min_length=1, max_length=128)]


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
