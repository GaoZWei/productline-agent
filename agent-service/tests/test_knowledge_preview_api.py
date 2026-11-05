"""指定修订预览的真实授权Client、确定性分块及HTTP安全边界验收。"""

import hashlib
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.knowledge.storage import KnowledgeOriginalStorage
from app.main import create_app
from app.repositories.managed_knowledge import ManagedKnowledgeRepository, RevisionRead
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge import ManagedKnowledgeRevisionSnapshot
from app.services.knowledge_management import KnowledgeManagementService
from app.settings import Settings
from tests.knowledge.managed_knowledge_fixtures import DOCUMENT_ID, VERSION_ID, revision_payload

ROOT = f"/api/agent/knowledge/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/revisions"
PATH = ROOT + "/1/preview"
HEADERS = {"X-User-Id": "reader", "X-User-Role": "REVIEWER", "X-Trace-Id": "kb-preview-test"}
BODY = "\n# 测试规范\n\n## 要求\n PRIVATE-PREVIEW <script>text</script> \n"


@pytest_asyncio.fixture
async def preview_api() -> AsyncIterator[tuple[httpx.AsyncClient, Mock, Mock, list[str]]]:
    """只替换知识读取结果，应用实际校验Java响应并执行相同分块算法。"""

    snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
        revision_payload(body=BODY, normalized_hash=hashlib.sha256(BODY.encode()).hexdigest())
    )
    repository = Mock(spec=ManagedKnowledgeRepository)
    repository.read_revision = AsyncMock(
        return_value=RevisionRead(
            DOCUMENT_ID, VERSION_ID, 4, 2, "DRAFT", snapshot, snapshot.metadata_digest()
        )
    )
    repository.recover_interrupted = AsyncMock()
    storage = Mock(spec=KnowledgeOriginalStorage)
    outcomes: list[str] = []

    async def authorize(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"action": "READ"}
        outcome = outcomes.pop(0) if outcomes else "SUCCESS"
        if outcome == "TIMEOUT":
            raise httpx.ReadTimeout("secret upstream path", request=request)
        if outcome == "NETWORK":
            raise httpx.ConnectError("secret upstream token", request=request)
        trace = request.headers["X-Trace-Id"]
        status = 403 if outcome == "DENIED" else 200
        return httpx.Response(
            status,
            headers={"X-Trace-Id": trace},
            json={
                "success": status == 200,
                "code": "PERMISSION_DENIED" if status == 403 else "SUCCESS",
                "message": "secret Java payload",
                "trace_id": trace,
                "retryable": False,
                "data": None
                if status == 403
                else {
                    "userId": "other" if outcome == "MISMATCH" else "reader",
                    "action": "READ",
                    "permissionScope": "INTERNAL_REVIEWER",
                    "confirmationRequired": False,
                },
            },
        )

    business = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(authorize)
    )
    service = KnowledgeManagementService(
        repository, storage, KnowledgeAuthorizationClient(business)
    )
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, repository, storage, outcomes
    await business.aclose()


