"""M4.11 固定规范问答图、带引用生成和SpecificationSkill分发门禁。"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, NotRequired, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from app.knowledge import (
    KnowledgeRetriever,
    Reranker,
    RerankOutcome,
    RetrievalResult,
    build_citations,
    rerank_retrieval_results,
)
from app.routing import BusinessSkill, Intent, skill_for_intent
from app.schemas.context import PageContext
from app.schemas.knowledge import Citation, KnowledgeSearchFilter, PermissionScope
from app.schemas.routing import RoutingDecision
from app.schemas.specification import (
    SpecificationAnswerDraft,
    SpecificationQaResult,
    SpecificationQaStatus,
)

_LOGGER = logging.getLogger("agent-service.specification-qa")
type _RelevanceRoute = Literal["generate", "safe"]


class SpecificationQaValidationError(ValueError):
    """问题、模型回答或引用身份不满足规范问答边界。"""


class SpecificationSkillDispatchError(ValueError):
    """路由决策尚未准备好或目标不是SpecificationSkill。"""


@dataclass(frozen=True, slots=True)
class SpecificationAnswerRequest:
    """回答模型只能读取问题和已经过门禁的引用候选。"""

    question: str
    rewritten_query: str
    citations: tuple[Citation, ...]


class SpecificationAnswerModel(Protocol):
    """模型适配器必须返回回答及其实际使用的引用身份。"""

    def generate(self, request: SpecificationAnswerRequest) -> Awaitable[object]:
        """生成引用既有候选的回答, 不能新增引用正文。"""


class _SpecificationQaState(TypedDict):
    question: str
    effective_at: date
    permission_scope: PermissionScope
    page_context: PageContext | None
    rewritten_query: NotRequired[str]
    filters: NotRequired[KnowledgeSearchFilter]
    retrieval_results: NotRequired[tuple[RetrievalResult, ...]]
    rerank_outcome: NotRequired[RerankOutcome]
    sufficient: NotRequired[bool]
    result: NotRequired[SpecificationQaResult]

# SpecificationQaWorkflow核心流程
class SpecificationQaWorkflow:
    """固定执行改写、过滤、召回、重排、充足性检查和带引用生成。"""

    def __init__(
        self,
        *,
        retriever: KnowledgeRetriever,
        reranker: Reranker,
        answer_model: SpecificationAnswerModel,
        rerank_timeout_seconds: float = 2.0,
        min_relevance_score: float = 0.5,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._answer_model = answer_model
        self._rerank_timeout_seconds = rerank_timeout_seconds
        self._min_relevance_score = min_relevance_score
        self.graph = self._build_graph()

    async def ainvoke(
        self,
        question: str,
        *,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> SpecificationQaResult:
        """执行一次规范问答, 页面元数据只作为可选检索收窄提示。"""

        result = await self.graph.ainvoke(
            {
                "question": question,
                "effective_at": effective_at,
                "permission_scope": permission_scope,
                "page_context": page_context,
            }
        )
        return cast(SpecificationQaResult, result["result"])

    def _build_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        builder = StateGraph(_SpecificationQaState)
        builder.add_node("rewrite_query", self.rewrite_query)  # 查询改写函数
        builder.add_node("build_metadata", self.build_metadata)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("rerank", self.rerank)
        builder.add_node("check_relevance", self.check_relevance)
        builder.add_node("generate_answer", self.generate_answer)
        builder.add_node("safe_answer", self.safe_answer)  # 安全回答函数
        builder.add_edge(START, "rewrite_query")
        builder.add_edge("rewrite_query", "build_metadata")
        builder.add_edge("build_metadata", "retrieve")
        builder.add_edge("retrieve", "rerank")
        builder.add_edge("rerank", "check_relevance")
        builder.add_conditional_edges(
            "check_relevance",
            self.route_after_relevance,  # 分支决策函数
            {"generate": "generate_answer", "safe": "safe_answer"},  # 路由决策表
        ) 
        builder.add_edge("generate_answer", END)
        builder.add_edge("safe_answer", END)
        return builder.compile(name="specification-qa")
    # 查询改写函数
    async def rewrite_query(self, state: _SpecificationQaState) -> dict[str, object]:
        """以确定性Unicode和空白规范化生成可重复检索Query。"""

        return {"rewritten_query": rewrite_specification_query(state["question"])}
    # 构造源数据过滤器
    async def build_metadata(self, state: _SpecificationQaState) -> dict[str, object]:
        """把显式安全边界与页面可选提示合并为知识检索过滤器。"""

        return {
            "filters": build_specification_metadata(
                effective_at=state["effective_at"],
                permission_scope=state["permission_scope"],
                page_context=state["page_context"],
            )
        }
    # 执行统一的检索流程
    async def retrieve(self, state: _SpecificationQaState) -> dict[str, object]:
        """执行Query Embedding、关键词/向量召回和RRF融合入口。"""

        results = await self._retriever.retrieve(
            state["rewritten_query"],
            filters=state["filters"],
        )
        return {"retrieval_results": tuple(results)}
    # 重排函数
    async def rerank(self, state: _SpecificationQaState) -> dict[str, object]:
        """调用M4.9重排并保留超时降级状态。"""

        outcome = await rerank_retrieval_results(
            state["rewritten_query"],
            state["retrieval_results"],
            self._reranker,
            timeout_seconds=self._rerank_timeout_seconds,
            min_score=self._min_relevance_score,
        )
        return {"rerank_outcome": outcome}
    # 充足性检查函数
    async def check_relevance(self, state: _SpecificationQaState) -> dict[str, object]:
        """只有完成重排且仍有候选时才允许模型形成规范结论。"""

        outcome = state["rerank_outcome"]
        return {"sufficient": bool(outcome.results) and not outcome.degraded}

    def route_after_relevance(self, state: _SpecificationQaState) -> _RelevanceRoute:
        """把无结果和重排降级统一路由到确定性安全回答。"""

        return "generate" if state["sufficient"] else "safe"
    # 生成带引用的规范回答
    async def generate_answer(self, state: _SpecificationQaState) -> dict[str, object]:
        """校验模型引用集合, 失败时不返回模型文案或候选引用。"""

        citations = build_citations(state["rerank_outcome"].results)
        # 1. 模型输入
        request = SpecificationAnswerRequest(
            question=state["question"].strip(),
            rewritten_query=state["rewritten_query"],
            citations=citations,
        )
        try:
            # 2. 模型输出
            raw_output = await self._answer_model.generate(request)
            draft = _parse_answer_draft(raw_output)
            # 3.引用白名单校验
            selected = _select_citations(citations, draft.citation_ids)
        except Exception as error:
            _LOGGER.warning(
                "specification_answer_generation_failed",
                extra={"error_type": type(error).__name__},
            )
            return {
                "result": _safe_result(
                    state,
                    status=SpecificationQaStatus.GENERATION_FAILED,
                    message="规范回答生成失败, 未形成规范结论。",
                )
            }
  
        return {
            "result": SpecificationQaResult(
                status=SpecificationQaStatus.ANSWERED,
                question=state["question"].strip(),
                rewritten_query=state["rewritten_query"],
                answer=draft.answer,
                citations=selected,
                rerank_degraded=False,
            )
        }
    # 安全回答函数
    async def safe_answer(self, state: _SpecificationQaState) -> dict[str, object]:
        """无结果或重排不可用时返回不含规范结论和引用的固定回答。"""
        # 重排服务超时或降级处理
        if state["rerank_outcome"].degraded:
            return {
                "result": _safe_result(
                    state,
                    status=SpecificationQaStatus.RERANK_UNAVAILABLE,
                    message="重排服务暂时不可用, 当前无法可靠形成规范结论。",
                )
            }
        # 没有足够相关的规范处理
        return {
            "result": _safe_result(
                state,
                status=SpecificationQaStatus.INSUFFICIENT_CONTEXT,
                message="未检索到足够相关的现行规范, 暂时无法给出规范结论。",
            )
        }

# 路由入口
class SpecificationSkill:
    """只接受已通过确定性门禁的SPEC_QA路由决策。"""

    def __init__(self, workflow: SpecificationQaWorkflow) -> None:
        self._workflow = workflow

    async def execute(
        self,
        decision: RoutingDecision,
        *,
        question: str,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> SpecificationQaResult:
        """校验Skill映射后执行固定规范问答图。"""
        # 检查路由决策是否符合要求
        if (
            not decision.can_dispatch 
            or decision.intent is not Intent.SPEC_QA
            or skill_for_intent(decision.intent) is not BusinessSkill.SPECIFICATION
        ):
            raise SpecificationSkillDispatchError(
                "routing decision cannot dispatch to SpecificationSkill"
            )
        return await self._workflow.ainvoke(
            question,
            effective_at=effective_at,
            permission_scope=permission_scope,
            page_context=page_context,
        )


# 查询改写函数 (暂时没有模型改写, 而是确定性规范化处理)
def rewrite_specification_query(question: str) -> str:
    """保留原问题语义, 仅统一Unicode、首尾和连续空白。"""

    if not isinstance(question, str):
        raise SpecificationQaValidationError("question must be text")
    rewritten = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", question)).strip()
    if not rewritten or len(rewritten) > 2000:
        raise SpecificationQaValidationError("question must contain 1 to 2000 characters")
    return rewritten

# 元数据构造函数
def build_specification_metadata(
    *,
    effective_at: date,  # 有效日期
    permission_scope: PermissionScope,  # 权限范围
    page_context: PageContext | None,  #  当前只用于收窄候选
) -> KnowledgeSearchFilter:
    """权限和日期必须显式提供, 页面字段只用于可选收窄。"""

    return KnowledgeSearchFilter(
        product_type=page_context.product_type if page_context else None,
        satellite_type=page_context.satellite_type if page_context else None,
        effective_at=effective_at,
        permission_scope=permission_scope,
    )


def _parse_answer_draft(raw_output: object) -> SpecificationAnswerDraft:
    try:
        if isinstance(raw_output, (str, bytes, bytearray)):
            return SpecificationAnswerDraft.model_validate_json(raw_output)
        return SpecificationAnswerDraft.model_validate(raw_output)
    except ValidationError as error:
        raise SpecificationQaValidationError(
            "specification answer schema validation failed"
        ) from error

# 引用白名单校验函数
def _select_citations(
    citations: tuple[Citation, ...],
    citation_ids: tuple[str, ...],
) -> tuple[Citation, ...]:
    if len(set(citation_ids)) != len(citation_ids):
        raise SpecificationQaValidationError("answer contains duplicate citation identity")
    citations_by_id = {citation.chunk_id: citation for citation in citations}
    if any(citation_id not in citations_by_id for citation_id in citation_ids):
        raise SpecificationQaValidationError("answer references unknown citation identity")
    return tuple(citations_by_id[citation_id] for citation_id in citation_ids)

# 安全结果的统一构造函数
def _safe_result(
    state: _SpecificationQaState,
    *,
    status: SpecificationQaStatus,
    message: str,
) -> SpecificationQaResult:
    return SpecificationQaResult(
        status=status,
        question=state["question"].strip(),
        rewritten_query=state["rewritten_query"],
        answer=message,
        citations=(),
        rerank_degraded=status is SpecificationQaStatus.RERANK_UNAVAILABLE,
    )
