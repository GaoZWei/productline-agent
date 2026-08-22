"""M4.11 规范问答检索、路由分发、带引用生成和安全回答测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from datetime import date

import pytest

from app.knowledge import (
    EmbeddingIndexDescriptor,
    KeywordSearchHit,
    KnowledgeRetrievalPipeline,
    KnowledgeSearchFilter,
    QueryEmbedding,
    RerankRequest,
    RetrievalResult,
    VectorSearchHit,
)
from app.routing import Intent
from app.routing.decision import build_routing_decision
from app.schemas import (
    EntityMergeResult,
    PageContext,
    PageType,
    PermissionScope,
    RouterEntities,
    RouterResult,
    RoutingDecision,
    SpecificationQaStatus,
)
from app.workflows import (
    SpecificationAnswerRequest,
    SpecificationQaWorkflow,
    SpecificationSkill,
    SpecificationSkillDispatchError,
)


def _retrieval(
    chunk_id: str,
    *,
    document_id: str,
    document_name: str,
    score: float,
    content: str,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_ids=(chunk_id,),
        document_id=document_id,
        document_name=document_name,
        document_version="2.1",
        chunk_indexes=(0,),
        section_path=("质量复核", "坐标系问题"),
        content=content,
        content_hashes=(f"hash-{chunk_id}",),
        keyword_score=1.0,
        vector_score=0.9,
        keyword_rank=1,
        vector_rank=1,
        rrf_score=score,
    )


class _StaticRetriever:
    def __init__(self, results: Sequence[RetrievalResult]) -> None:
        self.results = tuple(results)
        self.calls: list[tuple[str, KnowledgeSearchFilter]] = []

    async def retrieve(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
    ) -> tuple[RetrievalResult, ...]:
        self.calls.append((query, filters))
        return self.results


class _StaticReranker:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        async def _respond() -> object:
            return {
                "scores": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "score": self.scores[candidate.candidate_id],
                    }
                    for candidate in request.candidates
                ]
            }

        return _respond()


class _BlockingReranker:
    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        async def _wait() -> object:
            await asyncio.Event().wait()
            return {"scores": []}

        return _wait()


class _StaticAnswerModel:
    def __init__(self, output: object) -> None:
        self.output = output
        self.requests: list[SpecificationAnswerRequest] = []

    def generate(self, request: SpecificationAnswerRequest) -> Awaitable[object]:
        self.requests.append(request)

        async def _respond() -> object:
            return self.output

        return _respond()


@pytest.mark.unit
async def test_specification_skill_runs_full_qa_flow_with_page_metadata_and_citations() -> None:
    general = _retrieval(
        "CHUNK-A",
        document_id="DOC-QUALITY-001",
        document_name="通用质量规范",
        score=0.04,
        content="通用质量检查说明。",
    )
    coordinate = _retrieval(
        "CHUNK-B",
        document_id="DOC-COORD-001",
        document_name="坐标系统一与返工规范",
        score=0.03,
        content="坐标系不一致时必须返工, 完成后重新提交复核。",
    )
    retriever = _StaticRetriever((general, coordinate))
    answer_model = _StaticAnswerModel(
        {
            "answer": "发现坐标系不一致时必须返工, 处理完成后重新提交复核。",
            "citation_ids": ["CHUNK-B"],
        }
    )
    workflow = SpecificationQaWorkflow(
        retriever=retriever,
        reranker=_StaticReranker({"CHUNK-A": 0.65, "CHUNK-B": 0.95}),
        answer_model=answer_model,
    )
    skill = SpecificationSkill(workflow)

    result = await skill.execute(
        _spec_decision(),
        question="  坐标系   问题应该如何处理? ",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
        page_context=_page_context(),
    )

    assert result.status is SpecificationQaStatus.ANSWERED
    assert result.rewritten_query == "坐标系 问题应该如何处理?"
    assert result.answer == "发现坐标系不一致时必须返工, 处理完成后重新提交复核。"
    assert [citation.chunk_id for citation in result.citations] == ["CHUNK-B"]
    assert result.citations[0].document_name == "坐标系统一与返工规范"
    assert result.citations[0].relevance_score == pytest.approx(0.95)
    assert result.rerank_degraded is False
    assert len(retriever.calls) == 1
    query, filters = retriever.calls[0]
    assert query == "坐标系 问题应该如何处理?"
    assert filters.product_type == "DOM"
    assert filters.satellite_type == "GF-2"
    assert filters.effective_at == date(2026, 8, 20)
    assert filters.permission_scope is PermissionScope.INTERNAL_REVIEWER
    assert [citation.chunk_id for citation in answer_model.requests[0].citations] == [
        "CHUNK-B",
        "CHUNK-A",
    ]


@pytest.mark.unit
async def test_no_relevant_result_returns_safe_answer_without_calling_generation_model() -> None:
    answer_model = _StaticAnswerModel({"unexpected": True})
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever(()),
        reranker=_StaticReranker({}),
        answer_model=answer_model,
    )

    result = await workflow.ainvoke(
        "没有对应规范的问题",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    assert result.status is SpecificationQaStatus.INSUFFICIENT_CONTEXT
    assert result.citations == ()
    assert "未检索到足够相关的现行规范" in result.answer
    assert answer_model.requests == []


@pytest.mark.unit
async def test_rerank_timeout_returns_safe_answer_instead_of_unchecked_rrf_context() -> None:
    candidate = _retrieval(
        "CHUNK-A",
        document_id="DOC-QUALITY-001",
        document_name="通用质量规范",
        score=0.04,
        content="通用说明。",
    )
    answer_model = _StaticAnswerModel({"unexpected": True})
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever((candidate,)),
        reranker=_BlockingReranker(),
        answer_model=answer_model,
        rerank_timeout_seconds=0.001,
    )

    result = await workflow.ainvoke(
        "坐标系要求",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    assert result.status is SpecificationQaStatus.RERANK_UNAVAILABLE
    assert result.rerank_degraded is True
    assert result.citations == ()
    assert "重排服务暂时不可用" in result.answer
    assert answer_model.requests == []


@pytest.mark.unit
async def test_generation_with_unknown_citation_fails_to_safe_answer() -> None:
    candidate = _retrieval(
        "CHUNK-A",
        document_id="DOC-QUALITY-001",
        document_name="通用质量规范",
        score=0.04,
        content="通用说明。",
    )
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever((candidate,)),
        reranker=_StaticReranker({"CHUNK-A": 0.9}),
        answer_model=_StaticAnswerModel(
            {"answer": "模型编造的回答", "citation_ids": ["CHUNK-X"]}
        ),
    )

    result = await workflow.ainvoke(
        "质量要求",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    assert result.status is SpecificationQaStatus.GENERATION_FAILED
    assert result.citations == ()
    assert "未形成规范结论" in result.answer


@pytest.mark.unit
async def test_specification_skill_rejects_non_ready_routing_decision() -> None:
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever(()),
        reranker=_StaticReranker({}),
        answer_model=_StaticAnswerModel({}),
    )

    with pytest.raises(SpecificationSkillDispatchError):
        await SpecificationSkill(workflow).execute(
            _spec_decision(confidence=0.2),
            question="坐标系要求",
            effective_at=date(2026, 8, 20),
            permission_scope=PermissionScope.INTERNAL_REVIEWER,
        )


class _PipelineRepository:
    def __init__(self) -> None:
        self.keyword_filters: KnowledgeSearchFilter | None = None
        self.vector_filters: KnowledgeSearchFilter | None = None

    async def search_keywords(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
    ) -> tuple[KeywordSearchHit, ...]:
        self.keyword_filters = filters
        return (
            KeywordSearchHit(
                chunk_id="CHUNK-A",
                document_id="DOC-QUALITY-001",
                document_name="质量规范",
                document_version="2.1",
                chunk_index=0,
                section_path=("质量复核",),
                content="坐标系问题处理要求。",
                content_hash="hash-a",
                keyword_score=0.8,
            ),
        )

    async def search_vectors(
        self,
        query_embedding: QueryEmbedding,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
        min_similarity: float = -1.0,
    ) -> tuple[VectorSearchHit, ...]:
        self.vector_filters = filters
        return (
            VectorSearchHit(
                chunk_id="CHUNK-A",
                document_id="DOC-QUALITY-001",
                document_name="质量规范",
                document_version="2.1",
                chunk_index=0,
                section_path=("质量复核",),
                content="坐标系问题处理要求。",
                content_hash="hash-a",
                vector_score=0.9,
            ),
        )


class _QueryEmbeddingGenerator:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def generate_query(self, query: str) -> QueryEmbedding:
        self.queries.append(query)
        return QueryEmbedding(
            descriptor=EmbeddingIndexDescriptor(
                provider="test",
                model="test-model",
                dimension=1536,
                index_version="test-v1",
            ),
            vector=(1.0,),
        )


@pytest.mark.unit
async def test_retrieval_pipeline_executes_both_channels_with_same_metadata_filter() -> None:
    repository = _PipelineRepository()
    embedding_generator = _QueryEmbeddingGenerator()
    pipeline = KnowledgeRetrievalPipeline(
        repository=repository,
        embedding_generator=embedding_generator,
        channel_top_k=5,
        hybrid_top_k=3,
    )
    filters = KnowledgeSearchFilter(
        product_type="DOM",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
    )

    results = await pipeline.retrieve("坐标系要求", filters=filters)

    assert embedding_generator.queries == ["坐标系要求"]
    assert repository.keyword_filters is filters
    assert repository.vector_filters is filters
    assert len(results) == 1
    assert results[0].chunk_ids == ("CHUNK-A",)
    assert results[0].keyword_rank == 1
    assert results[0].vector_rank == 1


def _spec_decision(*, confidence: float = 0.95) -> RoutingDecision:
    raw = RouterResult(
        intent=Intent.SPEC_QA,
        confidence=confidence,
        entities=RouterEntities(),
        missing_fields=[],
        need_clarification=False,
    )
    return build_routing_decision(raw_result=raw, merge_result=EntityMergeResult())


def _page_context() -> PageContext:
    return PageContext(
        current_system="production-system",
        current_page=PageType.ORDER_DETAIL,
        order_id="ORDER-003",
        product_type="DOM",
        satellite_type="GF-2",
        user_role="REVIEWER",
    )
