"""M5.2 动态诊断动作决策及执行参数契约。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.schemas.tools import OrderIdInput, TaskIdInput
from app.schemas.workflow import (
    AgentAction,
    ReadToolName,
    WorkflowSchema,
    WorkflowText,
)

type ActionToolName = ReadToolName | Literal["retrieve_spec"] | None
ActionValue = Annotated[AgentAction, Field(strict=False)]
ActionToolArguments = Annotated[dict[str, Any], Field(max_length=8)]

# 规范检索参数定义
class SpecificationRetrievalArguments(WorkflowSchema):
    """动态诊断发起规范检索时允许生成的最小查询参数。"""

    question: WorkflowText

# 动作和Tool的唯一映射：每个动作只能对应一个执行器Tool MappingProxyType 映射表只读，防止被修改
ACTION_TOOL_NAMES: Final[Mapping[AgentAction, ActionToolName]] = MappingProxyType(
    {
        AgentAction.QUERY_ORDER: "get_order_detail",
        AgentAction.QUERY_TASKS: "get_related_tasks",
        AgentAction.QUERY_PROGRESS: "get_production_progress",
        AgentAction.QUERY_QUALITY: "get_quality_issues",
        AgentAction.QUERY_REVIEW: "get_review_result",
        AgentAction.QUERY_DELIVERY: "get_delivery_status",
        AgentAction.RETRIEVE_SPEC: "retrieve_spec",
        AgentAction.FINISH: None,
    }
)
# 参数模型映射：每个动作只能对应一个参数Schema
_ACTION_ARGUMENT_MODELS: Final[Mapping[AgentAction, type[BaseModel] | None]] = MappingProxyType(
    {
        AgentAction.QUERY_ORDER: OrderIdInput,
        AgentAction.QUERY_TASKS: OrderIdInput,
        AgentAction.QUERY_PROGRESS: TaskIdInput,
        AgentAction.QUERY_QUALITY: TaskIdInput,
        AgentAction.QUERY_REVIEW: TaskIdInput,
        AgentAction.QUERY_DELIVERY: OrderIdInput,
        AgentAction.RETRIEVE_SPEC: SpecificationRetrievalArguments,
        AgentAction.FINISH: None,
    }
)


def action_argument_model(action: AgentAction) -> type[BaseModel] | None:
    """返回一个动作唯一允许的参数Schema。"""

    return _ACTION_ARGUMENT_MODELS[action]

# ActionDecision结构体
class ActionDecision(WorkflowSchema):
    """模型给出的一次动作选择及其受控执行参数。"""

    action: ActionValue # 模型选择的稳定动作
    reason: WorkflowText # 模型解释为什么选择该动作
    tool_name: ActionToolName # 真正准备交给执行层的执行器名称
    tool_arguments: ActionToolArguments # 执行器参数对象

    @model_validator(mode="after")
    def validate_action_binding(self) -> ActionDecision:
        """阻止动作、执行器名称和参数Schema互相矛盾。"""
        # 第一步：检查动作和执行器名称是否匹配
        expected_tool_name = ACTION_TOOL_NAMES[self.action]
        if self.tool_name != expected_tool_name:
            raise ValueError("action does not match the required tool name")

        argument_model = action_argument_model(self.action)
        # FINISH的特殊处理：FINISH动作不允许有参数
        if argument_model is None:
            if self.tool_arguments:
                raise ValueError("FINISH must not contain tool arguments")
            return self

        # 查询动作的参数校验
        try:
            argument_model.model_validate(self.tool_arguments)
        except ValidationError as error:
            raise ValueError("tool arguments do not match the action schema") from error
        return self
