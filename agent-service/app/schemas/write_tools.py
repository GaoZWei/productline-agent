"""M6.5业务写Tool的严格输入、Java响应和持久化输出契约。"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.approval import ReworkType
from app.schemas.tools import BusinessIdentifier, TaskIdentifier, ToolSchema

ApprovalIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
IdempotencyKey = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
JavaTraceIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
FinalReviewStatus = Literal["APPROVED", "REJECTED", "REWORK_REQUIRED"]


class WriteReviewResultInput(ToolSchema):
    """只允许调用方选择已确认Approval并提供可重放幂等键。"""

    approval_id: ApprovalIdentifier
    idempotency_key: IdempotencyKey


class CreateReworkTaskInput(ToolSchema):
    """返工Tool不接受调用方覆盖任务、问题、原因或版本。"""

    approval_id: ApprovalIdentifier
    idempotency_key: IdempotencyKey  # 用于保证同一个写请求重复发送时不会重复创建记录


class ReviewWriteRecordData(ToolSchema):
    """Java写接口只可能返回最终结论和非空意见。"""

    review_id: BusinessIdentifier = Field(alias="reviewId")
    issue_id: BusinessIdentifier = Field(alias="issueId")
    status: FinalReviewStatus
    review_comment: Annotated[str, Field(min_length=1, max_length=1000)] = Field(
        alias="reviewComment"
    )


class ReviewWriteResponseData(ToolSchema):
    """Java ReviewWriteResponse对应的强类型data。"""

    review: ReviewWriteRecordData
    task_version: Annotated[int, Field(ge=0)] = Field(alias="taskVersion")


class ReworkTaskData(ToolSchema):
    """Java ReworkTaskDto对应的返工任务事实。"""

    rework_task_id: BusinessIdentifier = Field(alias="reworkTaskId")
    task_id: TaskIdentifier = Field(alias="taskId")
    source_issue_id: BusinessIdentifier = Field(alias="sourceIssueId")
    status: Literal["PENDING"]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class ReworkWriteResponseData(ToolSchema):
    """Java ReworkWriteResponse对应的强类型data。"""

    rework_task: ReworkTaskData = Field(alias="reworkTask")
    task_version: Annotated[int, Field(ge=0)] = Field(alias="taskVersion")


class WriteReviewResultOutput(ToolSchema):
    """保存并返回Java已写入的复核结果身份和新任务版本。"""

    approval_id: ApprovalIdentifier
    task_id: TaskIdentifier
    issue_id: BusinessIdentifier
    review_id: BusinessIdentifier
    status: FinalReviewStatus
    review_comment: Annotated[str, Field(min_length=1, max_length=1000)]
    task_version: Annotated[int, Field(ge=0)]
    java_trace_id: JavaTraceIdentifier


class CreateReworkTaskOutput(ToolSchema):
    """保存并返回Java新建返工任务身份和新任务版本。"""

    approval_id: ApprovalIdentifier
    task_id: TaskIdentifier
    source_issue_id: BusinessIdentifier
    rework_task_id: BusinessIdentifier
    rework_type: ReworkType
    status: Literal["PENDING"]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    task_version: Annotated[int, Field(ge=0)]
    java_trace_id: JavaTraceIdentifier
