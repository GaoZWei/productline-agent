"""上传HTTP的授权门禁、multipart命令、幂等Header和脱敏响应契约。"""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.main import create_app
from app.schemas.knowledge_management import KnowledgeManagementError, KnowledgeUploadResult
from app.services.knowledge_management import KnowledgeManagementService
from app.settings import Settings

ROOT = "/api/agent/knowledge"
DOC, VER = "DOC-" + "A" * 32, "VER-" + "B" * 32
PATHS = ("/documents", f"/documents/{DOC}/versions", f"/documents/{DOC}/versions/{VER}/revisions")
HEADERS = {
    "X-User-Id": "reader",
    "X-User-Role": "REVIEWER",
    "Idempotency-Key": "upload-1",
    "X-Trace-Id": "kb-upload-test",
}


def payload(**updates: object) -> dict[str, object]:
    """JSON日期在HTTP契约中采用ISO字符串，由严格JSON模型解析。"""

    return {
        "metadata": {
            "title": "测试规范",
            "document_type": "QUALITY_SPEC",
            "specification_version": "1.0",
            "effective_date": "2026-01-01",
            "permission_scope": "INTERNAL_REVIEWER",
            "change_summary": "首次上传",
        },
        **updates,
    }


def parts(command: object | None = None) -> dict[str, tuple[None, str] | tuple[str, bytes]]:
    """只提供一个命令和一个文件，不依赖本机真实规范文件。"""

    return {
        "command": (None, json.dumps(payload() if command is None else command)),
        "file": ("规范.txt", "原始正文".encode()),
    }


@pytest_asyncio.fixture
async def upload_api() -> AsyncIterator[tuple[httpx.AsyncClient, Mock, list[str], list[bytes]]]:
    """路由及授权Client为真实实现，仅上传应用结果替换为可检查调用。"""

    outcomes: list[str] = []
    received: list[bytes] = []
    service = Mock(spec=KnowledgeManagementService)

    async def authorize(request: httpx.Request) -> httpx.Response:
        outcome = outcomes.pop(0) if outcomes else "SUCCESS"
        assert json.loads(request.content) == {"action": "UPLOAD"}
        trace = request.headers["X-Trace-Id"]
        if outcome == "TIMEOUT":
            raise httpx.ReadTimeout("secret token", request=request)
        status = 403 if outcome == "DENIED" else 200
        return httpx.Response(
            status,
            headers={"X-Trace-Id": trace},
            json={
                "success": status == 200,
                "code": "PERMISSION_DENIED" if status == 403 else "SUCCESS",
                "message": "secret upstream path",
                "trace_id": trace,
                "retryable": False,
                "data": None
                if status == 403
                else {
                    "userId": "other" if outcome == "MISMATCH" else "reader",
                    "action": "UPLOAD",
                    "permissionScope": "INTERNAL_REVIEWER",
                    "confirmationRequired": True,
                },
            },
        )

    async def upload(*args: object, **kwargs: object) -> KnowledgeUploadResult:
        command, chunks = args
        assert hasattr(command, "filename")
        assert hasattr(chunks, "__aiter__")
        received.append(b"".join([chunk async for chunk in chunks]))
        return KnowledgeUploadResult(
            document_id=DOC,
            version_id=VER,
            revision_no=1,
            operation_id="OP-" + "C" * 32,
            task_id="TASK-" + "D" * 32,
            row_version=1,
            task_state="SUCCEEDED",
            error_code=None,
            is_current_revision=True,
            replayed=False,
        )

    business = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(authorize)
    )
    service.authorizer = KnowledgeAuthorizationClient(business)
    service.upload = AsyncMock(side_effect=upload)
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, service, outcomes, received
    await business.aclose()


@pytest.mark.parametrize("path", PATHS)
async def test_knowledge_upload_requires_authorization_before_reading_body(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
    path: str,
) -> None:
    client, service, outcomes, _ = upload_api

    async def unread_body() -> AsyncIterator[bytes]:
        raise AssertionError("unauthorized request body was consumed")
        yield b""

    for headers in ({"Idempotency-Key": "upload-1"}, HEADERS):
        if headers is HEADERS:
            outcomes.append("DENIED")
        response = await client.post(ROOT + path, headers=headers, content=unread_body())
        assert response.status_code == (403 if headers is HEADERS else 401)
        assert "secret" not in response.text
    service.upload.assert_not_called()


