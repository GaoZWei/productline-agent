"""M4.10 引用结构、合并Chunk身份和相关性分数测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.knowledge import RerankedResult, RetrievalResult, build_citations
from app.schemas.knowledge import Citation


def _retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        chunk_ids=("CHUNK-001", "CHUNK-002"),
        document_id="DOC-QUALITY-001",
        document_name="坐标系统一与返工规范",
        document_version="2.1",
        chunk_indexes=(1, 2),
        section_path=("质量复核", "坐标系问题"),
        content="发现坐标系不一致时必须返工。\n\n处理完成后重新提交复核。",
        content_hashes=("hash-001", "hash-002"),
        keyword_score=0.8,
        vector_score=0.9,
        keyword_rank=2,
        vector_rank=1,
        rrf_score=0.03,
    )


@pytest.mark.unit
def test_build_citation_preserves_document_section_and_all_merged_chunks() -> None:
    citations = build_citations(
        (RerankedResult(retrieval=_retrieval_result(), rerank_score=0.93),)
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation.document_id == "DOC-QUALITY-001"
    assert citation.document_name == "坐标系统一与返工规范"
    assert citation.document_version == "2.1"
    assert citation.section == ("质量复核", "坐标系问题")
    assert citation.chunk_id == "CHUNK-001"
    assert citation.chunk_ids == ("CHUNK-001", "CHUNK-002")
    assert citation.content == "发现坐标系不一致时必须返工。\n\n处理完成后重新提交复核。"
    assert citation.relevance_score == pytest.approx(0.93)


@pytest.mark.unit
def test_timeout_citation_does_not_mislabel_rrf_as_relevance_score() -> None:
    citations = build_citations(
        (RerankedResult(retrieval=_retrieval_result(), rerank_score=None),)
    )

    assert citations[0].relevance_score is None


@pytest.mark.unit
def test_citation_requires_primary_chunk_to_match_complete_chunk_identity() -> None:
    values = {
        "document_id": "DOC-QUALITY-001",
        "document_name": "坐标系统一与返工规范",
        "document_version": "2.1",
        "section": ("质量复核", "坐标系问题"),
        "chunk_id": "CHUNK-X",
        "chunk_ids": ("CHUNK-001", "CHUNK-002"),
        "content": "引用正文",
        "relevance_score": 0.9,
    }

    with pytest.raises(ValidationError, match="primary chunk"):
        Citation.model_validate(values)


@pytest.mark.unit
@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan")])
def test_citation_rejects_invalid_relevance_score(score: float) -> None:
    with pytest.raises(ValidationError):
        Citation(
            document_id="DOC-QUALITY-001",
            document_name="坐标系统一与返工规范",
            document_version="2.1",
            section=("质量复核",),
            chunk_id="CHUNK-001",
            chunk_ids=("CHUNK-001",),
            content="引用正文",
            relevance_score=score,
        )
