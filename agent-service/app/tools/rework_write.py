"""M8独立高风险写Tool映射，必须注入受信确认Store，不加入生产Agent。"""

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import NoReturn, TypedDict

from pydantic import ValidationError

from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.models import ApprovalStatus
from app.schemas.business import BusinessIdentity, BusinessResponse
from app.schemas.rework import (
    CreateLifecycleReworkRequest,
    RegisterReworkInspectionRequest,
    RegisterReworkResultRequest,
    ReworkOperation,
    ReworkReasonRequest,
    ReworkVersionRequest,
    ReworkWriteReceipt,
    SubmitReworkReviewRequest,
)
from app.schemas.rework_write_tools import (
    ReworkExecutionSnapshot,
    ReworkWriteInput,
    ReworkWriteOutput,
)
from app.services.rework_execution import ReworkExecutionStore
from app.tools.base import BaseTool, ToolRiskLevel
from app.tools.models import ToolContext, ToolResult
from app.tools.registry import ToolRegistry

_OPERATIONS: Mapping[str, ReworkOperation] = MappingProxyType(
    {
        "create_lifecycle_rework": "CREATE_LIFECYCLE_REWORK",
        "start_rework": "START_REWORK",
        "block_rework": "BLOCK_REWORK",
        "fail_rework": "FAIL_REWORK",
        "resume_rework": "RESUME_REWORK",
        "register_rework_result": "REGISTER_REWORK_RESULT",
        "register_rework_inspection": "REGISTER_REWORK_INSPECTION",
        "submit_rework_review": "SUBMIT_REWORK_REVIEW",
        "create_next_rework": "CREATE_NEXT_REWORK",
    }
)
REWORK_WRITE_TOOL_NAMES = frozenset(_OPERATIONS)


class _WriteOptions(TypedDict):
    """只从服务端上下文和确认快照传递身份、Trace及已绑定键。"""

    identity: BusinessIdentity
    trace_id: str
    idempotency_key: str


