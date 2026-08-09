"""确定性订单诊断Workflow的状态通道和结构化结果契约。"""

from typing import Annotated, Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.errors import ToolErrorCode
from app.schemas.tools import (
    DeliveryStatus,
    OrderDetail,
    OrderIdentifier,
    ProgressResult,
    QualityIssue,
    ReviewResult,
    TaskDetail,
)
# 稳定机器代码类型，用于唯一标识Workflow节点、根因、Tool字段等。
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

# 公共父类，为Workflow内部结果提供严格、不可变且禁止额外字段的共同配置。
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

# 诊断依据（有价值的）
class Evidence(WorkflowSchema):
    """把一条诊断依据定位到具体只读Tool及其单个响应字段。"""

    source_type: Literal["TOOL"]  # 当前只能是"TOOL"，模型自己的判断，不能直接成为业务事实证据
    tool_name: ReadToolName
    field_path: EvidenceFieldPath  # 这条结论具体来自Tool结果中的哪个字段
    value: EvidenceValue  # 只允许标量值
    description: WorkflowText

# 建议
class Suggestion(WorkflowSchema):
    """描述一个建议动作; 本阶段只生成建议, 不代表已经执行写操作。"""

    action_type: StableCode
    description: WorkflowText

# 未来某个Tool节点失败时，可以写入StepError
class StepError(WorkflowSchema):
    """保存Workflow分支所需的安全错误字段, 不承载原始响应或异常堆栈。"""

    step_name: StepName
    code: ToolErrorCode
    message: WorkflowText
    retryable: bool
    trace_id: TraceIdentifier | None = None

# 订单诊断结果（稳定输出）
class DiagnosisResult(WorkflowSchema):
    """订单阻塞阶段、结构化根因、可追溯证据和建议的稳定输出。"""

    order_id: OrderIdentifier
    blocking_stage: StableCode
    root_causes: list[RootCause]
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    suggestions: Annotated[list[Suggestion], Field(min_length=1)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_root_causes_for_blocking_stage(self) -> Self:
        """有阻塞时必须给出根因; 无阻塞时不得制造根因。"""

        if self.blocking_stage == "NONE" and self.root_causes:
            raise ValueError("NONE blocking stage must not contain root causes")
        if self.blocking_stage != "NONE" and not self.root_causes:
            raise ValueError("blocked diagnosis must contain at least one root cause")
        return self

# 订单诊断状态
class OrderDiagnosisState(TypedDict):
    """固定订单诊断节点共享的完整状态通道; 所有字段均由Workflow初始化。"""

    run_id: str
    order_id: str
    order: OrderDetail | None
    tasks: list[TaskDetail]
    progress: dict[str, ProgressResult]
    quality_issues: dict[str, list[QualityIssue]]
    reviews: dict[str, ReviewResult | None]
    delivery: DeliveryStatus | None
    diagnosis: DiagnosisResult | None
    errors: list[StepError]
