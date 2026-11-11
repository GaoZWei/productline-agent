"""M8六个内部只读Tool及独立注册表，尚未加入生产Agent动作白名单。"""

from pydantic import BaseModel

from app.clients.rework import ReworkHttpClient
from app.schemas.rework import (
    EffectiveReworkReviews,
    ReworkDetail,
    ReworkHistoryPage,
    ReworkInspection,
    ReworkPageQuery,
    ReworkProcessing,
    ReworkResource,
    ReworkReview,
)
from app.schemas.rework_delivery import DeliveryConditions
from app.schemas.rework_tools import ReworkHistoryInput, ReworkOrderInput, ReworkTaskInput
from app.tools.base import BaseTool, ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.registry import ToolRegistry
from app.tools.retry import RetryPolicy

REWORK_READ_TOOL_NAMES = frozenset(
    {
        "get_rework_detail",
        "get_rework_results",
        "get_rework_inspections",
        "get_rework_reviews",
        "get_effective_rework_reviews",
        "get_delivery_conditions",
    }
)
_DEFAULT_RETRY_POLICY = RetryPolicy(max_retries=1)


class _ReworkReadTool[InputT: BaseModel, OutputT: BaseModel](BaseTool[InputT, OutputT]):
    """统一只读权限和总预算。实际重试仅发生在BaseTool，不叠加Client重试。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        name: str,
        description: str,
        input_model: type[InputT],
        output_model: type[OutputT],
        timeout: float,
        retry_policy: RetryPolicy | None,
    ) -> None:
        """默认最多额外重试一次。总超时覆盖HTTP、退避与输出校验。"""

        policy = _DEFAULT_RETRY_POLICY if retry_policy is None else retry_policy
        if not isinstance(policy, RetryPolicy) or policy.max_retries > 1:
            raise ValueError("rework read tools allow at most one retry")
        super().__init__(
            name=name,
            description=description,
            input_model=input_model,
            output_model=output_model,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=frozenset({"REWORK_READ"}),
            timeout=timeout,
            max_retries=policy.max_retries,
            retry_policy=policy,
        )
        self._client = client


class GetReworkDetailTool(_ReworkReadTool[ReworkResource, ReworkDetail]):
    """读取指定父任务下的返工详情，保留存量缺失和当前材料绑定。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """定义固定端点契约，不在构造或注册时读取Java。"""

        super().__init__(
            client,
            name="get_rework_detail",
            description="读取指定任务下的返工详情和当前材料。允许动作不是执行授权",
            input_model=ReworkResource,
            output_model=ReworkDetail,
            timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _execute(self, tool_input: ReworkResource, context: ToolContext) -> ReworkDetail:
        """身份和Trace取自上下文，归属及响应绑定由T821适配器重验。"""

        response = await self._client.get_detail(
            tool_input.task_id,
            tool_input.rework_task_id,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        return response.data


class GetReworkResultsTool(
    _ReworkReadTool[ReworkHistoryInput, ReworkHistoryPage[ReworkProcessing]]
):
    """只读一页处理修订，保留原始版本、说明和证据，不自动下载引用。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """固定处理历史模型和只读元数据。"""

        super().__init__(
            client,
            name="get_rework_results",
            description="读取一页返工处理修订和证据。不选择或推断有效复核",
            input_model=ReworkHistoryInput,
            output_model=ReworkHistoryPage[ReworkProcessing],
            timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _execute(
        self,
        tool_input: ReworkHistoryInput,
        context: ToolContext,
    ) -> ReworkHistoryPage[ReworkProcessing]:
        """只把limit/cursor发送给Java，不在重试期间自动翻页。"""

        response = await self._client.get_results(
            tool_input.task_id,
            tool_input.rework_task_id,
            page=ReworkPageQuery(limit=tool_input.limit, cursor=tool_input.cursor),
            identity=context.identity,
            trace_id=context.trace_id,
        )
        return response.data


class GetReworkInspectionsTool(
    _ReworkReadTool[ReworkHistoryInput, ReworkHistoryPage[ReworkInspection]]
):
    """读取人工检查历史，失败与旧修订的记录均完整保留。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """固定检查历史模型和只读元数据。"""

        super().__init__(
            client,
            name="get_rework_inspections",
            description="读取一页真实人工检查历史，保留失败记录。不运行成果检查",
            input_model=ReworkHistoryInput,
            output_model=ReworkHistoryPage[ReworkInspection],
            timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _execute(
        self,
        tool_input: ReworkHistoryInput,
        context: ToolContext,
    ) -> ReworkHistoryPage[ReworkInspection]:
        """透传同一页参数，当前检查仍由Java选择。"""

        response = await self._client.get_inspections(
            tool_input.task_id,
            tool_input.rework_task_id,
            page=ReworkPageQuery(limit=tool_input.limit, cursor=tool_input.cursor),
            identity=context.identity,
            trace_id=context.trace_id,
        )
        return response.data


class GetReworkReviewsTool(_ReworkReadTool[ReworkHistoryInput, ReworkHistoryPage[ReworkReview]]):
    """完整新复核历史用于审计，不能以任意通过替代当前有效复核。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """固定新复核历史模型和只读元数据。"""

        super().__init__(
            client,
            name="get_rework_reviews",
            description="读取一页受控复核历史用于审计。不从历史猜测当前有效结论",
            input_model=ReworkHistoryInput,
            output_model=ReworkHistoryPage[ReworkReview],
            timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _execute(
        self,
        tool_input: ReworkHistoryInput,
        context: ToolContext,
    ) -> ReworkHistoryPage[ReworkReview]:
        """只读当前页，不删除或合并不同轮次材料。"""

        response = await self._client.get_reviews(
            tool_input.task_id,
            tool_input.rework_task_id,
            page=ReworkPageQuery(limit=tool_input.limit, cursor=tool_input.cursor),
            identity=context.identity,
            trace_id=context.trace_id,
        )
        return response.data


class GetEffectiveReworkReviewsTool(_ReworkReadTool[ReworkTaskInput, EffectiveReworkReviews]):
    """读取Java已裁决的当前复核及独立存量事实，不修改诊断规则。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """固定任务级当前绑定模型和只读元数据。"""

        super().__init__(
            client,
            name="get_effective_rework_reviews",
            description="读取任务当前轮次/成果/检查绑定的有效复核及独立存量记录",
            input_model=ReworkTaskInput,
            output_model=EffectiveReworkReviews,
            timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _execute(
        self,
        tool_input: ReworkTaskInput,
        context: ToolContext,
    ) -> EffectiveReworkReviews:
        """只透传Java事实，不把null补为通过或失败。"""

        response = await self._client.get_effective_reviews(
            tool_input.task_id,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        return response.data


class GetDeliveryConditionsTool(_ReworkReadTool[ReworkOrderInput, DeliveryConditions]):
    """读取整单已知阻塞，hasBlockers不是完整交付资格或操作授权。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """使用M8只读权限和独立订单输入，不修改原交付Tool。"""

        super().__init__(
            client,
            name="get_delivery_conditions",
            description="读取同一订单快照中的生产/质量/复核/交付已知阻塞，不推进状态",
            input_model=ReworkOrderInput,
            output_model=DeliveryConditions,
            timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _execute(
        self,
        tool_input: ReworkOrderInput,
        context: ToolContext,
    ) -> DeliveryConditions:
        """只返回Java当前条件，不计算新的交付决定。"""

        response = await self._client.get_delivery_conditions(
            tool_input.order_id,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        return response.data


def create_rework_read_tool_registry(
    client: ReworkHttpClient,
    *,
    timeout: float = 5.0,
    retry_policy: RetryPolicy | None = None,
) -> ToolRegistry:
    """显式创建六Tool内部注册表，不改变旧七Tool或生产动作白名单。"""

    registry = ToolRegistry()
    for tool in (
        GetReworkDetailTool(client, timeout=timeout, retry_policy=retry_policy),
        GetReworkResultsTool(client, timeout=timeout, retry_policy=retry_policy),
        GetReworkInspectionsTool(client, timeout=timeout, retry_policy=retry_policy),
        GetReworkReviewsTool(client, timeout=timeout, retry_policy=retry_policy),
        GetEffectiveReworkReviewsTool(client, timeout=timeout, retry_policy=retry_policy),
        GetDeliveryConditionsTool(client, timeout=timeout, retry_policy=retry_policy),
    ):
        registry.register(tool)
    return registry
