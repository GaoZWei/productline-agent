"""T826独立返工审批草稿契约。只描述待审查内容，不授予确认或执行权限。"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from app.schemas.rework import (
    BusinessId,
    CreateLifecycleReworkRequest,
    RegisterReworkInspectionRequest,
    RegisterReworkResultRequest,
    ReworkArtifact,
    ReworkOperation,
    ReworkReasonRequest,
    ReworkSchema,
    ReworkVersionRequest,
    SafeVersion,
    Sequence,
    SubmitReworkReviewRequest,
    TaskId,
)

type ReworkApprovalToolName = Literal[
    "create_lifecycle_rework",
    "start_rework",
    "block_rework",
    "fail_rework",
    "resume_rework",
    "register_rework_result",
    "register_rework_inspection",
    "submit_rework_review",
    "create_next_rework",
]
REWORK_APPROVAL_TOOLS: Mapping[ReworkOperation, ReworkApprovalToolName] = MappingProxyType(
    {
        "CREATE_LIFECYCLE_REWORK": "create_lifecycle_rework",
        "START_REWORK": "start_rework",
        "BLOCK_REWORK": "block_rework",
        "FAIL_REWORK": "fail_rework",
        "RESUME_REWORK": "resume_rework",
        "REGISTER_REWORK_RESULT": "register_rework_result",
        "REGISTER_REWORK_INSPECTION": "register_rework_inspection",
        "SUBMIT_REWORK_REVIEW": "submit_rework_review",
        "CREATE_NEXT_REWORK": "create_next_rework",
    }
)


class ReworkApprovalTarget(ReworkSchema):
    """由后续事实读取流程生成的目标快照，不是页面可自报的已验证事实。"""

    task_id: TaskId
    task_version: SafeVersion
    source_issue_id: BusinessId
    rework_task_id: BusinessId | None
    round_number: Sequence | None
    previous_rework_task_id: BusinessId | None
    processing_revision: Sequence | None
    artifact: ReworkArtifact | None
    inspection_id: BusinessId | None
    review_id: BusinessId | None

    @model_validator(mode="after")
    def validate_material_binding(self) -> Self:
        """缺失材料必须显式null，不能混用轮次、成果和检查的半份绑定。"""

        if self.rework_task_id is None:
            if any(
                value is not None
                for value in (
                    self.round_number,
                    self.previous_rework_task_id,
                    self.processing_revision,
                    self.artifact,
                    self.inspection_id,
                    self.review_id,
                )
            ):
                raise ValueError("uncreated round cannot contain lifecycle material")
        else:
            if self.round_number is None or (
                (self.round_number == 1) != (self.previous_rework_task_id is None)
            ):
                raise ValueError("round and predecessor must be consistent")
            if self.previous_rework_task_id == self.rework_task_id:
                raise ValueError("round cannot be its own predecessor")
        if (self.processing_revision is None) != (self.artifact is None):
            raise ValueError("processing revision and artifact must be bound together")
        if self.inspection_id is not None and self.processing_revision is None:
            raise ValueError("inspection requires current processing material")
        if self.review_id is not None and self.inspection_id is None:
            raise ValueError("review requires a current inspection")
        return self


class _ReworkDraft[RequestT: ReworkVersionRequest](ReworkSchema):
    """复用Java严格请求Schema，只允许编辑请求材料，目标和动作不能被替换。"""

    operation: ReworkOperation
    target: ReworkApprovalTarget
    request: RequestT

    @model_validator(mode="after")
    def validate_confirmable_binding(self) -> Self:
        """只验证结构与绑定，业务状态/权限和材料真实性仍需后续Java重读。"""

        if self.request.expected_version != self.target.task_version:
            raise ValueError("request version differs from target snapshot")
        if self.operation == "CREATE_LIFECYCLE_REWORK":
            if self.target.rework_task_id is not None:
                raise ValueError("first creation cannot reuse an existing round")
            if (
                not isinstance(self.request, CreateLifecycleReworkRequest)
                or self.request.source_issue_id != self.target.source_issue_id
            ):
                raise ValueError("creation issue differs from target snapshot")
        elif self.target.rework_task_id is None:
            raise ValueError("operation requires an existing managed round")
        if isinstance(self.request, (RegisterReworkInspectionRequest, SubmitReworkReviewRequest)):
            if (
                self.target.artifact is None
                or self.request.processing_revision != self.target.processing_revision
            ):
                raise ValueError("request processing material differs from target snapshot")
        if (
            isinstance(self.request, SubmitReworkReviewRequest)
            and self.request.inspection_id != self.target.inspection_id
        ):
            raise ValueError("review inspection differs from target snapshot")
        if self.operation == "CREATE_NEXT_REWORK" and self.target.review_id is None:
            raise ValueError("next round requires the previous review binding")
        return self


class CreateLifecycleReworkDraft(_ReworkDraft[CreateLifecycleReworkRequest]):
    """独立审查首轮创建，不复用旧CREATE_REWORK草稿。"""

    operation: Literal["CREATE_LIFECYCLE_REWORK"]


class StartReworkDraft(_ReworkDraft[ReworkVersionRequest]):
    """独立审查开始本轮返工，不继承创建确认。"""

    operation: Literal["START_REWORK"]


class BlockReworkDraft(_ReworkDraft[ReworkReasonRequest]):
    """独立审查阻塞原因。"""

    operation: Literal["BLOCK_REWORK"]


class FailReworkDraft(_ReworkDraft[ReworkReasonRequest]):
    """独立审查失败原因。"""

    operation: Literal["FAIL_REWORK"]


class ResumeReworkDraft(_ReworkDraft[ReworkReasonRequest]):
    """独立审查恢复原因，不重置原开始信息。"""

    operation: Literal["RESUME_REWORK"]


class RegisterReworkResultDraft(_ReworkDraft[RegisterReworkResultRequest]):
    """审查实际成果、处理说明和证据，不宣称检查通过。"""

    operation: Literal["REGISTER_REWORK_RESULT"]


class RegisterReworkInspectionDraft(_ReworkDraft[RegisterReworkInspectionRequest]):
    """审查当前成果上的完整人工检查项，整体结论不能另行填写。"""

    operation: Literal["REGISTER_REWORK_INSPECTION"]


class SubmitReworkReviewDraft(_ReworkDraft[SubmitReworkReviewRequest]):
    """再次复核绑定本轮成果和明确检查，不复用旧复核确认。"""

    operation: Literal["SUBMIT_REWORK_REVIEW"]


class CreateNextReworkDraft(_ReworkDraft[ReworkReasonRequest]):
    """审查本次后继创建，保留前轮成果、检查及复核身份。"""

    operation: Literal["CREATE_NEXT_REWORK"]


type ReworkApprovalDraft = Annotated[
    CreateLifecycleReworkDraft
    | StartReworkDraft
    | BlockReworkDraft
    | FailReworkDraft
    | ResumeReworkDraft
    | RegisterReworkResultDraft
    | RegisterReworkInspectionDraft
    | SubmitReworkReviewDraft
    | CreateNextReworkDraft,
    Field(discriminator="operation"),
]
_DRAFT_ADAPTER = TypeAdapter[ReworkApprovalDraft](ReworkApprovalDraft)


def parse_rework_approval_draft(value: object) -> ReworkApprovalDraft:
    """复制并严格校验草稿，拒绝旧动作/额外确认字段，不借用可变材料引用。"""

    raw = value.model_dump(mode="python") if isinstance(value, ReworkSchema) else value
    return _DRAFT_ADAPTER.validate_python(raw)


def validate_rework_draft_edit(original: object, edited: object) -> ReworkApprovalDraft:
    """仅允许本次请求材料进入再次审查，不能换动作、目标、版本、轮次或当前材料。"""

    before, after = parse_rework_approval_draft(original), parse_rework_approval_draft(edited)
    if before.operation != after.operation or before.target != after.target:
        raise ValueError("operation and target snapshot cannot be edited")
    return after


class ReworkExpectedEffects(ReworkSchema):
    """Java接受请求时的预期副作用，不是已发生事实或交付资格。"""

    production_status_after: Literal["COMPLETED"]
    rework_status_after: Literal["PENDING", "RUNNING", "BLOCKED", "FAILED", "COMPLETED"]
    issue_status_after: Literal["OPEN", "PROCESSING", "RESOLVED", "CLOSED"]
    delivery_effect: Literal["NONE", "RECHECK_ONLY"]


def expected_rework_effects(draft: ReworkApprovalDraft) -> ReworkExpectedEffects:
    """按冻结Java契约生成待审查影响，最终权限/状态和副作用由Java裁决。"""

    status: Literal["PENDING", "RUNNING", "BLOCKED", "FAILED", "COMPLETED"] = "RUNNING"
    issue: Literal["OPEN", "PROCESSING", "RESOLVED", "CLOSED"] = "PROCESSING"
    delivery: Literal["NONE", "RECHECK_ONLY"] = "NONE"
    if draft.operation in {"CREATE_LIFECYCLE_REWORK", "CREATE_NEXT_REWORK"}:
        status, issue = "PENDING", "OPEN"
    elif draft.operation == "BLOCK_REWORK":
        status = "BLOCKED"
    elif draft.operation == "FAIL_REWORK":
        status = "FAILED"
    elif draft.operation == "REGISTER_REWORK_INSPECTION" and all(
        item.result == "PASSED" for item in draft.request.items
    ):
        status, issue = "COMPLETED", "RESOLVED"
    elif draft.operation == "SUBMIT_REWORK_REVIEW":
        status = "COMPLETED"
        issue = "CLOSED" if draft.request.status == "APPROVED" else "OPEN"
        delivery = "RECHECK_ONLY" if draft.request.status == "APPROVED" else "NONE"
    return ReworkExpectedEffects(
        production_status_after="COMPLETED",
        rework_status_after=status,
        issue_status_after=issue,
        delivery_effect=delivery,
    )


class ReworkDraftReview(ReworkSchema):
    """完整审查包不包含人工确认凭证，也不提供已确认执行快照。"""

    draft: ReworkApprovalDraft
    pending_tool: ReworkApprovalToolName
    required_permission: Literal["REWORK_WRITE", "REVIEW_WRITE"]
    effect_semantics: Literal["EXPECTED_IF_JAVA_ACCEPTS"]
    expected_effects: ReworkExpectedEffects

    @model_validator(mode="after")
    def validate_review_metadata(self) -> Self:
        """不允许调用者伪造执行器、权限范围或隐藏检查/问题的副作用。"""

        permission = (
            "REVIEW_WRITE" if self.draft.operation == "SUBMIT_REWORK_REVIEW" else "REWORK_WRITE"
        )
        if (
            self.pending_tool != REWORK_APPROVAL_TOOLS[self.draft.operation]
            or self.required_permission != permission
            or self.expected_effects != expected_rework_effects(self.draft)
        ):
            raise ValueError("review metadata differs from the draft operation")
        return self


def review_rework_approval_draft(value: object) -> ReworkDraftReview:
    """纯函数生成可审查包，不读取Java、不写数据库、不创建或确认Approval。"""

    draft = parse_rework_approval_draft(value)
    return ReworkDraftReview(
        draft=draft,
        pending_tool=REWORK_APPROVAL_TOOLS[draft.operation],
        required_permission="REVIEW_WRITE"
        if draft.operation == "SUBMIT_REWORK_REVIEW"
        else "REWORK_WRITE",
        effect_semantics="EXPECTED_IF_JAVA_ACCEPTS",
        expected_effects=expected_rework_effects(draft),
    )
