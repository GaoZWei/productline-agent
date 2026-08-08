"""通过 Java API 读取订单生产链路事实的七个 Tool。"""

from collections.abc import Mapping

from pydantic import BaseModel

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode, ToolException
from app.schemas.tools import (
    DeliveryStatus,
    OrderDetail,
    OrderIdInput,
    ProgressResult,
    QualityIssueList,
    ReviewResult,
    TaskDetail,
    TaskIdInput,
    TaskList,
)
from app.tools.base import BaseTool, ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.registry import ToolRegistry
from app.tools.retry import RetryPolicy

_READ_TOOL_TIMEOUT_SECONDS = 5.0
_READ_TOOL_MAX_RETRIES = 1
# 重试策略: 最多重试1次，每次等待避时间200ms，最大等待避时间1s
_READ_TOOL_RETRY_POLICY = RetryPolicy(
    max_retries=_READ_TOOL_MAX_RETRIES,
    initial_backoff_seconds=0.1,
    backoff_multiplier=2.0,
    max_backoff_seconds=1.0,
)
READ_TOOL_NAMES = frozenset(
    {
        "get_order_detail",
        "get_related_tasks",
        "get_task_detail",
        "get_production_progress",
        "get_quality_issues",
        "get_review_result",
        "get_delivery_status",
    }
)

# 只读 Tool 公共基础类
class _BusinessReadTool[InputT: BaseModel, OutputT: BaseModel](BaseTool[InputT, OutputT]):
    """保存共享 Client 并统一七个只读 Tool 的静态风险与重试元数据。"""

    def __init__(
        self,
        client: BusinessHttpClient,
        *,
        name: str,
        description: str,
        input_model: type[InputT],
        output_model: type[OutputT],
        permission: str,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            input_model=input_model,
            output_model=output_model,
            risk_level=ToolRiskLevel.LOW,  # 只读 Tool的静态风险较低。
            required_permissions=frozenset({permission}),  # 调用前必须拥有的权限
            timeout=_READ_TOOL_TIMEOUT_SECONDS,  # 整个 Tool 执行不能超过5秒
            max_retries=_READ_TOOL_MAX_RETRIES,
            retry_policy=_READ_TOOL_RETRY_POLICY,
        )
        self._client = client

    @staticmethod
    def _raise_resource_mismatch(trace_id: str) -> None:
        """阻断结构正确但资源标识与请求不一致的上游事实。"""

        raise ToolException(
            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            message="business service returned mismatched resource identifiers",
            retryable=False,
            trace_id=trace_id,
            status_code=200,
        )

