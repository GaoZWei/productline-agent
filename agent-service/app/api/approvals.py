"""人工确认后重新校验并执行Java写入的HTTP入口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.api.identity import resolve_business_identity
from app.database import Database
from app.observability import get_trace_id
from app.schemas.approval_execution import (
    ApprovalConfirmationErrorResponse,
    ApprovalConfirmationRequest,
    ApprovalConfirmationResponse,
)
from app.schemas.events import EventStreamIdentifier, RunEventType
from app.schemas.operation_log import OperationLogDetail
from app.schemas.write_tools import ApprovalIdentifier
from app.services import (
    ApprovalConfirmationError,
    ApprovalConfirmationService,
    DatabaseApprovalConfirmationStore,
    DatabaseOperationLogService,
    EventStreamAccessDeniedError,
    EventStreamNotFoundError,
    OperationLogAccessError,
    RunEventPublisher,
    RunEventService,
)
from app.tools import ToolRegistry

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]
_EVENT_STREAM_HEADER = Annotated[
    EventStreamIdentifier | None,
    Header(alias="X-Event-Stream-Id"),
]

router = APIRouter(prefix="/api/agent/approvals", tags=["agent-approvals"])

# 操作日志详情接口
@router.get(
    "/{approval_id}/operation-log",
    response_model=OperationLogDetail,
    summary="查询一次人工确认写操作的审计详情",
    responses={
        401: {"model": ApprovalConfirmationErrorResponse},
        403: {"model": ApprovalConfirmationErrorResponse},
        404: {"model": ApprovalConfirmationErrorResponse},
    },
)
async def get_operation_log(
    approval_id: ApprovalIdentifier,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> OperationLogDetail | JSONResponse:
    """只向原确认人返回受控前后摘要、修改差异和Java Trace。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _operation_log_error_response(
            approval_id=approval_id,
            error=OperationLogAccessError(
                code="PERMISSION_DENIED",
                message="authenticated user identity is required",
                status_code=401,
            ),
        )
    try:
        return await _operation_log_service(request).get_by_approval(
            approval_id,
            identity=identity,
        )
    except OperationLogAccessError as error:
        return _operation_log_error_response(approval_id=approval_id, error=error)

# http请求入口
@router.post(
    "/{approval_id}/confirm",
    response_model=ApprovalConfirmationResponse,
    summary="确认复核草稿并安全执行Java写入",
    responses={
        401: {"model": ApprovalConfirmationErrorResponse},
        403: {"model": ApprovalConfirmationErrorResponse},
        404: {"model": ApprovalConfirmationErrorResponse},
        409: {"model": ApprovalConfirmationErrorResponse},
        410: {"model": ApprovalConfirmationErrorResponse},
        500: {"model": ApprovalConfirmationErrorResponse},
        502: {"model": ApprovalConfirmationErrorResponse},
        504: {"model": ApprovalConfirmationErrorResponse},
    },
)
async def confirm_approval(
    approval_id: ApprovalIdentifier,
    confirmation: ApprovalConfirmationRequest,
    request: Request,
    user_id: _USER_ID_HEADER = None,  # 从请求头获取用户ID
    user_role: _USER_ROLE_HEADER = None,  # 从请求头获取用户角色
    authorization: _AUTHORIZATION_HEADER = None,  # 从请求头获取授权信息
    event_stream_id: _EVENT_STREAM_HEADER = None,
) -> ApprovalConfirmationResponse | JSONResponse:
    """记录当前用户的最终草稿并在最新事实校验后执行唯一写Tool。"""
    # 取得Trace ID
    trace_id = get_trace_id()
    # 从Header解析当前用户
    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _error_response(
            approval_id=approval_id,
            error=ApprovalConfirmationError(
                code="PERMISSION_DENIED",
                message="authenticated user identity is required",
                status_code=401,
            ),
        )
    try:
        event_publisher = await _event_publisher(
            request,
            stream_id=event_stream_id,
            owner_user_id=identity.user_id,
            trace_id=trace_id,
        )
    except EventStreamAccessDeniedError:
        return _error_response(
            approval_id=approval_id,
            error=ApprovalConfirmationError(
                code="EVENT_STREAM_ACCESS_DENIED",
                message="event stream belongs to another user",
                status_code=403,
            ),
        )
    except EventStreamNotFoundError:
        return _error_response(
            approval_id=approval_id,
            error=ApprovalConfirmationError(
                code="EVENT_STREAM_NOT_READY",
                message="event stream must be connected before approval confirmation",
                status_code=409,
                retryable=True,
            ),
        )
    try:
        # 调用ApprovalConfirmationService.confirm_and_execute()
        execution = await _service(request, event_sink=event_publisher).confirm_and_execute(
            approval_id=approval_id,
            draft=confirmation.draft,
            identity=identity,
            trace_id=trace_id,
        )
    # 把领域错误转换成稳定HTTP错误响应
    except ApprovalConfirmationError as error:
        if event_publisher is not None and not event_publisher.terminal:
            await event_publisher.publish(
                RunEventType.RUN_FAILED,
                data={
                    "approval_id": approval_id,
                    "status": (
                        error.approval_status.value
                        if error.approval_status is not None
                        else None
                    ),
                    "error_code": error.code,
                    "retryable": error.retryable,
                },
            )
        return _error_response(approval_id=approval_id, error=error)
    return ApprovalConfirmationResponse(
        approval_id=execution.approval_id,
        status=execution.status,
        trace_id=trace_id,
        result=execution.result,
    )


def _service(
    request: Request,
    *,
    event_sink: RunEventPublisher | None = None,
) -> ApprovalConfirmationService:
    """从应用状态创建一次无跨请求可变状态的确认服务。"""

    database: Database = request.app.state.database
    read_tools: ToolRegistry = request.app.state.tool_registry
    write_tools: ToolRegistry = request.app.state.write_tool_registry
    return ApprovalConfirmationService(
        DatabaseApprovalConfirmationStore(database),
        read_tools,
        write_tools,
        approval_ttl_seconds=request.app.state.settings.approval_ttl_seconds,
        event_sink=event_sink,
    )


async def _event_publisher(
    request: Request,
    *,
    stream_id: str | None,
    owner_user_id: str,
    trace_id: str,
) -> RunEventPublisher | None:
    """把可选事件流标识绑定到当前确认用户。"""

    if stream_id is None:
        return None
    service: RunEventService = request.app.state.run_event_service
    return await service.publisher(
        stream_id,
        owner_user_id=owner_user_id,
        trace_id=trace_id,
    )


def _operation_log_service(request: Request) -> DatabaseOperationLogService:
    """创建只依赖Agent数据库的操作日志查询服务。"""

    return DatabaseOperationLogService(request.app.state.database)


def _error_response(
    *,
    approval_id: str,
    error: ApprovalConfirmationError,
) -> JSONResponse:
    """把确认领域错误转换为稳定HTTP状态和严格错误体。"""

    response = ApprovalConfirmationErrorResponse(
        approval_id=approval_id,
        status=error.approval_status,
        trace_id=get_trace_id(),
        code=error.code,
        message=error.message,
        retryable=error.retryable,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=response.model_dump(mode="json"),
    )


def _operation_log_error_response(
    *,
    approval_id: str,
    error: OperationLogAccessError,
) -> JSONResponse:
    response = ApprovalConfirmationErrorResponse(
        approval_id=approval_id,
        status=None,
        trace_id=get_trace_id(),
        code=error.code,
        message=error.message,
        retryable=False,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=response.model_dump(mode="json"),
    )
