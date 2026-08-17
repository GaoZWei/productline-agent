"""M3.7 路由评测数据契约、执行器、指标和安全失败样本。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.routing.intent_catalog import (
    Intent,
    required_parameters_for,
    skill_for_intent,
)
from app.schemas.context import PageContext
from app.schemas.routing import (
    ClarificationReason,
    RouterEntities,
    RoutingDecisionStatus,
)
from app.schemas.session import SessionContext


# 数据集固定覆盖八类情况
class RouterEvaluationCategory(StrEnum):
    """M3.7 固定数据集覆盖的八类路由场景。"""

    EXPLICIT_INTENT = "EXPLICIT_INTENT"  # 明确意图
    PARAPHRASE = "PARAPHRASE"  # 同义表达
    PAGE_REFERENCE = "PAGE_REFERENCE"  # 页面指代
    SESSION_REFERENCE = "SESSION_REFERENCE"  # 会话指代
    MISSING_PARAMETER = "MISSING_PARAMETER"  # 参数缺失
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"  # 多个候选意图
    INTENT_CONFUSION = "INTENT_CONFUSION"  # 意图混淆
    UNRELATED = "UNRELATED"  # 无关问题


EXPECTED_CATEGORY_COUNTS: Final[dict[RouterEvaluationCategory, int]] = {
    RouterEvaluationCategory.EXPLICIT_INTENT: 15,
    RouterEvaluationCategory.PARAPHRASE: 10,
    RouterEvaluationCategory.PAGE_REFERENCE: 10,
    RouterEvaluationCategory.SESSION_REFERENCE: 5,
    RouterEvaluationCategory.MISSING_PARAMETER: 8,
    RouterEvaluationCategory.MULTIPLE_CANDIDATES: 5,
    RouterEvaluationCategory.INTENT_CONFUSION: 4,
    RouterEvaluationCategory.UNRELATED: 3,
}

EvaluationCategoryValue = Annotated[RouterEvaluationCategory, Field(strict=False)]
IntentValue = Annotated[Intent, Field(strict=False)]
DecisionStatusValue = Annotated[RoutingDecisionStatus, Field(strict=False)]
ClarificationReasonValue = Annotated[ClarificationReason, Field(strict=False)]
CaseIdentifier = Annotated[
    str,
    Field(min_length=10, max_length=10, pattern=r"^router-[0-9]{3}$"),
]


class EvaluationSchema(BaseModel):
    """评测数据禁止额外字段和隐式标量转换。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class RouterEvaluationCase(EvaluationSchema):
    """一条不包含模型预测的固定路由期望用例。"""

    case_id: CaseIdentifier
    category: EvaluationCategoryValue
    user_message: Annotated[str, Field(min_length=1, max_length=2000)]
    page_context: PageContext | None = None
    session_context: SessionContext | None = None
    expected_intent: IntentValue
    expected_entities: RouterEntities
    expected_status: DecisionStatusValue
    expected_clarification_reason: ClarificationReasonValue | None = None

    # 标准答案还需要校验决策原因
    @model_validator(mode="after")
    def validate_expected_decision(self) -> Self:
        """保证固定期望本身不违反现有意图和分发门禁。"""

        if self.expected_status is RoutingDecisionStatus.READY:
            # READY不能同时要求澄清.
            if self.expected_clarification_reason is not None:
                raise ValueError("ready evaluation case cannot expect clarification")
            # READY意图必须有映射的业务Skill.
            if skill_for_intent(self.expected_intent) is None:
                raise ValueError("ready evaluation case requires a mapped intent")
            # READY的必填参数必须完整.
            if any(
                not self.expected_entities.contains(parameter)
                for parameter in required_parameters_for(self.expected_intent)
            ):
                raise ValueError("ready evaluation case requires complete parameters")
        # 如果不是READY, 必须提供澄清原因.
        elif self.expected_clarification_reason is None:
            raise ValueError("pending evaluation case requires clarification reason")
        # 如果意图是UNKNOWN, 澄清原因必须是UNKNOWN_INTENT.
        if (
            self.expected_intent is Intent.UNKNOWN
            and self.expected_clarification_reason
            is not ClarificationReason.UNKNOWN_INTENT
        ):
            raise ValueError("UNKNOWN evaluation case requires UNKNOWN clarification")
        return self

