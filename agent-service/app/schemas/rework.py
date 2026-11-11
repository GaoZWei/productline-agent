"""M8返工Java契约，保留原始文本、真实绑定和显式缺失值，不复用旧PENDING写响应。"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.schemas.tools import (
    ProductionStatus,
    QualityIssueStatus,
    ReviewStatus,
)

MAX_SAFE_INTEGER = 9007199254740991
_JAVA_WHITESPACE = frozenset(
    "\t\n\v\f\r\x1c\x1d\x1e\x1f \u1680\u2000\u2001\u2002\u2003\u2004"
    "\u2005\u2006\u2008\u2009\u200a\u2028\u2029\u205f\u3000"
)


def _text(maximum: int | None, *, trimmed: bool = False, allow_blank: bool = False) -> Callable[[str], str]:
    """按Java UTF-16及isBlank/strip语义检查，原样返回，不改变绑定值。"""

    def validate(value: str) -> str:
        """拒绝NUL、无损UTF-8不支持的代理项及超限文本。"""

        try:
            value.encode("utf-8")
            length = len(value.encode("utf-16-le")) // 2
        except UnicodeError:
            raise ValueError("text must be losslessly representable in UTF-8") from None
        if "\0" in value or (maximum is not None and length > maximum):
            raise ValueError("text exceeds the UTF-16 limit or contains NUL")
        if not allow_blank and (not value or all(char in _JAVA_WHITESPACE for char in value)):
            raise ValueError("text must not be blank")
        if trimmed and value and (value[0] in _JAVA_WHITESPACE or value[-1] in _JAVA_WHITESPACE):
            raise ValueError("identifier or reference must not contain boundary whitespace")
        return value

    return validate


def _business_id(value: str) -> str:
    """使用完整匹配阻止换行或路径字符混入业务ID。"""

    if re.fullmatch(r"[A-Z]+-[A-Z0-9][A-Z0-9-]*", value) is None:
        raise ValueError("business identifier is invalid")
    return value


def _utc(value: str) -> str:
    """保存Java原始UTC时间字符串，检查格式和日历值，不本地化或截断纳秒。"""

    if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|\+00:00)", value) is None:
        raise ValueError("timestamp must be a UTC ISO-8601 instant")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("timestamp has an invalid calendar value") from None
    return value


BusinessId = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(_business_id)]
TaskId = Annotated[BusinessId, Field(pattern=r"^TASK-[A-Z0-9][A-Z0-9-]*$")]
OrderId = Annotated[BusinessId, Field(pattern=r"^ORDER-[A-Z0-9][A-Z0-9-]*$")]
SafeVersion = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
Sequence = Annotated[int, Field(ge=1, le=MAX_SAFE_INTEGER)]
Comment = Annotated[str, AfterValidator(_text(1000))]
FactText = Annotated[str, AfterValidator(_text(None))]
Actor = Annotated[str, Field(max_length=128, pattern=r"^[^\r\n]+$"), AfterValidator(_text(128))]
UtcInstant = Annotated[str, AfterValidator(_utc)]
EvidenceReference = Annotated[str, AfterValidator(_text(1024, trimmed=True))]
References = Annotated[list[EvidenceReference], Field(min_length=1, max_length=20)]
type InspectionResult = Literal["PASSED", "FAILED"]
type FinalReviewStatus = Literal["APPROVED", "REJECTED", "REWORK_REQUIRED"]
type ReworkAction = Literal[
    "START_REWORK", "BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK",
    "REGISTER_REWORK_RESULT", "REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW",
    "CREATE_NEXT_REWORK",
]
type ReworkOperation = Literal["CREATE_LIFECYCLE_REWORK"] | ReworkAction


class ReworkSchema(BaseModel):
    """M8专用严格基类，避免旧ToolSchema自动strip导致请求内容与审查值不同。"""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, populate_by_name=True,
        str_strip_whitespace=False, revalidate_instances="always", hide_input_in_errors=True,
    )


class ReworkResource(ReworkSchema):
    """只定位业务资源，不证明归属、权限或人工确认。"""

    task_id: TaskId = Field(alias="taskId")
    rework_task_id: BusinessId = Field(alias="reworkTaskId")


class ReworkPageQuery(ReworkSchema):
    """只传Java支持的分页参数，游标保持原始不透明字符串。"""

    limit: Annotated[int, Field(ge=1, le=100)] = 20
    cursor: Annotated[str, Field(min_length=1)] | None = None


class ReworkArtifact(ReworkSchema):
    """成果标识和版本是外部原始字符串，不能套业务ID或数字转换。"""

    artifact_id: Annotated[str, AfterValidator(_text(256, trimmed=True))] = Field(alias="artifactId")
    artifact_version: Annotated[str, AfterValidator(_text(128, trimmed=True))] = Field(alias="artifactVersion")


class ReworkInspectionItem(ReworkSchema):
    """真实人工检查项；不执行引用、不代表自动检查。"""

    check_item: Annotated[str, AfterValidator(_text(128))] = Field(alias="checkItem")
    result: InspectionResult
    comment: Comment
    evidence_references: References = Field(alias="evidenceReferences")


class ReworkVersionRequest(ReworkSchema):
    """开始动作只提交共享任务版本。"""

    expected_version: SafeVersion = Field(alias="expectedVersion")


class ReworkReasonRequest(ReworkVersionRequest):
    """异常、恢复及后继创建只提交版本与本次原样原因。"""

    reason: Comment


class CreateLifecycleReworkRequest(ReworkReasonRequest):
    """受控首轮必须明确来源问题，轮次和创建人由Java确定。"""

    source_issue_id: BusinessId = Field(alias="sourceIssueId")


class RegisterReworkResultRequest(ReworkVersionRequest):
    """登记处理材料，不允许自报修订、检查或成功结论。"""

    artifact: ReworkArtifact
    processing_comment: Comment = Field(alias="processingComment")
    evidence_references: References = Field(alias="evidenceReferences")


class RegisterReworkInspectionRequest(ReworkVersionRequest):
    """绑定已审查修订，整体结论由Java汇总人工检查项。"""

    processing_revision: Sequence = Field(alias="processingRevision")
    items: Annotated[list[ReworkInspectionItem], Field(min_length=1, max_length=50)]


class SubmitReworkReviewRequest(ReworkVersionRequest):
    """再次复核绑定明确成果修订及检查，不接受人员、时间或自报确认。"""

    processing_revision: Sequence = Field(alias="processingRevision")
    inspection_id: BusinessId = Field(alias="inspectionId")
    status: FinalReviewStatus
    review_comment: Comment = Field(alias="reviewComment")


class ReworkTask(ReworkResource):
    """新读取使用完整五状态，存量无来源时保留null。"""

    source_issue_id: BusinessId | None = Field(alias="sourceIssueId")
    status: ProductionStatus
    reason: Comment


class ReworkProcessing(ReworkSchema):
    """Java已登记的不可变处理修订，人员与时间不是调用方可提交参数。"""

    processing_revision: Sequence = Field(alias="processingRevision")
    artifact: ReworkArtifact
    processing_comment: Comment = Field(alias="processingComment")
    evidence_references: References = Field(alias="evidenceReferences")
    registered_by: Actor = Field(alias="registeredBy")
    registered_at: UtcInstant = Field(alias="registeredAt")


class ReworkInspection(ReworkSchema):
    """保留Java真实检查序号与绑定，检查结论必须与非空检查项一致。"""

    inspection_id: BusinessId = Field(alias="inspectionId")
    inspection_sequence: Sequence = Field(alias="inspectionSequence")
    round_number: Sequence = Field(alias="roundNumber")
    processing_revision: Sequence = Field(alias="processingRevision")
    inspector_id: Actor = Field(alias="inspectorId")
    inspected_at: UtcInstant = Field(alias="inspectedAt")
    result: InspectionResult
    items: Annotated[list[ReworkInspectionItem], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        """拒绝与Java人工项汇总矛盾的总体检查结论。"""

        expected = "PASSED" if all(item.result == "PASSED" for item in self.items) else "FAILED"
        if self.result != expected:
            raise ValueError("inspection result does not match its items")
        return self


class ReworkReview(ReworkSchema):
    """新受控复核必须为最终结论，存量PENDING另由LegacyReview表示。"""

    review_id: BusinessId = Field(alias="reviewId")
    review_sequence: Sequence = Field(alias="reviewSequence")
    round_number: Sequence = Field(alias="roundNumber")
    processing_revision: Sequence = Field(alias="processingRevision")
    inspection_id: BusinessId = Field(alias="inspectionId")
    status: FinalReviewStatus
    review_comment: Comment = Field(alias="reviewComment")
    reviewed_by: Actor = Field(alias="reviewedBy")
    reviewed_at: UtcInstant = Field(alias="reviewedAt")


class ReworkDetail(ReworkSchema):
    """读取快照中的当前材料；允许动作来自Java，不是写入授权。"""

    rework_task: ReworkTask = Field(alias="reworkTask")
    issue_status: QualityIssueStatus | None = Field(alias="issueStatus")
    round_number: Sequence | None = Field(alias="roundNumber")
    previous_rework_task_id: BusinessId | None = Field(alias="previousReworkTaskId")
    allowed_actions: list[ReworkAction] = Field(alias="allowedActions")
    task_version: SafeVersion = Field(alias="taskVersion")
    processing: ReworkProcessing | None
    inspection: ReworkInspection | None
    review: ReworkReview | None

    @model_validator(mode="after")
    def consistent_binding(self) -> Self:
        """校验同一响应自洽，不从历史重新选择当前材料。"""

        if (self.rework_task.source_issue_id is None) != (self.issue_status is None):
            raise ValueError("issue status must match source presence")
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("allowed actions must be unique")
        if self.round_number is None:
            if any(value is not None for value in (
                self.previous_rework_task_id, self.processing, self.inspection, self.review,
            )) or self.allowed_actions:
                raise ValueError("legacy rework must not invent lifecycle or evidence")
        elif self.rework_task.source_issue_id is None or (
            (self.round_number == 1) != (self.previous_rework_task_id is None)
        ):
            raise ValueError("round predecessor or source is invalid")
        if self.inspection is not None and (
            self.processing is None or self.inspection.round_number != self.round_number
            or self.inspection.processing_revision != self.processing.processing_revision
        ):
            raise ValueError("inspection does not bind current processing")
        if self.review is not None and (
            self.inspection is None or self.inspection.result != "PASSED"
            or self.review.round_number != self.round_number
            or self.review.processing_revision != self.inspection.processing_revision
            or self.review.inspection_id != self.inspection.inspection_id
        ):
            raise ValueError("review does not bind current passed inspection")
        return self


class ReworkHistoryPage[RecordT](ReworkResource):
    """一页真实历史，null游标必须显式存在，不冒充跨页统一快照。"""

    records: list[RecordT]
    next_cursor: Annotated[str, Field(min_length=1)] | None = Field(alias="nextCursor")


class LegacyReview(ReworkSchema):
    """原ReviewRecordDto，保留PENDING、null或空说明，不强行升级受控证据。"""

    review_id: BusinessId = Field(alias="reviewId")
    issue_id: BusinessId = Field(alias="issueId")
    status: ReviewStatus
    review_comment: Annotated[str, AfterValidator(_text(1000, allow_blank=True))] | None = Field(alias="reviewComment")


class EffectiveReworkReview(ReworkSchema):
    """每个问题的Java当前绑定，受控事实与原始旧复核分开。"""

    issue_id: BusinessId = Field(alias="issueId")
    rework_task_id: BusinessId | None = Field(alias="reworkTaskId")
    round_number: Sequence | None = Field(alias="roundNumber")
    processing_revision: Sequence | None = Field(alias="processingRevision")
    inspection_id: BusinessId | None = Field(alias="inspectionId")
    review: ReworkReview | None
    legacy_reviews: list[LegacyReview] = Field(alias="legacyReviews")

    @model_validator(mode="after")
    def consistent_binding(self) -> Self:
        """拒绝错轮次、错材料或混入存量的响应，不自行决定哪个复核有效。"""

        if self.round_number is None:
            if any(value is not None for value in (self.rework_task_id, self.processing_revision, self.inspection_id, self.review)):
                raise ValueError("legacy issue must not invent controlled binding")
        elif self.rework_task_id is None or self.legacy_reviews:
            raise ValueError("controlled issue requires a rework and no legacy records")
        if self.processing_revision is None and self.inspection_id is not None:
            raise ValueError("inspection requires processing revision")
        if self.review is not None and (
            self.review.round_number != self.round_number
            or self.review.processing_revision != self.processing_revision
            or self.review.inspection_id != self.inspection_id
        ):
            raise ValueError("effective review has a different binding")
        if any(old.issue_id != self.issue_id for old in self.legacy_reviews):
            raise ValueError("legacy review belongs to another issue")
        return self


class EffectiveReworkReviews(ReworkSchema):
    """任务共享版本和全部问题的当前复核事实。"""

    task_id: TaskId = Field(alias="taskId")
    task_version: SafeVersion = Field(alias="taskVersion")
    issues: list[EffectiveReworkReview]

    @model_validator(mode="after")
    def unique_issues(self) -> Self:
        """重复问题不能当作不同的事实。"""

        if len({issue.issue_id for issue in self.issues}) != len(self.issues):
            raise ValueError("effective issue identities must be unique")
        return self


class ReworkWriteReceipt(ReworkResource):
    """Java原成功回执，不代表当前仍保持该状态，更不是Approval凭证。"""

    operation: ReworkOperation
    operation_id: BusinessId = Field(alias="operationId")
    task_version: Sequence = Field(alias="taskVersion")
    status: ProductionStatus
    issue_status: QualityIssueStatus = Field(alias="issueStatus")
    round_number: Sequence = Field(alias="roundNumber")
    previous_rework_task_id: BusinessId | None = Field(alias="previousReworkTaskId")
    processing_revision: Sequence | None = Field(alias="processingRevision")
    inspection_id: BusinessId | None = Field(alias="inspectionId")
    review_id: BusinessId | None = Field(alias="reviewId")

    @model_validator(mode="after")
    def consistent_presence(self) -> Self:
        """只检查响应内部身份/材料存在关系，操作匹配由HTTP适配器核对。"""

        if (self.round_number == 1) != (self.previous_rework_task_id is None):
            raise ValueError("receipt predecessor does not match round")
        if self.inspection_id is not None and self.processing_revision is None:
            raise ValueError("receipt inspection requires processing")
        if self.review_id is not None and self.inspection_id is None:
            raise ValueError("receipt review requires inspection")
        return self
