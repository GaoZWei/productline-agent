"""M4.9 模型重排、超时降级和低相关片段拦截测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

import pytest

from app.knowledge import (
    RerankExecutionError,
    RerankRequest,
    RerankValidationError,
    RetrievalResult,
    rerank_retrieval_results,
)


def _retrieval_result(
    chunk_id: str,
    *,
    document_id: str,
    content: str,
    rrf_score: float,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_ids=(chunk_id,),
        document_id=document_id,
        document_name=f"{document_id}测试规范",
        document_version="1.0",
        chunk_indexes=(0,),
        section_path=("质量规范", "复核要求"),
        content=content,
        content_hashes=(f"hash-{chunk_id}",),
        keyword_score=1.0,
        vector_score=0.8,
        keyword_rank=1,
        vector_rank=1,
        rrf_score=rrf_score,
    )


class _StaticReranker:
    def __init__(self, output: object) -> None:
        self.output = output
        self.requests: list[RerankRequest] = []

    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        self.requests.append(request)

        async def _respond() -> object:
            return self.output

        return _respond()


class _BlockingReranker:
    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        async def _wait_forever() -> object:
            await asyncio.Event().wait()
            return {"scores": []}

        return _wait_forever()


class _FailingReranker:
    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        async def _fail() -> object:
            raise RuntimeError("provider secret response")

        return _fail()


class _UnexpectedCallReranker:
    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        raise AssertionError("empty candidates must not call the reranker")


@pytest.mark.unit
async def test_model_scores_rerank_candidates_and_block_low_relevance() -> None:
    candidates = (
        _retrieval_result(
            "CHUNK-A",
            document_id="DOC-A",
            content="通用质量说明。",
            rrf_score=0.04,
        ),
        _retrieval_result(
            "CHUNK-B",
            document_id="DOC-B",
            content="坐标系问题处理要求。",
            rrf_score=0.03,
        ),
        _retrieval_result(
            "CHUNK-C",
            document_id="DOC-C",
            content="无关交付说明。",
            rrf_score=0.02,
        ),
    )
    reranker = _StaticReranker(
        {
            "scores": [
                {"candidate_id": "CHUNK-A", "score": 0.70},
                {"candidate_id": "CHUNK-B", "score": 0.95},
                {"candidate_id": "CHUNK-C", "score": 0.20},
            ]
        }
    )

    outcome = await rerank_retrieval_results(
        "坐标系问题应该如何返工?",
        candidates,
        reranker,
        min_score=0.50,
    )

    assert [item.retrieval.chunk_ids for item in outcome.results] == [
        ("CHUNK-B",),
        ("CHUNK-A",),
    ]
    assert [item.rerank_score for item in outcome.results] == [0.95, 0.70]
    assert outcome.results[0].retrieval.rrf_score == 0.03
    assert outcome.degraded is False
    assert outcome.degradation_reason is None
    assert len(reranker.requests) == 1
    assert reranker.requests[0].query == "坐标系问题应该如何返工?"
    assert [candidate.candidate_id for candidate in reranker.requests[0].candidates] == [
        "CHUNK-A",
        "CHUNK-B",
        "CHUNK-C",
    ]
    assert reranker.requests[0].candidates[1].content == "坐标系问题处理要求。"


@pytest.mark.unit
async def test_equal_rerank_scores_preserve_original_rrf_order() -> None:
    candidates = (
        _retrieval_result("CHUNK-A", document_id="DOC-A", content="A", rrf_score=0.04),
        _retrieval_result("CHUNK-B", document_id="DOC-B", content="B", rrf_score=0.03),
    )
    reranker = _StaticReranker(
        {
            "scores": [
                {"candidate_id": "CHUNK-B", "score": 0.80},
                {"candidate_id": "CHUNK-A", "score": 0.80},
            ]
        }
    )

    outcome = await rerank_retrieval_results(
        "复核要求",
        candidates,
        reranker,
        min_score=0.50,
    )

    assert [item.retrieval.chunk_ids for item in outcome.results] == [
        ("CHUNK-A",),
        ("CHUNK-B",),
    ]


@pytest.mark.unit
async def test_score_equal_to_threshold_is_retained() -> None:
    candidate = _retrieval_result(
        "CHUNK-A",
        document_id="DOC-A",
        content="A",
        rrf_score=0.04,
    )
    reranker = _StaticReranker(
        {"scores": [{"candidate_id": "CHUNK-A", "score": 0.50}]}
    )

    outcome = await rerank_retrieval_results(
        "复核要求",
        (candidate,),
        reranker,
        min_score=0.50,
    )

    assert len(outcome.results) == 1


@pytest.mark.unit
async def test_timeout_degrades_to_original_results_without_threshold_filtering() -> None:
    candidates = (
        _retrieval_result("CHUNK-A", document_id="DOC-A", content="A", rrf_score=0.04),
        _retrieval_result("CHUNK-B", document_id="DOC-B", content="B", rrf_score=0.03),
    )

    outcome = await rerank_retrieval_results(
        "复核要求",
        candidates,
        _BlockingReranker(),
        timeout_seconds=0.001,
        min_score=0.99,
    )

    assert [item.retrieval for item in outcome.results] == list(candidates)
    assert [item.rerank_score for item in outcome.results] == [None, None]
    assert outcome.degraded is True
    assert outcome.degradation_reason == "TIMEOUT"


@pytest.mark.unit
@pytest.mark.parametrize(
    "output",
    [
        {"scores": [{"candidate_id": "CHUNK-A", "score": 0.8}]},
        {
            "scores": [
                {"candidate_id": "CHUNK-A", "score": 0.8},
                {"candidate_id": "CHUNK-A", "score": 0.7},
            ]
        },
        {
            "scores": [
                {"candidate_id": "CHUNK-A", "score": 0.8},
                {"candidate_id": "CHUNK-X", "score": 0.7},
            ]
        },
        {
            "scores": [
                {"candidate_id": "CHUNK-A", "score": 1.1},
                {"candidate_id": "CHUNK-B", "score": 0.7},
            ]
        },
    ],
)
async def test_invalid_model_scores_fail_closed(output: object) -> None:
    candidates = (
        _retrieval_result("CHUNK-A", document_id="DOC-A", content="A", rrf_score=0.04),
        _retrieval_result("CHUNK-B", document_id="DOC-B", content="B", rrf_score=0.03),
    )

    with pytest.raises(RerankValidationError):
        await rerank_retrieval_results(
            "复核要求",
            candidates,
            _StaticReranker(output),
        )


@pytest.mark.unit
async def test_provider_failure_is_wrapped_without_exposing_provider_message() -> None:
    candidate = _retrieval_result(
        "CHUNK-A",
        document_id="DOC-A",
        content="A",
        rrf_score=0.04,
    )

    with pytest.raises(RerankExecutionError, match="reranker execution failed") as error:
        await rerank_retrieval_results(
            "复核要求",
            (candidate,),
            _FailingReranker(),
        )

    assert "provider secret response" not in str(error.value)


@pytest.mark.unit
async def test_empty_candidates_return_without_calling_model() -> None:
    outcome = await rerank_retrieval_results(
        "复核要求",
        (),
        _UnexpectedCallReranker(),
    )

    assert outcome.results == ()
    assert outcome.degraded is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "timeout_seconds", "min_score"),
    [
        ("", 2.0, 0.5),
        ("复核要求", True, 0.5),
        ("复核要求", 0.0, 0.5),
        ("复核要求", float("inf"), 0.5),
        ("复核要求", 2.0, -0.1),
        ("复核要求", 2.0, 1.1),
        ("复核要求", 2.0, float("nan")),
    ],
)
async def test_invalid_rerank_parameters_are_rejected(
    query: str,
    timeout_seconds: float,
    min_score: float,
) -> None:
    with pytest.raises(RerankValidationError):
        await rerank_retrieval_results(
            query,
            (),
            _UnexpectedCallReranker(),
            timeout_seconds=timeout_seconds,
            min_score=min_score,
        )


@pytest.mark.unit
async def test_duplicate_candidate_identity_is_rejected_before_model_call() -> None:
    candidates = (
        _retrieval_result("CHUNK-A", document_id="DOC-A", content="A", rrf_score=0.04),
        _retrieval_result("CHUNK-A", document_id="DOC-B", content="B", rrf_score=0.03),
    )

    with pytest.raises(RerankValidationError, match="duplicate candidate identity"):
        await rerank_retrieval_results(
            "复核要求",
            candidates,
            _UnexpectedCallReranker(),
        )