async def test_knowledge_preview_http_preserves_body_chunks_and_revision_identity(
    preview_api: tuple[httpx.AsyncClient, Mock, Mock, list[str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, repository, storage, _ = preview_api
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert response.headers["content-type"].startswith("application/json")
    result = response.json()
    assert result["body"] == BODY and result["revision_no"] == 1
    assert not result["is_current_revision"] and result["row_version"] == 4
    assert result["version_id"] == VERSION_ID and result["document_id"] == DOCUMENT_ID
    assert [item["section_path"] for item in result["chunks"]] == [
        ["测试规范"],
        ["测试规范", "要求"],
    ]
    assert "<script>text</script>" in result["chunks"][-1]["content"]
    assert set(result) == {
        "document_id",
        "version_id",
        "revision_no",
        "row_version",
        "is_current_revision",
        "metadata",
        "body",
        "chunks",
    }
    repository.read_revision.assert_awaited_once_with(
        VERSION_ID, 1, "INTERNAL_REVIEWER", document_id=DOCUMENT_ID
    )
    repository.recover_interrupted.assert_not_called()
    storage.read.assert_not_called()
    assert "PRIVATE-PREVIEW" not in caplog.text


async def test_knowledge_preview_http_missing_identity_never_reads(
    preview_api: tuple[httpx.AsyncClient, Mock, Mock, list[str]],
) -> None:
    client, repository, storage, _ = preview_api
    for headers in ({}, {**HEADERS, "Authorization": "Basic secret"}):
        response = await client.get(PATH, headers=headers)
        assert response.status_code == 401 and "PRIVATE-PREVIEW" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
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
async def test_knowledge_preview_http_authorization_failure_never_reads(
    preview_api: tuple[httpx.AsyncClient, Mock, Mock, list[str]],
    outcome: str,
    status: int,
) -> None:
    client, repository, _, outcomes = preview_api
    outcomes.extend([outcome] * 2)
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == status and "secret" not in response.text
    assert response.json()["trace_id"] == "kb-preview-test"
    repository.read_revision.assert_not_called()
    repository.recover_interrupted.assert_not_called()


@pytest.mark.parametrize(
    "path",
    (
        ROOT + "/0/preview",
        ROOT + "/-1/preview",
        ROOT + "/2147483648/preview",
        ROOT + "/not-a-revision/preview",
        PATH.replace(DOCUMENT_ID, "invalid"),
        PATH.replace(VERSION_ID, "invalid"),
    ),
)
async def test_knowledge_preview_http_validates_full_target(
    preview_api: tuple[httpx.AsyncClient, Mock, Mock, list[str]],
    path: str,
) -> None:
    client, repository, _, _ = preview_api
    assert (await client.get(path, headers=HEADERS)).status_code == 422
    repository.read_revision.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status", "code"),
    (
        (KnowledgeManagementError("RESOURCE_NOT_FOUND"), 404, "RESOURCE_NOT_FOUND"),
        (KnowledgeManagementError("PREVIEW_NOT_READY"), 409, "PREVIEW_NOT_READY"),
        (KnowledgeManagementError("KNOWLEDGE_DATA_INVALID"), 503, "KNOWLEDGE_PREVIEW_UNAVAILABLE"),
        (SQLAlchemyError("secret SQL /raw/file"), 503, "KNOWLEDGE_PREVIEW_UNAVAILABLE"),
    ),
)
async def test_knowledge_preview_http_maps_safe_failure_results(
    preview_api: tuple[httpx.AsyncClient, Mock, Mock, list[str]],
    error: Exception,
    status: int,
    code: str,
) -> None:
    client, repository, _, _ = preview_api
    repository.read_revision.side_effect = error
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == status and response.json()["code"] == code
    assert "secret" not in response.text and "PRIVATE-PREVIEW" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


async def test_knowledge_preview_http_rechecks_permission_and_does_not_prepare_missing_body(
    preview_api: tuple[httpx.AsyncClient, Mock, Mock, list[str]],
) -> None:
    client, repository, storage, outcomes = preview_api
    assert (await client.get(PATH, headers=HEADERS)).status_code == 200
    outcomes.append("DENIED")
    assert (await client.get(PATH, headers=HEADERS)).status_code == 403
    assert repository.read_revision.call_count == 1
    old = repository.read_revision.return_value
    pending = ManagedKnowledgeRevisionSnapshot.model_validate(revision_payload())
    repository.read_revision.return_value = RevisionRead(
        old.document_id,
        old.citation_document_id,
        old.row_version,
        old.current_revision_no,
        old.publication_state,
        pending,
        pending.metadata_digest(),
    )
    response = await client.get(PATH, headers=HEADERS)
    assert response.status_code == 409 and response.json()["code"] == "PREVIEW_NOT_READY"
    repository.recover_interrupted.assert_not_called()
    storage.read.assert_not_called()
