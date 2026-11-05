"""原件下载的授权、字节附件、安全文件名和失败不泄露内容的HTTP契约。"""

import hashlib
from unittest.mock import Mock
from urllib.parse import unquote

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.managed_knowledge import RevisionRead
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge import ManagedKnowledgeRevisionSnapshot
from tests.knowledge.managed_knowledge_fixtures import DOCUMENT_ID, VERSION_ID, revision_payload
from tests.test_knowledge_preview_api import HEADERS, ROOT
from tests.test_knowledge_preview_api import preview_api as preview_api

type ApiHarness = tuple[httpx.AsyncClient, Mock, Mock, list[str]]
PATH = ROOT + "/1/original"
RAW = b"\xef\xbb\xbf# ORIGINAL-PRIVATE\r\n\r\noriginal bytes\r\n"
FILENAME = '中文 "规范";v1%.MD'


@pytest.fixture
def original_api(preview_api: ApiHarness) -> ApiHarness:
    """复用真实授权Client，未解析快照也允许读取可信原件。"""

    _, repository, storage, _ = preview_api
    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(
            original_filename=FILENAME, raw_hash=hashlib.sha256(RAW).hexdigest(), byte_size=len(RAW)
        )
    )
    repository.read_revision.return_value = RevisionRead(
        DOCUMENT_ID, VERSION_ID, 4, 2, "DRAFT", snapshot, snapshot.metadata_digest()
    )
    storage.read.return_value = RAW
    return preview_api


async def test_knowledge_original_http_preserves_bytes_and_safe_attachment(
    original_api: ApiHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, repository, storage, _ = original_api
    response = await client.get(
        PATH + "?filename=wrong.txt&original_key=/etc/passwd", headers=HEADERS
    )
    assert response.status_code == 200 and response.content == RAW
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-length"] == str(len(RAW))
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith(
        "attachment; filename=\"knowledge-original.md\"; filename*=UTF-8''"
    )
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]) == FILENAME
    assert all(ord(char) < 128 and char not in "\r\n" for char in disposition)
    assert "etag" not in response.headers and "last-modified" not in response.headers
    assert "accept-ranges" not in response.headers
    repository.read_revision.assert_awaited_once_with(
        VERSION_ID, 1, "INTERNAL_REVIEWER", document_id=DOCUMENT_ID
    )
    repository.recover_interrupted.assert_not_called()
    storage.read.assert_called_once_with(
        f"versions/{VERSION_ID}/revisions/1/original.md", hashlib.sha256(RAW).hexdigest(), len(RAW)
    )
    assert "ORIGINAL-PRIVATE" not in caplog.text


async def test_knowledge_original_http_missing_identity_never_reads(
    original_api: ApiHarness,
) -> None:
    client, repository, storage, _ = original_api
    for headers in ({}, {**HEADERS, "Authorization": "Basic secret"}):
        response = await client.get(PATH, headers=headers)
        assert response.status_code == 401 and "ORIGINAL-PRIVATE" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert "content-disposition" not in response.headers
    repository.read_revision.assert_not_called()
    repository.recover_interrupted.assert_not_called()
    storage.read.assert_not_called()


@pytest.mark.parametrize(
    ("outcome", "status"),
    (
        ("DENIED", 403),
        ("MISMATCH", 502),
        ("TIMEOUT", 504),
        ("NETWORK", 502),
    ),
)
async def test_knowledge_original_http_authorization_failure_never_reads(
    original_api: ApiHarness,
    outcome: str,
    status: int,
) -> None:
    client, repository, storage, outcomes = original_api
    outcomes.extend([outcome] * 2)
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == status and "secret" not in response.text
    assert response.json()["trace_id"] == "kb-preview-test"
    assert "content-disposition" not in response.headers
    repository.read_revision.assert_not_called()
    storage.read.assert_not_called()


