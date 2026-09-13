"""M4.11 规范问答检索、路由分发、带引用生成和安全回答测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping, Sequence
from datetime import date

import pytest
from pydantic import JsonValue

from app.knowledge import (
    EmbeddingErrorCode,
    EmbeddingIndexDescriptor,
    EmbeddingProviderError,
    KeywordSearchHit,
    KnowledgeRetrievalError,
    KnowledgeRetrievalErrorCode,
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
    RunEventType,
    SpecificationQaStatus,
)
from app.workflows import (
    SpecificationAnswerRequest,
    SpecificationQaWorkflow,
    SpecificationSkill,
    SpecificationSkillDispatchError,
)


class _CaptureEventSink:
    def __init__(self) -> None:
        self.events: list[tuple[RunEventType, str | None, dict[str, JsonValue]]] = []

    async def publish(
        self,
        event_type: RunEventType,
        *,
        run_id: str | None = None,
        step_id: str | None = None,
        data: Mapping[str, JsonValue] | None = None,
    ) -> None:
        del step_id
        self.events.append((event_type, run_id, dict(data or {})))


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
    events = _CaptureEventSink()
    workflow = SpecificationQaWorkflow(
        retriever=retriever,
        reranker=_StaticReranker({"CHUNK-A": 0.65, "CHUNK-B": 0.95}),
        answer_model=answer_model,
        event_sink=events,
        run_id="run-specification-001",
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
    assert [event[0] for event in events.events] == [
        RunEventType.RETRIEVAL_STARTED,
        RunEventType.RETRIEVAL_COMPLETED,
    ]
    assert all(event[1] == "run-specification-001" for event in events.events)
    assert events.events[0][2] == {
        "permission_scope": "INTERNAL_REVIEWER",
        "effective_at": "2026-08-20",
        "product_type": "DOM",
        "satellite_type": "GF-2",
    }
    assert events.events[1][2] == {
        "retrieved_count": 2,
        "selected_count": 2,
        "rerank_degraded": False,
    }


@pytest.mark.unit
async def test_m77_s15_empty_retrieval_returns_safe_answer_without_generation() -> None:
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
async def test_m77_s16_all_low_score_fragments_return_safe_answer() -> None:
    candidate = _retrieval(
        "CHUNK-A",
        document_id="DOC-QUALITY-001",
        document_name="通用质量规范",
        score=0.04,
        content="与当前问题相关性不足的通用说明。",
    )
    answer_model = _StaticAnswerModel({"unexpected": True})
    workflow = SpecificationQaWorkflow(
        retriever=_StaticRetriever((candidate,)),
        reranker=_StaticReranker({"CHUNK-A": 0.49}),
        answer_model=answer_model,
    )

    result = await workflow.ainvoke(
        "坐标系要求",
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


class _FailingQueryEmbeddingGenerator(_QueryEmbeddingGenerator):
    async def generate_query(self, query: str) -> QueryEmbedding:
        self.queries.append(query)
        raise EmbeddingProviderError(
            code=EmbeddingErrorCode.UPSTREAM_UNAVAILABLE,
            message="embedding provider is unavailable",
            retryable=True,
        )


class _FailingPipelineRepository(_PipelineRepository):
    def __init__(
        self,
        *,
        keyword_error: Exception | None = None,
        vector_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.keyword_error = keyword_error
        self.vector_error = vector_error
        self.vector_calls = 0

    async def search_keywords(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
    ) -> tuple[KeywordSearchHit, ...]:
        if self.keyword_error is not None:
            raise self.keyword_error
        return await super().search_keywords(query, filters=filters, top_k=top_k)

    async def search_vectors(
        self,
        query_embedding: QueryEmbedding,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
        min_similarity: float = -1.0,
    ) -> tuple[VectorSearchHit, ...]:
        self.vector_calls += 1
        if self.vector_error is not None:
            raise self.vector_error
        return await super().search_vectors(
            query_embedding,
            filters=filters,
            top_k=top_k,
            min_similarity=min_similarity,
        )


def _knowledge_filters() -> KnowledgeSearchFilter:
    return KnowledgeSearchFilter(
        product_type="DOM",
        effective_at=date(2026, 8, 20),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
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


@pytest.mark.unit
async def test_m77_s11_embedding_failure_keeps_provider_code_and_skips_vector_search() -> None:
    repository = _FailingPipelineRepository()
    embedding_generator = _FailingQueryEmbeddingGenerator()
    pipeline = KnowledgeRetrievalPipeline(
        repository=repository,
        embedding_generator=embedding_generator,
    )

    with pytest.raises(EmbeddingProviderError) as caught:
        await pipeline.retrieve("坐标系要求", filters=_knowledge_filters())

    assert caught.value.code is EmbeddingErrorCode.UPSTREAM_UNAVAILABLE
    assert caught.value.retryable is True
    assert repository.vector_calls == 0


@pytest.mark.unit
async def test_m77_s12_vector_search_timeout_has_retryable_channel_error() -> None:
    repository = _FailingPipelineRepository(vector_error=TimeoutError("database detail"))
    pipeline = KnowledgeRetrievalPipeline(
        repository=repository,
        embedding_generator=_QueryEmbeddingGenerator(),
    )

    with pytest.raises(KnowledgeRetrievalError) as caught:
        await pipeline.retrieve("坐标系要求", filters=_knowledge_filters())

    assert caught.value.code is KnowledgeRetrievalErrorCode.VECTOR_SEARCH_TIMEOUT
    assert caught.value.retryable is True
    assert str(caught.value) == "vector knowledge search timed out"
    assert "database detail" not in str(caught.value)


@pytest.mark.unit
async def test_m77_s13_keyword_search_failure_stops_downstream_channels_safely() -> None:
    repository = _FailingPipelineRepository(
        keyword_error=RuntimeError("database credential detail")
    )
    embedding_generator = _QueryEmbeddingGenerator()
    pipeline = KnowledgeRetrievalPipeline(
        repository=repository,
        embedding_generator=embedding_generator,
    )

    with pytest.raises(KnowledgeRetrievalError) as caught:
        await pipeline.retrieve("坐标系要求", filters=_knowledge_filters())

    assert caught.value.code is KnowledgeRetrievalErrorCode.KEYWORD_SEARCH_FAILED
    assert caught.value.retryable is False
    assert str(caught.value) == "keyword knowledge search failed"
    assert "credential" not in str(caught.value)
    assert embedding_generator.queries == []
    assert repository.vector_calls == 0


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
