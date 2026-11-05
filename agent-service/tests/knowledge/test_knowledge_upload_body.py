"""流式multipart在超限、断流和取消时关闭临时文件，完整接收保留原字节。"""

import asyncio
import tempfile
from typing import BinaryIO, cast

import httpx
import pytest
from starlette.requests import Request
from starlette.types import Message

from app.api import knowledge_upload_body as body_api
from app.api.knowledge_upload_body import MAX_UPLOAD_BODY_BYTES, upload_body
from app.schemas.knowledge_management import KnowledgeManagementError
from tests.test_knowledge_upload_api import parts


def request_for(
    messages: list[Message | BaseException], content_type: str, length: str | None = None
) -> Request:
    """显式ASGI消息可以模拟缺失或伪造长度，以及上传途中断开连接。"""

    iterator = iter(messages)

    async def receive() -> Message:
        value = next(iterator)
        if isinstance(value, BaseException):
            raise value
        return value

    headers = [(b"content-type", content_type.encode())]
    if length is not None:
        headers.append((b"content-length", length.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers}, receive)


@pytest.mark.parametrize("ending", ("disconnect", "cancel", "oversize"))
async def test_knowledge_upload_body_closes_partial_spooled_files(
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    opened: list[BinaryIO] = []

    def temporary(*args: object, **kwargs: object) -> BinaryIO:
        file = tempfile.SpooledTemporaryFile(max_size=1024, mode="w+b")
        opened.append(cast(BinaryIO, file))
        return cast(BinaryIO, file)

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", temporary)
    prefix = (
        b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="spec.txt"'
        b"\r\nContent-Type: text/plain\r\n\r\n" + b"a" * 8192
    )
    ending_message: Message | BaseException
    if ending == "disconnect":
        ending_message = {"type": "http.disconnect"}
    elif ending == "cancel":
        ending_message = asyncio.CancelledError()
    else:
        ending_message = {
            "type": "http.request",
            "body": b"b" * MAX_UPLOAD_BODY_BYTES,
            "more_body": False,
        }
    request = request_for(
        [{"type": "http.request", "body": prefix, "more_body": True}, ending_message],
        "multipart/form-data; boundary=boundary",
        "1",
    )
    error = asyncio.CancelledError if ending == "cancel" else KnowledgeManagementError
    with pytest.raises(error) as caught:
        async with upload_body(request, document_id=None, version_id=None, idempotency_key="key"):
            pytest.fail("partial request was accepted")
    if ending != "cancel":
        assert str(caught.value) == (
            "UPLOAD_INTERRUPTED" if ending == "disconnect" else "REQUEST_TOO_LARGE"
        )
    assert opened and all(file.closed for file in opened)


async def test_knowledge_upload_body_closes_complete_file_and_keeps_exact_bytes() -> None:
    original = b"\xef\xbb\xbfraw\r\ntext\r\n"
    form = parts()
    form["file"] = ("规范.txt", original)
    encoded = httpx.Request("POST", "http://test", files=form)
    raw = encoded.read()
    request = request_for(
        [{"type": "http.request", "body": raw, "more_body": False}], encoded.headers["content-type"]
    )
    async with upload_body(request, document_id=None, version_id=None, idempotency_key="key") as (
        _,
        file,
    ):
        assert await file.read() == original
        assert not file.file.closed
    assert file.file.closed


@pytest.mark.parametrize("length", (str(MAX_UPLOAD_BODY_BYTES + 1), "-1", "not-a-number"))
async def test_knowledge_upload_body_checks_declared_size_before_receive(length: str) -> None:
    request = request_for([], "multipart/form-data; boundary=boundary", length)
    with pytest.raises(KnowledgeManagementError):
        async with upload_body(request, document_id=None, version_id=None, idempotency_key="key"):
            pytest.fail("invalid declared size was accepted")


async def test_knowledge_upload_body_rejects_oversized_metadata() -> None:
    encoded = httpx.Request(
        "POST",
        "http://test",
        files={
            "command": (None, "a" * (body_api.MAX_COMMAND_BYTES + 1)),
            "file": ("spec.txt", b"text"),
        },
    )
    raw = encoded.read()
    request = request_for(
        [{"type": "http.request", "body": raw, "more_body": False}], encoded.headers["content-type"]
    )
    with pytest.raises(KnowledgeManagementError, match="INVALID_MULTIPART"):
        async with upload_body(request, document_id=None, version_id=None, idempotency_key="key"):
            pytest.fail("oversized metadata was accepted")


@pytest.mark.parametrize("charset", ("utf-8", "iso-8859-1"))
async def test_knowledge_upload_body_rejects_non_utf8_command(charset: str) -> None:
    raw = (
        b'--boundary\r\nContent-Disposition: form-data; name="command"\r\n\r\n'
        b'{"metadata":{"title":"\xff"}}\r\n--boundary--\r\n'
    )
    request = request_for(
        [{"type": "http.request", "body": raw, "more_body": False}],
        f"multipart/form-data; boundary=boundary; charset={charset}",
    )
    with pytest.raises(KnowledgeManagementError, match="INVALID_MULTIPART"):
        async with upload_body(request, document_id=None, version_id=None, idempotency_key="key"):
            pytest.fail("non-UTF-8 command was accepted")
