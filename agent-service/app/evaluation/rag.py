"""M4.12 固定RAG评测契约、四策略执行器、指标和安全失败样本。"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.knowledge.hybrid import RetrievalResult, fuse_hybrid_results
from app.knowledge.reranking import Reranker, rerank_retrieval_results
from app.knowledge.retrieval import (
    KnowledgeSearchChannels,
    QueryEmbeddingGenerator,
)
from app.knowledge.search import KeywordSearchHit, VectorSearchHit
from app.schemas.knowledge import (
    CitationChunkIdentifier,
    DocumentIdentifier,
    KnowledgeSearchFilter,
    MetadataText,
)

EXPECTED_RAG_CASE_COUNT: Final = 50
_EVALUATION_TOP_K: Final = 5

# 策略枚举定义
class RagEvaluationStrategy(StrEnum):
    """M4.12要求固定对比的四种检索策略。"""

    VECTOR = "VECTOR"
    KEYWORD = "KEYWORD"
    HYBRID = "HYBRID"
    HYBRID_RERANK = "HYBRID_RERANK"


_DEFAULT_STRATEGIES: Final = tuple(RagEvaluationStrategy)
StrategyValue = Annotated[RagEvaluationStrategy, Field(strict=False)]
CaseIdentifier = Annotated[
    str,
    Field(min_length=7, max_length=7, pattern=r"^rag-[0-9]{3}$"),
]
SectionPath = Annotated[
    tuple[MetadataText, ...],
    Field(min_length=1, max_length=16, strict=False),
]


class _RagEvaluationSchema(BaseModel):
    """评测输入输出禁止额外字段、隐式标量转换和加载后修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 评测用例定义
class RagEvaluationCase(_RagEvaluationSchema):
    """一条带安全过滤条件、预期文档和预期章节的固定问题。"""

    case_id: CaseIdentifier  # 用例编号
    question: Annotated[str, Field(min_length=1, max_length=2000)]  # 用户可能提出的问题
    filters: KnowledgeSearchFilter  # 检索范围，包括产品、卫星、权限和生效时间
    expected_document_id: DocumentIdentifier  # 正确答案应来自哪份规范
    expected_section: Annotated[
        tuple[MetadataText, ...],
        Field(min_length=2, max_length=16, strict=False),  # 正确答案应来自规范的哪个完整章节
    ]


class RagRetrievedFragment(_RagEvaluationSchema):
    """评测只接收检索身份, 不把正文或供应商分数写入报告。"""

    chunk_ids: Annotated[
        tuple[CitationChunkIdentifier, ...],
        Field(min_length=1, strict=False),
    ]
    document_id: DocumentIdentifier
    section_path: SectionPath

    @model_validator(mode="after")
    def validate_chunk_ids(self) -> Self:
        """一个返回片段中的原始Chunk身份必须唯一。"""

        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("retrieved fragment contains duplicate chunk identities")
        return self


class RagEvaluationPrediction(_RagEvaluationSchema):
    """一个策略对一条用例返回的有序TopK片段。"""

    case_id: CaseIdentifier
    strategy: StrategyValue
    results: Annotated[
        tuple[RagRetrievedFragment, ...],
        Field(max_length=_EVALUATION_TOP_K, strict=False),
    ]

    @model_validator(mode="after")
    def validate_result_identity(self) -> Self:
        """同一个原始Chunk不能被多个结果重复计入指标。"""

        seen: set[str] = set()
        for result in self.results:
            overlap = seen.intersection(result.chunk_ids)
            if overlap:
                raise ValueError("prediction repeats a chunk identity")
            seen.update(result.chunk_ids)
        return self

# Subject 可以理解成“被评测对象”
class RagEvaluationSubject(Protocol):
    """真实Repository、离线回放或测试替身共享的策略评测边界。"""

    def retrieve(
        self,
        case: RagEvaluationCase,
        strategy: RagEvaluationStrategy,
        *,
        top_k: int,
    ) -> Awaitable[RagEvaluationPrediction]:
        """按指定策略返回一条固定问题的有序结果。"""

# 失败原因定义
class RagFailureReason(StrEnum):
    """失败样本只记录可稳定聚合的检索失败原因。"""

    NO_RESULTS = "NO_RESULTS"
    DOCUMENT_MISS = "DOCUMENT_MISS"
    SECTION_MISS = "SECTION_MISS"


FailureReasonValue = Annotated[RagFailureReason, Field(strict=False)]


