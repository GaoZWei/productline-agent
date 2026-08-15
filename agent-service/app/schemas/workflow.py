"""确定性订单诊断Workflow的状态通道和结构化结果契约。"""

from enum import StrEnum
from typing import Annotated, Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.errors import ToolErrorCode
from app.schemas.context import PageContext
from app.schemas.tools import (
    DeliveryStatus,
    OrderDetail,
    OrderIdentifier,
    ProgressResult,
    QualityIssue,
    ReviewResult,
    TaskDetail,
)

# 稳定机器代码类型, 用于唯一标识Workflow节点、根因、Tool字段等。
StableCode = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
# 用于根因、建议和错误说明的文本类型。
WorkflowText = Annotated[str, Field(min_length=1, max_length=2048)]
# 只接受稳定的Python风格步骤名
StepName = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
]
TraceIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
EvidenceFieldPath = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[A-Za-z_][A-Za-z0-9_.\[\]-]*$"),
]
EvidenceTextValue = Annotated[str, Field(max_length=2048)]
type EvidenceValue = EvidenceTextValue | int | float | bool | None
# 要求Evidence中的tool_name只能是已经实现的七个只读Tool
ReadToolName = Literal[
    "get_order_detail",
    "get_related_tasks",
    "get_task_detail",
    "get_production_progress",
    "get_quality_issues",
    "get_review_result",
    "get_delivery_status",
]

# 统一阻塞阶段枚举
class BlockingStage(StrEnum):
    """限定确定性诊断可以输出的稳定阻塞阶段。"""

    PRODUCTION = "PRODUCTION"  # 还在正常生产, 并非异常情况
    PRODUCTION_BLOCKED = "PRODUCTION_BLOCKED"  # 生产任务或生产步骤失败、阻塞
    QUALITY_REVIEW = "QUALITY_REVIEW"  # 存在未处理完的质检问题
    REVIEW = "REVIEW"  # 质检问题已处理, 但复核没有通过
    DELIVERY = "DELIVERY"  # 上游完成, 但交付还未就绪、失败或阻塞
    NONE = "NONE"  # 当前没有阻塞, 不代表一定已经交付
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"  # 事实不完整, 不能可靠诊断

# 公共父类, 为Workflow内部结果提供严格、不可变且禁止额外字段的共同配置。
class WorkflowSchema(BaseModel):
    """为Workflow内部结果提供严格、不可变且禁止额外字段的共同配置。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 稳定根因
class RootCause(WorkflowSchema):
    """描述由确定性规则识别出的一个稳定根因。"""

    code: StableCode
    description: WorkflowText

# 诊断依据(有价值的)
class Evidence(WorkflowSchema):
    """把一条诊断依据定位到具体只读Tool及其单个响应字段。"""

    source_type: Literal["TOOL"]  # 当前只能是"TOOL", 模型自己的判断, 不能直接成为业务事实证据
    tool_name: ReadToolName
    field_path: EvidenceFieldPath  # 这条结论具体来自Tool结果中的哪个字段
    value: EvidenceValue  # 只允许标量值
    description: WorkflowText

# 建议
class Suggestion(WorkflowSchema):
    """描述一个建议动作; 本阶段只生成建议, 不代表已经执行写操作。"""

    action_type: StableCode
    description: WorkflowText


class NarrativeRootCause(WorkflowSchema):
    """模型可改写的根因文案, 稳定代码必须与规则结果一致。"""

    code: StableCode
    description: WorkflowText


class NarrativeSuggestion(WorkflowSchema):
    """模型可改写的建议文案, 动作类型必须与规则结果一致。"""

    action_type: StableCode
    description: WorkflowText


class DiagnosisNarrative(WorkflowSchema):
    """限制模型只返回说明文字及其对应的稳定代码。"""

    summary: WorkflowText
    root_causes: list[NarrativeRootCause]
    suggestions: Annotated[list[NarrativeSuggestion], Field(min_length=1)]


# 未来某个Tool节点失败时, 可以写入StepError
class StepError(WorkflowSchema):
    """保存Workflow分支所需的安全错误字段, 不承载原始响应或异常堆栈。"""

    step_name: StepName
    code: ToolErrorCode
    message: WorkflowText
    retryable: bool
    trace_id: TraceIdentifier | None = None

# 机器裁决只回答诊断的是哪个订单以及它当前处于哪个阶段
class RuleDecision(WorkflowSchema):
    """保存规则节点得出的机器可读阶段, 不提前生成诊断文案。"""

    order_id: OrderIdentifier
    blocking_stage: BlockingStage

# 订单诊断结果(稳定输出) 未来真正返回给前端的完整结果  在机器裁决基础上生成的完整诊断说明
class DiagnosisResult(WorkflowSchema):
    """订单阻塞阶段、结构化根因、可追溯证据和建议的稳定输出。"""

    order_id: OrderIdentifier  # 诊断订单ID
    blocking_stage: BlockingStage  # 规则判断出的阻塞环节
    summary: WorkflowText  # 面向用户的阶段说明
    root_causes: list[RootCause]  # 结构化根因, 包含稳定 code 和说明
    evidence: Annotated[list[Evidence], Field(min_length=1)]  # Tool字段级证据
    suggestions: Annotated[list[Suggestion], Field(min_length=1)]  # 建议动作类型和说明
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]  # 规则结果置信度, 0-1之间, 1表示完全信

    @model_validator(mode="after")
    def validate_root_causes_for_blocking_stage(self) -> Self:
        """有阻塞时必须给出根因; 无阻塞时不得制造根因。"""

        if self.blocking_stage is BlockingStage.NONE and self.root_causes:
            raise ValueError("NONE blocking stage must not contain root causes")
        if self.blocking_stage is not BlockingStage.NONE and not self.root_causes:
            raise ValueError("blocked diagnosis must contain at least one root cause")
        return self

# 订单诊断状态
class OrderDiagnosisState(TypedDict):
    """固定订单诊断节点共享的完整状态通道; 所有字段均由Workflow初始化。"""

    run_id: str
    order_id: str
    page_context: PageContext | None
    order: OrderDetail | None
    tasks: list[TaskDetail]
    progress: dict[str, ProgressResult]
    quality_issues: dict[str, list[QualityIssue]]
    reviews: dict[str, ReviewResult | None]
    delivery: DeliveryStatus | None
    rule_decision: RuleDecision | None
    diagnosis: DiagnosisResult | None
    errors: list[StepError]
