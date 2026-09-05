"""订单与任务状态查询的确定性只读 Workflow。"""

from __future__ import annotations

from app.routing import BusinessSkill, Intent, skill_for_intent
from app.schemas.agent_messages import OrderStatusResult, OrderStatusSubject
from app.schemas.routing import RoutingDecision
from app.schemas.tools import OrderDetail, TaskDetail
from app.tools import ToolContext, ToolRegistry


class OrderStatusWorkflowError(RuntimeError):
    """状态查询 Tool 失败或返回类型不符合只读契约。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        error_step: str,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.error_step = error_step
        super().__init__(f"{code}: {message}")

# 订单状态查询skill的Workflow 处理订单状态和任务状态查询意图
class OrderStatusWorkflow:
    """根据已通过路由门禁的意图执行唯一匹配的 Java 只读 Tool。"""

    def __init__(self, *, tool_registry: ToolRegistry, tool_context: ToolContext) -> None:
        self._tool_registry = tool_registry
        self._tool_context = tool_context

    async def execute(self, decision: RoutingDecision) -> OrderStatusResult:
        """查询订单或任务状态, 结果字段只取自 Java Tool 返回事实。"""
        # 执行前先检查路由决策是否符合要求
        if (
            not decision.can_dispatch
            or skill_for_intent(decision.intent) is not BusinessSkill.ORDER_STATUS
        ):
            raise OrderStatusWorkflowError(
                code="SKILL_DISPATCH_INVALID",
                message="routing decision cannot dispatch to OrderStatusSkill",
                retryable=False,
                error_step="order_status",
            )
        entities = decision.entities.to_router_entities()
        # 订单查询核心代码
        if decision.intent is Intent.ORDER_QUERY and entities.order_id is not None:
            result = await self._tool_registry.get("get_order_detail").execute(
                {"order_id": entities.order_id},
                self._tool_context,
            )
            if not result.success:
                raise self._tool_error(result.error, "get_order_detail")
            if not isinstance(result.data, OrderDetail):
                raise self._response_error("get_order_detail")
            return OrderStatusResult(
                subject=OrderStatusSubject.ORDER,
                order_id=result.data.order_id,
                status=result.data.status,
                summary=f"订单 {result.data.order_id} 当前状态为 {result.data.status}。",
            )

        if decision.intent is Intent.TASK_TRACKING and entities.task_id is not None:
            result = await self._tool_registry.get("get_task_detail").execute(
                {"task_id": entities.task_id},
                self._tool_context,
            )
            if not result.success:
                raise self._tool_error(result.error, "get_task_detail")
            if not isinstance(result.data, TaskDetail):
                raise self._response_error("get_task_detail")
            return OrderStatusResult(
                subject=OrderStatusSubject.TASK,
                order_id=result.data.order_id,
                task_id=result.data.task_id,
                status=result.data.status,
                summary=f"任务 {result.data.task_id} 当前状态为 {result.data.status}。",
            )

        raise OrderStatusWorkflowError(
            code="SKILL_DISPATCH_INVALID",
            message="order status routing decision is missing its required entity",
            retryable=False,
            error_step="order_status",
        )

    @staticmethod
    def _tool_error(error: object, step_name: str) -> OrderStatusWorkflowError:
        """把标准 ToolError 转换为不泄露上游正文的 Workflow 错误。"""

        code = getattr(error, "code", None)
        message = getattr(error, "message", None)
        retryable = getattr(error, "retryable", None)
        if code is None or not isinstance(message, str) or not isinstance(retryable, bool):
            return OrderStatusWorkflow._response_error(step_name)
        return OrderStatusWorkflowError(
            code=code.value,
            message=message,
            retryable=retryable,
            error_step=step_name,
        )

    @staticmethod
    def _response_error(step_name: str) -> OrderStatusWorkflowError:
        return OrderStatusWorkflowError(
            code="RESPONSE_VALIDATION_ERROR",
            message="status tool returned an incompatible result",
            retryable=False,
            error_step=step_name,
        )


__all__ = ["OrderStatusWorkflow", "OrderStatusWorkflowError"]
