"""知识管理只读HTTP边界，身份透传Java裁决，不接受自报权限范围。"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.identity import resolve_business_identity
from app.errors import ToolErrorCode, ToolException
from app.observability import get_trace_id
from app.repositories.knowledge_management_read import KnowledgeManagementReadRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_management import KnowledgeManagementError, KnowledgePreview
from app.schemas.knowledge_management_read import (
    KnowledgeDocumentSummary,
    KnowledgePage,
    KnowledgeReadError,
    KnowledgeReadQuery,
    KnowledgeReadResult,
    KnowledgeTaskSummary,
    KnowledgeVersionSummary,
)
from app.services.knowledge_management import KnowledgeManagementService
from app.services.knowledge_management_read import (
    KnowledgeManagementReadService,
    KnowledgeReadAccessError,
)

_ID = Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9]*-[0-9A-F]{32}$", max_length=128)]
_PAGE = Annotated[int, Query(ge=1, le=1_000_000)]
_SIZE = Annotated[int, Query(ge=1, le=100)]
_REVISION = Annotated[int, Path(ge=1, le=2**31 - 1)]


def _identity(
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> BusinessIdentity | None:
    """只解析Header格式，角色是否可读必须交由Java判断。"""

    return resolve_business_identity(
        user_id=user_id, user_role=user_role, authorization=authorization
    )


_IDENTITY = Annotated[BusinessIdentity | None, Depends(_identity)]
router = APIRouter(
    prefix="/api/agent/knowledge",
    tags=["knowledge-management"],
    responses={code: {"model": KnowledgeReadError} for code in (401, 403, 404, 502, 503, 504)},
)


def _service(request: Request) -> KnowledgeManagementReadService:
    """读取共享Client，独立构造只读服务，不调用管理激活或恢复入口。"""

    return KnowledgeManagementReadService(
        KnowledgeManagementReadRepository(request.app.state.database),
        request.app.state.knowledge_authorization_client,
    )


async def _read(
    request: Request, query: KnowledgeReadQuery, identity: BusinessIdentity | None
) -> KnowledgeReadResult | JSONResponse:
    """统一安全响应，不复制异常对象、文件路径或Java原始错误。"""

    try:
        if identity is None:
            raise KnowledgeReadAccessError(
                "PERMISSION_DENIED", "authenticated user identity is required", 401
            )
        return await _service(request).query(query, identity=identity, trace_id=get_trace_id())
    except KnowledgeReadAccessError as error:
        payload = KnowledgeReadError(
            trace_id=get_trace_id(), code=error.code, message=error.message
        )
        return JSONResponse(status_code=error.status_code, content=payload.model_dump(mode="json"))


@router.get("/documents", response_model=KnowledgePage[KnowledgeDocumentSummary])
async def list_documents(
    request: Request, identity: _IDENTITY, page: _PAGE = 1, page_size: _SIZE = 20
) -> KnowledgeReadResult | JSONResponse:
    """按权限范围分页列出资料，包含草稿，不改变默认问答集合。"""

    return await _read(
        request, KnowledgeReadQuery(kind="documents", page=page, page_size=page_size), identity
    )


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentSummary)
async def get_document(
    request: Request, document_id: _ID, identity: _IDENTITY
) -> KnowledgeReadResult | JSONResponse:
    """查询资料摘要及最新可见规范版本。"""

    return await _read(
        request, KnowledgeReadQuery(kind="document", document_id=document_id), identity
    )


@router.get(
    "/documents/{document_id}/versions", response_model=KnowledgePage[KnowledgeVersionSummary]
)
async def list_versions(
    request: Request, document_id: _ID, identity: _IDENTITY, page: _PAGE = 1, page_size: _SIZE = 20
) -> KnowledgeReadResult | JSONResponse:
    """分页返回规范版本元数据，不返回历史正文。"""

    return await _read(
        request,
        KnowledgeReadQuery(
            kind="versions", document_id=document_id, page=page, page_size=page_size
        ),
        identity,
    )


@router.get(
    "/documents/{document_id}/versions/{version_id}", response_model=KnowledgeVersionSummary
)
async def get_version(
    request: Request, document_id: _ID, version_id: _ID, identity: _IDENTITY
) -> KnowledgeReadResult | JSONResponse:
    """同时验证资料和版本归属，不能跨资料拼接版本身份。"""

    return await _read(
        request,
        KnowledgeReadQuery(kind="version", document_id=document_id, version_id=version_id),
        identity,
    )


@router.get("/documents/{document_id}/tasks", response_model=KnowledgePage[KnowledgeTaskSummary])
async def list_tasks(
    request: Request, document_id: _ID, identity: _IDENTITY, page: _PAGE = 1, page_size: _SIZE = 20
) -> KnowledgeReadResult | JSONResponse:
    """按资料查询历史处理任务，保留过期修订和中断事实。"""

    return await _read(
        request,
        KnowledgeReadQuery(kind="tasks", document_id=document_id, page=page, page_size=page_size),
        identity,
    )


@router.get("/tasks/{task_id}", response_model=KnowledgeTaskSummary)
async def get_task(
    request: Request, task_id: _ID, identity: _IDENTITY
) -> KnowledgeReadResult | JSONResponse:
    """按任务所属修订的权限读取状态，不触发重试。"""

    return await _read(request, KnowledgeReadQuery(kind="task", task_id=task_id), identity)


def _content_service(request: Request) -> KnowledgeManagementService:
    """复用已装配的规范内容应用，读取不会调用其管理激活入口。"""

    service: KnowledgeManagementService = request.app.state.knowledge_management_service
    return service


def _content_error(code: str, status: int, message: str) -> JSONResponse:
    """内容相关响应禁止缓存，错误只包含受控码和固定文案。"""

    payload = KnowledgeReadError(trace_id=get_trace_id(), code=code, message=message)
    return JSONResponse(
        status_code=status,
        content=payload.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/documents/{document_id}/versions/{version_id}/revisions/{revision_no}/preview",
    response_model=KnowledgePreview,
    responses={409: {"model": KnowledgeReadError}},
    summary="预览指定知识修订的正文及分块",
)
async def preview_revision(
    request: Request,
    response: Response,
    document_id: _ID,
    version_id: _ID,
    revision_no: _REVISION,
    identity: _IDENTITY,
) -> KnowledgePreview | JSONResponse:
    """明确指定修订，保留历史证据和原文空白，不隐式改查当前版本。"""

    response.headers["Cache-Control"] = "no-store"
    if identity is None:
        return _content_error("PERMISSION_DENIED", 401, "authenticated user identity is required")
    try:
        return await _content_service(request).preview(
            version_id,
            revision_no,
            document_id=document_id,
            identity=identity,
            trace_id=get_trace_id(),
        )
    except ToolException as error:
        if error.code == ToolErrorCode.PERMISSION_DENIED:
            return _content_error(
                "PERMISSION_DENIED",
                401 if error.status_code == 401 else 403,
                "knowledge read permission denied",
            )
        if error.code == ToolErrorCode.TOOL_TIMEOUT:
            return _content_error("AUTHORIZATION_TIMEOUT", 504, "knowledge authorization timed out")
        return _content_error(
            "AUTHORIZATION_UNAVAILABLE", 502, "knowledge authorization is unavailable"
        )
    except KnowledgeManagementError as error:
        if error.code == "RESOURCE_NOT_FOUND":
            return _content_error(error.code, 404, "knowledge resource not found")
        if error.code == "PREVIEW_NOT_READY":
            return _content_error(
                error.code, 409, "revision has no completed preview; query its task"
            )
        if error.code == "INVALID_AUTHORIZATION_RESPONSE":
            return _content_error(error.code, 502, "invalid knowledge authorization response")
        if error.code == "PERMISSION_DENIED":
            return _content_error(error.code, 403, "knowledge read permission denied")
        return _content_error(
            "KNOWLEDGE_PREVIEW_UNAVAILABLE", 503, "knowledge preview is unavailable"
        )
    except (SQLAlchemyError, ValidationError):
        return _content_error(
            "KNOWLEDGE_PREVIEW_UNAVAILABLE", 503, "knowledge preview is unavailable"
        )


def _attachment_headers(filename: str) -> dict[str, str]:
    """显示文件名不能携带路径或控制字符，UTF-8文件名与固定ASCII回退分别编码。"""

    if (
        not 1 <= len(filename) <= 256
        or any(char in filename for char in ("/", "\\"))
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    ):
        raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
    suffix = filename.rpartition(".")[2].lower()
    if suffix not in {"md", "txt"}:
        raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
    try:
        encoded = quote(filename, safe="")
    except UnicodeError:
        raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
    return {
        "Content-Disposition": (
            f"attachment; filename=\"knowledge-original.{suffix}\"; filename*=UTF-8''{encoded}"
        ),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


@router.get(
    "/documents/{document_id}/versions/{version_id}/revisions/{revision_no}/original",
    response_class=Response,
    responses={
        200: {
            "description": "已校验的原始文件附件",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
    summary="下载指定知识修订的原始文件",
)
async def download_original(
    request: Request,
    document_id: _ID,
    version_id: _ID,
    revision_no: _REVISION,
    identity: _IDENTITY,
) -> Response:
    """完整校验后发送字节，原件丢失或损坏不替换为预览正文，不提供路径或范围下载。"""

    if identity is None:
        return _content_error("PERMISSION_DENIED", 401, "authenticated user identity is required")
    try:
        original = await _content_service(request).read_original(
            version_id,
            revision_no,
            document_id=document_id,
            identity=identity,
            trace_id=get_trace_id(),
        )
        return Response(
            content=original.content,
            media_type="application/octet-stream",
            headers=_attachment_headers(original.filename),
        )
    except ToolException as error:
        if error.code == ToolErrorCode.PERMISSION_DENIED:
            return _content_error(
                "PERMISSION_DENIED",
                401 if error.status_code == 401 else 403,
                "knowledge read permission denied",
            )
        if error.code == ToolErrorCode.TOOL_TIMEOUT:
            return _content_error("AUTHORIZATION_TIMEOUT", 504, "knowledge authorization timed out")
        return _content_error(
            "AUTHORIZATION_UNAVAILABLE", 502, "knowledge authorization is unavailable"
        )
    except KnowledgeManagementError as error:
        if error.code == "RESOURCE_NOT_FOUND":
            return _content_error(error.code, 404, "knowledge resource not found")
        if error.code == "ORIGINAL_NOT_FOUND":
            return _content_error(error.code, 404, "original file is missing")
        if error.code in {"ORIGINAL_INTEGRITY_ERROR", "FILE_TOO_LARGE"}:
            return _content_error(
                "ORIGINAL_INTEGRITY_ERROR", 503, "original file integrity check failed"
            )
        if error.code == "INVALID_AUTHORIZATION_RESPONSE":
            return _content_error(error.code, 502, "invalid knowledge authorization response")
        if error.code == "PERMISSION_DENIED":
            return _content_error(error.code, 403, "knowledge read permission denied")
        return _content_error(
            "KNOWLEDGE_ORIGINAL_UNAVAILABLE", 503, "knowledge original is unavailable"
        )
    except (SQLAlchemyError, ValidationError):
        return _content_error(
            "KNOWLEDGE_ORIGINAL_UNAVAILABLE", 503, "knowledge original is unavailable"
        )
