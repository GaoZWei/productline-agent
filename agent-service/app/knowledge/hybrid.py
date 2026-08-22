"""将关键词与向量候选确定性融合为可审查的混合检索结果。"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.knowledge.search import KeywordSearchHit, VectorSearchHit

_RRF_RANK_CONSTANT = 60


class HybridSearchValidationError(ValueError):
    """混合TopK、通道分数或同一Chunk载荷不满足融合契约。"""

# 统一输出结构
@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """保留来源Chunk、通道信号和RRF分数的混合检索结果。"""

    chunk_ids: tuple[str, ...]  # 使用复数是因为一个结果可能由多个相邻Chunk合并而来
    document_id: str
    document_name: str
    document_version: str
    chunk_indexes: tuple[int, ...]  # 记录Chunk在原文档中的顺序
    section_path: tuple[str, ...]  
    content: str
    content_hashes: tuple[str, ...]  # 和 chunk_ids 对应, 保留每个原始Chunk的内容哈希
    keyword_score: float | None # 两种原始分数
    vector_score: float | None
    keyword_rank: int | None # 两种通道名次
    vector_rank: int | None
    rrf_score: float # 最终用于混合排序的RRF分数


@dataclass(slots=True)
class _Candidate:
    """融合过程中按Chunk身份累积两个召回通道的内部候选。"""

    chunk_id: str
    document_id: str
    document_name: str
    document_version: str
    chunk_index: int
    section_path: tuple[str, ...]
    content: str
    content_hash: str
    keyword_score: float | None = None
    vector_score: float | None = None
    keyword_rank: int | None = None
    vector_rank: int | None = None

# 融合主函数
def fuse_hybrid_results(  # 两个输入列表必须已经按照各自通道的相关度从高到低排列
    keyword_hits: Sequence[KeywordSearchHit],  # 已经按关键词相关度排序的结果
    vector_hits: Sequence[VectorSearchHit],  # 已经按向量相关度排序的结果
    *,
    top_k: int = 10,  # 最终返回数量, 默认10个
) -> tuple[RetrievalResult, ...]:  # 返回统一的 RetrievalResult 元组
    """按RRF融合两路排名, 去重Chunk并在混合TopK前合并相邻片段。"""
    # 第一步: 校验TopK是否有效
    _validate_top_k(top_k)
    candidates: dict[str, _Candidate] = {}  # 候选保存在dict中
    # 第二步: 收集关键词候选
    for rank, keyword_hit in enumerate(keyword_hits, start=1):
        _validate_keyword_hit(keyword_hit)
        candidate = _get_or_create_candidate(candidates, keyword_hit)
        # 只保存第一次出现的排名
        if candidate.keyword_rank is None:
            candidate.keyword_rank = rank
            candidate.keyword_score = keyword_hit.keyword_score

    for rank, vector_hit in enumerate(vector_hits, start=1):
        _validate_vector_hit(vector_hit)
        # 第三步: 合并向量候选
        candidate = _get_or_create_candidate(candidates, vector_hit)
        # 只保存第一次出现的排名
        if candidate.vector_rank is None:
            candidate.vector_rank = rank
            candidate.vector_score = vector_hit.vector_score
    # 先合并相邻Chunk
    fused = tuple(_to_retrieval_result(candidate) for candidate in candidates.values())
    merged = _merge_adjacent_fragments(fused)
    return tuple(sorted(merged, key=_result_sort_key)[:top_k])

# 同一个Chunk被两路召回时, 会合并成一个RetrievalResult
def _get_or_create_candidate(
    candidates: dict[str, _Candidate],
    hit: KeywordSearchHit | VectorSearchHit,
) -> _Candidate:
    candidate = candidates.get(hit.chunk_id)
    if candidate is None:
        candidate = _Candidate(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            document_name=hit.document_name,
            document_version=hit.document_version,
            chunk_index=hit.chunk_index,
            section_path=hit.section_path,
            content=hit.content,
            content_hash=hit.content_hash,
        )
        candidates[hit.chunk_id] = candidate
        return candidate

    expected_payload = (
        candidate.document_id,
        candidate.document_name,
        candidate.document_version,
        candidate.chunk_index,
        candidate.section_path,
        candidate.content,
        candidate.content_hash,
    )
    actual_payload = (
        hit.document_id,
        hit.document_name,
        hit.document_version,
        hit.chunk_index,
        hit.section_path,
        hit.content,
        hit.content_hash,
    )
    # 发现相同 chunk_id 时, 不会直接相信它们是同一内容, 还会比较其他参数是否一致
    if actual_payload != expected_payload:
        raise HybridSearchValidationError("conflicting chunk payload across search channels")
    return candidate


def _to_retrieval_result(candidate: _Candidate) -> RetrievalResult:
    return RetrievalResult(
        chunk_ids=(candidate.chunk_id,),
        document_id=candidate.document_id,
        document_name=candidate.document_name,
        document_version=candidate.document_version,
        chunk_indexes=(candidate.chunk_index,),
        section_path=candidate.section_path,
        content=candidate.content,
        content_hashes=(candidate.content_hash,),
        keyword_score=candidate.keyword_score,
        vector_score=candidate.vector_score,
        keyword_rank=candidate.keyword_rank,
        vector_rank=candidate.vector_rank,
        rrf_score=_rrf_score(candidate.keyword_rank, candidate.vector_rank),
    )

# 相邻Chunk如何合并内容
def _merge_adjacent_fragments(
    results: Sequence[RetrievalResult],
) -> tuple[RetrievalResult, ...]:
    grouped: dict[tuple[str, tuple[str, ...]], list[RetrievalResult]] = {}
    for result in results:
        # 按文档ID和章节路径分组
        grouped.setdefault((result.document_id, result.section_path), []).append(result)

    merged: list[RetrievalResult] = []
    for group in grouped.values():
        # 然后按照 chunk_index 排序
        ordered = sorted(group, key=lambda result: (result.chunk_indexes[0], result.chunk_ids[0]))
        adjacent: list[RetrievalResult] = []
        for result in ordered:
            # 最后判断是否连续
            if adjacent and result.chunk_indexes[0] != adjacent[-1].chunk_indexes[-1] + 1:
                merged.append(_merge_result_group(adjacent))
                adjacent = []
            adjacent.append(result)
        if adjacent:
            merged.append(_merge_result_group(adjacent))
    return tuple(merged)

# 多个相邻Chunk合并时不会覆盖正文, 而是按原文顺序拼接并保留每段身份。
def _merge_result_group(group: Sequence[RetrievalResult]) -> RetrievalResult:
    first = group[0]
    # 每个通道只取组内最佳名次
    keyword_rank = _minimum_optional(result.keyword_rank for result in group)
    vector_rank = _minimum_optional(result.vector_rank for result in group)
    return RetrievalResult(
        chunk_ids=tuple(chunk_id for result in group for chunk_id in result.chunk_ids),
        document_id=first.document_id,
        document_name=first.document_name,
        document_version=first.document_version,
        chunk_indexes=tuple(index for result in group for index in result.chunk_indexes),
        section_path=first.section_path,
        content="\n\n".join(result.content for result in group),
        content_hashes=tuple(
            content_hash for result in group for content_hash in result.content_hashes
        ),
        # 原始分数同样保留组内最大值
        keyword_score=_maximum_optional(result.keyword_score for result in group),
        vector_score=_maximum_optional(result.vector_score for result in group),
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        # 然后重新计算RRF分数
        rrf_score=_rrf_score(keyword_rank, vector_rank),
    )


def _maximum_optional(values: Iterable[float | None]) -> float | None:
    present = tuple(value for value in values if value is not None)
    return max(present) if present else None


def _minimum_optional(values: Iterable[int | None]) -> int | None:
    present = tuple(value for value in values if value is not None)
    return min(present) if present else None

# RRF分数计算
# 关键词贡献 = 1 / (60 + keyword_rank)
# 向量贡献   = 1 / (60 + vector_rank)
def _rrf_score(keyword_rank: int | None, vector_rank: int | None) -> float:
    return sum(
        1.0 / (_RRF_RANK_CONSTANT + rank)
        for rank in (keyword_rank, vector_rank)
        if rank is not None
    )

# 稳定排序规则
def _result_sort_key(result: RetrievalResult) -> tuple[float, int, str, int, tuple[str, ...]]:
    ranks = tuple(rank for rank in (result.keyword_rank, result.vector_rank) if rank is not None)
    best_rank = min(ranks) if ranks else 0
    return (
        -result.rrf_score,  # RRF越大越靠前
        best_rank,  # RRF相同时, 单通道最佳名次更高的优先
        result.document_id,  # 继续相同时按文档ID稳定排序
        result.chunk_indexes[0],  # 同文档按正文顺序排序
        result.chunk_ids,  # 同文档按ChunkID排序
    )


def _validate_keyword_hit(hit: KeywordSearchHit) -> None:
    _validate_common_hit(hit)
    if not math.isfinite(hit.keyword_score) or hit.keyword_score < 0.0:
        raise HybridSearchValidationError("keyword score must be finite and nonnegative")


def _validate_vector_hit(hit: VectorSearchHit) -> None:
    _validate_common_hit(hit)
    if not math.isfinite(hit.vector_score) or not -1.0 <= hit.vector_score <= 1.0:
        raise HybridSearchValidationError("vector score must be finite and between -1 and 1")


def _validate_common_hit(hit: KeywordSearchHit | VectorSearchHit) -> None:
    if (
        not hit.chunk_id
        or not hit.document_id
        or isinstance(hit.chunk_index, bool)
        or hit.chunk_index < 0
        or not hit.section_path
        or not hit.content
        or not hit.content_hash
    ):
        raise HybridSearchValidationError("search hit does not satisfy hybrid schema")


def _validate_top_k(top_k: int) -> None:
    if isinstance(top_k, bool) or not 1 <= top_k <= 100:
        raise HybridSearchValidationError("top_k must be between 1 and 100")