class RagEvaluationFailure(_RagEvaluationSchema):
    """不包含问题和正文的安全失败样本。"""

    case_id: CaseIdentifier
    strategy: StrategyValue
    reason: FailureReasonValue
    expected_document_id: DocumentIdentifier
    expected_section: SectionPath
    returned_document_ids: Annotated[
        tuple[DocumentIdentifier, ...],
        Field(strict=False),
    ] = ()
    returned_sections: Annotated[
        tuple[SectionPath, ...],
        Field(strict=False),
    ] = ()


class RagStrategyMetrics(_RagEvaluationSchema):
    """一个检索策略在同一批用例上的聚合指标。"""

    strategy: StrategyValue
    total_cases: Annotated[int, Field(gt=0)]
    hit_count_at_5: Annotated[int, Field(ge=0)]
    reciprocal_rank_sum: Annotated[float, Field(ge=0.0)]
    retrieved_fragments: Annotated[int, Field(ge=0)]
    irrelevant_fragments: Annotated[int, Field(ge=0)]
    hit_at_5: Annotated[float, Field(ge=0.0, le=1.0)]
    mrr: Annotated[float, Field(ge=0.0, le=1.0)]
    irrelevant_fragment_ratio: Annotated[float, Field(ge=0.0, le=1.0)]


class RagEvaluationReport(_RagEvaluationSchema):
    """四策略指标与按稳定顺序输出的失败样本。"""

    total_cases: Annotated[int, Field(gt=0)]
    top_k: Annotated[int, Field(ge=1, le=100)]
    strategy_metrics: dict[StrategyValue, RagStrategyMetrics]
    failures: tuple[RagEvaluationFailure, ...] = ()


class RagEvaluationDataError(ValueError):
    """固定数据或Subject预测不满足可重复评测契约。"""


class RagEvaluationExecutionError(RuntimeError):
    """策略执行发生降级, 当前结果不能冒充对应策略质量。"""

