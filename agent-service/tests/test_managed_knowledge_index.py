"""动态就绪的全量集合、损坏证据、配置隔离和权限边界，不调用模型。"""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ToolException
from app.knowledge.catalog_import import import_plan
from app.knowledge.import_preflight import capture_import_files
from app.repositories.managed_knowledge_index import (
    ManagedKnowledgeIndexRepository,
    ManagedPublishedIndexSnapshot,
    PublishedIndexClaim,
)
from app.schemas.knowledge_index import KnowledgeIndexStatus
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge_index import ManagedKnowledgeIndexCapabilities
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT
from app.services.managed_knowledge_index import (
    ManagedKnowledgeIndexCapabilityService,
    evaluate_published_index,
)
from tests.knowledge.import_preflight_fixtures import INDEX, source_snapshot
from tests.test_catalog_import import command, reviewed
from tests.test_knowledge_publication import IDENTITY
from tests.test_managed_knowledge_search import SearchHarness
from tests.test_managed_knowledge_search import search as search


@pytest.fixture
def published_snapshot() -> ManagedPublishedIndexSnapshot:
    """复用纳管计划及完整假向量，不依赖固定发布数量判定逻辑。"""
    files = capture_import_files(DEFAULT_KNOWLEDGE_ROOT)
    plan = import_plan(files, command(reviewed()), actor=IDENTITY.user_id, index=INDEX)
    active = {item.source_id: item for item in plan if item.lifecycle == "ACTIVE"}
    now = datetime(2026, 11, 7, tzinfo=UTC)
    claims = []
    for item in active.values():
        claims.append(
            PublishedIndexClaim(
                item.document_id,
                item.version_id,
                {
                    "document_id": item.document_id,
                    "version_id": item.version_id,
                    "specification_version": item.snapshot.specification_version,
                    "citation_document_id": item.source_id,
                    "current_revision_no": 1,
                    "source_kind": "CATALOG_IMPORT",
                    "source_document_id": item.source_id,
                    "source_catalog_hash": files.catalog_hash,
                    "source_lifecycle": "ACTIVE",
                    "source_replaced_by": None,
                    "created_by": IDENTITY.user_id,
                    "publication_state": "PUBLISHED",
                    "published_revision_no": 1,
                    "published_generation_id": item.generation_id,
                    "published_at": now,
                },
                item.snapshot.model_dump(),
                item.snapshot.metadata_digest(),
                {
                    "generation_id": item.generation_id,
                    "version_id": item.version_id,
                    "revision_no": 1,
                    "embedding_provider": INDEX.provider,
                    "embedding_model": INDEX.model,
                    "embedding_dimension": 1536,
                    "index_version": INDEX.index_version,
                    "chunking_version": INDEX.chunking_version,
                    "input_hash": item.generation_hash,
                    "build_method": "COPIED_LEGACY",
                    "state": "READY",
                    "chunk_count": len(
                        next(
                            source.parsed.chunks
                            for source in files.files
                            if source.metadata.document_id == item.source_id
                        )
                    ),
                    "created_at": now,
                    "finished_at": now,
                },
            )
        )
    chunks = tuple(
        {
            "generation_id": active[chunk.document_id].generation_id,
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "section_path": chunk.section_path,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "token_count": chunk.token_count,
            "search_document": chunk.search_document,
            "embedding": chunk.embedding,
        }
        for chunk in source_snapshot(files).chunks
        if chunk.document_id in active
    )
    return ManagedPublishedIndexSnapshot("LEGACY", 1, tuple(claims), chunks)


def test_managed_readiness_uses_dynamic_set_and_full_identity(
    published_snapshot: ManagedPublishedIndexSnapshot,
) -> None:
    report = evaluate_published_index(published_snapshot, INDEX)
    assert report.ready and report.expected_document_count == report.document_count == len(
        published_snapshot.claims
    )
    assert report.chunk_count == len(published_snapshot.chunks)
    assert report.source == "MANAGED" and report.configured_source_mode == "LEGACY"
    changed = evaluate_published_index(
        published_snapshot, INDEX.model_copy(update={"model": "new-model"})
    )
    assert changed.status == KnowledgeIndexStatus.INDEX_MISMATCH and not changed.ready
    assert report == ManagedKnowledgeIndexCapabilities.model_validate_json(report.model_dump_json())
    assert "content" not in report.model_dump_json() and "embedding" not in report.model_dump_json()


