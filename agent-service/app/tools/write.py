"""只从已确认Approval映射参数并调用Java的两个高风险写Tool。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn

from pydantic import BaseModel

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode, ToolException
from app.models import ApprovalStatus, PendingToolName
from app.schemas import ReworkType
from app.schemas.write_tools import (
    CreateReworkTaskInput,
    CreateReworkTaskOutput,
    ReviewWriteResponseData,
    ReworkWriteResponseData,
    WriteReviewResultInput,
    WriteReviewResultOutput,
)
from app.services.approval_execution_store import (
    ApprovalExecutionSnapshot,
    ApprovalExecutionStore,
)
from app.tools.base import BaseTool, ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.registry import ToolRegistry

_WRITE_TOOL_TIMEOUT_SECONDS = 10.0
WRITE_TOOL_NAMES = frozenset({"write_review_result", "create_rework_task"})

# 两个写Tool共享的安全基类
class _BusinessWriteTool[InputT: BaseModel, OutputT: BaseModel](BaseTool[InputT, OutputT]):
    """统一保存Java Client、Approval Store和不可重试写操作元数据。"""

    def __init__(
        self,
        client: BusinessHttpClient,
        store: ApprovalExecutionStore,
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
            risk_level=ToolRiskLevel.HIGH,  # 高风险操作
            required_permissions=frozenset({permission}),
            timeout=_WRITE_TOOL_TIMEOUT_SECONDS,
            max_retries=0,  # 不可重试操作
            retry_policy=None,
        )
        self._client = client
        self._store = store

    # 执行前读取Approval快照，确保Approval状态符合预期
    async def _require_execution_snapshot(
        self,
        approval_id: str,
        *,
        expected_tool: PendingToolName,
        context: ToolContext,
    ) -> ApprovalExecutionSnapshot:
        approval = await self._store.get_execution_snapshot(approval_id)
        # Approval必须存在
        if approval is None:
            self._raise(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                "approval was not found",
                context=context,
                status_code=404,
            )
        # 必须处于EXECUTING状态
        if approval.status is not ApprovalStatus.EXECUTING:
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "approval is not locked for execution",
                context=context,
                status_code=409,
            )
        # Approval指定的Tool必须匹配预期Tool
        if approval.pending_tool_name is not expected_tool:
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "approval is assigned to another write tool",
                context=context,
                status_code=409,
            )
        # 调用人必须是确认人
        if (
            approval.confirmed_by_user_id is None
            or approval.confirmed_by_user_id != context.identity.user_id
        ):
            self._raise(
                ToolErrorCode.PERMISSION_DENIED,
                "approval was not confirmed by the current user",
                context=context,
                status_code=403,
            )
        if approval.target_id != approval.draft.task_id:
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "approval draft target does not match the execution target",
                context=context,
            )
        return approval

    async def _save_result(
        self,
        approval_id: str,
        output: OutputT,
        *,
        context: ToolContext,
    ) -> None:
        saved = await self._store.save_execution_result(
            approval_id,
            result=output.model_dump(mode="json"),
        )
        if not saved:
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "approval execution result could not be saved",
                context=context,
                status_code=409,
            )

    @staticmethod
    def _raise(
        code: ToolErrorCode,
        message: str,
        *,
        context: ToolContext,
        status_code: int | None = None,
    ) -> NoReturn:
        raise ToolException(
            code=code,
            message=message,
            retryable=False,
            trace_id=context.trace_id,
            status_code=status_code,
        )

# 复核回写流程Tool
class WriteReviewResultTool(
    _BusinessWriteTool[WriteReviewResultInput, WriteReviewResultOutput]
):
    """把已确认复核草稿映射到Java复核写接口并保存成功结果。"""

    def __init__(self, client: BusinessHttpClient, store: ApprovalExecutionStore) -> None:
        super().__init__(
            client,
            store,
            name="write_review_result",
            description="提交已经人工确认的复核结论和意见",
            input_model=WriteReviewResultInput,
            output_model=WriteReviewResultOutput,
            permission="REVIEW_WRITE",
        )

    async def _execute(
        self,
        tool_input: WriteReviewResultInput,
        context: ToolContext,
    ) -> WriteReviewResultOutput | Mapping[str, object]:
        approval = await self._require_execution_snapshot(
            tool_input.approval_id,
            expected_tool=PendingToolName.WRITE_REVIEW_RESULT,
            context=context,
        )
        draft = approval.draft
        # 从Approval构造Java请求参数
        response = await self._client.post(
            f"/api/tasks/{approval.target_id}/review",
            ReviewWriteResponseData,
            json_body={
                "issueId": draft.issue_id,
                "status": draft.conclusion.value,
                "reviewComment": draft.review_comment,
                "expectedVersion": approval.target_version,
            },
            identity=context.identity,
            trace_id=context.trace_id,
            idempotency_key=tool_input.idempotency_key,
        )
        review = response.data.review
        # 校验Java响应是否与请求一致
        if (
            review.issue_id != draft.issue_id
            or review.status != draft.conclusion.value
            or review.review_comment != draft.review_comment
            or response.data.task_version != approval.target_version + 1
        ):
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "business service returned a mismatched review write result",
                context=context,
                status_code=200,
            )
        # 构造执行结果
        output = WriteReviewResultOutput(
            approval_id=approval.approval_id,
            task_id=approval.target_id,
            issue_id=review.issue_id,
            review_id=review.review_id,
            status=review.status,
            review_comment=review.review_comment,
            task_version=response.data.task_version,
            java_trace_id=response.trace_id,
        )
        await self._save_result(approval.approval_id, output, context=context)
        return output

# 返工创建流程Tool
class CreateReworkTaskTool(
    _BusinessWriteTool[CreateReworkTaskInput, CreateReworkTaskOutput]
):
    """从已确认坐标系返工草稿创建Java返工任务并保存新任务身份。"""

    def __init__(self, client: BusinessHttpClient, store: ApprovalExecutionStore) -> None:
        super().__init__(
            client,
            store,
            name="create_rework_task",
            description="为已经人工确认的坐标系问题创建返工任务",
            input_model=CreateReworkTaskInput,
            output_model=CreateReworkTaskOutput,
            permission="REWORK_WRITE",
        )

    async def _execute(
        self,
        tool_input: CreateReworkTaskInput,
        context: ToolContext,
    ) -> CreateReworkTaskOutput | Mapping[str, object]:
        approval = await self._require_execution_snapshot(
            tool_input.approval_id,
            expected_tool=PendingToolName.CREATE_REWORK_TASK,
            context=context,
        )
        draft = approval.draft
        rework_type = draft.suggested_rework.type
        # 再次校验返工语义是否符合预期
        if (
            draft.conclusion.value != "REWORK_REQUIRED"  # 需要满足复核结论 = REWORK_REQUIRED
            or not draft.suggested_rework.required  # 需要满足建议返工 = true
            or rework_type is not ReworkType.COORDINATE_SYSTEM_FIX  #  需要满足返工类型 = COORDINATE_SYSTEM_FIX
        ):
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "approval does not authorize a supported rework type",
                context=context,
                status_code=409,
            )
        response = await self._client.post(
            f"/api/tasks/{approval.target_id}/rework",
            ReworkWriteResponseData,
            # 映射Java返工接口参数
            json_body={
                "sourceIssueId": draft.issue_id,
                "reason": draft.review_comment,
                "expectedVersion": approval.target_version,
            },
            identity=context.identity,
            trace_id=context.trace_id,
            idempotency_key=tool_input.idempotency_key,
        )
        rework = response.data.rework_task
        # 校验返回的返工任务是否与请求一致
        if (
            rework.task_id != approval.target_id
            or rework.source_issue_id != draft.issue_id
            or rework.reason != draft.review_comment
            or response.data.task_version != approval.target_version + 1
        ):
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "business service returned a mismatched rework task",
                context=context,
                status_code=200,
            )
        output = CreateReworkTaskOutput(
            approval_id=approval.approval_id,
            task_id=rework.task_id,
            source_issue_id=rework.source_issue_id,
            rework_task_id=rework.rework_task_id,
            rework_type=rework_type,
            status=rework.status,
            reason=rework.reason,
            task_version=response.data.task_version,
            java_trace_id=response.trace_id,
        )
        await self._save_result(approval.approval_id, output, context=context)
        return output


def create_write_tool_registry(
    client: BusinessHttpClient,
    store: ApprovalExecutionStore,
) -> ToolRegistry:
    """创建不暴露给动态模型、只供确认执行链使用的写Tool注册表。"""

    registry = ToolRegistry()
    registry.register(WriteReviewResultTool(client, store))
    registry.register(CreateReworkTaskTool(client, store))
    return registry
