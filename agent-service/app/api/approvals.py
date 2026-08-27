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
from app.schemas.write_tools import ApprovalIdentifier
from app.services import (
    ApprovalConfirmationError,
    ApprovalConfirmationService,
    DatabaseApprovalConfirmationStore,
)
from app.tools import ToolRegistry

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]

router = APIRouter(prefix="/api/agent/approvals", tags=["agent-approvals"])

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
        # 调用ApprovalConfirmationService.confirm_and_execute()
        execution = await _service(request).confirm_and_execute(
            approval_id=approval_id,
            draft=confirmation.draft,
            identity=identity,
            trace_id=trace_id,
        )
    # 把领域错误转换成稳定HTTP错误响应
    except ApprovalConfirmationError as error:
        return _error_response(approval_id=approval_id, error=error)
    return ApprovalConfirmationResponse(
        approval_id=execution.approval_id,
        status=execution.status,
        trace_id=trace_id,
        result=execution.result,
    )


def _service(request: Request) -> ApprovalConfirmationService:
    """从应用状态创建一次无跨请求可变状态的确认服务。"""

    database: Database = request.app.state.database
    read_tools: ToolRegistry = request.app.state.tool_registry
    write_tools: ToolRegistry = request.app.state.write_tool_registry
    return ApprovalConfirmationService(
        DatabaseApprovalConfirmationStore(database),
        read_tools,
        write_tools,
        approval_ttl_seconds=request.app.state.settings.approval_ttl_seconds,
    )


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
