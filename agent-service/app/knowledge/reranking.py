"""在混合召回之后执行可校验的模型重排与低相关片段拦截。"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.knowledge.hybrid import RetrievalResult

_LOGGER = logging.getLogger("agent-service.knowledge-reranking")

# 发送给模型的最小候选, 不携带权限或会话等无关上下文
class RerankValidationError(ValueError):
    """重排参数、候选身份或模型分数不满足严格契约。"""


class RerankExecutionError(RuntimeError):
    """非超时的模型调用失败, 且不向上游暴露供应商原始信息。"""


class RerankDegradationReason(StrEnum):
    """允许调用方区分正常重排与受控降级。"""

    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    """发送给模型的最小候选, 不携带权限或会话等无关上下文。"""

    candidate_id: str
    chunk_ids: tuple[str, ...]
    document_id: str
    section_path: tuple[str, ...]
    content: str
    rrf_score: float

# 一次完整重排请求
@dataclass(frozen=True, slots=True)
class RerankRequest:
    """一次模型重排请求的供应商无关输入。"""

    query: str
    candidates: tuple[RerankCandidate, ...]

# Reranker接口
class Reranker(Protocol):
    """模型适配器接口; 返回值仍需经过本模块的严格结构校验。"""

    def rerank(self, request: RerankRequest) -> Awaitable[object]:
        """为请求中的每个候选返回一个0到1之间的相关性分数。"""

# 模型返回结构
class _RerankModelSchema(BaseModel):
    """拒绝额外字段和隐式类型转换的模型输出共同契约。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class RerankScore(_RerankModelSchema):
    """模型对单个候选给出的归一化相关性分数。"""

    candidate_id: Annotated[str, Field(min_length=1, max_length=256)]
    score: Annotated[float, Field(ge=0.0, le=1.0)]


class RerankResponse(_RerankModelSchema):
    """模型必须一次性、完整地返回所有候选分数。"""

    scores: Annotated[tuple[RerankScore, ...], Field(strict=False)]

# 结果结构
@dataclass(frozen=True, slots=True)
class RerankedResult:
    """保留原始召回证据并附加可选模型分数。"""

    retrieval: RetrievalResult
    rerank_score: float | None # 模型针对当前问题给出的相关性判断

# 统一承载正常和降级结果
@dataclass(frozen=True, slots=True)
class RerankOutcome:
    """重排结果及其是否因超时回退到原始RRF顺序。"""

    results: tuple[RerankedResult, ...]
    degraded: bool = False
    degradation_reason: RerankDegradationReason | None = None

# 核心重排流程!!
async def rerank_retrieval_results(
    query: str,
    candidates: Sequence[RetrievalResult],
    reranker: Reranker,
    *,
    timeout_seconds: float = 2.0,
    min_score: float = 0.5,
) -> RerankOutcome:
    """按模型相关性重排并过滤低分候选; 超时则保留原RRF结果。"""
    # 参数校验
    _validate_parameters(query, timeout_seconds, min_score)
    # 固化输入候选
    retrieval_candidates = tuple(candidates)
    # 构造模型请求
    request = _build_request(query, retrieval_candidates)
    # 空候选短路, 没有候选时不调用模型, 避免无意义的网络请求和费用
    if not request.candidates:
        return RerankOutcome(results=())

    try:
        async with asyncio.timeout(timeout_seconds):
            raw_response = await reranker.rerank(request)
    except TimeoutError:
        _LOGGER.warning(
            "knowledge_rerank_timeout",
            extra={
                "candidate_count": len(request.candidates),
                "timeout_seconds": timeout_seconds,
            },
        )
        # 发生超时时不会让整条RAG链路直接失败
        return RerankOutcome(
            results=tuple(
                RerankedResult(retrieval=candidate, rerank_score=None)
                for candidate in retrieval_candidates
            ),
            degraded=True,
            degradation_reason=RerankDegradationReason.TIMEOUT,
        )
    except Exception as error:
        _LOGGER.error(
            "knowledge_rerank_execution_failed",
            extra={
                "candidate_count": len(request.candidates),
                "error_type": type(error).__name__,
            },
        )
        # 其他模型异常时, 直接抛出异常
        raise RerankExecutionError("reranker execution failed") from error

    response = _parse_response(raw_response)
    scores_by_id = _validate_and_index_scores(request, response)

    scored = (
        (position, candidate, scores_by_id[model_candidate.candidate_id])
        for position, (candidate, model_candidate) in enumerate(
            zip(retrieval_candidates, request.candidates, strict=True)
        )
    )
    # 低相关片段拦截和稳定排序
    retained = (item for item in scored if item[2] >= min_score)
    # 模型分数从高到低;
    # 分数相同时保持原始RRF顺序
    ordered = sorted(retained, key=lambda item: (-item[2], item[0]))
    return RerankOutcome(
        results=tuple(
            RerankedResult(retrieval=candidate, rerank_score=score)
            for _, candidate, score in ordered
        )
    )


def _build_request(
    query: str,
    candidates: Sequence[RetrievalResult],
) -> RerankRequest:
    model_candidates: list[RerankCandidate] = []
    candidate_ids: set[str] = set()
    for candidate in candidates:
        if not candidate.chunk_ids or not candidate.chunk_ids[0]:
            raise RerankValidationError("candidate must contain a stable chunk identity")
        candidate_id = candidate.chunk_ids[0]
        if candidate_id in candidate_ids:
            raise RerankValidationError("duplicate candidate identity")
        candidate_ids.add(candidate_id)
        model_candidates.append(
            RerankCandidate(
                candidate_id=candidate_id,
                chunk_ids=candidate.chunk_ids,
                document_id=candidate.document_id,
                section_path=candidate.section_path,
                content=candidate.content,
                rrf_score=candidate.rrf_score,
            )
        )
    return RerankRequest(query=query.strip(), candidates=tuple(model_candidates))

# 模型响应校验
def _parse_response(raw_response: object) -> RerankResponse:
    try:
        if isinstance(raw_response, (str, bytes, bytearray)):
            return RerankResponse.model_validate_json(raw_response)
        return RerankResponse.model_validate(raw_response)
    except ValidationError as error:
        # 解析失败, 抛出异常, 让调用方处理
        raise RerankValidationError("reranker output schema validation failed") from error


def _validate_and_index_scores(
    request: RerankRequest,
    response: RerankResponse,
) -> dict[str, float]:
    expected_ids = {candidate.candidate_id for candidate in request.candidates}
    scores_by_id: dict[str, float] = {}
    for scored_candidate in response.scores:
        if scored_candidate.candidate_id in scores_by_id:
            raise RerankValidationError("reranker output contains duplicate candidate identity")
        if scored_candidate.candidate_id not in expected_ids:
            raise RerankValidationError("reranker output contains unknown candidate identity")
        scores_by_id[scored_candidate.candidate_id] = scored_candidate.score

    if scores_by_id.keys() != expected_ids:
        raise RerankValidationError("reranker output does not cover every candidate")
    return scores_by_id


def _validate_parameters(
    query: str,
    timeout_seconds: float,
    min_score: float,
) -> None:
    if not isinstance(query, str) or not query.strip():
        raise RerankValidationError("query must not be blank")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0.0
    ):
        raise RerankValidationError("timeout_seconds must be finite and positive")
    if (
        isinstance(min_score, bool)
        or not isinstance(min_score, (int, float))
        or not math.isfinite(min_score)
        or not 0.0 <= min_score <= 1.0
    ):
        raise RerankValidationError("min_score must be between 0 and 1")
