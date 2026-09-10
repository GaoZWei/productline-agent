"""M7.9 Agent执行观测契约和六项稳定指标。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.workflow import BlockingStage

AgentCaseIdentifier = Annotated[
    str,
    Field(min_length=9, max_length=9, pattern=r"^agent-[0-9]{3}$"),
]
AgentCount = Annotated[int, Field(ge=0, le=2_147_483_647)]


class _AgentEvaluationSchema(BaseModel):
    """Agent评测数据禁止额外字段、隐式转换和加载后修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 一条 Agent 评测用例的最小执行事实
class AgentEvaluationOutcome(_AgentEvaluationSchema):
    """一条Agent用例执行后用于聚合的最小非敏感事实。"""

    case_id: AgentCaseIdentifier
    e2e_succeeded: bool # 表示整条 Agent 链路是否满足该用例的预期，不只是接口是否返回 HTTP 200
    executed_tool_calls: AgentCount = 0 # Tool 调用次数
    total_tool_call_attempts: AgentCount = 0 # Tool 调用尝试次数
    invalid_tool_call_attempts: AgentCount = 0 # 无效 Tool 调用尝试次数
    duplicate_tool_call_attempts: AgentCount = 0 # 重复 Tool 调用尝试次数
    diagnosis_duration_ms: AgentCount | None = None # 诊断用例耗时，单位毫秒
    expected_blocking_stage: BlockingStage | None = None # 阻塞阶段
    actual_blocking_stage: BlockingStage | None = None # 实际阻塞阶段
    # Outcome 一致性校验
    @model_validator(mode="after")
    def validate_tool_and_stage_observations(self) -> Self:
        """Tool尝试必须完整分类; 非诊断用例不得伪造实际阻塞阶段。"""
        # 防止采集代码漏记一次调用，或者让同一次调用同时算作“无效”和“重复”
        categorized_attempts = (
            self.executed_tool_calls # 执行失败的 Tool 仍属于 executed_tool_calls
            + self.invalid_tool_call_attempts
            + self.duplicate_tool_call_attempts
        )
        if categorized_attempts != self.total_tool_call_attempts:
            raise ValueError("tool call attempts must equal categorized attempt counts")
        if self.expected_blocking_stage is None and self.actual_blocking_stage is not None:
            raise ValueError("actual blocking stage requires an expected blocking stage")
        return self

# 保存所有指标的分子、分母和结果
class AgentEvaluationReport(_AgentEvaluationSchema):
    """Agent六项指标及可审计分子、分母和总量。"""

    total_cases: Annotated[int, Field(gt=0)]
    e2e_successes: AgentCount
    e2e_success_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    total_executed_tool_calls: AgentCount
    average_tool_call_count: Annotated[float, Field(ge=0.0)]
    total_tool_call_attempts: AgentCount
    invalid_tool_call_attempts: AgentCount
    invalid_tool_call_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    duplicate_tool_call_attempts: AgentCount
    duplicate_tool_call_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    diagnosis_timed_cases: AgentCount
    total_diagnosis_duration_ms: AgentCount
    average_diagnosis_duration_ms: Annotated[float, Field(ge=0.0)]
    blocking_stage_evaluated_cases: AgentCount
    blocking_stage_correct_cases: AgentCount
    blocking_stage_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]


class AgentEvaluationDataError(ValueError):
    """Agent评测观测集合不满足稳定聚合契约。"""


def _rate(numerator: int, denominator: int) -> float:
    """无适用观测时返回稳定零值。"""

    return numerator / denominator if denominator else 0.0

# Agent 指标计算函数
def evaluate_agent_metrics(
    outcomes: Sequence[AgentEvaluationOutcome],
) -> AgentEvaluationReport:
    """校验固定观测并计算成功、Tool、耗时与阻塞阶段指标。"""
    # 固定输入校验
    fixed_outcomes = tuple(outcomes)
    if not fixed_outcomes:
        raise AgentEvaluationDataError("agent evaluation requires at least one outcome")
    if len({outcome.case_id for outcome in fixed_outcomes}) != len(fixed_outcomes):
        raise AgentEvaluationDataError("agent evaluation outcomes contain duplicate ids")
    # 计算指标
    total_cases = len(fixed_outcomes)
    e2e_successes = sum(outcome.e2e_succeeded for outcome in fixed_outcomes)
    total_executed_tool_calls = sum(
        outcome.executed_tool_calls for outcome in fixed_outcomes
    )
    total_tool_call_attempts = sum(
        outcome.total_tool_call_attempts for outcome in fixed_outcomes
    )
    invalid_tool_call_attempts = sum(
        outcome.invalid_tool_call_attempts for outcome in fixed_outcomes
    )
    duplicate_tool_call_attempts = sum(
        outcome.duplicate_tool_call_attempts for outcome in fixed_outcomes
    )
    durations = tuple(
        outcome.diagnosis_duration_ms
        for outcome in fixed_outcomes
        if outcome.diagnosis_duration_ms is not None
    )
    total_diagnosis_duration_ms = sum(durations)
    stage_outcomes = tuple(
        outcome
        for outcome in fixed_outcomes
        if outcome.expected_blocking_stage is not None
    )
    blocking_stage_correct_cases = sum(
        outcome.actual_blocking_stage is outcome.expected_blocking_stage
        for outcome in stage_outcomes
    )

    return AgentEvaluationReport(
        total_cases=total_cases,
        e2e_successes=e2e_successes,
        e2e_success_rate=e2e_successes / total_cases, # E2E成功率 = 成功用例数 ÷ 全部用例数
        total_executed_tool_calls=total_executed_tool_calls,
        average_tool_call_count=total_executed_tool_calls / total_cases, # 平均Tool调用数 = 已执行Tool调用总数 ÷ 全部用例数
        total_tool_call_attempts=total_tool_call_attempts,
        invalid_tool_call_attempts=invalid_tool_call_attempts,
        invalid_tool_call_rate=_rate(
            invalid_tool_call_attempts,
            total_tool_call_attempts,
        ), # 无效Tool调用率 = 参数无效尝试数 ÷ 全部Tool尝试数
        duplicate_tool_call_attempts=duplicate_tool_call_attempts,
        duplicate_tool_call_rate=_rate(
            duplicate_tool_call_attempts,
            total_tool_call_attempts,
        ), # 重复Tool调用率 = 重复拒绝尝试数 ÷ 全部Tool尝试数
        diagnosis_timed_cases=len(durations),
        total_diagnosis_duration_ms=total_diagnosis_duration_ms,
        average_diagnosis_duration_ms=_rate(
            total_diagnosis_duration_ms,
            len(durations),
        ), # 平均诊断耗时 = 诊断耗时总和 ÷ 有计时的诊断用例数
        blocking_stage_evaluated_cases=len(stage_outcomes),
        blocking_stage_correct_cases=blocking_stage_correct_cases,
        blocking_stage_accuracy=_rate(
            blocking_stage_correct_cases,
            len(stage_outcomes),
        ), # 阻塞阶段正确率 = actual_blocking_stage与expected_blocking_stage相等的数量 ÷ 有预期阶段的用例数
    )
