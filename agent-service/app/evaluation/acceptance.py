"""诊断与Approval验收共享的最小结果和成功率聚合。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AcceptanceCaseIdentifier = Annotated[
    str,
    Field(min_length=5, max_length=64, pattern=r"^[a-z][a-z0-9_-]*-[0-9]{3}$"),
]
StableFailureCode = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


class _AcceptanceSchema(BaseModel):
    """验收结果禁止额外字段、隐式转换和加载后修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 诊断和Approval成功率聚合
class AcceptanceEvaluationOutcome(_AcceptanceSchema):
    """一条E2E或安全边界用例的最小非敏感结果。"""

    case_id: AcceptanceCaseIdentifier
    succeeded: bool
    duration_ms: Annotated[int, Field(ge=0, le=2_147_483_647)] | None = None
    error_code: StableFailureCode | None = None

    @model_validator(mode="after")
    def validate_terminal_result(self) -> Self:
        """成功用例不能携带错误码, 失败用例必须可稳定分类。"""

        if self.succeeded and self.error_code is not None:
            raise ValueError("successful acceptance outcome cannot contain an error code")
        if not self.succeeded and self.error_code is None:
            raise ValueError("failed acceptance outcome requires an error code")
        return self


class AcceptanceEvaluationFailure(_AcceptanceSchema):
    """报告只保留失败用例身份和稳定错误码。"""

    case_id: AcceptanceCaseIdentifier
    error_code: StableFailureCode


class AcceptanceEvaluationReport(_AcceptanceSchema):
    """诊断或Approval套件的成功率、耗时和失败摘要。"""

    total_cases: Annotated[int, Field(gt=0)]
    successful_cases: Annotated[int, Field(ge=0)]
    success_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    timed_cases: Annotated[int, Field(ge=0)]
    total_duration_ms: Annotated[int, Field(ge=0)]
    average_duration_ms: Annotated[float, Field(ge=0.0)]
    failures: tuple[AcceptanceEvaluationFailure, ...] = ()


class AcceptanceEvaluationDataError(ValueError):
    """验收结果集合不满足稳定聚合契约。"""


def evaluate_acceptance(
    outcomes: Sequence[AcceptanceEvaluationOutcome],
) -> AcceptanceEvaluationReport:
    """聚合成功率与可选耗时, 不复制业务输入或错误正文。"""

    fixed_outcomes = tuple(outcomes)
    if not fixed_outcomes:
        raise AcceptanceEvaluationDataError(
            "acceptance evaluation requires at least one outcome"
        )
    if len({outcome.case_id for outcome in fixed_outcomes}) != len(fixed_outcomes):
        raise AcceptanceEvaluationDataError(
            "acceptance evaluation outcomes contain duplicate ids"
        )

    successful_cases = sum(outcome.succeeded for outcome in fixed_outcomes)
    durations = tuple(
        outcome.duration_ms
        for outcome in fixed_outcomes
        if outcome.duration_ms is not None
    )
    total_duration_ms = sum(durations)
    failures = tuple(
        AcceptanceEvaluationFailure(
            case_id=outcome.case_id,
            error_code=outcome.error_code,
        )
        for outcome in fixed_outcomes
        if not outcome.succeeded and outcome.error_code is not None
    )
    return AcceptanceEvaluationReport(
        total_cases=len(fixed_outcomes),
        successful_cases=successful_cases,
        success_rate=successful_cases / len(fixed_outcomes),
        timed_cases=len(durations),
        total_duration_ms=total_duration_ms,
        average_duration_ms=(total_duration_ms / len(durations) if durations else 0.0),
        failures=failures,
    )
