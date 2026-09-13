"""把七类领域Subject和观测采集器接到统一EvalRunner。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from app.evaluation.acceptance import (
    AcceptanceEvaluationOutcome,
    AcceptanceEvaluationReport,
    evaluate_acceptance,
)
from app.evaluation.agents import (
    AgentEvaluationOutcome,
    AgentEvaluationReport,
    evaluate_agent_metrics,
)
from app.evaluation.observability import (
    ObservabilityEvaluationOutcome,
    ObservabilityEvaluationReport,
    evaluate_observability_metrics,
)
from app.evaluation.rag import (
    RagEvaluationReport,
    RagEvaluationStrategy,
    RagEvaluationSubject,
    evaluate_rag,
    load_rag_evaluation_cases,
)
from app.evaluation.router import (
    RouterEvaluationReport,
    RouterEvaluationSubject,
    evaluate_router,
    load_router_evaluation_cases,
)
from app.evaluation.runner import EvaluationSuite
from app.evaluation.tools import (
    ToolEvaluationOutcome,
    ToolEvaluationReport,
    evaluate_tool_metrics,
)
# 固定注册七类评测
STANDARD_EVALUATION_SUITE_NAMES = (
    "router",
    "tools",
    "rag",
    "diagnosis",
    "agent_policy",
    "approval",
    "fault_injection",
)

ToolOutcomeProvider = Callable[[], Awaitable[Sequence[ToolEvaluationOutcome]]]
AgentOutcomeProvider = Callable[[], Awaitable[Sequence[AgentEvaluationOutcome]]]
AcceptanceOutcomeProvider = Callable[
    [], Awaitable[Sequence[AcceptanceEvaluationOutcome]]
]
ObservabilityOutcomeProvider = Callable[
    [], Awaitable[Sequence[ObservabilityEvaluationOutcome]]
]

# Router评测
def router_evaluation_suite(
    dataset_path: Path,  # 固定Router数据集路径
    subject: RouterEvaluationSubject,  # 被评测的RouterEvaluationSubject
    *,
    failure_path: Path | None = None,  # 可选失败样本文件路径
) -> EvaluationSuite:
    """加载固定路由集并执行真实或明确标识的替身Subject。"""

    cases = load_router_evaluation_cases(dataset_path)

    async def execute() -> RouterEvaluationReport:
        return await evaluate_router(cases, subject, failure_path=failure_path)

    return EvaluationSuite("router", execute)

# Tool评测 不直接调用某个Tool，而是接收一个Outcome Provider
def tool_evaluation_suite(provider: ToolOutcomeProvider) -> EvaluationSuite:
    """采集Tool门禁与调用结果并复用M7.9指标。"""

    async def execute() -> ToolEvaluationReport:
        return evaluate_tool_metrics(await provider())

    return EvaluationSuite("tools", execute)

# RAG评测 加载固定50条RAG数据集，然后让Subject分别运行
def rag_evaluation_suite(
    dataset_path: Path,
    subject: RagEvaluationSubject,
    *,
    strategies: Sequence[RagEvaluationStrategy] | None = None,
    failure_path: Path | None = None,
) -> EvaluationSuite:
    """加载固定RAG集并运行显式选择的检索策略。"""

    cases = load_rag_evaluation_cases(dataset_path)

    async def execute() -> RagEvaluationReport:
        if strategies is None:
            return await evaluate_rag(cases, subject, failure_path=failure_path)
        return await evaluate_rag(
            cases, subject, strategies=strategies, failure_path=failure_path
        )

    return EvaluationSuite("rag", execute)

# Diagnosis评测 聚合诊断E2E成功率、耗时和错误码
def diagnosis_evaluation_suite(provider: AcceptanceOutcomeProvider) -> EvaluationSuite:
    """聚合诊断E2E成功率、耗时和稳定失败码。"""

    async def execute() -> AcceptanceEvaluationReport:
        return evaluate_acceptance(await provider())

    return EvaluationSuite("diagnosis", execute)

# Agent Policy评测 计算Agent成功率、Tool调用次数、无效调用和重复调用
def agent_policy_evaluation_suite(provider: AgentOutcomeProvider) -> EvaluationSuite:
    """聚合Agent动作有效性、重复调用和执行预算结果。"""

    async def execute() -> AgentEvaluationReport:
        return evaluate_agent_metrics(await provider())

    return EvaluationSuite("agent_policy", execute)

# Approval评测 计算确认成功率、过期、并发冲突和写回失败
def approval_evaluation_suite(provider: AcceptanceOutcomeProvider) -> EvaluationSuite:
    """聚合Approval确认、过期、并发和写回安全验收。"""

    async def execute() -> AcceptanceEvaluationReport:
        return evaluate_acceptance(await provider())

    return EvaluationSuite("approval", execute)

# Fault Injection评测 计算错误类型识别率、异常Step定位率和排查耗时
def fault_injection_evaluation_suite(
    provider: ObservabilityOutcomeProvider,
) -> EvaluationSuite:
    """把M7.7固定故障结果转换为异常定位与分类指标。"""

    async def execute() -> ObservabilityEvaluationReport:
        return evaluate_observability_metrics(await provider())

    return EvaluationSuite("fault_injection", execute)


def assert_standard_suite_catalog(suites: Sequence[EvaluationSuite]) -> None:
    """要求标准评测注册表完整且顺序稳定。"""

    names = tuple(suite.name for suite in suites)
    if names != STANDARD_EVALUATION_SUITE_NAMES:
        raise ValueError("standard evaluation suites are incomplete or out of order")

# 组装标准评测注册表
def standard_evaluation_suites(
    *,
    router_dataset_path: Path,
    router_subject: RouterEvaluationSubject,
    tool_outcomes: ToolOutcomeProvider,
    rag_dataset_path: Path,
    rag_subject: RagEvaluationSubject,
    diagnosis_outcomes: AcceptanceOutcomeProvider,
    agent_policy_outcomes: AgentOutcomeProvider,
    approval_outcomes: AcceptanceOutcomeProvider,
    fault_injection_outcomes: ObservabilityOutcomeProvider,
    failure_directory: Path | None = None,
) -> tuple[EvaluationSuite, ...]:
    """按固定顺序组装M7.8七类标准评测入口。"""

    suites = (
        router_evaluation_suite(
            router_dataset_path,
            router_subject,
            failure_path=(failure_directory / "router.jsonl" if failure_directory else None),
        ),
        tool_evaluation_suite(tool_outcomes),
        rag_evaluation_suite(
            rag_dataset_path,
            rag_subject,
            failure_path=(failure_directory / "rag.jsonl" if failure_directory else None),
        ),
        diagnosis_evaluation_suite(diagnosis_outcomes),
        agent_policy_evaluation_suite(agent_policy_outcomes),
        approval_evaluation_suite(approval_outcomes),
        fault_injection_evaluation_suite(fault_injection_outcomes),
    )
    assert_standard_suite_catalog(suites)
    return suites