class ReworkWriteTool(BaseTool[ReworkWriteInput, ReworkWriteOutput]):
    """检查执行快照与固定动作后仅提交一次Java请求，并以原快照保存结果。"""

    def __init__(
        self,
        client: ReworkHttpClient,
        store: ReworkExecutionStore,
        *,
        name: str,
        timeout: float = 10.0,
    ) -> None:
        """Tool名称只能来自固定映射，所有动作均HIGH风险且禁止自动重试。"""

        if name not in _OPERATIONS:
            raise ValueError("unknown rework write tool")
        operation = _OPERATIONS[name]
        super().__init__(
            name=name,
            description=f"执行独立人工确认后的{operation}，参数仅来自服务端确认快照",
            input_model=ReworkWriteInput,
            output_model=ReworkWriteOutput,
            risk_level=ToolRiskLevel.HIGH,
            required_permissions=frozenset(
                {"REVIEW_WRITE" if operation == "SUBMIT_REWORK_REVIEW" else "REWORK_WRITE"}
            ),
            timeout=timeout,
            max_retries=0,
            retry_policy=None,
        )
        self._client = client
        self._store = store
        self._operation = operation

    async def execute(
        self,
        raw_input: ReworkWriteInput | Mapping[str, object],
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> ToolResult[ReworkWriteOutput]:
        """保留公共门禁，外层预算超时也不得被标为可自动重试的业务写入。"""

        result = await super().execute(raw_input, context, force_refresh=force_refresh)
        if result.error is not None and result.error.retryable:
            return result.model_copy(
                update={"error": result.error.model_copy(update={"retryable": False})}
            )
        return result

    async def _execute(
        self, tool_input: ReworkWriteInput, context: ToolContext
    ) -> ReworkWriteOutput:
        """没有有效独立确认执行快照时，绝不产生HTTP或临时创建确认。"""

        stored = await self._store.get_execution_snapshot(tool_input.approval_id)
        if stored is None:
            self._raise(ToolErrorCode.RESOURCE_NOT_FOUND, "approval was not found", context, 404)
        if not isinstance(stored, ReworkExecutionSnapshot):
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR, "invalid execution snapshot", context
            )
        try:
            # 冻结模型仍可能含可变列表，重新复制校验后再跨await，不能借用Store对象的材料引用。
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
        if approval.owner_user_id != context.identity.user_id or approval.run_id != context.run_id:
            self._raise(
                ToolErrorCode.PERMISSION_DENIED,
                "approval does not belong to this user and run",
                context,
                403,
            )
        if approval.confirmed_by_user_id != context.identity.user_id:
            self._raise(
                ToolErrorCode.PERMISSION_DENIED,
                "approval was not confirmed by this user",
                context,
                403,
            )
        now = datetime.now(UTC)
        if (
            approval.status is not ApprovalStatus.EXECUTING
            or approval.confirmed_at is None
            or approval.confirmed_at > now
            or approval.confirmed_at >= approval.expires_at
            or approval.expires_at <= now
        ):
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT, "approval is not valid for execution", context, 409
            )
        if (
            approval.operation != self._operation
            or approval.idempotency_key != tool_input.idempotency_key
        ):
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "operation or key differs from confirmation",
                context,
                409,
            )
        response = await self._dispatch(approval, context)
        self._check_receipt(approval, response.data, context)
        output = ReworkWriteOutput(
            approval_id=approval.approval_id, receipt=response.data, java_trace_id=response.trace_id
        )
        if not await self._store.save_execution_result(approval, output):
            self._raise(
                ToolErrorCode.BUSINESS_CONFLICT,
                "confirmed Java result could not be saved",
                context,
                409,
            )
        return output

    async def _dispatch(
        self, approval: ReworkExecutionSnapshot, context: ToolContext
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """固定操作调用已验证Client，不接受任意路径、请求体或额外身份参数。"""

        options: _WriteOptions = {
            "identity": context.identity,
            "trace_id": context.trace_id,
            "idempotency_key": approval.idempotency_key,
        }
        match approval.operation, approval.request:
            case "CREATE_LIFECYCLE_REWORK", CreateLifecycleReworkRequest() as request:
                return await self._client.create_first(approval.task_id, request, **options)
            case "START_REWORK", ReworkVersionRequest() as request:
                return await self._client.start(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "BLOCK_REWORK", ReworkReasonRequest() as request:
                return await self._client.block(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "FAIL_REWORK", ReworkReasonRequest() as request:
                return await self._client.fail(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "RESUME_REWORK", ReworkReasonRequest() as request:
                return await self._client.resume(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "REGISTER_REWORK_RESULT", RegisterReworkResultRequest() as request:
                return await self._client.register_result(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "REGISTER_REWORK_INSPECTION", RegisterReworkInspectionRequest() as request:
                return await self._client.register_inspection(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "SUBMIT_REWORK_REVIEW", SubmitReworkReviewRequest() as request:
                return await self._client.submit_review(
                    approval.task_id, self._resource(approval), request, **options
                )
            case "CREATE_NEXT_REWORK", ReworkReasonRequest() as request:
                return await self._client.create_next(
                    approval.task_id, self._resource(approval), request, **options
                )
        self._raise(
            ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            "unsupported confirmed request binding",
            context,
        )

    @staticmethod
    def _resource(approval: ReworkExecutionSnapshot) -> str:
        """既有轮次操作的资源已由严格快照校验，首轮不调用本方法。"""

        if approval.rework_task_id is None:
            raise ValueError("confirmed rework resource is required")
        return approval.rework_task_id

    def _check_receipt(
        self, approval: ReworkExecutionSnapshot, receipt: ReworkWriteReceipt, context: ToolContext
    ) -> None:
        """补齐Client无法获知的轮次、前驱及原材料指针，不能重建Java事实。"""

        if approval.operation == "CREATE_LIFECYCLE_REWORK":
            return  # Client已经核对首轮1及空材料、空前驱。
        expected_round = approval.round_number
        if approval.operation == "CREATE_NEXT_REWORK":
            valid = expected_round is not None and receipt.round_number == expected_round + 1
        else:
            valid = (
                receipt.round_number == expected_round
                and receipt.previous_rework_task_id == approval.previous_rework_task_id
            )
        if approval.operation == "REGISTER_REWORK_RESULT":
            valid = valid and receipt.processing_revision == (approval.processing_revision or 0) + 1
        elif approval.operation in {"START_REWORK", "BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK"}:
            valid = valid and (
                receipt.processing_revision,
                receipt.inspection_id,
                receipt.review_id,
            ) == (approval.processing_revision, approval.inspection_id, approval.review_id)
        elif approval.operation == "REGISTER_REWORK_INSPECTION":
            valid = valid and receipt.inspection_id != approval.inspection_id
        elif approval.operation == "SUBMIT_REWORK_REVIEW":
            valid = valid and receipt.review_id != approval.review_id
        if not valid:
            self._raise(
                ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                "Java receipt differs from confirmed bindings",
                context,
            )

    @staticmethod
    def _raise(
        code: ToolErrorCode, message: str, context: ToolContext, status: int | None = None
    ) -> NoReturn:
        raise ToolException(
            code=code,
            message=message,
            retryable=False,
            trace_id=context.trace_id,
            status_code=status,
        )


def create_rework_write_tool_registry(
    client: ReworkHttpClient, store: ReworkExecutionStore, *, timeout: float = 10.0
) -> ToolRegistry:
    """必须显式注入受信Store，独立注册九个Tool，不改变旧写Tool或生产装配。"""

    registry = ToolRegistry()
    for name in _OPERATIONS:
        registry.register(ReworkWriteTool(client, store, name=name, timeout=timeout))
    return registry