# 预测结果契约表示整个路由链路的最终输出, 而不只是模型的原始输出.
class RouterEvaluationPrediction(EvaluationSchema):
    """被测路由器对一条固定用例产出的最终预测。"""

    case_id: CaseIdentifier
    intent: IntentValue
    entities: RouterEntities
    status: DecisionStatusValue
    clarification_reason: ClarificationReasonValue | None = None

# Subject 可以理解成“被考试的路由系统”
class RouterEvaluationSubject(Protocol):
    """真实模型、离线回放或测试替身均可实现的评测边界。"""

    def predict(
        self,
        case: RouterEvaluationCase,
    ) -> Awaitable[RouterEvaluationPrediction]:
        """对单条固定用例返回最终路由预测。"""


class EvaluationFailureType(StrEnum):
    """失败样本中允许记录的稳定差异类型。"""

    INTENT = "INTENT"
    PARAMETERS = "PARAMETERS"
    STATUS = "STATUS"
    CLARIFICATION = "CLARIFICATION"


FailureTypeValue = Annotated[EvaluationFailureType, Field(strict=False)]


class RouterEvaluationFailure(EvaluationSchema):
    """不保存用户消息和上下文的安全失败样本。"""

    case_id: CaseIdentifier
    category: EvaluationCategoryValue
    failure_types: tuple[FailureTypeValue, ...]
    expected_intent: IntentValue
    predicted_intent: IntentValue
    expected_entities: RouterEntities
    predicted_entities: RouterEntities
    expected_status: DecisionStatusValue
    predicted_status: DecisionStatusValue
    expected_clarification_reason: ClarificationReasonValue | None = None
    predicted_clarification_reason: ClarificationReasonValue | None = None


class RouterEvaluationReport(EvaluationSchema):
    """一次路由评测的可重复聚合指标和混淆矩阵。"""

    total_cases: Annotated[int, Field(gt=0)]
    intent_correct: Annotated[int, Field(ge=0)]
    parameters_complete: Annotated[int, Field(ge=0)]
    intent_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]
    parameter_completeness: Annotated[float, Field(ge=0.0, le=1.0)]
    confusion_matrix: dict[IntentValue, dict[IntentValue, int]]
    failures: tuple[RouterEvaluationFailure, ...] = ()


class RouterEvaluationDataError(ValueError):
    """评测数据或Subject响应不满足稳定契约。"""

