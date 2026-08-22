"""M4.12 固定RAG评测集、检索指标、策略对比和失败样本测试。"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from app.evaluation.rag import (
    EXPECTED_RAG_CASE_COUNT,
    KnowledgeRagEvaluationSubject,
    RagEvaluationCase,
    RagEvaluationDataError,
    RagEvaluationPrediction,
    RagEvaluationStrategy,
    RagRetrievedFragment,
    evaluate_rag,
    load_rag_evaluation_cases,
)
from app.knowledge import (
    EMBEDDING_DIMENSION,
    EmbeddingIndexDescriptor,
    KeywordSearchHit,
    QueryEmbedding,
    RerankRequest,
    VectorSearchHit,
)
from app.schemas.knowledge import KnowledgeSearchFilter, PermissionScope

_DATASET_PATH = Path(__file__).parents[2] / "evaluation" / "rag_cases.jsonl"
_EFFECTIVE_AT = date(2026, 8, 20)
_FILTERS = KnowledgeSearchFilter(
    product_type="DOM",
    satellite_type="GF-2",
    effective_at=_EFFECTIVE_AT,
    permission_scope=PermissionScope.INTERNAL_REVIEWER,
)


def _case(case_id: str, document_id: str, section: tuple[str, ...]) -> RagEvaluationCase:
    return RagEvaluationCase(
        case_id=case_id,
        question=f"{case_id}的规范要求是什么?",
        filters=_FILTERS,
        expected_document_id=document_id,
        expected_section=section,
    )


def _fragment(
    chunk_id: str,
    document_id: str,
    section: tuple[str, ...],
) -> RagRetrievedFragment:
    return RagRetrievedFragment(
        chunk_ids=(chunk_id,),
        document_id=document_id,
        section_path=section,
    )


class _StaticSubject:
    def __init__(
        self,
        outputs: dict[
            tuple[RagEvaluationStrategy, str],
            tuple[RagRetrievedFragment, ...],
        ],
    ) -> None:
        self.outputs = outputs

    async def retrieve(
        self,
        case: RagEvaluationCase,
        strategy: RagEvaluationStrategy,
        *,
        top_k: int,
    ) -> RagEvaluationPrediction:
        return RagEvaluationPrediction(
            case_id=case.case_id,
            strategy=strategy,
            results=self.outputs.get((strategy, case.case_id), ())[:top_k],
        )


class _ExpectedTargetSubject:
    async def retrieve(
        self,
        case: RagEvaluationCase,
        strategy: RagEvaluationStrategy,
        *,
        top_k: int,
    ) -> RagEvaluationPrediction:
        return RagEvaluationPrediction(
            case_id=case.case_id,
            strategy=strategy,
            results=(
                RagRetrievedFragment(
                    chunk_ids=(f"KCH-{case.case_id.upper()}-{strategy.value}",),
                    document_id=case.expected_document_id,
                    section_path=case.expected_section,
                ),
            ),
        )


def test_rag_dataset_contains_exactly_fifty_unique_annotated_cases() -> None:
    cases = load_rag_evaluation_cases(_DATASET_PATH)

    assert len(cases) == EXPECTED_RAG_CASE_COUNT == 50
    assert len({case.case_id for case in cases}) == 50
    assert all(case.expected_document_id for case in cases)
    assert all(len(case.expected_section) >= 2 for case in cases)
    assert all(case.filters.effective_at == _EFFECTIVE_AT for case in cases)
    assert all(
        case.filters.permission_scope is PermissionScope.INTERNAL_REVIEWER
        for case in cases
    )


@pytest.mark.asyncio
async def test_controlled_full_dataset_exercises_all_four_strategies() -> None:
    cases = load_rag_evaluation_cases(_DATASET_PATH)

    report = await evaluate_rag(cases, _ExpectedTargetSubject())

    assert report.total_cases == 50
    assert set(report.strategy_metrics) == set(RagEvaluationStrategy)
    assert report.failures == ()
    assert all(metric.hit_at_5 == 1.0 for metric in report.strategy_metrics.values())
    assert all(metric.mrr == 1.0 for metric in report.strategy_metrics.values())
    assert all(
        metric.irrelevant_fragment_ratio == 0.0
        for metric in report.strategy_metrics.values()
    )


def test_dataset_loader_rejects_duplicate_ids_without_echoing_questions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicate.jsonl"
    case = {
        "case_id": "rag-001",
        "question": "包含不应进入错误信息的问题",
        "filters": {
            "product_type": "DOM",
            "satellite_type": "GF-2",
            "effective_at": "2026-08-20",
            "permission_scope": "INTERNAL_REVIEWER",
        },
        "expected_document_id": "COORDINATE-REFERENCE-002",
        "expected_section": ["DOM坐标参考要求", "坐标信息"],
    }
    path.write_text(
        f"{json.dumps(case, ensure_ascii=False)}\n"
        f"{json.dumps(case, ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    with pytest.raises(RagEvaluationDataError) as error:
        load_rag_evaluation_cases(path, enforce_case_count=False)

    assert "duplicate case_id" in str(error.value)
    assert "包含不应进入错误信息的问题" not in str(error.value)


@pytest.mark.asyncio
async def test_metrics_compare_four_strategies_and_write_safe_failures(
    tmp_path: Path,
) -> None:
    cases = (
        _case("rag-001", "DOC-A", ("规范A", "章节A")),
        _case("rag-002", "DOC-B", ("规范B", "章节B")),
    )
    wrong = _fragment("CHUNK-X", "DOC-X", ("无关规范", "无关章节"))
    relevant_a = _fragment("CHUNK-A", "DOC-A", ("规范A", "章节A"))
    relevant_b = _fragment("CHUNK-B", "DOC-B", ("规范B", "章节B"))
    outputs = {
        (RagEvaluationStrategy.VECTOR, "rag-001"): (wrong, relevant_a),
        (RagEvaluationStrategy.VECTOR, "rag-002"): (),
        (RagEvaluationStrategy.KEYWORD, "rag-001"): (relevant_a,),
        (RagEvaluationStrategy.KEYWORD, "rag-002"): (relevant_b,),
        (RagEvaluationStrategy.HYBRID, "rag-001"): (relevant_a,),
        (RagEvaluationStrategy.HYBRID, "rag-002"): (wrong, relevant_b),
        (RagEvaluationStrategy.HYBRID_RERANK, "rag-001"): (relevant_a,),
        (RagEvaluationStrategy.HYBRID_RERANK, "rag-002"): (relevant_b,),
    }
    failure_path = tmp_path / "rag-failures.jsonl"

    report = await evaluate_rag(
        cases,
        _StaticSubject(outputs),
        failure_path=failure_path,
    )

    vector = report.strategy_metrics[RagEvaluationStrategy.VECTOR]
    assert vector.hit_at_5 == 0.5
    assert vector.mrr == 0.25
    assert vector.irrelevant_fragment_ratio == 0.5
    keyword = report.strategy_metrics[RagEvaluationStrategy.KEYWORD]
    assert keyword.hit_at_5 == 1.0
    assert keyword.mrr == 1.0
    assert keyword.irrelevant_fragment_ratio == 0.0
    hybrid = report.strategy_metrics[RagEvaluationStrategy.HYBRID]
    assert hybrid.hit_at_5 == 1.0
    assert hybrid.mrr == 0.75
    assert hybrid.irrelevant_fragment_ratio == pytest.approx(1 / 3)
    reranked = report.strategy_metrics[RagEvaluationStrategy.HYBRID_RERANK]
    assert reranked.hit_at_5 == 1.0
    assert reranked.mrr == 1.0
    assert reranked.irrelevant_fragment_ratio == 0.0

    assert [(failure.strategy, failure.case_id) for failure in report.failures] == [
        (RagEvaluationStrategy.VECTOR, "rag-002")
    ]
    failure_text = failure_path.read_text(encoding="utf-8")
    assert "question" not in failure_text
    assert "content" not in failure_text
    assert "rag-002" in failure_text


@pytest.mark.asyncio
async def test_evaluator_rejects_prediction_for_another_case_or_strategy() -> None:
    case = _case("rag-001", "DOC-A", ("规范A", "章节A"))

    class _WrongSubject:
        async def retrieve(
            self,
            evaluation_case: RagEvaluationCase,
            strategy: RagEvaluationStrategy,
            *,
            top_k: int,
        ) -> RagEvaluationPrediction:
            return RagEvaluationPrediction(
                case_id="rag-999",
                strategy=RagEvaluationStrategy.KEYWORD,
                results=(),
            )

    with pytest.raises(RagEvaluationDataError, match="prediction"):
        await evaluate_rag(
            (case,),
            _WrongSubject(),
            strategies=(RagEvaluationStrategy.VECTOR,),
        )


def _hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


class _SearchRepository:
    def __init__(self) -> None:
        self.filters: list[KnowledgeSearchFilter] = []
        correct_content = "坐标信息要求。"
        wrong_content = "交付包要求。"
        self.keyword_hits = (
            KeywordSearchHit(
                chunk_id="CHUNK-WRONG",
                document_id="DELIVERY-PACKAGE-002",
                document_name="DOM交付包组织规范",
                document_version="2.0",
                chunk_index=1,
                section_path=("DOM交付包组织规范", "包含内容"),
                content=wrong_content,
                content_hash=_hash(wrong_content),
                keyword_score=0.9,
            ),
            KeywordSearchHit(
                chunk_id="CHUNK-CORRECT",
                document_id="COORDINATE-REFERENCE-002",
                document_name="DOM坐标参考要求",
                document_version="2.0",
                chunk_index=2,
                section_path=("DOM坐标参考要求", "坐标信息"),
                content=correct_content,
                content_hash=_hash(correct_content),
                keyword_score=0.8,
            ),
        )
        self.vector_hits = (
            VectorSearchHit(
                chunk_id="CHUNK-CORRECT",
                document_id="COORDINATE-REFERENCE-002",
                document_name="DOM坐标参考要求",
                document_version="2.0",
                chunk_index=2,
                section_path=("DOM坐标参考要求", "坐标信息"),
                content=correct_content,
                content_hash=_hash(correct_content),
                vector_score=0.95,
            ),
            VectorSearchHit(
                chunk_id="CHUNK-WRONG",
                document_id="DELIVERY-PACKAGE-002",
                document_name="DOM交付包组织规范",
                document_version="2.0",
                chunk_index=1,
                section_path=("DOM交付包组织规范", "包含内容"),
                content=wrong_content,
                content_hash=_hash(wrong_content),
                vector_score=0.7,
            ),
        )

    async def search_keywords(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
    ) -> tuple[KeywordSearchHit, ...]:
        self.filters.append(filters)
        return self.keyword_hits[:top_k]

    async def search_vectors(
        self,
        query_embedding: QueryEmbedding,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
        min_similarity: float = -1.0,
    ) -> tuple[VectorSearchHit, ...]:
        self.filters.append(filters)
        return self.vector_hits[:top_k]


class _EmbeddingGenerator:
    async def generate_query(self, query: str) -> QueryEmbedding:
        return QueryEmbedding(
            descriptor=EmbeddingIndexDescriptor(
                provider="test",
                model="test-model",
                dimension=EMBEDDING_DIMENSION,
                index_version="test-v1",
            ),
            vector=tuple(0.0 for _ in range(EMBEDDING_DIMENSION)),
        )


class _Reranker:
    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        async def _respond() -> object:
            return {
                "scores": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "score": 0.95 if candidate.candidate_id == "CHUNK-CORRECT" else 0.1,
                    }
                    for candidate in request.candidates
                ]
            }

        return _respond()


@pytest.mark.asyncio
async def test_concrete_subject_executes_all_four_strategies_with_same_filters() -> None:
    repository = _SearchRepository()
    subject = KnowledgeRagEvaluationSubject(
        repository=repository,
        embedding_generator=_EmbeddingGenerator(),
        reranker=_Reranker(),
        rerank_min_score=0.5,
    )
    case = _case(
        "rag-001",
        "COORDINATE-REFERENCE-002",
        ("DOM坐标参考要求", "坐标信息"),
    )

    predictions = {
        strategy: await subject.retrieve(case, strategy, top_k=5)
        for strategy in RagEvaluationStrategy
    }

    assert predictions[RagEvaluationStrategy.KEYWORD].results[0].document_id == (
        "DELIVERY-PACKAGE-002"
    )
    assert predictions[RagEvaluationStrategy.VECTOR].results[0].document_id == (
        "COORDINATE-REFERENCE-002"
    )
    assert predictions[RagEvaluationStrategy.HYBRID].results[0].document_id == (
        "COORDINATE-REFERENCE-002"
    )
    assert [
        result.document_id
        for result in predictions[RagEvaluationStrategy.HYBRID_RERANK].results
    ] == ["COORDINATE-REFERENCE-002"]
    assert repository.filters
    assert all(filters == _FILTERS for filters in repository.filters)
