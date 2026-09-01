"""从当前进程配置和真实 Tool 契约构建 Run 版本快照。"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from app.knowledge.hybrid import RRF_RANK_CONSTANT
from app.knowledge.reranking import (
    DEFAULT_MIN_RELEVANCE_SCORE,
    DEFAULT_RERANK_TIMEOUT_SECONDS,
)
from app.knowledge.retrieval import (
    DEFAULT_CHANNEL_TOP_K,
    DEFAULT_HYBRID_TOP_K,
    DEFAULT_MIN_VECTOR_SIMILARITY,
)
from app.model_adapters import (
    RERANK_PROMPT_VERSION,
    REVIEW_DRAFT_PROMPT_VERSION,
    SPECIFICATION_ANSWER_PROMPT_VERSION,
)
from app.routing.prompt import ROUTER_PROMPT_VERSION
from app.schemas.versioning import (
    ModelRuntimeSnapshot,
    RagStrategySnapshot,
    RunVersionSnapshot,
    ToolSchemaSnapshot,
    VersionCaptureStatus,
)
from app.settings import Settings
from app.tools import ToolRegistry
from app.workflows.action_prompt import ACTION_DECISION_PROMPT_VERSION

TOOL_SCHEMA_VERSION: Final = "read-tool-schema-v1"
RAG_STRATEGY_VERSION: Final = "hybrid-rrf-rerank-v2"


# 完整快照生成函数
def build_run_version_snapshot(
    settings: Settings,
    registry: ToolRegistry,
) -> RunVersionSnapshot:
    """冻结一次进程级版本视图, 供该进程创建的每个 Run 复用。"""

    return RunVersionSnapshot(
        capture_status=VersionCaptureStatus.CAPTURED,
        router_prompt_version=ROUTER_PROMPT_VERSION,  # Router Prompt版本
        agent_prompt_version=ACTION_DECISION_PROMPT_VERSION,  # Agent Prompt版本
        model=_model_snapshot(settings),  # 模型运行时参数
        tool_schema=_tool_schema_snapshot(registry),  # Tool Schema版本
        rag_strategy=RagStrategySnapshot(  # RAG 策略版本
            version=RAG_STRATEGY_VERSION,
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            embedding_index_version=settings.embedding_index_version,
            parameters={
                "embedding_dimension": settings.embedding_dimension,
                "channel_top_k": DEFAULT_CHANNEL_TOP_K,
                "hybrid_top_k": DEFAULT_HYBRID_TOP_K,
                "min_vector_similarity": DEFAULT_MIN_VECTOR_SIMILARITY,
                "rrf_rank_constant": RRF_RANK_CONSTANT,
                "rerank_timeout_seconds": DEFAULT_RERANK_TIMEOUT_SECONDS,
                "min_relevance_score": DEFAULT_MIN_RELEVANCE_SCORE,
                "rerank_prompt_version": RERANK_PROMPT_VERSION,
                "specification_answer_prompt_version": (SPECIFICATION_ANSWER_PROMPT_VERSION),
            },
        ),
    )


def _model_snapshot(settings: Settings) -> ModelRuntimeSnapshot:
    """只在模型名称已配置时记录有效参数, 避免把默认供应商冒充实际调用。"""
    # 模型未启用时, 记录空配置
    if not settings.model_configured:
        return ModelRuntimeSnapshot(
            configured=False,
            provider=None,
            model_name=None,
            parameters={},
        )
    return ModelRuntimeSnapshot(
        configured=True,
        provider=settings.model_provider,
        model_name=settings.model_name,
        parameters={
            "temperature": settings.model_temperature,
            "max_output_tokens": settings.model_max_output_tokens,
            "timeout_seconds": settings.model_timeout_seconds,
            "max_retries": settings.model_max_retries,
            "initial_backoff_seconds": settings.model_initial_backoff_seconds,
            "max_backoff_seconds": settings.model_max_backoff_seconds,
            "review_draft_prompt_version": REVIEW_DRAFT_PROMPT_VERSION,
        },
    )


# Tool Schema 版本快照生成函数
def _tool_schema_snapshot(registry: ToolRegistry) -> ToolSchemaSnapshot:
    """对排序后的真实输入/输出 Schema 与安全元数据计算稳定 SHA-256。"""

    contracts: list[dict[str, object]] = []
    for name in registry.names:  # registry.names 本身按名称排序
        tool = registry.get(name)
        # 每个tool提取输入输出schema和风险等级
        contracts.append(
            {
                "name": tool.name,
                "input_schema": tool.input_model.model_json_schema(mode="validation"),
                "output_schema": tool.output_model.model_json_schema(mode="validation"),
                "risk_level": tool.risk_level.value,
                "required_permissions": sorted(tool.required_permissions),
            }
        )
    # 对所有tool的schema进行排序, 确保一致的哈希结果
    serialized = json.dumps(
        contracts,
        ensure_ascii=False,
        sort_keys=True,  # JSON字段使用 sort_keys=True 排序
        separators=(",", ":"),
    ).encode()
    return ToolSchemaSnapshot(
        version=TOOL_SCHEMA_VERSION,
        digest=hashlib.sha256(serialized).hexdigest(),  # Tool Schema哈希值
        tool_names=registry.names,
    )
