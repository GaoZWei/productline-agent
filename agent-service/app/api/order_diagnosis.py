"""固定订单诊断的对外 HTTP API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.api.identity import resolve_business_identity
from app.database import Database
from app.observability import get_trace_id
from app.schemas.agent import (
    OrderDiagnosisErrorResponse,
    OrderDiagnosisRequest,
    OrderDiagnosisResponse,
)
from app.schemas.business import BusinessIdentity
from app.services import OrderDiagnosisExecutionError, OrderDiagnosisService
from app.tools import ToolRegistry

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]

_ERROR_HTTP_STATUS = {
    "PARAM_VALIDATION_ERROR": 400,
    "RESOURCE_NOT_FOUND": 404,
    "PERMISSION_DENIED": 403,
    "BUSINESS_CONFLICT": 409,
    "TOOL_TIMEOUT": 504,
    "UPSTREAM_UNAVAILABLE": 502,
    "RESPONSE_VALIDATION_ERROR": 502,
    "DUPLICATE_CALL": 409,
    "UNKNOWN_TOOL_ERROR": 500,
    "WORKFLOW_EXECUTION_ERROR": 500,
    "SESSION_NOT_FOUND": 404,
    "SESSION_EXPIRED": 410,
    "SESSION_CONTEXT_INCOMPLETE": 400,
    "SESSION_CONTEXT_INVALID": 500,
}

router = APIRouter(prefix="/api/agent", tags=["agent"])

# 订单诊断API
@router.post(
    "/order-diagnosis",
    response_model=OrderDiagnosisResponse,
    summary="诊断订单阻塞原因",
    responses={
        400: {"model": OrderDiagnosisErrorResponse},
        401: {"model": OrderDiagnosisErrorResponse},
        403: {"model": OrderDiagnosisErrorResponse},
        404: {"model": OrderDiagnosisErrorResponse},
        409: {"model": OrderDiagnosisErrorResponse},
        410: {"model": OrderDiagnosisErrorResponse},
        500: {"model": OrderDiagnosisErrorResponse},
        502: {"model": OrderDiagnosisErrorResponse},
        504: {"model": OrderDiagnosisErrorResponse},
    },
)
# 订单诊断处理函数
async def diagnose_order(
    diagnosis_request: OrderDiagnosisRequest,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> OrderDiagnosisResponse | JSONResponse:
    """创建 Run、执行固定 Workflow 并返回诊断或安全错误。"""

    trace_id = get_trace_id()
    # 先处理身份信息, 确保用户已认证
    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _error_response(
            status_code=401,
            error=OrderDiagnosisErrorResponse(
                run_id=None,
                trace_id=trace_id,
                code="PERMISSION_DENIED",
                message="authenticated user identity is required",
                retryable=False,
                error_step=None,
            ),
        )

    context_role = (
        diagnosis_request.page_context.user_role
        if diagnosis_request.page_context is not None
        else None
    )
    # 检查用户是否有权限诊断订单
    if not _has_diagnosis_permission(identity, context_role):
        return _error_response(
            status_code=403,
            error=OrderDiagnosisErrorResponse(
                run_id=None,
                trace_id=trace_id,
                code="PERMISSION_DENIED",
                message="order diagnosis permission is required",
                retryable=False,
                error_step=None,
            ),
        )

    database: Database = request.app.state.database
    registry: ToolRegistry = request.app.state.tool_registry
    service = OrderDiagnosisService(
        database,
        registry,
        session_ttl_seconds=request.app.state.settings.session_ttl_seconds,
        version_snapshot=request.app.state.run_version_snapshot,  # API 从应用状态取出运行版本快照
    )
    try:
        execution = await service.diagnose(
            session_id=diagnosis_request.session_id,
            order_id=diagnosis_request.order_id,
            user_message=diagnosis_request.user_message,
            page_context=diagnosis_request.page_context,
            identity=identity,
            trace_id=trace_id,
        )
    except OrderDiagnosisExecutionError as error:
        return _error_response(
            status_code=_ERROR_HTTP_STATUS.get(error.code, 500),
            error=OrderDiagnosisErrorResponse(
                run_id=error.run_id,
                trace_id=trace_id,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                error_step=error.error_step,
            ),
        )

    return OrderDiagnosisResponse(
        run_id=execution.run_id,
        session_id=execution.session_id,
        trace_id=trace_id,
        diagnosis=execution.diagnosis,
    )


def _has_diagnosis_permission(
    identity: BusinessIdentity,
    context_role: str | None,
) -> bool:
    """只信任服务端角色策略, 并要求页面角色提示与身份Header一致。"""

    return identity.role == "REVIEWER" and (
        context_role is None or context_role == identity.role
    )


def _error_response(
    *,
    status_code: int,
    error: OrderDiagnosisErrorResponse,
) -> JSONResponse:
    """使用已校验 Schema 返回一致错误体。"""

    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))
