"""T827内部草稿命令和事实审查包，不接收页面自报的版本、当前材料或确认凭证。"""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from app.schemas.rework import (
    BusinessId,
    Comment,
    FinalReviewStatus,
    OrderId,
    References,
    ReworkArtifact,
    ReworkDetail,
    ReworkInspectionItem,
    ReworkSchema,
    TaskId,
)
from app.schemas.rework_approval import ReworkDraftReview
from app.schemas.rework_delivery import DeliveryTaskConditions


class _TaskCommand(ReworkSchema):
    """任务ID仅用于定位，版本和实际所属订单必须重新读取Java。"""

    task_id: TaskId


class _RoundCommand(_TaskCommand):
    """请求已有返工的动作，来源问题及真实轮次由Java确定。"""

    rework_task_id: BusinessId


class CreateReworkDraftCommand(_TaskCommand):
    """只有首轮创建需要用户明确选择来源问题。"""

    operation: Literal["CREATE_LIFECYCLE_REWORK"]
    source_issue_id: BusinessId
    reason: Comment


class StartReworkDraftCommand(_RoundCommand):
    """开始动作不接收其他材料或自报版本。"""

    operation: Literal["START_REWORK"]


class ReworkReasonDraftCommand(_RoundCommand):
    """异常、恢复及后继创建的原因保留原值，不覆盖原创建原因。"""

    operation: Literal["BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK", "CREATE_NEXT_REWORK"]
    reason: Comment


class ReworkResultDraftCommand(_RoundCommand):
    """人工提供待登记成果及证据，不能自报修订或检查通过。"""

    operation: Literal["REGISTER_REWORK_RESULT"]
    artifact: ReworkArtifact
    processing_comment: Comment
    evidence_references: References


class ReworkInspectionDraftCommand(_RoundCommand):
    """人工提供完整检查项，当前成果与修订由Java读取。"""

    operation: Literal["REGISTER_REWORK_INSPECTION"]
    items: Annotated[list[ReworkInspectionItem], Field(min_length=1, max_length=50)]


class ReworkReviewDraftCommand(_RoundCommand):
    """最终结论和意见来自本次人工输入，当前检查身份不接受自报。"""

    operation: Literal["SUBMIT_REWORK_REVIEW"]
    status: FinalReviewStatus
    review_comment: Comment


type ReworkDraftCommand = Annotated[
    CreateReworkDraftCommand
    | StartReworkDraftCommand
    | ReworkReasonDraftCommand
    | ReworkResultDraftCommand
    | ReworkInspectionDraftCommand
    | ReworkReviewDraftCommand,
    Field(discriminator="operation"),
]
_COMMAND = TypeAdapter[ReworkDraftCommand](ReworkDraftCommand)


def parse_rework_draft_command(value: object) -> ReworkDraftCommand:
    """复制嵌套材料并校验，拒绝期望版本、当前事实、权限及确认字段。"""

    raw = value.model_dump(mode="python") if isinstance(value, ReworkSchema) else value
    return _COMMAND.validate_python(raw)


class PreparedReworkDraft(ReworkSchema):
    """草稿及可核对的完整当前材料，不保存Approval或签发执行权。"""

    review: ReworkDraftReview
    order_id: OrderId
    current_task: DeliveryTaskConditions
    current_rework: ReworkDetail | None
