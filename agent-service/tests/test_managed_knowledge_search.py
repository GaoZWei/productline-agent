"""管理检索的授权、查询边界、模型前置、来源定位及无回退契约。"""

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import date
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.errors import ToolException
from app.knowledge.embeddings import EmbeddingIndexDescriptor, QueryEmbedding
from app.knowledge.search import KeywordQueryError, KeywordSearchHit, VectorSearchHit
from app.repositories.managed_knowledge_search import (
    ManagedKnowledgeSearchRepository,
    ManagedKnowledgeSearchSnapshot,
    validate_managed_query,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge import PermissionScope
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge_search import (
    ManagedKnowledgeEvidence,
    ManagedKnowledgeReadContext,
    ManagedKnowledgeSearchFilter,
    ManagedKnowledgeSearchOptions,
)
from app.services.managed_knowledge_search import ManagedKnowledgeSearchService
from app.settings import Settings
from tests.knowledge.import_preflight_fixtures import INDEX

IDENTITY = BusinessIdentity(user_id="search-reviewer", role="REVIEWER")
FILTERS = ManagedKnowledgeSearchFilter(
    effective_at=date(2026, 11, 7), permission_scope=PermissionScope.INTERNAL_REVIEWER
)
QUERY_VECTOR = QueryEmbedding(
    EmbeddingIndexDescriptor(INDEX.provider, INDEX.model, 1536, INDEX.index_version),
    (1.0,) + (0.0,) * 1535,
)


@dataclass
class SearchHarness:
    """授权Client真实校验信封，知识读取与向量生成使用可观察替身。"""

    service: ManagedKnowledgeSearchService
    repository: Mock
    generator: Mock
    events: list[str]
    outcomes: list[str]


@pytest_asyncio.fixture
async def search() -> AsyncIterator[SearchHarness]:
    """来源身份与分块数据稳定，不调用数据库、文件或真实模型。"""
    events: list[str] = []
    outcomes: list[str] = []

    async def authorize(request: httpx.Request) -> httpx.Response:
        """只模拟Java READ，保留请求关联和失败关闭的真实Client。"""
        action = json.loads(request.content)["action"]
        assert action == "READ"
        events.append(action)
        denied = bool(outcomes and outcomes.pop(0) == "DENIED")
        trace = request.headers["X-Trace-Id"]
        return httpx.Response(
            403 if denied else 200,
            headers={"X-Trace-Id": trace},
            json={
                "success": not denied,
                "code": "PERMISSION_DENIED" if denied else "SUCCESS",
                "message": "denied" if denied else "success",
                "trace_id": trace,
                "retryable": False,
                "data": None
                if denied
                else {
                    "userId": request.headers["X-User-Id"],
                    "action": action,
                    "permissionScope": "INTERNAL_REVIEWER",
                    "confirmationRequired": False,
                },
            },
        )

    client = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(authorize)
    )
    context = ManagedKnowledgeReadContext(
        configured_source_mode="LEGACY", release_revision=7, index=INDEX
    )
    content = "坐标信息必须一致。"
    # 明确构造同一块的两路数据，融合后必须仍能定位到管理修订。
    keyword = KeywordSearchHit(
        chunk_id="chunk-1",
        document_id="COORDINATE-REFERENCE-002",
        document_name="测试规范",
        document_version="2.0",
        chunk_index=0,
        section_path=("要求",),
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        keyword_score=0.5,
    )
    vector = VectorSearchHit(
        chunk_id=keyword.chunk_id,
        document_id=keyword.document_id,
        document_name=keyword.document_name,
        document_version=keyword.document_version,
        chunk_index=0,
        section_path=keyword.section_path,
        content=content,
        content_hash=keyword.content_hash,
        vector_score=1.0,
    )
    binding = ManagedKnowledgeEvidence(
        citation_document_id=keyword.document_id,
        chunk_id=keyword.chunk_id,
        document_id="DOC-" + "1" * 32,
        version_id="VER-" + "1" * 32,
        revision_no=1,
        generation_id="GEN-" + "1" * 32,
    )
    snapshot = ManagedKnowledgeSearchSnapshot(context, (keyword,), (vector,), (binding,))

    async def retrieve(*args: object, **kwargs: object) -> ManagedKnowledgeSearchSnapshot:
        """记录数据库读取发生于查询向量完成之后。"""
        events.append("SQL")
        return snapshot

    async def generate(query: str) -> QueryEmbedding:
        """完整查询用于向量生成，不传入经缩减的关键词词元。"""
        events.append("EMBEDDING")
        return QUERY_VECTOR

    repository = Mock(spec=ManagedKnowledgeSearchRepository)
    repository.search = AsyncMock(side_effect=retrieve)
    generator = Mock()
    generator.generate_query = AsyncMock(side_effect=generate)
    service = ManagedKnowledgeSearchService(
        repository, KnowledgeAuthorizationClient(client), generator
    )
    yield SearchHarness(service, repository, generator, events, outcomes)
    await client.aclose()


