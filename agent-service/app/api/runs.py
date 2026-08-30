"""M7.5 当前用户Run历史列表、详情和Step时间线HTTP入口。"""

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request
from fastapi.responses import JSONResponse

from app.api.identity import resolve_business_identity
from app.database import Database
from app.observability import get_trace_id
from app.schemas.run_history import (
    RunDetailResponse,
    RunHistoryErrorResponse,
    RunListResponse,
    StepListResponse,
)
from app.services import DatabaseRunHistoryService, RunHistoryAccessError

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]
_PAGE_QUERY = Annotated[int, Query(ge=1, le=1_000_000)]
_PAGE_SIZE_QUERY = Annotated[int, Query(ge=1, le=100)]
_RUN_ID_PATH = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]

router = APIRouter(prefix="/api/agent/runs", tags=["agent-runs"])


@router.get(
    "",
    response_model=RunListResponse,
    summary="分页查询当前用户的Agent运行历史",
    responses={
        401: {"model": RunHistoryErrorResponse},
        403: {"model": RunHistoryErrorResponse},
    },
)
async def list_runs(
    request: Request,
    page: _PAGE_QUERY = 1,
    page_size: _PAGE_SIZE_QUERY = 20,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> RunListResponse | JSONResponse:
    """只返回当前用户自己的Run摘要, 完整结果和内部快照留给后续详情边界。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _error_response(
            RunHistoryAccessError(
                code="PERMISSION_DENIED",
                message="authenticated user identity is required",
                status_code=401,
            )
        )
    try:
        return await _service(request).list_runs(
            identity=identity,
            page=page,
            page_size=page_size,
        )
    except RunHistoryAccessError as error:
        return _error_response(error)


@router.get(
    "/{run_id}",
    response_model=RunDetailResponse,
    summary="查询当前用户的单个Agent运行详情",
    responses={
        401: {"model": RunHistoryErrorResponse},
        403: {"model": RunHistoryErrorResponse},
        404: {"model": RunHistoryErrorResponse},
    },
)
async def get_run_detail(
    request: Request,
    run_id: _RUN_ID_PATH,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> RunDetailResponse | JSONResponse:
    """返回诊断结果和Approval历史, 不返回消息、上下文或版本快照。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _missing_identity_response()
    try:
        return await _service(request).get_run_detail(identity=identity, run_id=run_id)
    except RunHistoryAccessError as error:
        return _error_response(error)


@router.get(
    "/{run_id}/steps",
    response_model=StepListResponse,
    summary="查询当前用户的Agent运行步骤",
    responses={
        401: {"model": RunHistoryErrorResponse},
        403: {"model": RunHistoryErrorResponse},
        404: {"model": RunHistoryErrorResponse},
    },
)
async def list_run_steps(
    request: Request,
    run_id: _RUN_ID_PATH,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
) -> StepListResponse | JSONResponse:
    """返回持久化Step的受控摘要时间线。"""

    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _missing_identity_response()
    try:
        return await _service(request).list_steps(identity=identity, run_id=run_id)
    except RunHistoryAccessError as error:
        return _error_response(error)


def _service(request: Request) -> DatabaseRunHistoryService:
    """为当前请求构建只读Run历史服务。"""

    database: Database = request.app.state.database
    return DatabaseRunHistoryService(database)


def _error_response(error: RunHistoryAccessError) -> JSONResponse:
    """把身份或角色错误转换为不泄露Run存在性的稳定响应。"""

    response = RunHistoryErrorResponse(
        trace_id=get_trace_id(),
        code=error.code,
        message=error.message,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=response.model_dump(mode="json"),
    )


def _missing_identity_response() -> JSONResponse:
    """生成三个Run历史入口共享的缺失身份响应。"""

    return _error_response(
        RunHistoryAccessError(
            code="PERMISSION_DENIED",
            message="authenticated user identity is required",
            status_code=401,
        )
    )
