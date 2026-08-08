"""只读业务 Tool 的输入和输出 Schema。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# 订单状态只能取以下固定值。
type OrderStatus = Literal[
    "CREATED",
    "PRODUCING",
    "QUALITY_CHECKING",
    "REVIEWING",
    "READY_FOR_DELIVERY",
    "DELIVERING",
    "DELIVERED",
    "BLOCKED",
]
type ProductionStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "BLOCKED"]
type QualityIssueStatus = Literal["OPEN", "PROCESSING", "RESOLVED", "CLOSED"]
type ReviewStatus = Literal["PENDING", "APPROVED", "REJECTED", "REWORK_REQUIRED"]
type DeliveryState = Literal["NOT_READY", "READY", "DELIVERING", "DELIVERED", "FAILED", "BLOCKED"]
# 订单标识格式限制
OrderIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^ORDER-[A-Z0-9][A-Z0-9-]*$"),
]
# 任务标识格式限制
TaskIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^TASK-[A-Z0-9][A-Z0-9-]*$"),
]
# 通用业务标识格式限制
BusinessIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Z]+-[A-Z0-9][A-Z0-9-]*$"),
]
NonBlankText = Annotated[str, Field(min_length=1, max_length=2048)]


# ToolSchema 公共配置
class ToolSchema(BaseModel):
    """为 Tool 契约提供严格、不可变且禁止额外字段的共同配置。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class OrderIdInput(ToolSchema):
    """订单类 Tool 的安全路径参数。"""

    order_id: OrderIdentifier


class TaskIdInput(ToolSchema):
    """任务类 Tool 的安全路径参数。"""

    task_id: TaskIdentifier


class OrderDetail(ToolSchema):
    """Java OrderDto 对应的订单事实。"""

    order_id: OrderIdentifier = Field(alias="orderId")
    product_type: NonBlankText = Field(alias="productType")
    status: OrderStatus


class ProductionTask(ToolSchema):
    """Java ProductionTaskDto 对应的生产任务事实。"""

    task_id: TaskIdentifier = Field(alias="taskId")
    order_id: OrderIdentifier = Field(alias="orderId")
    status: ProductionStatus
    version: Annotated[int, Field(ge=0)]


class TaskList(ToolSchema):
    """保留父订单 ID 和稳定任务数组的查询结果。"""

    order_id: OrderIdentifier = Field(alias="orderId")
    tasks: list[ProductionTask]


class TaskDetail(ProductionTask):
    """任务详情端点的强类型输出。"""


class ProductionStep(ToolSchema):
    """Java ProductionStepDto 对应的生产步骤事实。"""

    step_id: BusinessIdentifier = Field(alias="stepId")
    task_id: TaskIdentifier = Field(alias="taskId")
    step_name: NonBlankText = Field(alias="stepName")
    sequence_number: Annotated[int, Field(gt=0)] = Field(alias="sequenceNumber")
    status: ProductionStatus


class ProgressResult(ToolSchema):
    """保留父任务 ID 和业务顺序步骤数组的进度结果。"""

    task_id: TaskIdentifier = Field(alias="taskId")
    steps: list[ProductionStep]


class QualityIssue(ToolSchema):
    """Java QualityIssueDto 对应的质检问题事实。"""

    issue_id: BusinessIdentifier = Field(alias="issueId")
    task_id: TaskIdentifier = Field(alias="taskId")
    issue_type: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$"),
    ] = Field(alias="issueType")
    status: QualityIssueStatus
    description: NonBlankText


class QualityIssueList(ToolSchema):
    """保留父任务 ID 和质检问题数组的查询结果。"""

    task_id: TaskIdentifier = Field(alias="taskId")
    issues: list[QualityIssue]


class ReviewRecord(ToolSchema):
    """Java ReviewRecordDto 对应的复核事实。"""

    review_id: BusinessIdentifier = Field(alias="reviewId")
    issue_id: BusinessIdentifier = Field(alias="issueId")
    status: ReviewStatus
    review_comment: Annotated[str, Field(max_length=1000)] | None = Field(
        alias="reviewComment"
    )


class ReviewResult(ToolSchema):
    """保留父任务 ID 和复核记录数组的查询结果。"""

    task_id: TaskIdentifier = Field(alias="taskId")
    reviews: list[ReviewRecord]


class DeliveryRecord(ToolSchema):
    """Java DeliveryRecordDto 对应的交付事实。"""

    delivery_id: BusinessIdentifier = Field(alias="deliveryId")
    order_id: OrderIdentifier = Field(alias="orderId")
    status: DeliveryState


class DeliveryStatus(ToolSchema):
    """保留父订单 ID 和全部交付记录的查询结果。"""

    order_id: OrderIdentifier = Field(alias="orderId")
    records: list[DeliveryRecord]
