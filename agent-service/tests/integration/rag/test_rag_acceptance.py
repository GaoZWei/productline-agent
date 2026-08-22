"""M4完整验收中的固定语料、空结果和引用可追溯边界。"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from datetime import date
from pathlib import Path

import pytest

from app.evaluation.rag import load_rag_evaluation_cases
from app.knowledge import DocumentProcessingPipeline, RerankRequest, RetrievalResult
from app.schemas.knowledge import (
    DocumentCatalog,
    DocumentLifecycle,
    KnowledgeSearchFilter,
    PermissionScope,
)
from app.schemas.specification import SpecificationQaStatus
from app.workflows import SpecificationAnswerRequest, SpecificationQaWorkflow

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_KNOWLEDGE_ROOT = _REPOSITORY_ROOT / "knowledge-base"
_CATALOG_PATH = _KNOWLEDGE_ROOT / "catalog.json"
_DATASET_PATH = _REPOSITORY_ROOT / "agent-service" / "evaluation" / "rag_cases.jsonl"


def test_all_fifty_annotations_point_to_active_current_catalog_sections() -> None:
    catalog = DocumentCatalog.model_validate_json(_CATALOG_PATH.read_text(encoding="utf-8"))
    processed = DocumentProcessingPipeline().process_catalog(_KNOWLEDGE_ROOT, catalog)
    active_targets = {
        (document.metadata.document_id, chunk.section_path)
        for document in processed
        if document.metadata.lifecycle is DocumentLifecycle.ACTIVE
        for chunk in document.chunks
    }
    active_document_ids = {
        document.metadata.document_id
        for document in processed
        if document.metadata.lifecycle is DocumentLifecycle.ACTIVE
    }

    cases = load_rag_evaluation_cases(_DATASET_PATH)

    assert all(
        (case.expected_document_id, case.expected_section) in active_targets
        for case in cases
    )
    assert all(case.filters.product_type == "DOM" for case in cases)
    assert all(case.filters.effective_at == date(2026, 8, 20) for case in cases)
    assert all(not case.expected_document_id.endswith("-001") for case in cases)
    assert {case.expected_document_id for case in cases} == active_document_ids
    coordinate_case = next(case for case in cases if case.case_id == "rag-029")
    assert coordinate_case.expected_section == ("DOM坐标参考要求", "坐标信息")


class _StaticRetriever:
    def __init__(self, results: Sequence[RetrievalResult]) -> None:
        self.results = tuple(results)

    async def retrieve(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
    ) -> tuple[RetrievalResult, ...]:
        return self.results


class _StaticReranker:
    def __init__(self) -> None:
        self.called = False

    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        self.called = True

        async def _respond() -> object:
            return {
                "scores": [
                    {"candidate_id": candidate.candidate_id, "score": 0.95}
                    for candidate in request.candidates
                ]
            }

        return _respond()


class _SelectingAnswerModel:
    def __init__(self) -> None:
        self.called = False

    def generate(self, request: SpecificationAnswerRequest) -> Awaitable[object]:
        self.called = True

        async def _respond() -> object:
            return {
                "answer": "坐标参考需要在元数据中明确声明。",
                "citation_ids": [request.citations[0].chunk_id],
            }

        return _respond()


def _retrieval() -> RetrievalResult:
    return RetrievalResult(
        chunk_ids=("KCH-TRACE-A", "KCH-TRACE-B"),
        document_id="COORDINATE-REFERENCE-002",
        document_name="DOM坐标参考要求",
        document_version="2.0",
        chunk_indexes=(1, 2),
        section_path=("DOM坐标参考要求", "坐标信息"),
        content="坐标参考和处理参数版本必须在元数据中声明。",
        content_hashes=("hash-a", "hash-b"),
        keyword_score=0.9,
        vector_score=0.95,
        keyword_rank=1,
        vector_rank=1,
        rrf_score=2 / 61,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_empty_retrieval_returns_safe_answer_without_generation() -> None:
    reranker = _StaticReranker()
    answer_model = _SelectingAnswerModel()
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever(()),
        reranker=reranker,
        answer_model=answer_model,
    )

    result = await workflow.ainvoke(
        "没有对应规范的问题",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    assert result.status is SpecificationQaStatus.INSUFFICIENT_CONTEXT
    assert result.citations == ()
    assert reranker.called is False
    assert answer_model.called is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_answer_citations_preserve_every_source_chunk_identity() -> None:
    answer_model = _SelectingAnswerModel()
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever((_retrieval(),)),
        reranker=_StaticReranker(),
        answer_model=answer_model,
    )

    result = await workflow.ainvoke(
        "DOM成果坐标信息需要声明什么?",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    assert result.status is SpecificationQaStatus.ANSWERED
    assert result.citations[0].document_id == "COORDINATE-REFERENCE-002"
    assert result.citations[0].section == ("DOM坐标参考要求", "坐标信息")
    assert result.citations[0].chunk_ids == ("KCH-TRACE-A", "KCH-TRACE-B")
