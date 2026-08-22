"""把重排结果转换为不丢失合并Chunk身份的规范引用。"""

from __future__ import annotations

from collections.abc import Sequence

from app.knowledge.reranking import RerankedResult
from app.schemas.knowledge import Citation


# 转换函数  把重排结果转换为规范引用
def build_citations(results: Sequence[RerankedResult]) -> tuple[Citation, ...]:
    """保留规范、章节、正文和全部Chunk身份, 不用RRF冒充模型相关性。"""

    return tuple(
        Citation(
            document_id=item.retrieval.document_id,
            document_name=item.retrieval.document_name,
            document_version=item.retrieval.document_version,
            section=item.retrieval.section_path,
            chunk_id=item.retrieval.chunk_ids[0],
            chunk_ids=item.retrieval.chunk_ids,
            content=item.retrieval.content,
            relevance_score=item.rerank_score,  # 重排分数作为相关性
        )
        for item in results
    )
