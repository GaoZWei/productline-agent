"""T824独立只读核对Tool，不写业务、不取得执行权、不恢复Approval终态。"""

from datetime import UTC, datetime
from typing import NoReturn

from pydantic import ValidationError

from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.models import ApprovalStatus
from app.schemas.rework_operation_query import (
    ReworkOperationLookupInput,
    ReworkOperationQueryRequest,
    ReworkOperationResolution,
)
from app.schemas.rework_write_tools import ReworkExecutionSnapshot
from app.services.rework_execution import ReworkExecutionStore
from app.services.rework_receipts import validate_rework_receipt_binding
from app.tools.models import ToolContext
from app.tools.registry import ToolRegistry
from app.tools.retry import RetryPolicy
from app.tools.rework_readonly import _ReworkReadTool


class QueryReworkOperationTool(
    _ReworkReadTool[ReworkOperationLookupInput, ReworkOperationResolution]
):
    """从受信原确认快照读取目标和原键，只核对可见成功回执。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        store: ReworkExecutionStore,
        *,
        timeout: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """沿用只读权限/去重/总预算和最多一次瞬时重试，保持独立注册。"""

        super().__init__(
            client,
            name="query_rework_operation",
            description="按原确认快照核对Java首次成功回执。未见回执仍未知，不授权重发",
            input_model=ReworkOperationLookupInput,
            output_model=ReworkOperationResolution,
            timeout=timeout,
            retry_policy=retry_policy,
        )
        self._store = store

    async def _snapshot(
        self, tool_input: ReworkOperationLookupInput, context: ToolContext
    ) -> ReworkExecutionSnapshot:
        """复制服务端快照，校验所有权和曾实际确认，不接受调用方生成的快照。"""

        stored = await self._store.get_execution_snapshot(tool_input.approval_id)
        if stored is None:
            self._raise(ToolErrorCode.RESOURCE_NOT_FOUND, "approval was not found", context)
        if not isinstance(stored, ReworkExecutionSnapshot):
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR, "invalid execution snapshot", context
            )
        try:
            approval = ReworkExecutionSnapshot.model_validate(stored.model_dump(mode="python"))
        except ValidationError:
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "invalid execution snapshot binding",
                context,
            )
        if approval.approval_id != tool_input.approval_id:
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "execution snapshot identity mismatch",
                context,
            )
        if (
            approval.owner_user_id != context.identity.user_id
            or approval.run_id != context.run_id
            or approval.confirmed_by_user_id != context.identity.user_id
        ):
            self._raise(
                ToolErrorCode.PERMISSION_DENIED,
                "approval does not belong to this confirmed user and run",
                context,
            )
        if (
            approval.status
            not in {ApprovalStatus.EXECUTING, ApprovalStatus.SUCCEEDED, ApprovalStatus.FAILED}
            or approval.confirmed_at is None
            or approval.confirmed_at > datetime.now(UTC)
            or approval.confirmed_at >= approval.expires_at
        ):
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "approval has no confirmed execution snapshot",
                context,
            )
        if approval.idempotency_key != tool_input.idempotency_key:
            self._raise(ToolErrorCode.BUSINESS_CONFLICT, "key differs from confirmation", context)
        # 已确认执行后的过期不阻止只读核对，绝不因此恢复写权限。
        return approval

    async def _execute(
        self, tool_input: ReworkOperationLookupInput, context: ToolContext
    ) -> ReworkOperationResolution:
        """成功查询也不保存执行结果，回执与确认终态的持久化留给确认服务。"""

        approval = await self._snapshot(tool_input, context)
        response = await self._client.query_operation(
            approval.task_id,
            ReworkOperationQueryRequest(idempotency_key=approval.idempotency_key),
            identity=context.identity,
            trace_id=context.trace_id,
        )
        receipt = response.data.receipt
        if receipt is not None:
            self._client.check_write_receipt(
                approval.task_id,
                approval.rework_task_id,
                approval.operation,
                approval.request,
                receipt,
                context.trace_id,
            )
            validate_rework_receipt_binding(approval, receipt, context.trace_id)
        # 查询期间确认可能改动。旧响应不能被呈现为新快照的核对结果。
        if await self._snapshot(tool_input, context) != approval:
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT, "confirmation changed during lookup", context
            )
        return ReworkOperationResolution(
            approval_id=approval.approval_id,
            outcome="MATCHED_RECEIPT" if receipt is not None else "UNKNOWN",
            receipt=receipt,
            java_trace_id=response.trace_id,
        )

    @staticmethod
    def _raise(code: ToolErrorCode, message: str, context: ToolContext) -> NoReturn:
        """错误保留既有分类，不输出原键、材料或确认正文。"""

        raise ToolException(code=code, message=message, retryable=False, trace_id=context.trace_id)


def create_rework_operation_query_tool_registry(
    client: ReworkHttpClient,
    store: ReworkExecutionStore,
    *,
    timeout: float = 5.0,
    retry_policy: RetryPolicy | None = None,
) -> ToolRegistry:
    """仅显式创建一个独立核对Tool，不改旧注册表、生产白名单或lifespan。"""

    registry = ToolRegistry()
    registry.register(
        QueryReworkOperationTool(client, store, timeout=timeout, retry_policy=retry_policy)
    )
    return registry