async def test_managed_search_authorizes_generates_then_reads_and_retains_references(
    search: SearchHarness,
) -> None:
    result = await search.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert search.events == ["READ", "EMBEDDING", "SQL"]
    assert result.context.source == "MANAGED" and result.context.configured_source_mode == "LEGACY"
    assert result.results[0].document_id == "COORDINATE-REFERENCE-002"
    assert result.evidence[0].version_id.startswith("VER-")
    search.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await search.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert search.repository.search.await_count == search.generator.generate_query.await_count == 1


@pytest.mark.parametrize("query", ["", "   ", "坐", "!", "x" * 2001])
async def test_managed_search_rejects_bad_query_before_model_or_sql(
    search: SearchHarness, query: str
) -> None:
    with pytest.raises(KeywordQueryError):
        await search.service.retrieve(query, filters=FILTERS, identity=IDENTITY)
    search.generator.generate_query.assert_not_awaited()
    search.repository.search.assert_not_awaited()


async def test_managed_search_scope_cannot_be_granted_by_filter(search: SearchHarness) -> None:
    forged = FILTERS.model_copy(update={"permission_scope": "OUT_OF_SCOPE"})
    with pytest.raises(KnowledgeManagementError, match="PERMISSION_DENIED"):
        await search.service.retrieve("坐标", filters=forged, identity=IDENTITY)
    search.generator.generate_query.assert_not_awaited()
    search.repository.search.assert_not_awaited()


async def test_managed_search_model_failure_never_reads_or_falls_back(
    search: SearchHarness,
) -> None:
    search.generator.generate_query.side_effect = TimeoutError("model unavailable")
    with pytest.raises(TimeoutError):
        await search.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    search.repository.search.assert_not_awaited()


async def test_managed_search_sql_failure_is_safe_and_does_not_fall_back(
    search: SearchHarness,
) -> None:
    search.repository.search.side_effect = SQLAlchemyError("private connection and SQL")
    with pytest.raises(
        KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"
    ) as caught:
        await search.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert "private" not in str(caught.value) and search.repository.search.await_count == 1


async def test_managed_search_requires_complete_evidence_and_returns_empty_without_old_source(
    search: SearchHarness,
) -> None:
    search.repository.search.side_effect = None
    context = ManagedKnowledgeReadContext(
        configured_source_mode="LEGACY", release_revision=8, index=INDEX
    )
    search.repository.search.return_value = ManagedKnowledgeSearchSnapshot(context, (), (), ())
    result = await search.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)
    assert result.results == () and result.evidence == () and result.context.release_revision == 8
    content = "坐标一致"
    keyword = KeywordSearchHit(
        "chunk-1",
        "TEST-001",
        "测试",
        "1.0",
        0,
        ("正文",),
        content,
        hashlib.sha256(content.encode()).hexdigest(),
        0.5,
    )
    search.repository.search.return_value = ManagedKnowledgeSearchSnapshot(
        context, (keyword,), (), ()
    )
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_DATA_INVALID"):
        await search.service.retrieve("坐标", filters=FILTERS, identity=IDENTITY)


@pytest.mark.parametrize(
    "vector",
    [
        (0.0,) * 1536,
        (1.0,),
        (float("nan"),) + (0.0,) * 1535,
        (float("inf"),) + (0.0,) * 1535,
        (1e39,) + (0.0,) * 1535,
        (1e-100,) + (0.0,) * 1535,
    ],
)
def test_managed_search_validates_query_embedding(vector: tuple[float, ...]) -> None:
    with pytest.raises(KnowledgeManagementError, match="INVALID_QUERY_EMBEDDING"):
        validate_managed_query(replace(QUERY_VECTOR, vector=vector), INDEX)


def test_managed_search_rejects_wrong_query_index_and_keeps_processing_level_local() -> None:
    with pytest.raises(KnowledgeManagementError, match="MANAGED_QUERY_INDEX_MISMATCH"):
        validate_managed_query(QUERY_VECTOR, INDEX.model_copy(update={"model": "another-model"}))
    assert (
        ManagedKnowledgeSearchFilter.model_validate(
            {**FILTERS.model_dump(), "processing_level": "L2"}
        ).processing_level
        == "L2"
    )
    with pytest.raises(ValidationError):
        ManagedKnowledgeSearchFilter.model_validate({"effective_at": date(2026, 11, 7)})


@pytest.mark.parametrize(
    "payload",
    [
        {"channel_top_k": True},
        {"channel_top_k": 1.5},
        {"channel_top_k": 0},
        {"hybrid_top_k": 101},
        {"min_vector_similarity": True},
        {"min_vector_similarity": float("nan")},
        {"min_vector_similarity": 1.1},
    ],
)
def test_managed_search_options_are_strict(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ManagedKnowledgeSearchOptions.model_validate(payload)
