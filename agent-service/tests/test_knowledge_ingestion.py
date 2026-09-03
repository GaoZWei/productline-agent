"""M7.6-C全量知识入库应用服务与CLI安全退出测试。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.cli import knowledge_ingest as cli
from app.knowledge import (
    ChunkEmbedding,
    DocumentChunk,
    EmbeddingErrorCode,
    EmbeddingGeneration,
    EmbeddingIndexDescriptor,
    EmbeddingProviderError,
    ProcessedDocument,
)
from app.schemas.knowledge import EMBEDDING_DIMENSION
from app.schemas.knowledge_index import KnowledgeIndexIdentity, KnowledgeIngestionSummary
from app.services.knowledge_ingestion import (
    DEFAULT_KNOWLEDGE_ROOT,
    KnowledgeCatalogLoadError,
    KnowledgeIngestionService,
    load_document_catalog,
)
from app.settings import Settings


class _CaptureRepository:
    def __init__(self, *, removed_count: int = 0) -> None:
        self.removed_count = removed_count
        self.pruned_ids: list[tuple[str, ...]] = []
        self.reindexes: list[tuple[tuple[ProcessedDocument, ...], EmbeddingGeneration]] = []

    async def prune_documents_not_in(self, document_ids: Sequence[str]) -> int:
        self.pruned_ids.append(tuple(document_ids))
        return self.removed_count

    async def reindex_documents(
        self,
        documents: Sequence[ProcessedDocument],
        generation: EmbeddingGeneration,
    ) -> object:
        self.reindexes.append((tuple(documents), generation))
        return object()


class _DeterministicEmbeddingGenerator:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[DocumentChunk, ...]] = []

    async def generate(self, chunks: Sequence[DocumentChunk]) -> EmbeddingGeneration:
        normalized = tuple(chunks)
        self.calls.append(normalized)
        if self.failure is not None:
            raise self.failure
        return EmbeddingGeneration(
            descriptor=EmbeddingIndexDescriptor(
                provider="openai_compatible",
                model="text-embedding-3-small",
                dimension=EMBEDDING_DIMENSION,
                index_version="catalog-test-v1",
            ),
            generated_at=datetime(2026, 9, 1, tzinfo=UTC),
            embeddings=tuple(
                ChunkEmbedding(
                    chunk_id=chunk.chunk_id,
                    vector=(1.0, *([0.0] * (EMBEDDING_DIMENSION - 1))),
                )
                for chunk in normalized
            ),
        )


@pytest.mark.unit
def test_catalog_loader_validates_default_sixteen_document_catalog() -> None:
    catalog = load_document_catalog(DEFAULT_KNOWLEDGE_ROOT)

    assert len(catalog.documents) == 16
    assert len({document.document_id for document in catalog.documents}) == 16


@pytest.mark.unit
def test_catalog_loader_rejects_catalog_outside_knowledge_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text('{"schema_version":1,"documents":[]}', encoding="utf-8")

    with pytest.raises(KnowledgeCatalogLoadError, match="missing or invalid"):
        load_document_catalog(DEFAULT_KNOWLEDGE_ROOT, outside)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingestion_processes_all_documents_before_atomic_reindex() -> None:
    repository = _CaptureRepository(removed_count=2)
    generator = _DeterministicEmbeddingGenerator()
    service = KnowledgeIngestionService(
        repository=repository,
        embedding_generator=generator,
    )

    first = await service.ingest_catalog(DEFAULT_KNOWLEDGE_ROOT)
    second = await service.ingest_catalog(DEFAULT_KNOWLEDGE_ROOT)

    assert first == second
    assert first.document_count == 16
    assert first.chunk_count == 80
    assert first.removed_document_count == 2
    assert len(repository.reindexes) == 2
    first_ids = [chunk.chunk_id for chunk in generator.calls[0]]
    second_ids = [chunk.chunk_id for chunk in generator.calls[1]]
    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids)) == 80
    assert repository.pruned_ids[0] == tuple(
        document.metadata.document_id for document in repository.reindexes[0][0]
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embedding_failure_happens_before_any_repository_write() -> None:
    repository = _CaptureRepository()
    generator = _DeterministicEmbeddingGenerator(
        failure=EmbeddingProviderError(
            code=EmbeddingErrorCode.AUTHENTICATION,
            message="embedding authentication failed",
            retryable=False,
        )
    )

    with pytest.raises(EmbeddingProviderError):
        await KnowledgeIngestionService(
            repository=repository,
            embedding_generator=generator,
        ).ingest_catalog(DEFAULT_KNOWLEDGE_ROOT)

    assert repository.pruned_ids == []
    assert repository.reindexes == []


@pytest.mark.unit
def test_cli_reports_configuration_failure_with_stable_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(environment="test"))

    exit_code = cli.main([])

    assert exit_code is cli.KnowledgeIngestionExitCode.INPUT_OR_CONFIGURATION_ERROR
    assert capsys.readouterr().out.strip() == (
        '{"error_code": "KNOWLEDGE_INGESTION_INPUT_ERROR", "ok": false}'
    )


@pytest.mark.unit
def test_cli_success_only_prints_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = KnowledgeIngestionSummary(
        document_count=16,
        chunk_count=80,
        removed_document_count=0,
        index=KnowledgeIndexIdentity(
            provider="openai_compatible",
            model="embedding-test",
            dimension=EMBEDDING_DIMENSION,
            index_version="catalog-test-v1",
        ),
    )

    async def successful_run(*args: Any, **kwargs: Any) -> KnowledgeIngestionSummary:
        return summary

    monkeypatch.setattr(cli, "run_ingestion", successful_run)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(environment="test"))

    exit_code = cli.main([])
    output = capsys.readouterr().out

    assert exit_code is cli.KnowledgeIngestionExitCode.SUCCESS
    assert '"document_count": 16' in output
    assert '"chunk_count": 80' in output
    assert "api_key" not in output
    assert "content" not in output


@pytest.mark.unit
def test_cli_hides_embedding_provider_error_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def failed_run(*args: Any, **kwargs: Any) -> KnowledgeIngestionSummary:
        raise EmbeddingProviderError(
            code=EmbeddingErrorCode.AUTHENTICATION,
            message="secret-provider-body",
            retryable=False,
        )

    monkeypatch.setattr(cli, "run_ingestion", failed_run)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(environment="test"))

    exit_code = cli.main([])
    output = capsys.readouterr().out

    assert exit_code is cli.KnowledgeIngestionExitCode.EMBEDDING_ERROR
    assert "EMBEDDING_AUTHENTICATION_ERROR" in output
    assert "secret-provider-body" not in output