# 订单详情 Tool: 根据订单 ID 查询订单基础事实。
class GetOrderDetailTool(_BusinessReadTool[OrderIdInput, OrderDetail]):
    """根据订单 ID 查询订单基础事实。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_order_detail",
            description="根据订单 ID 查询产品类型和订单状态",
            input_model=OrderIdInput,
            output_model=OrderDetail,
            permission="ORDER_READ",
        )
    # _execute 只处理业务调用, 不处理输入输出验证。
    async def _execute(
        self,
        tool_input: OrderIdInput,
        context: ToolContext,
    ) -> OrderDetail | Mapping[str, object]:
        response = await self._client.get(
            f"/api/orders/{tool_input.order_id}",
            OrderDetail,
            identity=context.identity,  # 从 Java 成功信封中的 data 必须符合 OrderDetail Schema
            trace_id=context.trace_id,
        )
        if response.data.order_id != tool_input.order_id:
            self._raise_resource_mismatch(response.trace_id)
        return response.data


class GetRelatedTasksTool(_BusinessReadTool[OrderIdInput, TaskList]):
    """根据订单 ID 查询按业务 ID 排序的关联任务。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_related_tasks",
            description="根据订单 ID 查询全部关联生产任务",
            input_model=OrderIdInput,
            output_model=TaskList,
            permission="ORDER_READ",
        )

    async def _execute(
        self,
        tool_input: OrderIdInput,
        context: ToolContext,
    ) -> TaskList | Mapping[str, object]:
        response = await self._client.get(
            f"/api/orders/{tool_input.order_id}/tasks",
            TaskList,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if response.data.order_id != tool_input.order_id or any(
            task.order_id != tool_input.order_id for task in response.data.tasks
        ):
            self._raise_resource_mismatch(response.trace_id)
        return response.data

# 任务详情 Tool: 根据任务 ID 查询任务事实。
class GetTaskDetailTool(_BusinessReadTool[TaskIdInput, TaskDetail]):
    """根据任务 ID 查询任务状态、所属订单和版本。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_task_detail",
            description="根据任务 ID 查询生产任务详情和并发版本",
            input_model=TaskIdInput,
            output_model=TaskDetail,
            permission="TASK_READ",
        )

    async def _execute(
        self,
        tool_input: TaskIdInput,
        context: ToolContext,
    ) -> TaskDetail | Mapping[str, object]:
        response = await self._client.get(
            f"/api/tasks/{tool_input.task_id}",
            TaskDetail,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if response.data.task_id != tool_input.task_id:
            self._raise_resource_mismatch(response.trace_id)
        return response.data

# 生产进度 Tool: 根据任务 ID 查询生产步骤。
class GetProductionProgressTool(_BusinessReadTool[TaskIdInput, ProgressResult]):
    """根据任务 ID 查询按业务顺序排列的生产步骤。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_production_progress",
            description="根据任务 ID 查询生产步骤和执行状态",
            input_model=TaskIdInput,
            output_model=ProgressResult,
            permission="TASK_READ",
        )

    async def _execute(
        self,
        tool_input: TaskIdInput,
        context: ToolContext,
    ) -> ProgressResult | Mapping[str, object]:
        response = await self._client.get(
            f"/api/tasks/{tool_input.task_id}/progress",
            ProgressResult,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if response.data.task_id != tool_input.task_id or any(
            step.task_id != tool_input.task_id for step in response.data.steps
        ):
            self._raise_resource_mismatch(response.trace_id)
        return response.data

# 质检问题 Tool: 根据任务 ID 查询质检问题。
class GetQualityIssuesTool(_BusinessReadTool[TaskIdInput, QualityIssueList]):
    """根据任务 ID 查询全部质检问题而不自行过滤事实。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_quality_issues",
            description="根据任务 ID 查询全部质检问题及当前状态",
            input_model=TaskIdInput,
            output_model=QualityIssueList,
            permission="QUALITY_ISSUE_READ",
        )

    async def _execute(
        self,
        tool_input: TaskIdInput,
        context: ToolContext,
    ) -> QualityIssueList | Mapping[str, object]:
        response = await self._client.get(
            f"/api/tasks/{tool_input.task_id}/quality-issues",
            QualityIssueList,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if response.data.task_id != tool_input.task_id or any(
            issue.task_id != tool_input.task_id for issue in response.data.issues
        ):
            self._raise_resource_mismatch(response.trace_id)
        return response.data

# 复核记录 Tool: 根据任务 ID 查询复核记录。
class GetReviewResultTool(_BusinessReadTool[TaskIdInput, ReviewResult]):
    """根据任务 ID 查询全部复核记录并保留空列表语义。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_review_result",
            description="根据任务 ID 查询全部质检复核记录",
            input_model=TaskIdInput,
            output_model=ReviewResult,
            permission="REVIEW_READ",
        )

    async def _execute(
        self,
        tool_input: TaskIdInput,
        context: ToolContext,
    ) -> ReviewResult | Mapping[str, object]:
        response = await self._client.get(
            f"/api/tasks/{tool_input.task_id}/review",
            ReviewResult,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if response.data.task_id != tool_input.task_id:
            self._raise_resource_mismatch(response.trace_id)
        return response.data

# 交付状态 Tool: 根据订单 ID 查询交付记录。
class GetDeliveryStatusTool(_BusinessReadTool[OrderIdInput, DeliveryStatus]):
    """根据订单 ID 查询全部交付记录而不猜测最新状态。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        super().__init__(
            client,
            name="get_delivery_status",
            description="根据订单 ID 查询全部交付记录及状态",
            input_model=OrderIdInput,
            output_model=DeliveryStatus,
            permission="DELIVERY_READ",
        )

    async def _execute(
        self,
        tool_input: OrderIdInput,
        context: ToolContext,
    ) -> DeliveryStatus | Mapping[str, object]:
        response = await self._client.get(
            f"/api/orders/{tool_input.order_id}/delivery-status",
            DeliveryStatus,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if response.data.order_id != tool_input.order_id or any(
            record.order_id != tool_input.order_id for record in response.data.records
        ):
            self._raise_resource_mismatch(response.trace_id)
        return response.data

# 模型注册位置
def create_read_tool_registry(client: BusinessHttpClient) -> ToolRegistry:
    """使用同一个应用级 HTTP Client 注册全部七个只读 Tool。"""

    registry = ToolRegistry()
    for tool in (
        GetOrderDetailTool(client),
        GetRelatedTasksTool(client),
        GetTaskDetailTool(client),
        GetProductionProgressTool(client),
        GetQualityIssuesTool(client),
        GetReviewResultTool(client),
        GetDeliveryStatusTool(client),
    ):
        registry.register(tool)
    return registry