# 数据加载过程
def load_router_evaluation_cases(
    path: Path,
    *,
    enforce_planned_distribution: bool = True,
) -> tuple[RouterEvaluationCase, ...]:
    """逐行加载JSONL数据, 错误信息只暴露行号或重复ID。"""
    # 1. 读取文件
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    # 文件读取失败时, 统一转换成RouterEvaluationDataError.
    except OSError as exc:
        raise RouterEvaluationDataError("router evaluation dataset is unavailable") from exc

    cases: list[RouterEvaluationCase] = []
    seen_ids: set[str] = set()
    # 2. 逐行解析
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = RouterEvaluationCase.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise RouterEvaluationDataError(
                f"invalid router evaluation case at line {line_number}"
            ) from exc
        # 3. 检查重复ID
        if case.case_id in seen_ids:
            raise RouterEvaluationDataError(f"duplicate case_id: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise RouterEvaluationDataError("router evaluation dataset is empty")
    if enforce_planned_distribution: # 4. 检查数据分布是否符合预期
        counts = Counter(case.category for case in cases)
        if counts != Counter(EXPECTED_CATEGORY_COUNTS):
            raise RouterEvaluationDataError(
                "router evaluation dataset does not match planned category distribution"
            )
    return tuple(cases)


def _entity_values(entities: RouterEntities) -> dict[str, object]:
    """生成用于严格参数比较的稳定非空实体字典。"""

    return entities.model_dump(mode="json", exclude_none=True)


def _failure_types(
    case: RouterEvaluationCase,
    prediction: RouterEvaluationPrediction,
) -> tuple[EvaluationFailureType, ...]:
    """按固定顺序计算一条预测的全部差异。"""

    failures: list[EvaluationFailureType] = []
    if prediction.intent is not case.expected_intent:
        failures.append(EvaluationFailureType.INTENT)
    if _entity_values(prediction.entities) != _entity_values(case.expected_entities):
        failures.append(EvaluationFailureType.PARAMETERS)
    if prediction.status is not case.expected_status:
        failures.append(EvaluationFailureType.STATUS)
    if prediction.clarification_reason is not case.expected_clarification_reason:
        failures.append(EvaluationFailureType.CLARIFICATION)
    return tuple(failures)


def _empty_confusion_matrix() -> dict[Intent, dict[Intent, int]]:
    """创建包含全部已知意图行列的稳定零矩阵。"""

    return {
        expected: {predicted: 0 for predicted in Intent}
        for expected in Intent
    }


def _write_failure_samples(
    path: Path,
    failures: Sequence[RouterEvaluationFailure],
) -> None:
    """以固定顺序写入不含消息和上下文的JSONL失败样本。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        f"{failure.model_dump_json()}\n" for failure in failures
    )
    path.write_text(content, encoding="utf-8")

# 核心评测算法
async def evaluate_router(
    cases: Sequence[RouterEvaluationCase],
    subject: RouterEvaluationSubject,
    *,
    failure_path: Path | None = None,
) -> RouterEvaluationReport:
    """顺序执行固定用例并计算意图准确率、参数完整率和混淆矩阵。"""
    # 1. 空用例和重复ID直接失败    
    if not cases:
        raise RouterEvaluationDataError("router evaluation requires at least one case")
    if len({case.case_id for case in cases}) != len(cases):
        raise RouterEvaluationDataError("router evaluation cases contain duplicate ids")

    intent_correct = 0
    parameters_complete = 0
    confusion_matrix = _empty_confusion_matrix()
    failures: list[RouterEvaluationFailure] = []
    # 2. 逐条调用Subject预测
    for case in cases:
        prediction = await subject.predict(case)
        # 3. 检查预测ID是否匹配
        if prediction.case_id != case.case_id:
            raise RouterEvaluationDataError(
                f"prediction case_id mismatch for {case.case_id}"
            )
        # 4. 每条预测先进入混淆矩阵
        confusion_matrix[case.expected_intent][prediction.intent] += 1
        if prediction.intent is case.expected_intent:
            intent_correct += 1
        # 5. 检查参数是否完整
        if _entity_values(prediction.entities) == _entity_values(
            case.expected_entities
        ):
            parameters_complete += 1
        failure_types = _failure_types(case, prediction)
        if failure_types:
            failures.append(
                RouterEvaluationFailure(
                    case_id=case.case_id,
                    category=case.category,
                    failure_types=failure_types,
                    expected_intent=case.expected_intent,
                    predicted_intent=prediction.intent,
                    expected_entities=case.expected_entities,
                    predicted_entities=prediction.entities,
                    expected_status=case.expected_status,
                    predicted_status=prediction.status,
                    expected_clarification_reason=(
                        case.expected_clarification_reason
                    ),
                    predicted_clarification_reason=(
                        prediction.clarification_reason
                    ),
                )
            )

    if failure_path is not None:
        _write_failure_samples(failure_path, failures)
    total_cases = len(cases)
    return RouterEvaluationReport(
        total_cases=total_cases,
        intent_correct=intent_correct,
        parameters_complete=parameters_complete,
        intent_accuracy=intent_correct / total_cases,
        parameter_completeness=parameters_complete / total_cases,
        confusion_matrix=confusion_matrix,
        failures=tuple(failures),
    )
