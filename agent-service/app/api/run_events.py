"""按客户端流标识建立可重连的SSE运行事件连接。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.identity import resolve_business_identity
from app.observability import get_trace_id
from app.schemas.events import EventStreamIdentifier, RunEventStreamErrorResponse
from app.services.run_events import (
    EventReplayUnavailableError,
    EventStreamAccessDeniedError,
    EventStreamCapacityError,
    EventStreamNotFoundError,
    RunEventService,
)

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]
_LAST_EVENT_ID_HEADER = Annotated[str | None, Header(alias="Last-Event-ID")]

router = APIRouter(prefix="/api/agent/events", tags=["agent-events"])

# SSE HTTP接口订阅事件
@router.get(
    "/{stream_id}",
    summary="订阅一次Agent运行的SSE事件",
    response_model=None,
    response_class=StreamingResponse,
    responses={
        400: {"model": RunEventStreamErrorResponse},
        401: {"model": RunEventStreamErrorResponse},
        403: {"model": RunEventStreamErrorResponse},
        404: {"model": RunEventStreamErrorResponse},
        409: {"model": RunEventStreamErrorResponse},
        503: {"model": RunEventStreamErrorResponse},
    },
)
async def subscribe_run_events(
    stream_id: EventStreamIdentifier,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
    last_event_id: _LAST_EVENT_ID_HEADER = None,
) -> StreamingResponse | JSONResponse:
    """创建用户隔离事件流, 并从Last-Event-ID之后实时发送或回放。"""
    # 解析用户身份
    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _error_response(
            stream_id=stream_id,
            status_code=401,
            code="PERMISSION_DENIED",
            message="authenticated user identity is required",
        )
    try:
        # 解析Last-Event-ID
        parsed_last_event_id = _parse_last_event_id(last_event_id)
    except ValueError:
        return _error_response(
            stream_id=stream_id,
            status_code=400,
            code="INVALID_LAST_EVENT_ID",
            message="Last-Event-ID must be a nonnegative integer",
        )

    service: RunEventService = request.app.state.run_event_service
    try:
        # 打开事件流
        await service.open_stream(stream_id, owner_user_id=identity.user_id)
        # 订阅事件流
        subscription = await service.subscribe(
            stream_id,
            owner_user_id=identity.user_id,
            last_event_id=parsed_last_event_id,
        )
    except EventStreamAccessDeniedError:
        return _error_response(
            stream_id=stream_id,
            status_code=403,
            code="EVENT_STREAM_ACCESS_DENIED",
            message="event stream belongs to another user",
        )
    except EventReplayUnavailableError:
        return _error_response(
            stream_id=stream_id,
            status_code=409,
            code="EVENT_REPLAY_UNAVAILABLE",
            message="requested event history is no longer available",
        )
    except EventStreamCapacityError:
        return _error_response(
            stream_id=stream_id,
            status_code=503,
            code="EVENT_STREAM_CAPACITY_REACHED",
            message="event stream capacity was reached",
        )
    except EventStreamNotFoundError:
        return _error_response(
            stream_id=stream_id,
            status_code=404,
            code="EVENT_STREAM_NOT_FOUND",
            message="event stream was not found",
        )
    # 返回StreamingResponse
    return StreamingResponse(
        subscription.iter_sse(request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _parse_last_event_id(value: str | None) -> int:
    if value is None or not value.strip():
        return 0
    parsed = int(value)
    if parsed < 0:
        raise ValueError("Last-Event-ID must not be negative")
    return parsed


def _error_response(
    *,
    stream_id: str,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    error = RunEventStreamErrorResponse(
        stream_id=stream_id,
        trace_id=get_trace_id(),
        code=code,
        message=message,
    )
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))