@pytest.mark.parametrize(
    "path",
    (
        ROOT + "/0/original",
        ROOT + "/-1/original",
        ROOT + "/2147483648/original",
        ROOT + "/invalid/original",
        PATH.replace(DOCUMENT_ID, "invalid"),
        PATH.replace(VERSION_ID, "invalid"),
    ),
)
async def test_knowledge_original_http_validates_target(
    original_api: ApiHarness, path: str
) -> None:
    client, repository, storage, _ = original_api
    assert (await client.get(path, headers=HEADERS)).status_code == 422
    repository.read_revision.assert_not_called()
    storage.read.assert_not_called()


@pytest.mark.parametrize(
    ("code", "status", "public_code"),
    (
        ("ORIGINAL_NOT_FOUND", 404, "ORIGINAL_NOT_FOUND"),
        ("ORIGINAL_INTEGRITY_ERROR", 503, "ORIGINAL_INTEGRITY_ERROR"),
        ("FILE_TOO_LARGE", 503, "ORIGINAL_INTEGRITY_ERROR"),
        ("STORAGE_ERROR", 503, "KNOWLEDGE_ORIGINAL_UNAVAILABLE"),
        ("INVALID_STORAGE_PATH", 503, "KNOWLEDGE_ORIGINAL_UNAVAILABLE"),
        ("secret /internal/file", 503, "KNOWLEDGE_ORIGINAL_UNAVAILABLE"),
    ),
)
async def test_knowledge_original_http_never_returns_bytes_after_storage_failure(
    original_api: ApiHarness,
    code: str,
    status: int,
    public_code: str,
) -> None:
    client, _, storage, _ = original_api
    storage.read.side_effect = KnowledgeManagementError(code)
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == status and response.json()["code"] == public_code
    assert "ORIGINAL-PRIVATE" not in response.text and "secret" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize(
    "error",
    (
        KnowledgeManagementError("RESOURCE_NOT_FOUND"),
        KnowledgeManagementError("KNOWLEDGE_DATA_INVALID"),
        SQLAlchemyError("secret SQL /internal/path"),
    ),
)
async def test_knowledge_original_http_read_failure_precedes_file_access(
    original_api: ApiHarness,
    error: Exception,
) -> None:
    client, repository, storage, _ = original_api
    repository.read_revision.side_effect = error
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == (404 if str(error) == "RESOURCE_NOT_FOUND" else 503)
    assert "secret" not in response.text and "ORIGINAL-PRIVATE" not in response.text
    storage.read.assert_not_called()


@pytest.mark.parametrize(
    "filename",
    (
        "../private.md",
        "folder\\private.txt",
        "bad\r\nInjected: yes.md",
        "bad\x00.md",
        "wrong.html",
    ),
)
async def test_knowledge_original_http_rejects_unsafe_stored_filename(
    original_api: ApiHarness,
    filename: str,
) -> None:
    client, repository, _, _ = original_api
    old = repository.read_revision.return_value
    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        {**old.snapshot.model_dump(), "original_filename": filename}
    )
    repository.read_revision.return_value = RevisionRead(
        old.document_id,
        old.citation_document_id,
        old.row_version,
        old.current_revision_no,
        old.publication_state,
        snapshot,
        old.metadata_hash,
    )
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == 503 and "content-disposition" not in response.headers
    assert "ORIGINAL-PRIVATE" not in response.text and "Injected" not in response.text


async def test_knowledge_original_http_rechecks_permission_for_range_and_conditional_request(
    original_api: ApiHarness,
) -> None:
    client, repository, _, outcomes = original_api
    response = await client.get(
        PATH, headers={**HEADERS, "Range": "bytes=0-1", "If-None-Match": '"old"'}
    )
    assert response.status_code == 200 and response.content == RAW
    outcomes.append("DENIED")
    denied = await client.get(PATH, headers={**HEADERS, "If-None-Match": '"old"'})
    assert denied.status_code == 403 and "ORIGINAL-PRIVATE" not in denied.text
    assert repository.read_revision.call_count == 1
    repository.recover_interrupted.assert_not_called()
