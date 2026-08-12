"""固定订单诊断的对外 HTTP API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr, ValidationError

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
    identity = _resolve_identity(
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

    database: Database = request.app.state.database
    registry: ToolRegistry = request.app.state.tool_registry
    service = OrderDiagnosisService(database, registry)
    try:
        execution = await service.diagnose(
            order_id=diagnosis_request.order_id,
            user_message=diagnosis_request.user_message,
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
        trace_id=trace_id,
        diagnosis=execution.diagnosis,
    )


def _resolve_identity(
    *,
    user_id: str | None,
    user_role: str | None,
    authorization: str | None,
) -> BusinessIdentity | None:
    """把最小身份 Header 转换为 Java Tool 使用的安全身份。"""

    if user_id is None or user_role is None:
        return None
    token: SecretStr | None = None
    if authorization is not None:
        scheme, separator, value = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not value.strip():
            return None
        token = SecretStr(value.strip())
    try:
        return BusinessIdentity(user_id=user_id, role=user_role, token=token)
    except ValidationError:
        return None


def _error_response(
    *,
    status_code: int,
    error: OrderDiagnosisErrorResponse,
) -> JSONResponse:
    """使用已校验 Schema 返回一致错误体。"""

    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))
