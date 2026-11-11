"""T820订单级交付条件的Python传输契约，不重新计算Java阻塞规则。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.rework import (
    BusinessId,
    EffectiveReworkReview,
    FactText,
    OrderId,
    ReworkSchema,
    ReworkTask,
    SafeVersion,
    TaskId,
)
from app.schemas.tools import DeliveryState, OrderStatus, ProductionStatus, QualityIssueStatus

type DeliveryConditionCode = Literal[
    "ORDER_BLOCKED",
    "MISSING_PRODUCTION_TASKS",
    "PRODUCTION_TASK_NOT_COMPLETED",
    "MISSING_PRODUCTION_STEPS",
    "PRODUCTION_STEP_NOT_COMPLETED",
    "ACTIVE_REWORK",
    "QUALITY_ISSUE_UNRESOLVED",
    "CONTROLLED_ISSUE_NOT_CLOSED",
    "EFFECTIVE_REVIEW_NOT_APPROVED",
    "LEGACY_REVIEW_NOT_APPROVED",
    "LEGACY_RESOLVED_ISSUE_WITHOUT_APPROVAL",
    "MISSING_DELIVERY_RECORDS",
    "DELIVERY_NOT_READY",
]


class DeliveryConditionOrder(ReworkSchema):
    """Java原订单字段，保留真实状态。"""

    order_id: OrderId = Field(alias="orderId")
    product_type: FactText = Field(alias="productType")
    status: OrderStatus


class DeliveryConditionStep(ReworkSchema):
    """原生产步骤DTO，不把数据库INTEGER序号误限制为返工轮次。"""

    step_id: BusinessId = Field(alias="stepId")
    task_id: TaskId = Field(alias="taskId")
    step_name: FactText = Field(alias="stepName")
    sequence_number: Annotated[int, Field(gt=0, le=2147483647)] = Field(alias="sequenceNumber")
    status: ProductionStatus


class DeliveryConditionIssue(ReworkSchema):
    """原问题DTO及来源归属，不生成或改写业务事实。"""

    issue_id: BusinessId = Field(alias="issueId")
    task_id: TaskId = Field(alias="taskId")
    issue_type: FactText = Field(alias="issueType")
    status: QualityIssueStatus
    description: FactText


class DeliveryIssueCondition(ReworkSchema):
    """同一个问题的事实和Java选择的有效复核必须匹配。"""

    issue: DeliveryConditionIssue
    effective_review: EffectiveReworkReview = Field(alias="effectiveReview")

    @model_validator(mode="after")
    def consistent_issue(self) -> Self:
        """不允许把别的问题的有效复核混入本问题。"""

        if self.issue.issue_id != self.effective_review.issue_id:
            raise ValueError("delivery issue and effective review have different identities")
        return self


class DeliveryTaskConditions(ReworkSchema):
    """同一快照内的任务版本及关联事实。"""

    task_id: TaskId = Field(alias="taskId")
    task_version: SafeVersion = Field(alias="taskVersion")
    production_status: ProductionStatus = Field(alias="productionStatus")
    steps: list[DeliveryConditionStep]
    issues: list[DeliveryIssueCondition]
    active_reworks: list[ReworkTask] = Field(alias="activeReworks")

    @model_validator(mode="after")
    def consistent_ownership(self) -> Self:
        """核对任务内资源归属及重复身份，不重新裁决是否可交付。"""

        if (
            any(step.task_id != self.task_id for step in self.steps)
            or any(entry.issue.task_id != self.task_id for entry in self.issues)
            or any(rework.task_id != self.task_id for rework in self.active_reworks)
        ):
            raise ValueError("delivery facts belong to another task")
        for identities in (
            [step.step_id for step in self.steps],
            [entry.issue.issue_id for entry in self.issues],
            [rework.rework_task_id for rework in self.active_reworks],
        ):
            if len(identities) != len(set(identities)):
                raise ValueError("delivery resource identities must be unique")
        issue_ids = {entry.issue.issue_id for entry in self.issues}
        if any(
            rework.source_issue_id is not None and rework.source_issue_id not in issue_ids
            for rework in self.active_reworks
        ):
            raise ValueError("active rework source is not part of this task")
        return self


class DeliveryConditionRecord(ReworkSchema):
    """原交付记录的真实状态，不代表已授权下一步操作。"""

    delivery_id: BusinessId = Field(alias="deliveryId")
    order_id: OrderId = Field(alias="orderId")
    status: DeliveryState


class DeliveryConditionBlocker(ReworkSchema):
    """稳定Java阻塞代码及资源定位。缺失状态显式为null。"""

    code: DeliveryConditionCode
    task_id: TaskId | None = Field(alias="taskId")
    resource_id: BusinessId = Field(alias="resourceId")
    status: (
        ProductionStatus
        | QualityIssueStatus
        | DeliveryState
        | OrderStatus
        | Literal["APPROVED", "REJECTED", "REWORK_REQUIRED"]
        | None
    )


class DeliveryConditions(ReworkSchema):
    """只校验Java响应的归属和自洽，hasBlockers不构成交付资格或人工确认。"""

    order: DeliveryConditionOrder
    tasks: list[DeliveryTaskConditions]
    delivery_records: list[DeliveryConditionRecord] = Field(alias="deliveryRecords")
    blockers: list[DeliveryConditionBlocker]
    has_blockers: bool = Field(alias="hasBlockers")

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Self:
        """拒绝错订单、错任务和与阻塞数组矛盾的标记。"""

        task_ids = {task.task_id for task in self.tasks}
        if len(task_ids) != len(self.tasks):
            raise ValueError("delivery tasks must be unique")
        if any(record.order_id != self.order.order_id for record in self.delivery_records):
            raise ValueError("delivery record belongs to another order")
        if len({record.delivery_id for record in self.delivery_records}) != len(
            self.delivery_records
        ):
            raise ValueError("delivery records must be unique")
        if any(row.task_id is not None and row.task_id not in task_ids for row in self.blockers):
            raise ValueError("blocker belongs to another task")
        resources: dict[str | None, set[str]] = {
            None: {self.order.order_id, *(record.delivery_id for record in self.delivery_records)}
        }
        for task in self.tasks:
            resources[task.task_id] = {
                task.task_id,
                *(step.step_id for step in task.steps),
                *(entry.issue.issue_id for entry in task.issues),
                *(rework.rework_task_id for rework in task.active_reworks),
                *(
                    old.review_id
                    for entry in task.issues
                    for old in entry.effective_review.legacy_reviews
                ),
            }
        if any(row.resource_id not in resources[row.task_id] for row in self.blockers):
            raise ValueError("blocker resource is not part of its stated scope")
        if self.has_blockers != bool(self.blockers):
            raise ValueError("hasBlockers does not match blockers")
        return self
