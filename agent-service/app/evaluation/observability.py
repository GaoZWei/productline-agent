"""M7.9异常观测评测契约和三项稳定指标。"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ObservabilityCaseIdentifier = Annotated[
    str,
    Field(min_length=7, max_length=7, pattern=r"^obs-[0-9]{3}$"),
]
StableErrorType = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
StableStepName = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
ObservabilityCount = Annotated[int, Field(ge=0, le=2_147_483_647)]


class _ObservabilityEvaluationSchema(BaseModel):
    """异常观测评测数据禁止额外字段、隐式转换和加载后修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 保存一条异常场景的观测结果
class ObservabilityEvaluationOutcome(_ObservabilityEvaluationSchema):
    """一个异常场景留下的稳定错误类型、步骤定位和排查耗时。"""

    case_id: ObservabilityCaseIdentifier
    expected_error_type: StableErrorType
    observed_error_type: StableErrorType | None = None
    expected_error_step: StableStepName | None = None
    located_error_step: StableStepName | None = None
    troubleshooting_duration_ms: ObservabilityCount | None = None
    # Step 定位约束验证
    @model_validator(mode="after")
    def reject_unscored_step_location(self) -> Self:
        """没有预期步骤的场景不得提交无法评分的定位结果。"""

        if self.expected_error_step is None and self.located_error_step is not None:
            raise ValueError("located error step requires an expected error step")
        return self


class ObservabilityEvaluationReport(_ObservabilityEvaluationSchema):
    """异常可定位性、错误分类和排查时长指标。"""

    total_cases: Annotated[int, Field(gt=0)]
    step_location_evaluated_cases: ObservabilityCount
    correctly_located_steps: ObservabilityCount
    exception_step_locatable_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    correctly_identified_error_types: ObservabilityCount
    error_type_identification_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]
    troubleshooting_timed_cases: ObservabilityCount
    median_troubleshooting_duration_ms: Annotated[float, Field(ge=0.0)]


class ObservabilityEvaluationDataError(ValueError):
    """异常观测评测集合不满足稳定聚合契约。"""


def _rate(numerator: int, denominator: int) -> float:
    """无适用观测时返回稳定零值。"""

    return numerator / denominator if denominator else 0.0


# 异常观测评测指标计算函数
def evaluate_observability_metrics(
    outcomes: Sequence[ObservabilityEvaluationOutcome],
) -> ObservabilityEvaluationReport:
    """校验固定异常观测并计算步骤、错误类型和排查时长指标。"""

    fixed_outcomes = tuple(outcomes)
    if not fixed_outcomes:
        raise ObservabilityEvaluationDataError(
            "observability evaluation requires at least one outcome"
        )
    if len({outcome.case_id for outcome in fixed_outcomes}) != len(fixed_outcomes):
        raise ObservabilityEvaluationDataError(
            "observability evaluation outcomes contain duplicate ids"
        )

    step_outcomes = tuple(
        outcome
        for outcome in fixed_outcomes
        if outcome.expected_error_step is not None # 只有定义了预期 Step 的异常进入分母
    )
    correctly_located_steps = sum(
        outcome.located_error_step == outcome.expected_error_step
        for outcome in step_outcomes
    )
    correctly_identified_error_types = sum(
        outcome.observed_error_type == outcome.expected_error_type # 成功条件是类型匹配
        for outcome in fixed_outcomes
    )
    # 问题排查中位时长 10、20、30、100 => (20 + 30) / 2 = 25ms
    durations = tuple(
        outcome.troubleshooting_duration_ms
        for outcome in fixed_outcomes
        if outcome.troubleshooting_duration_ms is not None
    )

    return ObservabilityEvaluationReport(
        total_cases=len(fixed_outcomes),
        step_location_evaluated_cases=len(step_outcomes),
        correctly_located_steps=correctly_located_steps,
        exception_step_locatable_rate=_rate(
            correctly_located_steps,
            len(step_outcomes),
        ),
        correctly_identified_error_types=correctly_identified_error_types,
        error_type_identification_accuracy=(
            correctly_identified_error_types / len(fixed_outcomes)
        ),
        troubleshooting_timed_cases=len(durations),
        median_troubleshooting_duration_ms=(
            float(median(durations)) if durations else 0.0
        ),
    )
