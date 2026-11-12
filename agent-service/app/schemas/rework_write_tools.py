"""M8写Tool的独立执行契约，不复用旧ReviewDraft或接收调用方业务正文。"""

from typing import Self

from pydantic import AwareDatetime, model_validator

from app.models import ApprovalStatus
from app.schemas.rework import (
    Actor,
    BusinessId,
    CreateLifecycleReworkRequest,
    RegisterReworkInspectionRequest,
    RegisterReworkResultRequest,
    ReworkOperation,
    ReworkReasonRequest,
    ReworkSchema,
    ReworkVersionRequest,
    ReworkWriteReceipt,
    SafeVersion,
    Sequence,
    SubmitReworkReviewRequest,
    TaskId,
)
from app.schemas.write_tools import ApprovalIdentifier, IdempotencyKey, JavaTraceIdentifier
from app.tools.models import ContextIdentifier

type ReworkWriteRequest = (
    CreateLifecycleReworkRequest
    | ReworkReasonRequest
    | RegisterReworkResultRequest
    | RegisterReworkInspectionRequest
    | SubmitReworkReviewRequest
    | ReworkVersionRequest
)

_REQUEST_TYPES: dict[ReworkOperation, type[ReworkVersionRequest]] = {
    "CREATE_LIFECYCLE_REWORK": CreateLifecycleReworkRequest,
    "START_REWORK": ReworkVersionRequest,
    "BLOCK_REWORK": ReworkReasonRequest,
    "FAIL_REWORK": ReworkReasonRequest,
    "RESUME_REWORK": ReworkReasonRequest,
    "REGISTER_REWORK_RESULT": RegisterReworkResultRequest,
    "REGISTER_REWORK_INSPECTION": RegisterReworkInspectionRequest,
    "SUBMIT_REWORK_REVIEW": SubmitReworkReviewRequest,
    "CREATE_NEXT_REWORK": ReworkReasonRequest,
}


class ReworkWriteInput(ReworkSchema):
    """模型或页面只能引用确认单及其绑定键，不能覆盖目标、版本或材料。"""

    approval_id: ApprovalIdentifier
    idempotency_key: IdempotencyKey


class ReworkExecutionSnapshot(ReworkSchema):
    """受信确认Store提供的执行快照，T823不生成确认或取得执行权。"""

    approval_id: ApprovalIdentifier
    run_id: ContextIdentifier
    owner_user_id: Actor
    confirmed_by_user_id: Actor | None
    confirmed_at: AwareDatetime | None
    expires_at: AwareDatetime
    status: ApprovalStatus
    operation: ReworkOperation
    idempotency_key: IdempotencyKey
    task_id: TaskId
    task_version: SafeVersion
    source_issue_id: BusinessId
    rework_task_id: BusinessId | None
    round_number: Sequence | None
    previous_rework_task_id: BusinessId | None
    processing_revision: Sequence | None
    inspection_id: BusinessId | None
    review_id: BusinessId | None
    request: ReworkWriteRequest

    @model_validator(mode="after")
    def validate_request_binding(self) -> Self:
        """检查完整材料与已确认事实绑定，不以Python快照替代Java最终校验。"""

        if type(self.request) is not _REQUEST_TYPES[self.operation]:
            raise ValueError("request does not match the confirmed operation")
        if self.request.expected_version != self.task_version:
            raise ValueError("request version differs from confirmed task version")
        if self.inspection_id is not None and self.processing_revision is None:
            raise ValueError("inspection requires a processing revision")
        if self.review_id is not None and self.inspection_id is None:
            raise ValueError("review requires an inspection")
        if self.operation == "CREATE_LIFECYCLE_REWORK":
            if any(
                value is not None
                for value in (
                    self.rework_task_id,
                    self.round_number,
                    self.previous_rework_task_id,
                    self.processing_revision,
                    self.inspection_id,
                    self.review_id,
                )
            ):
                raise ValueError("first creation cannot inherit lifecycle bindings")
            if (
                not isinstance(self.request, CreateLifecycleReworkRequest)
                or self.request.source_issue_id != self.source_issue_id
            ):
                raise ValueError("first creation source differs from confirmed issue")
        else:
            if self.rework_task_id is None or self.round_number is None:
                raise ValueError("existing operation requires a managed round")
            if (self.round_number == 1) != (self.previous_rework_task_id is None):
                raise ValueError("predecessor differs from the confirmed round")
            if self.previous_rework_task_id == self.rework_task_id:
                raise ValueError("round cannot be its own predecessor")
        if isinstance(self.request, (RegisterReworkInspectionRequest, SubmitReworkReviewRequest)):
            if self.request.processing_revision != self.processing_revision:
                raise ValueError("request processing revision differs from confirmation")
        if (
            isinstance(self.request, SubmitReworkReviewRequest)
            and self.request.inspection_id != self.inspection_id
        ):
            raise ValueError("request inspection differs from confirmation")
        return self


class ReworkWriteOutput(ReworkSchema):
    """保留Java首次原回执与链路标识，不重新构造当前业务状态。"""

    approval_id: ApprovalIdentifier
    receipt: ReworkWriteReceipt
    java_trace_id: JavaTraceIdentifier
