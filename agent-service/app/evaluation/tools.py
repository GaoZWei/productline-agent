"""M7.9 Tool评测观测契约和五项稳定指标。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

ToolCaseIdentifier = Annotated[
    str,
    Field(min_length=8, max_length=8, pattern=r"^tool-[0-9]{3}$"),
]


class _ToolEvaluationSchema(BaseModel):
    """Tool评测数据禁止额外字段、隐式转换和加载后修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 一个评测用例最终留下的最小事实
class ToolEvaluationOutcome(_ToolEvaluationSchema):
    """一条Tool评测用例完成后的最小非敏感观测。"""

    case_id: ToolCaseIdentifier # 用例编号
    initial_validation_passed: bool # 模型第一次生成的 Tool 参数是否通过 Schema 校验
    final_call_succeeded: bool # 经过纠正、重试后，Tool 最终是否调用成功
    retry_count: Annotated[int, Field(ge=0)] = 0 # 首次调用之后又重试了几次
    duplicate_call_detected: bool = False # 是否发现重复调用


class ToolEvaluationReport(_ToolEvaluationSchema):
    """Tool五项指标及其可审计计数。"""

    total_cases: Annotated[int, Field(gt=0)]
    initial_validation_passed: Annotated[int, Field(ge=0)]
    initial_validation_pass_rate: Annotated[float, Field(ge=0.0, le=1.0)] # 首次校验通过率： 首次参数合法数 ÷ 总用例数
    initial_validation_failed: Annotated[int, Field(ge=0)]
    corrected_successes: Annotated[int, Field(ge=0)]
    correction_success_rate: Annotated[float, Field(ge=0.0, le=1.0)] # 纠错成功率： 首次失败但最终成功数 ÷ 首次失败数
    final_call_successes: Annotated[int, Field(ge=0)]
    final_valid_call_success_rate: Annotated[float, Field(ge=0.0, le=1.0)] # 最终调用成功率： 最终成功数 ÷ 总用例数
    total_retries: Annotated[int, Field(ge=0)]
    average_retry_count: Annotated[float, Field(ge=0.0)] # 平均重试次数： 总重试次数 ÷ 总用例数
    duplicate_call_cases: Annotated[int, Field(ge=0)]
    duplicate_call_rate: Annotated[float, Field(ge=0.0, le=1.0)] # 重复调用率： 出现重复调用的用例数 ÷ 总用例数


class ToolEvaluationDataError(ValueError):
    """Tool评测观测集合不满足稳定聚合契约。"""


def _rate(numerator: int, denominator: int) -> float:
    """无适用样本时返回稳定零值。"""

    return numerator / denominator if denominator else 0.0

# 核心指标计算函数
def evaluate_tool_metrics(
    outcomes: Sequence[ToolEvaluationOutcome],
) -> ToolEvaluationReport:
    """校验固定观测并计算参数、修正、成功、重试和重复调用指标。"""
    # 把输入快照成不可变元组，避免计算过程中数据变化导致的结果不一致
    fixed_outcomes = tuple(outcomes)
    # 拒绝空数据集，防止生成没有意义的报告
    if not fixed_outcomes:
        raise ToolEvaluationDataError("tool evaluation requires at least one outcome")
    if len({outcome.case_id for outcome in fixed_outcomes}) != len(fixed_outcomes):
        raise ToolEvaluationDataError("tool evaluation outcomes contain duplicate ids")
    # 分别统计首次通过、纠错成功、最终成功、重试次数和重复调用次数
    total_cases = len(fixed_outcomes)
    initial_validation_passed = sum(
        outcome.initial_validation_passed for outcome in fixed_outcomes
    )
    initial_validation_failed = total_cases - initial_validation_passed
    corrected_successes = sum(
        not outcome.initial_validation_passed and outcome.final_call_succeeded
        for outcome in fixed_outcomes
    )
    final_call_successes = sum(outcome.final_call_succeeded for outcome in fixed_outcomes)
    total_retries = sum(outcome.retry_count for outcome in fixed_outcomes)
    duplicate_call_cases = sum(outcome.duplicate_call_detected for outcome in fixed_outcomes)
    # 返回 ToolEvaluationReport 实例
    return ToolEvaluationReport(
        total_cases=total_cases,
        initial_validation_passed=initial_validation_passed,
        initial_validation_pass_rate=initial_validation_passed / total_cases,
        initial_validation_failed=initial_validation_failed,
        corrected_successes=corrected_successes,
        correction_success_rate=_rate(corrected_successes, initial_validation_failed),
        final_call_successes=final_call_successes,
        final_valid_call_success_rate=final_call_successes / total_cases,
        total_retries=total_retries,
        average_retry_count=total_retries / total_cases,
        duplicate_call_cases=duplicate_call_cases,
        duplicate_call_rate=duplicate_call_cases / total_cases,
    )
