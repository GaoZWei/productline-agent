"""只读知识管理HTTP入口的授权顺序、参数与失败脱敏验收。"""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.main import create_app
from app.repositories.knowledge_management_read import KnowledgeManagementReadRepository
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_management_read import KnowledgeDocumentSummary, KnowledgePage
from app.services.knowledge_management_read import KnowledgeManagementReadService
from app.settings import Settings

DOC = "DOC-" + "A" * 32
VER = "VER-" + "B" * 32
TASK = "TASK-" + "C" * 32
ROOT = "/api/agent/knowledge"
PATHS = (
    "/documents",
    f"/documents/{DOC}",
    f"/documents/{DOC}/versions",
    f"/documents/{DOC}/versions/{VER}",
    f"/documents/{DOC}/tasks",
    f"/tasks/{TASK}",
)
HEADERS = {"X-User-Id": "reader", "X-User-Role": "REVIEWER", "X-Trace-Id": "kb-read-test"}


@pytest_asyncio.fixture
async def read_api() -> AsyncIterator[tuple[httpx.AsyncClient, Mock, list[str]]]:
    """真实授权Client与HTTP路由，替换SQL结果以独立覆盖失败分支。"""

    repository = Mock(spec=KnowledgeManagementReadRepository)
    repository.query = AsyncMock(
        return_value=KnowledgePage[KnowledgeDocumentSummary](
            items=(), page=1, page_size=20, total=0
        )
    )
    outcomes: list[str] = []

    async def authorize(request: httpx.Request) -> httpx.Response:
        """模拟Java信封，响应不能用来绕过真正Client的绑定校验。"""

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
                "message": "secret Java details",
                "trace_id": trace,
                "retryable": False,
                "data": None
                if status == 403
                else {
                    "userId": "intruder" if outcome == "MISMATCH" else request.headers["X-User-Id"],
                    "action": "READ",
                    "permissionScope": "INTERNAL_REVIEWER",
                    "confirmationRequired": False,
                },
            },
        )

    business = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(authorize)
    )
    authorizer = KnowledgeAuthorizationClient(business)
    app = create_app(Settings(environment="test"))
    # 不执行lifespan, 防止测试创建默认数据库连接或恢复管理任务。
    from app.api import knowledge_management as api

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            api, "_service", lambda _: KnowledgeManagementReadService(repository, authorizer)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, repository, outcomes
    await business.aclose()


@pytest.mark.parametrize("path", PATHS)
async def test_knowledge_read_api_requires_identity_and_fresh_java_authorization(
    read_api: tuple[httpx.AsyncClient, Mock, list[str]],
    path: str,
) -> None:
    client, repository, outcomes = read_api
    for headers in ({}, {**HEADERS, "Authorization": "Basic secret"}):
        response = await client.get(ROOT + path, headers=headers)
        assert response.status_code == 401
    outcomes.append("DENIED")
    response = await client.get(ROOT + path, headers=HEADERS)
    assert response.status_code == 403
    assert response.json()["trace_id"] == "kb-read-test"
    assert "secret" not in response.text
    repository.query.assert_not_called()


@pytest.mark.parametrize(
    "suffix",
    (
        "/documents?page=0",
        "/documents?page_size=101",
        "/documents?page=1000001",
        "/documents?page_size=no",
        "/documents/not-an-id",
        f"/documents/{DOC}/versions?page_size=0",
        f"/documents/{DOC}/tasks?page=-1",
        f"/documents/{DOC}/versions/invalid",
        "/tasks/invalid",
    ),
)
async def test_knowledge_read_api_rejects_invalid_pagination_and_identifiers(
    read_api: tuple[httpx.AsyncClient, Mock, list[str]],
    suffix: str,
) -> None:
    client, repository, _ = read_api
    assert (await client.get(ROOT + suffix, headers=HEADERS)).status_code == 422
    repository.query.assert_not_called()


async def test_knowledge_read_api_rechecks_authorization_after_success(
    read_api: tuple[httpx.AsyncClient, Mock, list[str]],
) -> None:
    client, repository, outcomes = read_api
    response = await client.get(ROOT + "/documents?page=2&page_size=1", headers=HEADERS)
    assert response.status_code == 200 and response.json()["total"] == 0
    query, scope = repository.query.call_args.args
    assert (query.page, query.page_size, scope) == (2, 1, "INTERNAL_REVIEWER")
    outcomes.append("DENIED")
    assert (await client.get(ROOT + "/documents", headers=HEADERS)).status_code == 403
    assert repository.query.call_count == 1


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    (
        ("MISMATCH", 502, "AUTHORIZATION_UNAVAILABLE"),
        ("TIMEOUT", 504, "AUTHORIZATION_TIMEOUT"),
        ("NETWORK", 502, "AUTHORIZATION_UNAVAILABLE"),
    ),
)
async def test_knowledge_read_api_authorization_failure_never_queries_sql(
    read_api: tuple[httpx.AsyncClient, Mock, list[str]],
    outcome: str,
    status: int,
    code: str,
) -> None:
    client, repository, outcomes = read_api
    outcomes.extend([outcome] * 2)
    response = await client.get(ROOT + "/documents", headers=HEADERS)
    assert response.status_code == status and response.json()["code"] == code
    assert "secret" not in response.text
    repository.query.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    (
        (KnowledgeManagementError("RESOURCE_NOT_FOUND"), 404),
        (SQLAlchemyError("secret SQL /raw/files token"), 503),
    ),
)
async def test_knowledge_read_api_hides_resource_and_database_errors(
    read_api: tuple[httpx.AsyncClient, Mock, list[str]],
    error: Exception,
    status: int,
) -> None:
    client, repository, _ = read_api
    repository.query.side_effect = error
    response = await client.get(ROOT + "/documents", headers=HEADERS)
    assert response.status_code == status
    assert "secret" not in response.text
