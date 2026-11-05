"""授权之后才解析multipart，限制请求总量并关闭所有完整或部分接收的文件。"""

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from pydantic import ValidationError
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect, Request

from app.knowledge.storage import MAX_ORIGINAL_BYTES
from app.schemas.knowledge_management import KnowledgeManagementError, KnowledgeUploadCommand
from app.schemas.knowledge_upload import KnowledgeUploadHttpCommand

MAX_COMMAND_BYTES = 16 * 1024
MAX_UPLOAD_BODY_BYTES = MAX_ORIGINAL_BYTES + 64 * 1024


class KnowledgeMultipartParser(MultiPartParser):
    """隔离Starlette内部的部分文件清理，取消和断流时也不能遗留已打开的临时文件。"""

    def on_part_end(self) -> None:
        """命令必须是UTF-8，拒绝框架为显示普通表单而采用的Latin-1回退。"""

        if self._current_part.file is None and self._current_part.field_name == "command":
            if self._charset.lower() not in {"utf-8", "utf8"}:
                raise MultiPartException("command must use UTF-8")
            try:
                bytes(self._current_part.data).decode("utf-8")
            except UnicodeDecodeError:
                raise MultiPartException("command must use UTF-8") from None
        super().on_part_end()

    def close_files(self) -> None:
        """失败时没有完整FormData，使用锁定版本解析器登记的文件集合统一关闭。"""

        for file in self._files_to_close_on_error:
            file.close()


async def _limited_stream(request: Request) -> AsyncGenerator[bytes, None]:
    """不信任Content-Length，chunked请求同样逐块累计并限制实际字节数。"""

    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BODY_BYTES:
            raise KnowledgeManagementError("REQUEST_TOO_LARGE")
        yield chunk


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """拒绝重复JSON键，避免页面显示和服务端实际解释不同。"""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _command(
    form: FormData, *, document_id: str | None, version_id: str | None, idempotency_key: str
) -> tuple[KnowledgeUploadCommand, UploadFile]:
    """只接收command和file各一个，文件名和资源身份不能由JSON覆盖。"""

    if sorted(key for key, _ in form.multi_items()) != ["command", "file"]:
        raise KnowledgeManagementError("INVALID_UPLOAD_COMMAND")
    encoded, file = form["command"], form["file"]
    if not isinstance(encoded, str) or not isinstance(file, UploadFile) or not file.filename:
        raise KnowledgeManagementError("INVALID_UPLOAD_COMMAND")
    try:
        if len(encoded.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise ValueError("command too large")
        json.loads(encoded, object_pairs_hook=_unique_object)
        command = KnowledgeUploadHttpCommand.model_validate_json(encoded)
        # JSON可使用转义的孤立代理字符，必须在进入哈希/数据库前拒绝不可编码文本。
        json.dumps(command.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
        result = KnowledgeUploadCommand(
            filename=file.filename,
            metadata=command.metadata,
            idempotency_key=idempotency_key,
            document_id=document_id,
            version_id=version_id,
            expected_row_version=command.expected_row_version,
            expected_revision_no=command.expected_revision_no,
        )
    except (ValueError, ValidationError):
        raise KnowledgeManagementError("INVALID_UPLOAD_COMMAND") from None
    if file.size is not None and file.size > MAX_ORIGINAL_BYTES:
        raise KnowledgeManagementError("FILE_TOO_LARGE")
    return result, file


@asynccontextmanager
async def upload_body(
    request: Request, *, document_id: str | None, version_id: str | None, idempotency_key: str
) -> AsyncIterator[tuple[KnowledgeUploadCommand, UploadFile]]:
    """限制原始请求和字段数量，所有退出路径关闭临时文件，取消保持向上传播。"""

    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != "multipart/form-data":
        raise KnowledgeManagementError("UNSUPPORTED_MEDIA_TYPE")
    declared_size = request.headers.get("content-length")
    if declared_size is not None:
        try:
            size = int(declared_size)
            if size < 0:
                raise ValueError("negative size")
        except ValueError:
            raise KnowledgeManagementError("INVALID_MULTIPART") from None
        if size > MAX_UPLOAD_BODY_BYTES:
            raise KnowledgeManagementError("REQUEST_TOO_LARGE")
    parser = KnowledgeMultipartParser(
        headers=request.headers,
        stream=_limited_stream(request),
        max_files=1,
        max_fields=1,
        max_part_size=MAX_COMMAND_BYTES,
    )
    try:
        form = await parser.parse()
        yield _command(
            form, document_id=document_id, version_id=version_id, idempotency_key=idempotency_key
        )
    except (MultiPartException, MultipartParseError):
        raise KnowledgeManagementError("INVALID_MULTIPART") from None
    except ClientDisconnect:
        raise KnowledgeManagementError("UPLOAD_INTERRUPTED") from None
    except OSError:
        raise KnowledgeManagementError("UPLOAD_TEMPORARY_UNAVAILABLE") from None
    finally:
        parser.close_files()


async def file_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    """分段传给原件适配器，原件层仍独立校验大小、编码与正文。"""

    while chunk := await file.read(64 * 1024):
        yield chunk
