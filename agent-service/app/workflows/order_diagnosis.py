"""M2.5-M2.6 固定订单事实加载与确定性阻塞阶段诊断图。"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from itertools import pairwise
from typing import Any, Literal, TypeVar, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ValidationError

from app.errors import ToolErrorCode
from app.models import AgentStepType
from app.schemas.tools import (
    DeliveryStatus,
    OrderDetail,
    OrderIdInput,
    ProgressResult,
    QualityIssue,
    QualityIssueList,
    ReviewResult,
    TaskDetail,
    TaskList,
)
from app.schemas.workflow import OrderDiagnosisState, StepError
from app.tools import ToolContext, ToolError, ToolNotRegisteredError, ToolRegistry
from app.workflows.diagnosis_rules import evaluate_diagnosis_rules
from app.workflows.recording import WorkflowStepRecorder

DataT = TypeVar("DataT", bound=BaseModel)
type StateUpdate = dict[str, object]
type RouteDecision = Literal["continue", "stop"]

_LOADER_NODES = (
    "load_context",
    "load_order",
    "load_tasks",
    "load_progress",
    "load_quality",
    "load_review",
    "load_delivery",
)

# 订单诊断工作流
class OrderDiagnosisWorkflow:
    """按固定顺序读取 Java 事实并计算阶段, 在首个错误处停止。"""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,  # 找到需要调用的只读Tool实例
        tool_context: ToolContext,  # 保存身份、权限、Trace ID、Run ID和重复调用账本
        step_recorder: WorkflowStepRecorder,  # 记录每次节点开始、成功、失败和耗时
    ) -> None:
        self._tool_registry = tool_registry
        self._tool_context = tool_context
        self._step_recorder = step_recorder
        self._next_sequence_number = 1
        self._invoked = False
        self.graph = self._build_graph()

    async def ainvoke(self, order_id: str) -> OrderDiagnosisState:
        """执行一次绑定当前 ToolContext 的固定图, 同一实例不允许重复运行。"""
        # 一个Workflow实例只能执行一次, 避免重复调用
        if self._invoked:
            raise RuntimeError("one workflow instance can only execute once")
        self._invoked = True
        result = await self.graph.ainvoke(
            {
                "run_id": self._tool_context.run_id,
                "order_id": order_id,
            }
        )
        return cast(OrderDiagnosisState, result)
    # 图构建代码(重点)
    def _build_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """编译线性加载与规则图, Tool错误路由只进入 END。"""
        # 先定义共享状态通道
        builder = StateGraph(OrderDiagnosisState)
        # 注册节点 add_node只是注册“节点名称对应哪个Python函数”, 并没有说明执行顺序
        builder.add_node("load_context", self.load_context)
        builder.add_node("load_order", self.load_order)
        builder.add_node("load_tasks", self.load_tasks)
        builder.add_node("load_progress", self.load_progress)
        builder.add_node("load_quality", self.load_quality)
        builder.add_node("load_review", self.load_review)
        builder.add_node("load_delivery", self.load_delivery)
        builder.add_node("diagnose_by_rules", self.diagnose_by_rules)
        # 执行顺序由边决定
        builder.add_edge(START, "load_context")
        # 后续节点使用条件边, 根据路由决策继续执行或停止
        for current_name, next_name in pairwise(_LOADER_NODES):
            builder.add_conditional_edges(
                current_name,
                self._route_after_node,
                {"continue": next_name, "stop": END},
            )
        builder.add_conditional_edges(
            "load_delivery",
            self._route_after_node,
            {"continue": "diagnose_by_rules", "stop": END},
        )
        builder.add_edge("diagnose_by_rules", END)
        return builder.compile(name="order-diagnosis-rules")
    # 不调用Java, 它负责初始化执行上下文
    async def load_context(self, state: OrderDiagnosisState) -> StateUpdate:
        """校验 Run 与订单上下文, 并初始化全部 Workflow 状态通道。"""

        step_id = await self._start_step(
            step_name="load_context",
            step_type=AgentStepType.CONTEXT,
            input_summary=f"order_id={state.get('order_id', '')}",
        )
        # 初始化状态通道
        base_state: StateUpdate = {
            "run_id": self._tool_context.run_id,
            "order_id": state.get("order_id", ""),
            "order": None,
            "tasks": [],
            "progress": {},
            "quality_issues": {},
            "reviews": {},
            "delivery": None,
            "rule_decision": None,
            "diagnosis": None,
            "errors": [],
        }
        # Run一致性: 避免Workflow状态说自己属于run-A, ToolContext却使用run-B的身份和调用账本
        try:
            if state.get("run_id") != self._tool_context.run_id:
                raise ValueError("workflow run_id does not match ToolContext")
            # 订单ID校验: 确保订单ID是有效的字符串
            validated_input = OrderIdInput.model_validate(
                {"order_id": state.get("order_id")}
            )
        except (ValidationError, ValueError):
            error = StepError(
                step_name="load_context",
                code=ToolErrorCode.PARAM_VALIDATION_ERROR,
                message="workflow context validation failed",
                retryable=False,
                trace_id=self._tool_context.trace_id,
            )
            await self._step_recorder.mark_failed(
                step_id,
                error_code=error.code.value,
                output_summary=f"code={error.code.value}",
            )
            return {**base_state, "errors": [error]}

        await self._step_recorder.mark_succeeded(
            step_id,
            output_summary=f"order_id={validated_input.order_id}",
        )
        return {**base_state, "order_id": validated_input.order_id}
    # 订单节点load_order负责查询订单详情并写入状态通道
    async def load_order(self, state: OrderDiagnosisState) -> StateUpdate:
        """调用 get_order_detail 并写入订单事实。"""

        result = await self._invoke_tool(
            step_name="load_order",
            tool_name="get_order_detail",
            raw_input={"order_id": state["order_id"]},
            expected_type=OrderDetail,
            input_summary=f"order_id={state['order_id']}",
            output_summary=lambda order: f"status={order.status}",
        )
        if isinstance(result, StepError):
            return self._failed_update(state, result)
        return {"order": result}
    # 订单节点load_tasks负责查询关联任务并转换为 Workflow 统一使用的 TaskDetail
    async def load_tasks(self, state: OrderDiagnosisState) -> StateUpdate:
        """查询关联任务并转换为 Workflow 统一使用的 TaskDetail。"""

        result = await self._invoke_tool(
            step_name="load_tasks",
            tool_name="get_related_tasks",
            raw_input={"order_id": state["order_id"]},
            expected_type=TaskList,
            input_summary=f"order_id={state['order_id']}",
            output_summary=lambda task_list: f"task_count={len(task_list.tasks)}",
        )
        if isinstance(result, StepError):
            return self._failed_update(state, result)
        tasks = [
            TaskDetail.model_validate(task.model_dump(by_alias=True))
            for task in sorted(result.tasks, key=lambda task: task.task_id)
        ]
        return {"tasks": tasks}

    async def load_progress(self, state: OrderDiagnosisState) -> StateUpdate:
        """按任务稳定顺序查询生产进度, 全部成功后一次性合并。"""

        progress: dict[str, ProgressResult] = {}
        for task in state["tasks"]:
            result = await self._invoke_tool(
                step_name="load_progress",
                tool_name="get_production_progress",
                raw_input={"task_id": task.task_id},
                expected_type=ProgressResult,
                input_summary=f"task_id={task.task_id}",
                output_summary=lambda item: f"step_count={len(item.steps)}",
            )
            if isinstance(result, StepError):
                return self._failed_update(state, result)
            progress[task.task_id] = result
        # 只有所有任务查询成功, 才返回
        return {"progress": progress}

    async def load_quality(self, state: OrderDiagnosisState) -> StateUpdate:
        """按任务查询全部质检问题, 保留空列表与问题原始状态。"""

        quality_issues: dict[str, list[QualityIssue]] = {}
        for task in state["tasks"]:
            result = await self._invoke_tool(
                step_name="load_quality",
                tool_name="get_quality_issues",
                raw_input={"task_id": task.task_id},
                expected_type=QualityIssueList,
                input_summary=f"task_id={task.task_id}",
                output_summary=lambda item: f"issue_count={len(item.issues)}",
            )
            if isinstance(result, StepError):
                return self._failed_update(state, result)
            quality_issues[task.task_id] = list(result.issues)
        return {"quality_issues": quality_issues}

    async def load_review(self, state: OrderDiagnosisState) -> StateUpdate:
        """按任务查询复核结果, 不把无复核记录误判为成功。"""

        reviews: dict[str, ReviewResult | None] = {}
        for task in state["tasks"]:
            result = await self._invoke_tool(
                step_name="load_review",
                tool_name="get_review_result",
                raw_input={"task_id": task.task_id},
                expected_type=ReviewResult,
                input_summary=f"task_id={task.task_id}",
                output_summary=lambda item: f"review_count={len(item.reviews)}",
            )
            if isinstance(result, StepError):
                return self._failed_update(state, result)
            reviews[task.task_id] = result
        return {"reviews": reviews}

    async def load_delivery(self, state: OrderDiagnosisState) -> StateUpdate:
        """调用 get_delivery_status 并写入订单全部交付记录。"""

        result = await self._invoke_tool(
            step_name="load_delivery",
            tool_name="get_delivery_status",
            raw_input={"order_id": state["order_id"]},
            expected_type=DeliveryStatus,
            input_summary=f"order_id={state['order_id']}",
            output_summary=lambda delivery: f"record_count={len(delivery.records)}",
        )
        if isinstance(result, StepError):
            return self._failed_update(state, result)
        return {"delivery": result}

    async def diagnose_by_rules(self, state: OrderDiagnosisState) -> StateUpdate:
        """计算稳定阻塞阶段, 并把规则执行作为独立 Step 记录。"""

        step_id = await self._start_step(
            step_name="diagnose_by_rules",
            step_type=AgentStepType.RULE,
            input_summary=(
                f"order_id={state['order_id']}; task_count={len(state['tasks'])}"
            ),
        )
        decision = evaluate_diagnosis_rules(state)
        await self._step_recorder.mark_succeeded(
            step_id,
            output_summary=f"blocking_stage={decision.blocking_stage.value}",
        )
        return {"rule_decision": decision}
    # 所有业务节点最终都会进入
    async def _invoke_tool(
        self,
        *,
        step_name: str,
        tool_name: str,
        raw_input: dict[str, object],
        expected_type: type[DataT],
        input_summary: str,
        output_summary: Callable[[DataT], str],
    ) -> DataT | StepError:
        """记录一次 Tool Step, 并把标准失败转换为 Workflow StepError。"""

        step_id = await self._start_step(
            step_name=step_name,
            step_type=AgentStepType.TOOL,
            input_summary=input_summary,
        )
        try:
            tool = self._tool_registry.get(tool_name)
            tool_result = await tool.execute(raw_input, self._tool_context)
        except ToolNotRegisteredError:  # 如果注册表里找不到Tool, 返回错误
            error = ToolError(
                code=ToolErrorCode.UNKNOWN_TOOL_ERROR,
                message="required workflow tool is not registered",
                retryable=False,
                trace_id=self._tool_context.trace_id,
            )
            return await self._record_tool_failure(step_id, step_name, error)

        if not tool_result.success:
            if tool_result.error is None:
                raise RuntimeError("failed ToolResult must contain an error")
            return await self._record_tool_failure(step_id, step_name, tool_result.error)
        if not isinstance(tool_result.data, expected_type):  # 防止注册配置错误, 校验数据类型
            error = ToolError(
                code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                message="workflow received an unexpected tool result type",
                retryable=False,
                trace_id=self._tool_context.trace_id,
            )
            return await self._record_tool_failure(step_id, step_name, error)

        validated_data = tool_result.data
        await self._step_recorder.mark_succeeded(
            step_id,
            output_summary=output_summary(validated_data),
        )
        return validated_data

    async def _record_tool_failure(
        self,
        step_id: str,
        step_name: str,
        error: ToolError,
    ) -> StepError:
        """持久化安全失败摘要, 并返回图状态可以消费的错误。"""

        await self._step_recorder.mark_failed(
            step_id,
            error_code=error.code.value,
            output_summary=f"code={error.code.value}; retryable={str(error.retryable).lower()}",
        )
        return StepError(
            step_name=step_name,
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            trace_id=error.trace_id,
        )

    async def _start_step(
        self,
        *,
        step_name: str,
        step_type: AgentStepType,
        input_summary: str,
    ) -> str:
        """分配稳定序号和不可泄露 Run 原文的 Step ID。"""

        sequence_number = self._next_sequence_number
        self._next_sequence_number += 1
        digest = sha256(
            f"{self._tool_context.run_id}:{sequence_number}:{step_name}".encode()
        ).hexdigest()[:32]
        step_id = f"workflow-step-{digest}"
        await self._step_recorder.start_step(
            step_id=step_id,
            run_id=self._tool_context.run_id,
            sequence_number=sequence_number,
            step_type=step_type,
            step_name=step_name,
            input_summary=input_summary,
        )
        return step_id

    @staticmethod
    def _failed_update(state: OrderDiagnosisState, error: StepError) -> StateUpdate:
        """保留已有错误并追加当前首个失败。"""

        return {"errors": [*state["errors"], error]}
    # 每个节点之后检查error是否为空, 为空就继续执行下一个节点, 否则结束图
    @staticmethod
    def _route_after_node(state: OrderDiagnosisState) -> RouteDecision:
        """存在错误时结束图, 否则进入固定的下一个节点。"""

        return "stop" if state["errors"] else "continue"
