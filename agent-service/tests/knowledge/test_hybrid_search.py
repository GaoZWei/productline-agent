"""M4.8 RRF融合、Chunk去重、相邻片段合并和混合TopK测试。"""

from __future__ import annotations

from hashlib import sha256

import pytest

from app.knowledge import (
    HybridSearchValidationError,
    KeywordSearchHit,
    VectorSearchHit,
    fuse_hybrid_results,
)


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _keyword_hit(
    chunk_id: str,
    *,
    document_id: str,
    chunk_index: int,
    score: float,
    section_path: tuple[str, ...] = ("测试规范", "处理要求"),
    content: str | None = None,
) -> KeywordSearchHit:
    resolved_content = content or f"{chunk_id}关键词正文"
    return KeywordSearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=f"{document_id}测试规范",
        document_version="1.0",
        chunk_index=chunk_index,
        section_path=section_path,
        content=resolved_content,
        content_hash=_content_hash(resolved_content),
        keyword_score=score,
    )


def _vector_hit(
    chunk_id: str,
    *,
    document_id: str,
    chunk_index: int,
    score: float,
    section_path: tuple[str, ...] = ("测试规范", "处理要求"),
    content: str | None = None,
) -> VectorSearchHit:
    resolved_content = content or f"{chunk_id}关键词正文"
    return VectorSearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=f"{document_id}测试规范",
        document_version="1.0",
        chunk_index=chunk_index,
        section_path=section_path,
        content=resolved_content,
        content_hash=_content_hash(resolved_content),
        vector_score=score,
    )


@pytest.mark.unit
def test_rrf_fuses_channel_ranks_and_deduplicates_the_same_chunk() -> None:
    keyword_hits = (
        _keyword_hit("CHUNK-A", document_id="DOC-A", chunk_index=0, score=100.0),
        _keyword_hit("CHUNK-B", document_id="DOC-B", chunk_index=0, score=0.01),
    )
    vector_hits = (
        _vector_hit("CHUNK-B", document_id="DOC-B", chunk_index=0, score=0.2),
        _vector_hit("CHUNK-C", document_id="DOC-C", chunk_index=0, score=0.99),
    )

    results = fuse_hybrid_results(keyword_hits, vector_hits, top_k=10)

    assert [result.chunk_ids for result in results] == [
        ("CHUNK-B",),
        ("CHUNK-A",),
        ("CHUNK-C",),
    ]
    assert results[0].keyword_rank == 2
    assert results[0].vector_rank == 1
    assert results[0].keyword_score == pytest.approx(0.01)
    assert results[0].vector_score == pytest.approx(0.2)
    assert results[0].rrf_score == pytest.approx((1 / 62) + (1 / 61))


@pytest.mark.unit
def test_adjacent_fragments_merge_in_document_order_before_hybrid_top_k() -> None:
    keyword_hits = (
        _keyword_hit(
            "CHUNK-2",
            document_id="DOC-A",
            chunk_index=2,
            score=0.9,
            content="第二段。",
        ),
        _keyword_hit("CHUNK-X", document_id="DOC-X", chunk_index=0, score=0.8),
        _keyword_hit(
            "CHUNK-1",
            document_id="DOC-A",
            chunk_index=1,
            score=0.7,
            content="第一段。",
        ),
    )
    vector_hits = (
        _vector_hit(
            "CHUNK-1",
            document_id="DOC-A",
            chunk_index=1,
            score=0.95,
            content="第一段。",
        ),
    )

    results = fuse_hybrid_results(keyword_hits, vector_hits, top_k=1)

    assert len(results) == 1
    assert results[0].chunk_ids == ("CHUNK-1", "CHUNK-2")
    assert results[0].chunk_indexes == (1, 2)
    assert results[0].content == "第一段。\n\n第二段。"
    assert len(results[0].content_hashes) == 2
    assert results[0].keyword_score == pytest.approx(0.9)
    assert results[0].vector_score == pytest.approx(0.95)
    assert results[0].keyword_rank == 1
    assert results[0].vector_rank == 1
    assert results[0].rrf_score == pytest.approx(2 / 61)


@pytest.mark.unit
def test_fragments_do_not_merge_across_sections_or_non_adjacent_indexes() -> None:
    keyword_hits = (
        _keyword_hit("CHUNK-A", document_id="DOC-A", chunk_index=0, score=0.9),
        _keyword_hit(
            "CHUNK-B",
            document_id="DOC-A",
            chunk_index=1,
            score=0.8,
            section_path=("测试规范", "另一章节"),
        ),
        _keyword_hit("CHUNK-C", document_id="DOC-A", chunk_index=3, score=0.7),
    )

    results = fuse_hybrid_results(keyword_hits, (), top_k=10)

    assert [result.chunk_ids for result in results] == [
        ("CHUNK-A",),
        ("CHUNK-B",),
        ("CHUNK-C",),
    ]


@pytest.mark.unit
def test_rrf_ties_use_stable_document_and_chunk_order() -> None:
    keyword_hits = (_keyword_hit("CHUNK-B", document_id="DOC-B", chunk_index=0, score=0.9),)
    vector_hits = (_vector_hit("CHUNK-A", document_id="DOC-A", chunk_index=0, score=0.9),)

    results = fuse_hybrid_results(keyword_hits, vector_hits, top_k=1)

    assert results[0].chunk_ids == ("CHUNK-A",)


@pytest.mark.unit
def test_hybrid_search_rejects_conflicting_payload_for_the_same_chunk() -> None:
    keyword_hits = (
        _keyword_hit(
            "CHUNK-A",
            document_id="DOC-A",
            chunk_index=0,
            score=0.9,
            content="关键词正文。",
        ),
    )
    vector_hits = (
        _vector_hit(
            "CHUNK-A",
            document_id="DOC-A",
            chunk_index=0,
            score=0.9,
            content="不一致的向量正文。",
        ),
    )

    with pytest.raises(HybridSearchValidationError, match="conflicting chunk payload"):
        fuse_hybrid_results(keyword_hits, vector_hits)


@pytest.mark.unit
@pytest.mark.parametrize("top_k", [True, 0, 101])
def test_hybrid_search_rejects_invalid_top_k(top_k: int) -> None:
    with pytest.raises(HybridSearchValidationError, match="top_k"):
        fuse_hybrid_results((), (), top_k=top_k)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("keyword_score", "vector_score"),
    [
        (float("nan"), None),
        (-0.1, None),
        (None, float("inf")),
        (None, 1.1),
    ],
)
def test_hybrid_search_rejects_invalid_channel_scores(
    keyword_score: float | None,
    vector_score: float | None,
) -> None:
    keyword_hits = (
        (
            _keyword_hit(
                "CHUNK-A",
                document_id="DOC-A",
                chunk_index=0,
                score=keyword_score,
            ),
        )
        if keyword_score is not None
        else ()
    )
    vector_hits = (
        (
            _vector_hit(
                "CHUNK-A",
                document_id="DOC-A",
                chunk_index=0,
                score=vector_score,
            ),
        )
        if vector_score is not None
        else ()
    )

    with pytest.raises(HybridSearchValidationError, match="score"):
        fuse_hybrid_results(keyword_hits, vector_hits)
