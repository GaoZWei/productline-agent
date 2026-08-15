"""M3.2 Agent会话创建、读取与清除API。"""

from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from app.api.identity import resolve_business_identity
from app.database import Database
from app.observability import get_trace_id
from app.schemas.session import (
    SessionCreateRequest,
    SessionErrorResponse,
    SessionIdentifier,
    SessionResponse,
)
from app.services.session_context import SessionContextError, SessionContextService

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]
_ERROR_STATUS = {
    "SESSION_NOT_FOUND": 404,
    "PERMISSION_DENIED": 403,
    "SESSION_EXPIRED": 410,
    "SESSION_CONTEXT_INVALID": 500,
}

router = APIRouter(prefix="/api/agent/sessions", tags=["agent-sessions"])

# 创建Agent会话
@router.post(
    "",
    response_model=SessionResponse,
    status_code=201,
    summary="创建Agent会话",
    responses={401: {"model": SessionErrorResponse}, 403: {"model": SessionErrorResponse}},
)
async def create_session(
    session_request: SessionCreateRequest,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> SessionResponse | JSONResponse:
    """创建带滑动过期时间的最小会话上下文。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _identity_required()
    service = _service(request)
    try:
        snapshot = await service.create(
            identity=identity,
            page_context=session_request.page_context,
        )
    except SessionContextError as error:
        return _session_error(error)
    return SessionResponse(
        session_id=snapshot.session_id,
        context=snapshot.context,
        expires_at=snapshot.expires_at,
    )

# 读取Agent会话
@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="读取Agent会话",
    responses={
        401: {"model": SessionErrorResponse},
        403: {"model": SessionErrorResponse},
        404: {"model": SessionErrorResponse},
        410: {"model": SessionErrorResponse},
    },
)
async def get_session(
    session_id: SessionIdentifier,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> SessionResponse | JSONResponse:
    """返回属于当前身份且尚未过期的会话。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _identity_required()
    try:
        snapshot = await _service(request).get_active(
            session_id=session_id,
            identity=identity,
        )
    except SessionContextError as error:
        return _session_error(error)
    return SessionResponse(
        session_id=snapshot.session_id,
        context=snapshot.context,
        expires_at=snapshot.expires_at,
    )

# 删除Agent会话
@router.delete(
    "/{session_id}",
    status_code=204,
    summary="清除Agent会话",
    responses={
        401: {"model": SessionErrorResponse},
        403: {"model": SessionErrorResponse},
        404: {"model": SessionErrorResponse},
    },
)
async def delete_session(
    session_id: SessionIdentifier,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> Response:
    """显式清除会话, 级联删除其Agent运行元数据。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _identity_required()
    try:
        await _service(request).delete(session_id=session_id, identity=identity)
    except SessionContextError as error:
        return _session_error(error)
    return Response(status_code=204)


def _service(request: Request) -> SessionContextService:
    """从应用状态构建请求级会话服务。"""

    database: Database = request.app.state.database
    ttl_seconds: int = request.app.state.settings.session_ttl_seconds
    return SessionContextService(database, ttl_seconds=ttl_seconds)


def _identity_required() -> JSONResponse:
    """返回未通过最小身份解析的统一错误。"""

    error = SessionErrorResponse(
        trace_id=get_trace_id(),
        code="PERMISSION_DENIED",
        message="authenticated user identity is required",
    )
    return JSONResponse(status_code=401, content=error.model_dump(mode="json"))


def _session_error(error: SessionContextError) -> JSONResponse:
    """把会话服务错误映射为安全HTTP响应。"""

    response = SessionErrorResponse(
        trace_id=get_trace_id(),
        code=error.code,
        message=error.message,
    )
    return JSONResponse(
        status_code=_ERROR_STATUS.get(error.code, 500),
        content=response.model_dump(mode="json"),
    )
