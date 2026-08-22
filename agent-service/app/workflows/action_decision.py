"""M5.2 动作模型调用、结构化解析、可用性校验和安全回退。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Protocol

from pydantic import ValidationError

from app.schemas.action import ActionDecision
from app.schemas.workflow import AgentAction, OrderDiagnosisState
from app.tools import ToolRegistry, ToolRiskLevel
from app.tools.registry import ToolNotRegisteredError
from app.workflows.action_prompt import ActionDecisionPrompt, build_action_decision_prompt

_LOGGER = logging.getLogger("agent-service.action-decider")
_SAFE_FINISH_REASON = "无法获得有效的下一步只读动作, 已安全停止自动查询。"


class ActionDecisionModel(Protocol):
    """供应商无关的结构化动作生成边界。"""

    def generate(self, prompt: ActionDecisionPrompt) -> Awaitable[object]:
        """根据受控Prompt和JSON Schema生成一次动作候选。"""


class InvalidActionDecisionOutputError(ValueError):
    """模型动作无法通过Schema或当前执行器目录校验。"""

# 解析模型决策输出 （JSON文本或py对象解析）
def parse_action_decision(raw_output: object) -> ActionDecision:
    """同时接受JSON文本或对象并收口为严格ActionDecision。"""

    try:
        if isinstance(raw_output, (str, bytes, bytearray)):
            return ActionDecision.model_validate_json(raw_output)
        return ActionDecision.model_validate(raw_output)
    except ValidationError as error:
        raise InvalidActionDecisionOutputError(
            "action decision output schema validation failed"
        ) from error

# 安全结束动作
def safe_finish_decision() -> ActionDecision:
    """返回不执行Tool也不声称业务结论的安全结束动作。"""

    return ActionDecision(
        action=AgentAction.FINISH,
        reason=_SAFE_FINISH_REASON,
        tool_name=None,
        tool_arguments={},
    )

# 校验动作决策是否符合注册Tool和状态要求
def _validate_registered_tool(
    decision: ActionDecision,
    registry: ToolRegistry,
    state: OrderDiagnosisState,
) -> ActionDecision:
    """保证业务查询只使用已注册LOW风险Tool及状态中已有的资源身份。"""

    if decision.action in {AgentAction.FINISH, AgentAction.RETRIEVE_SPEC}:
        return decision
    if decision.tool_name is None:
        raise InvalidActionDecisionOutputError("action requires a registered tool")
    try:
        tool = registry.get(decision.tool_name)
    except ToolNotRegisteredError as error:
        raise InvalidActionDecisionOutputError("action selected an unavailable tool") from error
    if tool.risk_level is not ToolRiskLevel.LOW:
        raise InvalidActionDecisionOutputError("action selected a non-read-only tool")
    try:
        tool.input_model.model_validate(decision.tool_arguments)
    except ValidationError as error:
        raise InvalidActionDecisionOutputError(
            "action arguments do not match the registered tool"
        ) from error
    # 校验资源ID来自当前状态中的资源
    if decision.action in {
        AgentAction.QUERY_ORDER,
        AgentAction.QUERY_TASKS,
        AgentAction.QUERY_DELIVERY,
    }:
        if decision.tool_arguments.get("order_id") != state["order_id"]:
            raise InvalidActionDecisionOutputError("action invented a different order id")
    else:
        known_task_ids = {task.task_id for task in state["tasks"]}
        if decision.tool_arguments.get("task_id") not in known_task_ids:
            raise InvalidActionDecisionOutputError("action selected an unknown task id")
    return decision


class ActionDecider:
    """执行最多两次结构化动作生成且失败时安全结束。"""

    def __init__(self, *, model: ActionDecisionModel, registry: ToolRegistry) -> None:
        self._model = model
        self._registry = registry

    async def decide(self, state: OrderDiagnosisState) -> ActionDecision:
        """首次非法输出纠错一次且模型异常或二次失败时返回FINISH。"""
        # 最多调用两次模型
        # 第一次输出合法：生成动作 → Schema通过 → Registry通过 → 状态身份通过 → 立即返回
        for attempt in (1, 2):
            # 第一步：构造Prompt
            prompt = build_action_decision_prompt(
                state=state,
                registry=self._registry,
                attempt=attempt,
            )
            # 第二步：调用模型
            try:
                raw_output = await self._model.generate(prompt)
            # 模型异常不重试：当前策略是直接安全结束
            except Exception as error:
                _LOGGER.error(
                    "action_decision_model_call_failed",
                    extra={
                        "attempt": attempt,
                        "prompt_version": prompt.version,
                        "error_type": type(error).__name__,
                    },
                )
                return safe_finish_decision()
            # 第三步：解析模型输出
            try:
                decision = parse_action_decision(raw_output)
                # 第四步：校验Tool与资源校验
                return _validate_registered_tool(decision, self._registry, state)
            # 决策非法时如何重试：纠错一次
            except InvalidActionDecisionOutputError:
                _LOGGER.warning(
                    "action_decision_output_invalid",
                    extra={"attempt": attempt, "prompt_version": prompt.version},
                )
                # 第二次仍非法：返回FINISH动作
                if attempt == 2:
                    return safe_finish_decision()

        return safe_finish_decision()