def test_managed_readiness_empty_does_not_require_fixed_catalog() -> None:
    report = evaluate_published_index(ManagedPublishedIndexSnapshot("LEGACY", 5, (), ()), INDEX)
    assert not report.ready and report.status == KnowledgeIndexStatus.NOT_INDEXED
    assert report.expected_document_count == report.document_count == report.chunk_count == 0
    assert report.message == "无已发布资料" and report.stored_index is None


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "extra",
        "duplicate",
        "zero",
        "content",
        "section",
        "sequence",
        "search",
        "metadata",
        "input",
        "pointer",
        "document",
        "multiple",
    ],
)
def test_managed_readiness_checks_entire_published_evidence(
    published_snapshot: ManagedPublishedIndexSnapshot, kind: str
) -> None:
    state = published_snapshot
    if kind == "missing":
        state = replace(state, chunks=state.chunks[:-1])
    elif kind == "extra":
        state = replace(
            state, chunks=(*state.chunks, {**state.chunks[-1], "chunk_id": "foreign-chunk"})
        )
    elif kind == "duplicate":
        state = replace(state, chunks=(*state.chunks[:-1], state.chunks[-2]))
    elif kind in {"zero", "content", "section", "sequence", "search"}:
        updates_by_kind: dict[str, dict[str, object]] = {
            "zero": {"embedding": (0.0,) * 1536},
            "content": {"content": "changed"},
            "section": {"section_path": ("wrong",)},
            "sequence": {"chunk_index": 99},
            "search": {"search_document": "wrong"},
        }
        changes = updates_by_kind[kind]
        state = replace(state, chunks=(*state.chunks[:-1], {**state.chunks[-1], **changes}))
    else:
        first = state.claims[0]
        if kind == "metadata":
            first = replace(first, metadata_hash="a" * 64)
        elif kind == "input":
            assert first.generation is not None
            first = replace(first, generation={**first.generation, "input_hash": "a" * 64})
        elif kind == "pointer":
            first = replace(first, current_version_id=None)
        elif kind == "document":
            first = replace(first, document_id="DOC-" + "F" * 32)
        if kind == "multiple":
            state = replace(state, claims=(*state.claims, first))
        else:
            state = replace(state, claims=(first, *state.claims[1:]))
    report = evaluate_published_index(state, INDEX)
    assert not report.ready and report.status == KnowledgeIndexStatus.INCOMPLETE


@pytest.mark.parametrize(
    "updates",
    [
        {"ready": True},
        {"expected_document_count": -1},
        {"expected_document_count": 1},
        {"source": "LEGACY"},
        {"message": "已发布索引可用"},
        {"release_revision": True},
    ],
)
def test_managed_readiness_schema_rejects_inconsistent_zero_state(
    updates: dict[str, object],
) -> None:
    report = evaluate_published_index(ManagedPublishedIndexSnapshot("LEGACY", 1, (), ()), INDEX)
    with pytest.raises(ValidationError):
        ManagedKnowledgeIndexCapabilities.model_validate({**report.model_dump(), **updates})


async def test_managed_readiness_reauthorizes_and_sql_failure_is_safe(
    search: SearchHarness, published_snapshot: ManagedPublishedIndexSnapshot
) -> None:
    repository = Mock(spec=ManagedKnowledgeIndexRepository)
    repository.read_published_snapshot = AsyncMock(return_value=published_snapshot)
    service = ManagedKnowledgeIndexCapabilityService(
        repository, search.service.authorizer, index_identity=INDEX
    )
    result = await service.get(identity=IDENTITY)
    assert result.ready and search.events == ["READ"]
    search.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await service.get(identity=IDENTITY)
    assert repository.read_published_snapshot.await_count == 1
    search.generator.generate_query.assert_not_awaited()
    repository.read_published_snapshot.side_effect = SQLAlchemyError("private connection")
    with pytest.raises(
        KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"
    ) as caught:
        await service.get(identity=IDENTITY)
    assert "private" not in str(caught.value)