# 评测数据校验逻辑
def load_rag_evaluation_cases(
    path: Path,
    *,
    enforce_case_count: bool = True,
) -> tuple[RagEvaluationCase, ...]:
    """逐行加载JSONL, 仅在错误中暴露行号或重复ID。"""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RagEvaluationDataError("rag evaluation dataset is unavailable") from error

    cases: list[RagEvaluationCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = RagEvaluationCase.model_validate_json(line)
        except (ValidationError, ValueError) as error:
            raise RagEvaluationDataError(
                f"invalid rag evaluation case at line {line_number}"
            ) from error
        if case.case_id in seen_ids:
            raise RagEvaluationDataError(f"duplicate case_id: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise RagEvaluationDataError("rag evaluation dataset is empty")
    if enforce_case_count:
        expected_ids = {f"rag-{index:03d}" for index in range(1, EXPECTED_RAG_CASE_COUNT + 1)}
        if len(cases) != EXPECTED_RAG_CASE_COUNT or seen_ids != expected_ids:
            raise RagEvaluationDataError("rag evaluation dataset must contain rag-001 to rag-050")
    return tuple(cases)

# 检索命中核心判断
def _is_relevant(case: RagEvaluationCase, result: RagRetrievedFragment) -> bool:
    """文档和完整章节路径必须同时命中才算相关片段。"""
    # 必须同时满足 文档ID正确 和 完整章节路径正确
    return (
        result.document_id == case.expected_document_id
        and result.section_path == case.expected_section
    )

# 失败原因判断逻辑
def _failure_reason(
    case: RagEvaluationCase,
    results: Sequence[RagRetrievedFragment],
) -> RagFailureReason:
    """区分无结果、文档未命中和文档命中但章节错误。"""
    # 第一层：没有任何结果
    if not results:
        return RagFailureReason.NO_RESULTS
    # 第二层：有结果，但文档全错
    if all(result.document_id != case.expected_document_id for result in results):
        return RagFailureReason.DOCUMENT_MISS
    # 第三层：出现了正确文档，但章节都不正确
    return RagFailureReason.SECTION_MISS


def _write_failure_samples(
    path: Path,
    failures: Sequence[RagEvaluationFailure],
) -> None:
    """覆盖写入稳定JSONL, 不记录问题文本、正文或模型请求。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{failure.model_dump_json()}\n" for failure in failures)
    path.write_text(content, encoding="utf-8")

# 核心评测算法！！！！！！
async def evaluate_rag(
    cases: Sequence[RagEvaluationCase],  # 固定的评测问题集合
    subject: RagEvaluationSubject,  # 被评测的检索实现
    *,
    strategies: Sequence[RagEvaluationStrategy] = _DEFAULT_STRATEGIES,  # 需要评测的策略集合
    failure_path: Path | None = None,  # 可选的失败样本输出路径
) -> RagEvaluationReport:
    """顺序运行四策略并计算Hit@5、MRR和无关片段占比。"""
    # 固定本次评测输入，确保可重复性
    fixed_cases = tuple(cases)
    fixed_strategies = tuple(strategies)
    # 先校验用例和策略是否符合要求
    if not fixed_cases:
        raise RagEvaluationDataError("rag evaluation requires at least one case")
    # 校验用例ID是否唯一，检查重复用例
    if len({case.case_id for case in fixed_cases}) != len(fixed_cases):
        raise RagEvaluationDataError("rag evaluation cases contain duplicate ids")
    # 检查是否包含重复策略
    if not fixed_strategies or len(set(fixed_strategies)) != len(fixed_strategies):
        raise RagEvaluationDataError("rag evaluation strategies must be nonempty and unique")

    metrics: dict[RagEvaluationStrategy, RagStrategyMetrics] = {}
    failures: list[RagEvaluationFailure] = []
    # 运行每个策略的检索
    for strategy in fixed_strategies:
        hit_count = 0  # 记录每个策略在 Top 5 中至少找到一次正确章节的用例数量
        reciprocal_rank_sum = 0.0  # 所有用例“第一个正确结果的倒数排名”之和，后面累加再除以用例数量，得到MRR
        retrieved_fragments = 0  # 当前策略在全部用例中总共返回了多少片段
        irrelevant_fragments = 0  # 这些返回片段中，有多少不满足“文档和章节同时正确”的条件
        for case in fixed_cases:
            prediction = await subject.retrieve(case, strategy, top_k=_EVALUATION_TOP_K)
            # 核对预测结果身份
            if prediction.case_id != case.case_id or prediction.strategy is not strategy:
                raise RagEvaluationDataError(
                    f"prediction identity mismatch for {case.case_id} and {strategy.value}"
                )
            # 计算返回总数和无关结果数
            results = prediction.results
            retrieved_fragments += len(results)
            irrelevant_fragments += sum(
                1 for result in results if not _is_relevant(case, result)
            )
            # 只寻找第一个正确结果的排名
            relevant_rank = next(  # 只取第一个值
                (
                    rank
                    for rank, result in enumerate(results, start=1)
                    if _is_relevant(case, result)  # 只保留正确结果的排名
                ),
                None,
            )
            # 命中时怎么累计MRR
            if relevant_rank is not None:
                hit_count += 1
                reciprocal_rank_sum += 1.0 / relevant_rank
                continue  # 一旦命中，这条用例就不需要创建失败样本，直接进入下一条用例
            # 未命中时创建一个失败对象
            failures.append(
                RagEvaluationFailure(
                    case_id=case.case_id,
                    strategy=strategy,
                    reason=_failure_reason(case, results),
                    expected_document_id=case.expected_document_id,
                    expected_section=case.expected_section,
                    returned_document_ids=tuple(result.document_id for result in results),
                    returned_sections=tuple(result.section_path for result in results),
                )
            )
        # 策略跑完后如何计算指标
        total_cases = len(fixed_cases)
        # 构造该策略的指标对象
        metrics[strategy] = RagStrategyMetrics(
            strategy=strategy,
            total_cases=total_cases,
            hit_count_at_5=hit_count,
            reciprocal_rank_sum=reciprocal_rank_sum,
            retrieved_fragments=retrieved_fragments,
            irrelevant_fragments=irrelevant_fragments,
            hit_at_5=hit_count / total_cases,
            mrr=reciprocal_rank_sum / total_cases,
            irrelevant_fragment_ratio=(
                irrelevant_fragments / retrieved_fragments
                if retrieved_fragments
                else 0.0
            ),
        )
    # 生成报告
    if failure_path is not None:
        _write_failure_samples(failure_path, failures)
    return RagEvaluationReport(
        total_cases=len(fixed_cases),
        top_k=_EVALUATION_TOP_K,
        strategy_metrics=metrics,
        failures=tuple(failures),
    )

# 真正调用当前检索实现的评测主体
class KnowledgeRagEvaluationSubject:
    """把当前关键词、向量、RRF和Reranker实现接到统一评测边界。"""

    def __init__(
        self,
        *,
        repository: KnowledgeSearchChannels,
        embedding_generator: QueryEmbeddingGenerator,
        reranker: Reranker,
        channel_top_k: int = 20,
        rerank_candidate_k: int = 10,
        min_vector_similarity: float = -1.0,
        rerank_timeout_seconds: float = 2.0,
        rerank_min_score: float = 0.5,
    ) -> None:
        _validate_top_k("channel_top_k", channel_top_k)
        _validate_top_k("rerank_candidate_k", rerank_candidate_k)
        if not math.isfinite(min_vector_similarity) or not -1.0 <= min_vector_similarity <= 1.0:
            raise ValueError("min_vector_similarity must be between -1 and 1")
        if not math.isfinite(rerank_timeout_seconds) or rerank_timeout_seconds <= 0.0:
            raise ValueError("rerank_timeout_seconds must be finite and positive")
        if not math.isfinite(rerank_min_score) or not 0.0 <= rerank_min_score <= 1.0:
            raise ValueError("rerank_min_score must be between 0 and 1")
        self._repository = repository
        self._embedding_generator = embedding_generator
        self._reranker = reranker
        self._channel_top_k = channel_top_k
        self._rerank_candidate_k = rerank_candidate_k
        self._min_vector_similarity = min_vector_similarity
        self._rerank_timeout_seconds = rerank_timeout_seconds
        self._rerank_min_score = rerank_min_score

    async def retrieve(
        self,
        case: RagEvaluationCase,
        strategy: RagEvaluationStrategy,
        *,
        top_k: int,
    ) -> RagEvaluationPrediction:
        """对四种策略复用同一问题和安全过滤条件。"""

        _validate_top_k("top_k", top_k)
        # 1. KEYWORD 检索策略
        if strategy is RagEvaluationStrategy.KEYWORD:
            keyword_hits = await self._keyword_hits(case)
            results = tuple(_from_keyword(hit) for hit in keyword_hits[:top_k])
        # 2. VECTOR 检索策略
        elif strategy is RagEvaluationStrategy.VECTOR:
            vector_hits = await self._vector_hits(case)
            results = tuple(_from_vector(hit) for hit in vector_hits[:top_k])
        # 3. HYBRID 检索策略
        else:
            keyword_hits = await self._keyword_hits(case)
            vector_hits = await self._vector_hits(case)
            hybrid_top_k = (
                self._rerank_candidate_k
                if strategy is RagEvaluationStrategy.HYBRID_RERANK
                else top_k
            )
            fused = fuse_hybrid_results(
                keyword_hits,
                vector_hits,
                top_k=hybrid_top_k,
            )
            if strategy is RagEvaluationStrategy.HYBRID:
                results = tuple(_from_retrieval(result) for result in fused[:top_k])
            # 4. HYBRID_RERANK 检索策略
            else:
                outcome = await rerank_retrieval_results(
                    case.question,
                    fused,
                    self._reranker,
                    timeout_seconds=self._rerank_timeout_seconds,
                    min_score=self._rerank_min_score,
                )
                if outcome.degraded:
                    raise RagEvaluationExecutionError(
                        "rerank evaluation degraded and cannot represent rerank quality"
                    )
                results = tuple(
                    _from_retrieval(result.retrieval)
                    for result in outcome.results[:top_k]
                )
        return RagEvaluationPrediction(
            case_id=case.case_id,
            strategy=strategy,
            results=results,
        )

    async def _keyword_hits(
        self,
        case: RagEvaluationCase,
    ) -> tuple[KeywordSearchHit, ...]:
        return await self._repository.search_keywords(
            case.question,
            filters=case.filters,
            top_k=self._channel_top_k,
        )

    async def _vector_hits(
        self,
        case: RagEvaluationCase,
    ) -> tuple[VectorSearchHit, ...]:
        # 先把问题转换为向量，然后调用search_vectors方法进行检索
        query_embedding = await self._embedding_generator.generate_query(case.question)
        return await self._repository.search_vectors(
            query_embedding,
            filters=case.filters,
            top_k=self._channel_top_k,
            min_similarity=self._min_vector_similarity,
        )


def _from_keyword(hit: KeywordSearchHit) -> RagRetrievedFragment:
    return RagRetrievedFragment(
        chunk_ids=(hit.chunk_id,),
        document_id=hit.document_id,
        section_path=hit.section_path,
    )


def _from_vector(hit: VectorSearchHit) -> RagRetrievedFragment:
    return RagRetrievedFragment(
        chunk_ids=(hit.chunk_id,),
        document_id=hit.document_id,
        section_path=hit.section_path,
    )


def _from_retrieval(result: RetrievalResult) -> RagRetrievedFragment:
    return RagRetrievedFragment(
        chunk_ids=result.chunk_ids,
        document_id=result.document_id,
        section_path=result.section_path,
    )


def _validate_top_k(name: str, value: int) -> None:
    if isinstance(value, bool) or not 1 <= value <= 100:
        raise ValueError(f"{name} must be between 1 and 100")
