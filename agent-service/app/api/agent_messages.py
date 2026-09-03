"""统一Agent能力查询和消息Turn的FastAPI入口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.api.identity import resolve_business_identity
from app.clients.model import OpenAICompatibleChatClient
from app.database import Database
from app.observability import get_trace_id
from app.repositories import KnowledgeIndexRepository
from app.schemas.agent_messages import (
    AgentCapabilitiesResponse,
    AgentMessageErrorResponse,
    AgentMessageRequest,
    AgentMessageResponse,
    AgentResultKind,
)
from app.schemas.events import EventStreamIdentifier
from app.services.agent_messages import (
    AgentMessageExecutionError,
    AgentMessageService,
    AgentSkillDispatcher,
)
from app.services.knowledge_index_capabilities import KnowledgeIndexCapabilityService
from app.services.model_capabilities import ModelCapabilityService
from app.services.run_events import (
    EventStreamAccessDeniedError,
    EventStreamNotFoundError,
    RunEventPublisher,
    RunEventService,
)

_USER_ID_HEADER = Annotated[str | None, Header(alias="X-User-Id")]
_USER_ROLE_HEADER = Annotated[str | None, Header(alias="X-User-Role")]
_AUTHORIZATION_HEADER = Annotated[str | None, Header(alias="Authorization")]
_EVENT_STREAM_HEADER = Annotated[
    EventStreamIdentifier | None,
    Header(alias="X-Event-Stream-Id"),
]

_ERROR_STATUS = {
    "PERMISSION_DENIED": 403,
    "SESSION_NOT_FOUND": 404,
    "SESSION_EXPIRED": 410,
    "SESSION_CONTEXT_INVALID": 500,
    "CLARIFICATION_SELECTION_INVALID": 409,
    "MODEL_NOT_CONFIGURED": 503,
    "MODEL_TIMEOUT": 504,
    "MODEL_UPSTREAM_UNAVAILABLE": 502,
    "MODEL_RATE_LIMITED": 429,
    "MODEL_AUTHENTICATION_ERROR": 502,
    "MODEL_INVALID_REQUEST": 502,
    "MODEL_RESPONSE_VALIDATION_ERROR": 502,
    "MODEL_OUTPUT_VALIDATION_ERROR": 502,
    "SKILL_NOT_AVAILABLE": 503,
    "SKILL_EXECUTION_ERROR": 500,
    "AGENT_EXECUTION_ERROR": 500,
    "AGENT_INITIALIZATION_ERROR": 500,
}
# FastAPI 入口路由
router = APIRouter(prefix="/api/agent", tags=["agent"])

# 能力查询路由 模型是否配置、当前模型Provider和模型名、知识索引状态、统一入口支持的五类结果
@router.get(
    "/capabilities",
    response_model=AgentCapabilitiesResponse,
    summary="查询统一Agent入口能力",
)
async def get_agent_capabilities(request: Request) -> AgentCapabilitiesResponse:
    """聚合安全模型配置和知识索引状态, 不发起模型或Embedding调用。"""

    model_service: ModelCapabilityService = request.app.state.model_capability_service
    knowledge_service: KnowledgeIndexCapabilityService = (
        request.app.state.knowledge_index_capability_service
    )
    database: Database = request.app.state.database
    async with database.session() as session:
        knowledge_index = await knowledge_service.get(KnowledgeIndexRepository(session))
    return AgentCapabilitiesResponse(
        result_kinds=tuple(AgentResultKind),
        model=model_service.get(),
        knowledge_index=knowledge_index,
    )

# 消息入口路由 执行一轮统一Agent消息
@router.post(
    "/messages",
    response_model=AgentMessageResponse,
    summary="执行一轮统一Agent消息",
    responses={
        401: {"model": AgentMessageErrorResponse},
        403: {"model": AgentMessageErrorResponse},
        404: {"model": AgentMessageErrorResponse},
        409: {"model": AgentMessageErrorResponse},
        410: {"model": AgentMessageErrorResponse},
        429: {"model": AgentMessageErrorResponse},
        500: {"model": AgentMessageErrorResponse},
        502: {"model": AgentMessageErrorResponse},
        503: {"model": AgentMessageErrorResponse},
        504: {"model": AgentMessageErrorResponse},
    },
)
async def create_agent_message(
    message_request: AgentMessageRequest,
    request: Request,
    user_id: _USER_ID_HEADER = None,
    user_role: _USER_ROLE_HEADER = None,
    authorization: _AUTHORIZATION_HEADER = None,
    event_stream_id: _EVENT_STREAM_HEADER = None,
) -> AgentMessageResponse | JSONResponse:
    """校验身份与事件流后执行Turn, 失败时返回稳定错误且不固定路由降级。"""
    # 校验身份和事件流是否存在
    trace_id = get_trace_id()
    identity = resolve_business_identity(
        user_id=user_id,
        user_role=user_role,
        authorization=authorization,
    )
    if identity is None:
        return _error_response(
            status_code=401,
            error=AgentMessageErrorResponse(
                run_id=None,
                trace_id=trace_id,
                code="PERMISSION_DENIED",
                message="authenticated user identity is required",
                retryable=False,
                error_step=None,
            ),
        )
    try:
        publisher = await _event_publisher(
            request,
            stream_id=event_stream_id,
            owner_user_id=identity.user_id,
            trace_id=trace_id,
        )
    except EventStreamAccessDeniedError:
        return _error_response(
            status_code=403,
            error=AgentMessageErrorResponse(
                run_id=None,
                trace_id=trace_id,
                code="EVENT_STREAM_ACCESS_DENIED",
                message="event stream belongs to another user",
                retryable=False,
                error_step=None,
            ),
        )
    except EventStreamNotFoundError:
        return _error_response(
            status_code=409,
            error=AgentMessageErrorResponse(
                run_id=None,
                trace_id=trace_id,
                code="EVENT_STREAM_NOT_READY",
                message="event stream must be connected before agent message starts",
                retryable=True,
                error_step=None,
            ),
        )
    # 创建请求级 AgentMessageService 执行 Turn 执行
    service = _message_service(request, publisher)
    try:
        execution = await service.execute(
            message_request,
            identity=identity,
            trace_id=trace_id,
        )
    except AgentMessageExecutionError as error:
        return _error_response(
            status_code=_ERROR_STATUS.get(error.code, 500),
            error=AgentMessageErrorResponse(
                run_id=error.run_id,
                trace_id=trace_id,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                error_step=error.error_step,
            ),
        )
    return AgentMessageResponse(
        run_id=execution.run_id,
        session_id=execution.session_id,
        trace_id=trace_id,
        result=execution.result,
    )

# 创建请求级 AgentMessageService 执行 Turn 执行
def _message_service(
    request: Request,
    publisher: RunEventPublisher | None,
) -> AgentMessageService:
    """从应用状态组装请求级服务, 方便测试替换Skill边界。"""

    database: Database = request.app.state.database
    model_client: OpenAICompatibleChatClient = request.app.state.model_client
    dispatcher: AgentSkillDispatcher = request.app.state.agent_skill_dispatcher
    return AgentMessageService(
        database,
        model_client,
        dispatcher,
        session_ttl_seconds=request.app.state.settings.session_ttl_seconds,
        version_snapshot=request.app.state.run_version_snapshot,
        event_sink=publisher,
    )


async def _event_publisher(
    request: Request,
    *,
    stream_id: str | None,
    owner_user_id: str,
    trace_id: str,
) -> RunEventPublisher | None:
    """只绑定客户端已先建立且属于当前身份的事件流。"""

    if stream_id is None:
        return None
    service: RunEventService = request.app.state.run_event_service
    return await service.publisher(
        stream_id,
        owner_user_id=owner_user_id,
        trace_id=trace_id,
    )


def _error_response(
    *,
    status_code: int,
    error: AgentMessageErrorResponse,
) -> JSONResponse:
    """使用已校验Schema生成统一安全错误体。"""

    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


__all__ = ["router"]
