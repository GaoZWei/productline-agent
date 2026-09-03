"""M7.6-C知识索引能力状态与只读HTTP契约测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import create_app
from app.repositories import KnowledgeIndexState, StoredKnowledgeDocumentIndex
from app.schemas.knowledge import EMBEDDING_DIMENSION
from app.schemas.knowledge_index import (
    KnowledgeIndexCapabilitiesResponse,
    KnowledgeIndexIdentity,
    KnowledgeIndexStatus,
)
from app.services.knowledge_index_capabilities import KnowledgeIndexCapabilityService
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT, load_document_catalog
from app.settings import Settings


def _expected_ids() -> tuple[str, ...]:
    return tuple(
        document.document_id for document in load_document_catalog(DEFAULT_KNOWLEDGE_ROOT).documents
    )


def _state(
    *,
    document_ids: tuple[str, ...] | None = None,
    chunk_count: int = 5,
    index_version: str = "text-embedding-3-small-1536-v1",
) -> KnowledgeIndexState:
    return KnowledgeIndexState(
        documents=tuple(
            StoredKnowledgeDocumentIndex(
                document_id=document_id,
                chunk_count=chunk_count,
                embedding_provider="openai_compatible",
                embedding_model="text-embedding-3-small",
                embedding_dimension=EMBEDDING_DIMENSION,
                index_version=index_version,
            )
            for document_id in document_ids or _expected_ids()
        )
    )


class _StateRepository:
    def __init__(self, state: KnowledgeIndexState) -> None:
        self.state = state

    async def get_index_state(self) -> KnowledgeIndexState:
        return self.state


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capability_distinguishes_empty_incomplete_mismatch_and_ready() -> None:
    service = KnowledgeIndexCapabilityService(Settings(environment="test"))

    empty = await service.get(_StateRepository(KnowledgeIndexState(documents=())))
    incomplete = await service.get(_StateRepository(_state(document_ids=_expected_ids()[:-1])))
    mismatch = await service.get(_StateRepository(_state(index_version="different-index-v2")))
    ready = await service.get(_StateRepository(_state()))

    assert empty.status is KnowledgeIndexStatus.NOT_INDEXED
    assert empty.ready is False
    assert empty.document_count == empty.chunk_count == 0
    assert incomplete.status is KnowledgeIndexStatus.INCOMPLETE
    assert incomplete.document_count == 15
    assert mismatch.status is KnowledgeIndexStatus.INDEX_MISMATCH
    assert mismatch.stored_index is not None
    assert mismatch.stored_index.index_version == "different-index-v2"
    assert ready.status is KnowledgeIndexStatus.READY
    assert ready.ready is True
    assert ready.expected_document_count == ready.document_count == 16
    assert ready.chunk_count == 80
    assert ready.stored_index == ready.expected_index


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capability_rejects_document_without_chunks_and_mixed_identity() -> None:
    service = KnowledgeIndexCapabilityService(Settings(environment="test"))
    no_chunks_documents = list(_state().documents)
    no_chunks_documents[0] = replace(no_chunks_documents[0], chunk_count=0)
    mixed_documents = list(_state().documents)
    mixed_documents[0] = replace(mixed_documents[0], index_version="other-v2")

    incomplete = await service.get(
        _StateRepository(KnowledgeIndexState(tuple(no_chunks_documents)))
    )
    mismatch = await service.get(_StateRepository(KnowledgeIndexState(tuple(mixed_documents))))

    assert incomplete.status is KnowledgeIndexStatus.INCOMPLETE
    assert mismatch.status is KnowledgeIndexStatus.INDEX_MISMATCH
    assert mismatch.stored_index is None


@pytest.mark.unit
def test_capability_schema_rejects_ready_count_or_identity_mismatch() -> None:
    expected = KnowledgeIndexIdentity(
        provider="openai_compatible",
        model="text-embedding-3-small",
        dimension=EMBEDDING_DIMENSION,
        index_version="expected-v1",
    )

    with pytest.raises(ValidationError, match="must match expected catalog"):
        KnowledgeIndexCapabilitiesResponse(
            ready=True,
            status=KnowledgeIndexStatus.READY,
            expected_document_count=16,
            document_count=15,
            chunk_count=80,
            expected_index=expected,
            stored_index=expected,
        )


class _FakeDatabase:
    @asynccontextmanager
    async def session(self) -> AsyncIterator[object]:
        yield object()


class _FakeCapabilityService:
    def __init__(self, response: KnowledgeIndexCapabilitiesResponse) -> None:
        self.response = response
        self.calls = 0

    async def get(self, repository: object) -> KnowledgeIndexCapabilitiesResponse:
        self.calls += 1
        return self.response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_knowledge_index_capability_endpoint_returns_safe_readiness() -> None:
    application = create_app(Settings(environment="test"))
    expected = KnowledgeIndexIdentity(
        provider="openai_compatible",
        model="text-embedding-3-small",
        dimension=EMBEDDING_DIMENSION,
        index_version="text-embedding-3-small-1536-v1",
    )
    response = KnowledgeIndexCapabilitiesResponse(
        ready=True,
        status=KnowledgeIndexStatus.READY,
        expected_document_count=16,
        document_count=16,
        chunk_count=80,
        expected_index=expected,
        stored_index=expected,
    )
    service = _FakeCapabilityService(response)
    application.state.database = _FakeDatabase()
    application.state.knowledge_index_capability_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        result = await client.get("/api/agent/capabilities/knowledge-index")

    assert result.status_code == 200
    assert result.json()["status"] == "READY"
    assert result.json()["document_count"] == 16
    assert "api_key" not in result.text
    assert "base_url" not in result.text
    assert service.calls == 1
