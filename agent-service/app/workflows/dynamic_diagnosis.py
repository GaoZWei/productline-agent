"""M5.3 动态订单诊断的 LangGraph 循环与安全结束边界。"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import date
from typing import Any, Literal, Protocol, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ValidationError

from app.errors import ToolErrorCode
from app.schemas.action import (
    ActionDecision,
    SpecificationRetrievalArguments,
    action_argument_model,
)
from app.schemas.context import PageContext, PageType
from app.schemas.knowledge import PermissionScope
from app.schemas.specification import SpecificationQaResult
from app.schemas.tools import (
    DeliveryStatus,
    OrderDetail,
    OrderIdInput,
    ProgressResult,
    QualityIssueList,
    ReviewResult,
    TaskDetail,
    TaskList,
)
from app.schemas.workflow import (
    AgentAction,
    AgentObservation,
    AgentTerminationReason,
    BlockingStage,
    OrderDiagnosisState,
    StepError,
)
from app.tools import ToolContext, ToolRegistry, ToolRiskLevel
from app.tools.deduplication import build_tool_call_fingerprint
from app.workflows.action_decision import ActionDecider
from app.workflows.diagnosis_generation import generate_rule_diagnosis
from app.workflows.diagnosis_rules import evaluate_diagnosis_rules

type StateUpdate = dict[str, object]
type StartRoute = Literal["plan", "exceptional"]
type CompletionRoute = Literal["continue", "generate", "exceptional"]

# 动态诊断状态定义
class DynamicDiagnosisState(OrderDiagnosisState):
    """在共享诊断事实上增加单轮动作和规范检索的瞬时通道。"""

    current_decision: ActionDecision | None  # 模型本轮选择的动作
    current_call_fingerprint: str | None  # Tool名称和参数生成的SHA-256调用身份
    pending_observation: AgentObservation | None  # 已执行但还没有正式写入历史的观察
    specification_result: SpecificationQaResult | None  #  RAG规范检索结果，与Java业务事实隔离保存


class SpecificationActionWorkflow(Protocol):
    """动态图调用规范问答时依赖的最小协议。"""

    def ainvoke(
        self,
        question: str,
        *,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> Awaitable[SpecificationQaResult]:
        """在显式时间、权限和页面提示下返回带状态的规范结果。"""


class DynamicDiagnosisWorkflow:
    """让模型选择只读动作, 由确定性节点校验、执行并生成规则诊断。"""

    def __init__(
        self,
        *,
        action_decider: ActionDecider,
        tool_registry: ToolRegistry,
        tool_context: ToolContext,
        specification_workflow: SpecificationActionWorkflow,
        effective_at: date,
        permission_scope: PermissionScope,
    ) -> None:
        self._action_decider = action_decider
        self._tool_registry = tool_registry
        self._tool_context = tool_context
        self._specification_workflow = specification_workflow
        self._effective_at = effective_at
        self._permission_scope = permission_scope
        self._invoked = False
        self.graph = self._build_graph()

    async def ainvoke(
        self,
        order_id: str,
        *,
        page_context: PageContext | None = None,
    ) -> DynamicDiagnosisState:
        """执行一次绑定当前 ToolContext 的动态循环。"""

        if self._invoked:
            raise RuntimeError("one workflow instance can only execute once")
        self._invoked = True
        raw_context: object = page_context or {
            "current_system": "production-system",
            "current_page": PageType.ORDER_DETAIL,
            "order_id": order_id,
            "user_role": self._tool_context.identity.role,
        }
        result = await self.graph.ainvoke(
            {
                "run_id": self._tool_context.run_id,
                "order_id": order_id,
                "page_context": raw_context,
            }
        )
        return cast(DynamicDiagnosisState, result)
    # 图结构定义
    def _build_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """编译“决策—校验—执行—观察—判断”的可回环状态图。"""

        builder = StateGraph(DynamicDiagnosisState)
        builder.add_node("initialize", self.initialize)
        builder.add_node("plan_next_action", self.plan_next_action)
        builder.add_node("validate_action", self.validate_action)
        builder.add_node("execute_action", self.execute_action)
        builder.add_node("save_observation", self.save_observation)
        builder.add_node("check_completion", self.check_completion)
        builder.add_node("generate_result", self.generate_result)
        builder.add_node("exceptional_finish", self.exceptional_finish)
        builder.add_edge(START, "initialize")
        builder.add_conditional_edges(
            "initialize",
            self._route_after_initialize,
            {"plan": "plan_next_action", "exceptional": "exceptional_finish"},
        )
        builder.add_conditional_edges(
            "plan_next_action",
            self._route_after_initialize,
            {"plan": "validate_action", "exceptional": "exceptional_finish"},
        )
        builder.add_conditional_edges(
            "validate_action",
            self._route_after_initialize,
            {"plan": "execute_action", "exceptional": "exceptional_finish"},
        )
        builder.add_edge("execute_action", "save_observation")
        builder.add_edge("save_observation", "check_completion")
        builder.add_conditional_edges(
            "check_completion",
            self._route_after_completion,
            {
                "continue": "plan_next_action",  # 继续下一轮决策
                "generate": "generate_result",  # 生成正常诊断结果
                "exceptional": "exceptional_finish",  # 进入异常安全出口
            },
        )
        builder.add_edge("generate_result", END)
        builder.add_edge("exceptional_finish", END)
        return builder.compile(name="dynamic-order-diagnosis")
    # 初始化与上下文校验
    async def initialize(self, state: DynamicDiagnosisState) -> StateUpdate:
        """校验运行身份与页面订单, 并初始化全部共享及瞬时状态。"""
        # 初始化全部状态字段
        base: StateUpdate = {
            "run_id": self._tool_context.run_id,
            "order_id": state.get("order_id", ""),
            "page_context": None,
            "order": None,
            "tasks": [],
            "progress": {},
            "quality_issues": {},
            "reviews": {},
            "delivery": None,
            "rule_decision": None,
            "diagnosis": None,
            "errors": [],
            "tool_history": [],
            "information_gaps": [],
            "iteration_count": 0,
            "termination_reason": None,
            "current_decision": None,
            "current_call_fingerprint": None,
            "pending_observation": None,
            "specification_result": None,
        }
        try:
            if state.get("run_id") != self._tool_context.run_id:  #  Workflow的run_id必须等于ToolContext.run_id
                raise ValueError("workflow run_id does not match ToolContext")
            # 校验order_id是否符合ORDER-xxx格式
            order_input = OrderIdInput.model_validate({"order_id": state.get("order_id")})
            context = PageContext.model_validate(state.get("page_context"))
            # 页面中的订单和用户角色必须与本次执行身份一致
            if context.order_id != order_input.order_id: 
                raise ValueError("page context order_id does not match request")
            if context.user_role != self._tool_context.identity.role:
                raise ValueError("page context user_role does not match identity")
        except (ValidationError, ValueError):
            return {
                **base,
                "errors": [self._step_error("initialize", ToolErrorCode.PARAM_VALIDATION_ERROR)],
            }
        return {**base, "order_id": order_input.order_id, "page_context": context}
    # 模型只负责选择动作，不负责执行Tool或写入事实
    async def plan_next_action(self, state: DynamicDiagnosisState) -> StateUpdate:
        """只请求下一动作, 不允许决策模型直接执行 Tool 或写入事实。"""

        try:
            # 调用模型决策器获取动作决策
            decision = await self._action_decider.decide(state)
        except Exception:
            return {
                "errors": [
                    *state["errors"],
                    self._step_error("plan_next_action", ToolErrorCode.UNKNOWN_TOOL_ERROR),
                ]
            }
        return {
            "current_decision": decision,
            "current_call_fingerprint": None,
            "pending_observation": None,
        }
    # 二次校验动作决策是否符合注册Tool和状态要求
    async def validate_action(self, state: DynamicDiagnosisState) -> StateUpdate:
        """再次校验动作参数、注册表风险和状态资源归属并生成调用指纹。"""

        decision = state["current_decision"]
        if decision is None:
            return self._validation_failure(state)
        if decision.action is AgentAction.FINISH:
            return {"current_call_fingerprint": None}
        argument_model = action_argument_model(decision.action)
        if argument_model is None:
            return self._validation_failure(state)
        try:
            arguments = argument_model.model_validate(decision.tool_arguments)
            if decision.action is AgentAction.RETRIEVE_SPEC:
                fingerprint = build_tool_call_fingerprint("retrieve_spec", arguments)
            else:
                if decision.tool_name is None:
                    raise ValueError("business action requires a tool")
                tool = self._tool_registry.get(decision.tool_name)
                if tool.risk_level is not ToolRiskLevel.LOW:  #  动作决策中的 Tool必须是LOW风险
                    raise ValueError("dynamic diagnosis only permits LOW risk tools")
                validated = tool.input_model.model_validate(decision.tool_arguments) 
                self._validate_resource_identity(decision, state)
                # 生成稳定调用指纹
                fingerprint = build_tool_call_fingerprint(tool.name, validated)
        except (ValidationError, LookupError, ValueError):
            return self._validation_failure(state)
        return {"current_call_fingerprint": fingerprint}
    # 真正执行Tool动作 只负责执行并描述这次发生了什么
    async def execute_action(self, state: DynamicDiagnosisState) -> StateUpdate:  #  接收完整动态图状态
        """执行一个已校验动作并把原始结果转换成事实更新和安全 Observation。"""
        # 读取当前动作
        decision = state["current_decision"]
        # 检查是否FINISH FINISH不执行任何Tool
        if decision is None or decision.action is AgentAction.FINISH:
            return {"pending_observation": None}
        # 检查调用指纹是否存在
        fingerprint = state["current_call_fingerprint"]
        if fingerprint is None:
            return self._validation_failure(state)
        # 规范检索单独处理
        if decision.action is AgentAction.RETRIEVE_SPEC:
            return await self._execute_specification(state, decision, fingerprint)
        
        if decision.tool_name is None:
            return self._validation_failure(state)
        # 获取并执行Java Tool
        tool = self._tool_registry.get(decision.tool_name)
        result = await tool.execute(decision.tool_arguments, self._tool_context) #会经过通用门禁
        # Tool失败如何处理
        if not result.success:
            error = result.error
            if error is None:
                return self._execution_failure(state, decision.action, fingerprint)
            # 先转换为Workflow使用的StepError
            step_error = StepError(
                step_name="execute_action",
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                trace_id=error.trace_id,
            )
            # 然后生成失败Observation
            return {
                "pending_observation": AgentObservation(
                    action=decision.action,
                    call_fingerprint=fingerprint,
                    success=False,
                    summary=f"只读动作执行失败: {error.code.value}",
                    has_new_information=False,  # 失败必须设置为False
                    error=step_error,
                )
            }
        # 成功但data为空如何处理
        if result.data is None:
            return self._execution_failure(state, decision.action, fingerprint)
        try: 
            # 把Tool结果合并进业务状态
            fact_update, summary, has_new = self._merge_business_fact(
                state,
                decision,
                result.data,
            )
        except (ValidationError, ValueError):
            return self._execution_failure(state, decision.action, fingerprint)
        # 成功时返回更新后的状态和Observation
        return {
            **fact_update,
            "pending_observation": AgentObservation(
                action=decision.action,
                call_fingerprint=fingerprint,
                success=True,
                summary=summary,
                has_new_information=has_new,
            ),
        }
    # 统一保存Observation 负责更新历史、轮次和错误通道
    async def save_observation(self, state: DynamicDiagnosisState) -> StateUpdate:
        """把单轮观察按顺序追加到历史, 失败同时进入结构化错误通道。"""

        observation = state["pending_observation"]
        if observation is None:
            return {}
        errors = state["errors"]
        if observation.error is not None:
            errors = [*errors, observation.error]
        return {
            "tool_history": [*state["tool_history"], observation],
            "iteration_count": state["iteration_count"] + 1,
            "errors": errors,
            "pending_observation": None,
        }
    # 谁决定是否结束流程
    async def check_completion(self, state: DynamicDiagnosisState) -> StateUpdate:
        """在显式 FINISH 时以确定性规则区分事实充分与安全不足。"""
        # 存在错误则进入异常出口
        if state["errors"]:
            return {"termination_reason": AgentTerminationReason.EXECUTION_ERROR}
        decision = state["current_decision"]
        # 当前动作不是FINISH 则继续执行
        if decision is None or decision.action is not AgentAction.FINISH:
            return {}
        # 当前动作是FINISH，不会直接相信模型，而是再次执行
        rule_decision = evaluate_diagnosis_rules(state)
        reason = (
            AgentTerminationReason.INSUFFICIENT_INFORMATION
            if rule_decision.blocking_stage is BlockingStage.INSUFFICIENT_INFORMATION 
            else AgentTerminationReason.SUFFICIENT_INFORMATION #如果事实完整且规则能形成结论
        )
        return {"termination_reason": reason}
    # 正常结果
    async def generate_result(self, state: DynamicDiagnosisState) -> StateUpdate:
        """只用已保存的 Java Tool 事实运行规则并生成最终诊断。"""

        decision = evaluate_diagnosis_rules(state)
        diagnosis_state = cast(OrderDiagnosisState, {**state, "rule_decision": decision})
        return {
            "rule_decision": decision,
            "diagnosis": generate_rule_diagnosis(diagnosis_state),
        }
    # 异常结果
    async def exceptional_finish(self, state: DynamicDiagnosisState) -> StateUpdate:
        """异常时生成信息不足结果, 不把执行失败误报为业务阻塞。"""

        try:
            OrderIdInput.model_validate({"order_id": state["order_id"]})
        except ValidationError:
            return {"termination_reason": AgentTerminationReason.EXECUTION_ERROR}
        decision = evaluate_diagnosis_rules(state)
        diagnosis_state = cast(OrderDiagnosisState, {**state, "rule_decision": decision})
        return {
            "termination_reason": AgentTerminationReason.EXECUTION_ERROR,
            "rule_decision": decision,
            "diagnosis": generate_rule_diagnosis(diagnosis_state),
        }

    async def _execute_specification(
        self,
        state: DynamicDiagnosisState,
        decision: ActionDecision,
        fingerprint: str,
    ) -> StateUpdate:
        arguments = SpecificationRetrievalArguments.model_validate(decision.tool_arguments)
        try:
            result = await self._specification_workflow.ainvoke(
                arguments.question,
                effective_at=self._effective_at,
                permission_scope=self._permission_scope,
                page_context=state["page_context"],
            )
        except Exception:
            return self._execution_failure(state, decision.action, fingerprint)
        return {
            "specification_result": result,
            "pending_observation": AgentObservation(
                action=decision.action,
                call_fingerprint=fingerprint,
                success=True,
                summary=(
                    f"规范检索状态={result.status.value}; citation_count={len(result.citations)}"
                ),
                has_new_information=result != state["specification_result"],
            ),
        }
    # 核心事实合并算法 根据动作类型，把Tool结果放入唯一对应的状态字段
    @staticmethod
    def _merge_business_fact(
        state: DynamicDiagnosisState,
        decision: ActionDecision,
        data: BaseModel,
    ) -> tuple[StateUpdate, str, bool]:
        action = decision.action
        if action is AgentAction.QUERY_ORDER and isinstance(data, OrderDetail):
            return {"order": data}, f"已读取订单状态={data.status}", data != state["order"]
        if action is AgentAction.QUERY_TASKS and isinstance(data, TaskList):
            tasks = [
                TaskDetail.model_validate(item.model_dump(by_alias=True))
                for item in sorted(data.tasks, key=lambda item: item.task_id)
            ]
            return {"tasks": tasks}, f"已读取关联任务数量={len(tasks)}", tasks != state["tasks"]
        task_id = cast(str, decision.tool_arguments.get("task_id"))
        if action is AgentAction.QUERY_PROGRESS and isinstance(data, ProgressResult):
            updated = {**state["progress"], task_id: data}
            return (
                {"progress": updated},
                f"已读取生产步骤数量={len(data.steps)}",
                updated != state["progress"],
            )
        if action is AgentAction.QUERY_QUALITY and isinstance(data, QualityIssueList):
            updated_issues = {**state["quality_issues"], task_id: data.issues}
            return (
                {"quality_issues": updated_issues},
                f"已读取质检问题数量={len(data.issues)}",
                updated_issues != state["quality_issues"],
            )
        if action is AgentAction.QUERY_REVIEW and isinstance(data, ReviewResult):
            updated_reviews = {**state["reviews"], task_id: data}
            return (
                {"reviews": updated_reviews},
                f"已读取复核记录数量={len(data.reviews)}",
                updated_reviews != state["reviews"],
            )
        if action is AgentAction.QUERY_DELIVERY and isinstance(data, DeliveryStatus):
            return (
                {"delivery": data},
                f"已读取交付记录数量={len(data.records)}",
                data != state["delivery"],
            )
        raise ValueError("tool output does not match dynamic action")

    @staticmethod
    def _validate_resource_identity(
        decision: ActionDecision,
        state: DynamicDiagnosisState,
    ) -> None:
        if decision.action in {
            AgentAction.QUERY_ORDER,
            AgentAction.QUERY_TASKS,
            AgentAction.QUERY_DELIVERY,
        }:
            if decision.tool_arguments.get("order_id") != state["order_id"]:
                raise ValueError("action order id does not match state")
            return
        task_ids = {item.task_id for item in state["tasks"]}
        if decision.tool_arguments.get("task_id") not in task_ids:
            raise ValueError("action task id is not present in state")

    def _validation_failure(self, state: DynamicDiagnosisState) -> StateUpdate:
        return {
            "errors": [
                *state["errors"],
                self._step_error("validate_action", ToolErrorCode.PARAM_VALIDATION_ERROR),
            ]
        }

    def _execution_failure(
        self,
        state: DynamicDiagnosisState,
        action: AgentAction,
        fingerprint: str,
    ) -> StateUpdate:
        del state
        error = self._step_error("execute_action", ToolErrorCode.RESPONSE_VALIDATION_ERROR)
        return {
            "pending_observation": AgentObservation(
                action=action,
                call_fingerprint=fingerprint,
                success=False,
                summary="只读动作未返回可识别的安全结果。",
                has_new_information=False,
                error=error,
            )
        }

    def _step_error(self, step_name: str, code: ToolErrorCode) -> StepError:
        return StepError(
            step_name=step_name,
            code=code,
            message=f"dynamic diagnosis stopped at {step_name}",
            retryable=False,
            trace_id=self._tool_context.trace_id,
        )

    @staticmethod
    def _route_after_initialize(state: DynamicDiagnosisState) -> StartRoute:
        return "exceptional" if state["errors"] else "plan"

    @staticmethod
    def _route_after_completion(state: DynamicDiagnosisState) -> CompletionRoute:
        if state["errors"]:
            return "exceptional"
        if state["termination_reason"] is not None:
            return "generate"
        return "continue"