@pytest.mark.parametrize(
    ("path", "updates"),
    (
        (PATHS[0], {}),
        (PATHS[1], {"expected_row_version": 2}),
        (PATHS[2], {"expected_row_version": 2, "expected_revision_no": 1}),
    ),
)
async def test_knowledge_upload_binds_path_filename_and_command(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
    path: str,
    updates: dict[str, int],
) -> None:
    client, service, _, received = upload_api
    response = await client.post(ROOT + path, headers=HEADERS, files=parts(payload(**updates)))
    assert response.status_code == 201 and received == ["原始正文".encode()]
    command = service.upload.call_args.args[0]
    assert command.document_id == (None if path == PATHS[0] else DOC)
    assert command.version_id == (VER if path == PATHS[2] else None)
    assert command.filename == "规范.txt" and command.idempotency_key == "upload-1"
    assert service.upload.call_args.kwargs["trace_id"] == "kb-upload-test"


@pytest.mark.parametrize(
    "extra",
    (
        {"publication_state": "PUBLISHED"},
        {"filename": "server.md"},
        {"document_id": DOC},
        {"original_key": "/secret"},
        {"expected_row_version": True},
        {"expected_revision_no": 1},
    ),
)
async def test_knowledge_upload_rejects_self_reported_state_and_bad_snapshots(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
    extra: dict[str, object],
) -> None:
    client, service, _, _ = upload_api
    response = await client.post(
        ROOT + "/documents", headers=HEADERS, files=parts(payload(**extra))
    )
    assert response.status_code == 422
    assert set(response.json()) == {"trace_id", "code", "message"}
    assert "/secret" not in response.text
    service.upload.assert_not_called()


@pytest.mark.parametrize("raw", ("{bad json", '{"metadata": {}, "metadata": {}}'))
async def test_knowledge_upload_rejects_invalid_and_duplicate_json(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
    raw: str,
) -> None:
    client, service, _, _ = upload_api
    response = await client.post(
        ROOT + "/documents",
        headers=HEADERS,
        files={"command": (None, raw), "file": ("spec.txt", b"text")},
    )
    assert response.status_code == 422
    service.upload.assert_not_called()


@pytest.mark.parametrize(
    ("code", "status"),
    (
        ("FILE_TOO_LARGE", 413),
        ("UNSUPPORTED_FORMAT", 415),
        ("EMPTY_DOCUMENT", 422),
        ("INVALID_ENCODING", 422),
        ("STALE_DOCUMENT", 409),
        ("STALE_REVISION", 409),
        ("IDEMPOTENCY_CONFLICT", 409),
        ("SEALED_VERSION_REQUIRES_NEW_VERSION", 409),
        ("RESOURCE_NOT_FOUND", 404),
        ("KNOWLEDGE_PERSISTENCE_UNAVAILABLE", 503),
        ("secret /internal/location", 503),
    ),
)
async def test_knowledge_upload_maps_safe_application_errors(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
    code: str,
    status: int,
) -> None:
    client, service, _, _ = upload_api
    service.upload.side_effect = KnowledgeManagementError(code)
    response = await client.post(ROOT + "/documents", headers=HEADERS, files=parts())
    assert response.status_code == status and "secret" not in response.text


@pytest.mark.parametrize(("outcome", "status"), (("MISMATCH", 502), ("TIMEOUT", 504)))
async def test_knowledge_upload_authorization_failure_does_not_submit(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
    outcome: str,
    status: int,
) -> None:
    client, service, outcomes, _ = upload_api
    outcomes.extend([outcome] * 2)
    response = await client.post(ROOT + "/documents", headers=HEADERS, files=parts())
    assert response.status_code == status and "secret" not in response.text
    service.upload.assert_not_called()


async def test_knowledge_upload_rejects_wrong_media_shape_and_headers(
    upload_api: tuple[httpx.AsyncClient, Mock, list[str], list[bytes]],
) -> None:
    client, service, _, _ = upload_api
    assert (
        await client.post(ROOT + "/documents", headers=HEADERS, json=payload())
    ).status_code == 415
    missing_key = {key: value for key, value in HEADERS.items() if key != "Idempotency-Key"}
    assert (
        await client.post(ROOT + "/documents", headers=missing_key, files=parts())
    ).status_code == 422
    for files in (
        {"file": ("spec.txt", b"text")},
        [*parts().items(), ("file", ("second.txt", b"text"))],
    ):
        response = await client.post(ROOT + "/documents", headers=HEADERS, files=files)
        assert response.status_code in {400, 422}
    service.upload.assert_not_called()
