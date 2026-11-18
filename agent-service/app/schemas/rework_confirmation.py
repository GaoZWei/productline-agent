"""独立返工审查、确认与执行证据契约，Schema不能替代权限和人工确认。"""

from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from app.schemas.rework import Actor, ReworkSchema, SafeVersion
from app.schemas.rework_approval import ReworkApprovalDraft, ReworkApprovalTarget
from app.schemas.rework_draft import PreparedReworkDraft
from app.schemas.rework_execution import ReworkReceiptEvidence
from app.schemas.write_tools import ApprovalIdentifier, IdempotencyKey
from app.tools.models import ContextIdentifier, ToolError

type ReworkConfirmationStatus = Literal[
    "WAITING_CONFIRMATION", "CONFIRMED", "CANCELLED", "EXPIRED", "STALE", "EXECUTING", "SUCCEEDED"
]


class ReworkConfirmationRequest(ReworkSchema):
    """人工确认提交完整最终草稿，不能自报状态、时间、权限或执行键。"""

    approval_id: ApprovalIdentifier
    draft: ReworkApprovalDraft


class ReworkConfirmationSnapshot(ReworkSchema):
    """原审查与确认事实不可替换，T829执行键和回执只由受控Store记录。"""

    approval_id: ApprovalIdentifier
    run_id: ContextIdentifier
    owner_user_id: Actor
    revision: SafeVersion
    status: ReworkConfirmationStatus
    prepared: PreparedReworkDraft
    created_at: AwareDatetime
    expires_at: AwareDatetime
    confirmed_draft: ReworkApprovalDraft | None = None
    confirmed_by_user_id: Actor | None = None
    confirmed_at: AwareDatetime | None = None
    execution_key: IdempotencyKey | None = None
    claimed_at: AwareDatetime | None = None
    submission_started_at: AwareDatetime | None = None
    receipt_evidence: ReworkReceiptEvidence | None = None
    execution_error: ToolError | None = None

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Self:
        """拒绝不完整确认、自报对象与已保存材料冲突以及错误生命周期时间。"""

        if self.expires_at <= self.created_at:
            raise ValueError("confirmation expiry must follow creation")
        present = (self.confirmed_draft, self.confirmed_by_user_id, self.confirmed_at)
        has_confirmation = all(v is not None for v in present)
        if (
            (any(v is not None for v in present) and not has_confirmation)
            or (self.status in {"CONFIRMED", "EXECUTING", "SUCCEEDED"} and not has_confirmation)
            or (self.status in {"WAITING_CONFIRMATION", "CANCELLED"} and has_confirmation)
        ):
            raise ValueError("confirmation facts differ from status")
        if self.confirmed_at is not None and (
            not self.created_at <= self.confirmed_at < self.expires_at
            or self.confirmed_by_user_id != self.owner_user_id
        ):
            raise ValueError("confirmation actor or time is invalid")
        executing = self.status in {"EXECUTING", "SUCCEEDED"}
        if executing != (self.execution_key is not None and self.claimed_at is not None):
            raise ValueError("execution claim differs from status")
        if not executing and any(
            v is not None
            for v in (
                self.execution_key,
                self.claimed_at,
                self.submission_started_at,
                self.receipt_evidence,
                self.execution_error,
            )
        ):
            raise ValueError("unclaimed confirmation cannot contain execution facts")
        if self.claimed_at is not None and (
            self.confirmed_at is None or not self.confirmed_at <= self.claimed_at < self.expires_at
        ):
            raise ValueError("execution claim is outside its confirmation window")
        if self.submission_started_at is not None and (
            self.claimed_at is None
            or not self.claimed_at <= self.submission_started_at < self.expires_at
        ):
            raise ValueError("submission time is outside its execution window")
        if (self.status == "SUCCEEDED") != (self.receipt_evidence is not None):
            raise ValueError("success requires persisted receipt evidence")
        if self.receipt_evidence is not None and (
            self.receipt_evidence.approval_id != self.approval_id
            or self.submission_started_at is None
            or self.execution_error is not None
        ):
            raise ValueError("receipt is not attached to a submitted execution")
        draft = self.prepared.review.draft
        task, detail = self.prepared.current_task, self.prepared.current_rework
        actual = ReworkApprovalTarget(
            task_id=task.task_id,
            task_version=task.task_version,
            source_issue_id=draft.target.source_issue_id,
            rework_task_id=detail.rework_task.rework_task_id if detail else None,
            round_number=detail.round_number if detail else None,
            previous_rework_task_id=detail.previous_rework_task_id if detail else None,
            processing_revision=detail.processing.processing_revision
            if detail and detail.processing
            else None,
            artifact=detail.processing.artifact if detail and detail.processing else None,
            inspection_id=detail.inspection.inspection_id if detail and detail.inspection else None,
            review_id=detail.review.review_id if detail and detail.review else None,
        )
        if (
            actual != draft.target
            or not any(row.issue.issue_id == actual.source_issue_id for row in task.issues)
            or (
                detail is not None
                and (
                    detail.rework_task.task_id != actual.task_id
                    or detail.task_version != actual.task_version
                    or detail.rework_task.source_issue_id != actual.source_issue_id
                )
            )
        ):
            raise ValueError("prepared facts differ from the reviewed target")
        if self.confirmed_draft is not None and (
            self.confirmed_draft.operation != draft.operation
            or self.confirmed_draft.target != draft.target
        ):
            raise ValueError("confirmed draft replaced its target or operation")
        return self
