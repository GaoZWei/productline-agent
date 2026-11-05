"""明确文件提交只创建草稿，不自动确认发布，也不覆盖已发布规范。"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.responses import Response

from app.api.identity import resolve_business_identity
from app.api.knowledge_upload_body import file_chunks, upload_body
from app.errors import ToolErrorCode, ToolException
from app.observability import get_trace_id
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import KnowledgeManagementError, KnowledgeUploadResult
from app.schemas.knowledge_upload import KnowledgeUploadError
from app.services.knowledge_management import KnowledgeManagementService

_ID = Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9]*-[0-9A-F]{32}$", max_length=128)]
_KEY = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]
_ERRORS: dict[str, tuple[int, str]] = {
    "INVALID_UPLOAD_COMMAND": (422, "upload command or filename is invalid"),
    "INVALID_MULTIPART": (400, "exactly one command field and one file are required"),
    "UNSUPPORTED_MEDIA_TYPE": (415, "multipart/form-data is required"),
    "UNSUPPORTED_FORMAT": (415, "only Markdown and UTF-8 TXT files are supported"),
    "REQUEST_TOO_LARGE": (413, "upload request is too large"),
    "FILE_TOO_LARGE": (413, "file exceeds the 10 MiB limit"),
    "UPLOAD_INTERRUPTED": (400, "file upload was interrupted"),
    "INVALID_FILENAME": (422, "filename must be a display basename"),
    "EMPTY_DOCUMENT": (422, "document must contain nonempty text"),
    "INVALID_ENCODING": (422, "document must use UTF-8 encoding"),
    "INVALID_TEXT_CONTENT": (422, "document contains invalid text"),
    "INVALID_UPLOAD_STREAM": (400, "file upload stream is invalid"),
    "PERMISSION_DENIED": (403, "knowledge upload permission denied"),
    "INVALID_AUTHORIZATION_RESPONSE": (502, "invalid knowledge authorization response"),
    "RESOURCE_NOT_FOUND": (404, "knowledge resource not found"),
    "IDEMPOTENCY_CONFLICT": (409, "idempotency key was used with different input"),
    "STALE_DOCUMENT": (409, "document has changed; refresh before submitting"),
    "STALE_REVISION": (409, "draft revision has changed; refresh before submitting"),
    "SEALED_VERSION_REQUIRES_NEW_VERSION": (
        409,
        "sealed version requires a new specification version",
    ),
    "SPECIFICATION_VERSION_CONFLICT": (409, "specification version conflicts with the target"),
    "KNOWLEDGE_CONFLICT": (409, "knowledge changed concurrently; refresh before submitting"),
    "ORIGINAL_CONFLICT": (409, "original file already exists with different bytes"),
    "AUTHORIZATION_TIMEOUT": (504, "knowledge authorization timed out"),
    "AUTHORIZATION_UNAVAILABLE": (502, "knowledge authorization is unavailable"),
}
_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["command", "file"],
                    "additionalProperties": False,
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "JSON: metadata and optional "
                                "expected_row_version/expected_revision_no"
                            ),
                        },
                        "file": {"type": "string", "format": "binary"},
                    },
                }
            }
        },
    }
}


class KnowledgeUploadRoute(APIRoute):
    """仅上传入口统一参数错误，避免默认422响应回显元数据或敏感Header。"""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """保持FastAPI参数校验，错误只提供固定码及请求Trace。"""

        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return _error("INVALID_UPLOAD_COMMAND")

        return safe_handler


router = APIRouter(
    prefix="/api/agent/knowledge",
    tags=["knowledge-management"],
    route_class=KnowledgeUploadRoute,
    responses={
        code: {"model": KnowledgeUploadError}
        for code in (400, 401, 403, 404, 409, 413, 415, 422, 502, 503, 504)
    },
)


def _identity(
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> BusinessIdentity | None:
    """身份格式在入口解析，实际角色权限仍由Java裁决。"""

    return resolve_business_identity(
        user_id=user_id, user_role=user_role, authorization=authorization
    )


_IDENTITY = Annotated[BusinessIdentity | None, Depends(_identity)]


def _service(request: Request) -> KnowledgeManagementService:
    """使用lifespan共享的上传服务，保持同实例修订锁和任务owner。"""

    service: KnowledgeManagementService = request.app.state.knowledge_management_service
    return service


async def _upload(
    request: Request,
    identity: BusinessIdentity | None,
    idempotency_key: str,
    document_id: str | None = None,
    version_id: str | None = None,
) -> JSONResponse:
    """预先授权才接收multipart，应用提交前再次授权以覆盖上传期间的权限撤销。"""

    try:
        if identity is None:
            return _error(
                "PERMISSION_DENIED", status=401, message="authenticated user identity is required"
            )
        service = _service(request)
        response = await service.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.UPLOAD),
            identity=identity,
            trace_id=get_trace_id(),
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != KnowledgeManagementAction.UPLOAD
            or not response.data.confirmation_required
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        async with upload_body(
            request, document_id=document_id, version_id=version_id, idempotency_key=idempotency_key
        ) as (command, file):
            if command.metadata.permission_scope != response.data.permission_scope:
                raise KnowledgeManagementError("PERMISSION_DENIED")
            result = await service.upload(
                command, file_chunks(file), identity=identity, trace_id=get_trace_id()
            )
        return JSONResponse(
            status_code=200 if result.replayed else 201, content=result.model_dump(mode="json")
        )
    except ToolException as error:
        if error.code == ToolErrorCode.PERMISSION_DENIED:
            return _error("PERMISSION_DENIED", status=401 if error.status_code == 401 else 403)
        return _error(
            "AUTHORIZATION_TIMEOUT"
            if error.code == ToolErrorCode.TOOL_TIMEOUT
            else "AUTHORIZATION_UNAVAILABLE"
        )
    except KnowledgeManagementError as error:
        return _error(error.code)


def _error(code: str, *, status: int | None = None, message: str | None = None) -> JSONResponse:
    """未列入公开契约的内部错误统一不可用，不复制异常原文或物理路径。"""

    actual_status, actual_message = _ERRORS.get(code, (503, "knowledge upload is unavailable"))
    payload = KnowledgeUploadError(
        trace_id=get_trace_id(),
        code=code if code in _ERRORS else "KNOWLEDGE_UPLOAD_UNAVAILABLE",
        message=message or actual_message,
    )
    return JSONResponse(
        status_code=status or actual_status, content=payload.model_dump(mode="json")
    )


@router.post(
    "/documents",
    status_code=201,
    response_model=KnowledgeUploadResult,
    responses={200: {"model": KnowledgeUploadResult}},
    openapi_extra=_BODY,
)
async def upload_document(
    request: Request, identity: _IDENTITY, idempotency_key: _KEY
) -> JSONResponse:
    """新建逻辑资料及首个草稿版本，文件提交不等于发布。"""

    return await _upload(request, identity, idempotency_key)


@router.post(
    "/documents/{document_id}/versions",
    status_code=201,
    response_model=KnowledgeUploadResult,
    responses={200: {"model": KnowledgeUploadResult}},
    openapi_extra=_BODY,
)
async def upload_version(
    request: Request, document_id: _ID, identity: _IDENTITY, idempotency_key: _KEY
) -> JSONResponse:
    """同资料新增规范版本，必须携带预期资料计数，不覆盖发布版本。"""

    return await _upload(request, identity, idempotency_key, document_id)


@router.post(
    "/documents/{document_id}/versions/{version_id}/revisions",
    status_code=201,
    response_model=KnowledgeUploadResult,
    responses={200: {"model": KnowledgeUploadResult}},
    openapi_extra=_BODY,
)
async def revise_draft(
    request: Request, document_id: _ID, version_id: _ID, identity: _IDENTITY, idempotency_key: _KEY
) -> JSONResponse:
    """只修正未封存草稿，事务复查资料归属、规范版本、行版本及修订号。"""

    return await _upload(request, identity, idempotency_key, document_id, version_id)
