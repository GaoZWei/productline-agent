"""M6.1 Approval草稿、修改副本和状态机单元测试。"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from app.models import (
    ApprovalRecord,
    ApprovalStatus,
    OperationType,
    PendingToolName,
)
from app.services import (
    ApprovalLifecycleService,
    ApprovalLifecycleValidationError,
    ApprovalNotFoundError,
    InvalidApprovalTransitionError,
)

_NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
_ORIGINAL_DRAFT = {
    "task_id": "TASK-003",
    "conclusion": "REWORK_REQUIRED",
    "problem_summary": "存在未关闭的坐标系质量问题",
    "review_comment": "完成坐标系统处理后重新提交复核",
    "specification_references": [],
    "suggested_rework": {
        "required": True,
        "type": "COORDINATE_SYSTEM_FIX",
    },
}


class _MemoryApprovalRepository:
    def __init__(self) -> None:
        self.records: dict[str, ApprovalRecord] = {}
        self.concurrent_status: ApprovalStatus | None = None

    async def create(self, approval: ApprovalRecord) -> ApprovalRecord:
        self.records[approval.approval_id] = approval
        return approval

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        return self.records.get(approval_id)

    async def transition_status(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        target_status: ApprovalStatus,
        changes: Mapping[str, Any],
    ) -> ApprovalRecord | None:
        approval = self.records.get(approval_id)
        if approval is None or approval.status is not expected_status:
            return None
        if self.concurrent_status is not None:
            approval.status = self.concurrent_status
            self.concurrent_status = None
            return None
        approval.status = target_status
        for field_name, value in changes.items():
            setattr(approval, field_name, value)
        return approval

    async def save_user_modified_draft(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        draft: dict[str, Any],
        updated_at: datetime,
    ) -> ApprovalRecord | None:
        approval = self.records.get(approval_id)
        if approval is None or approval.status is not expected_status:
            return None
        approval.user_modified_draft = draft
        approval.updated_at = updated_at
        return approval


def _service() -> tuple[ApprovalLifecycleService, _MemoryApprovalRepository]:
    repository = _MemoryApprovalRepository()
    return ApprovalLifecycleService(repository, now=lambda: _NOW), repository


async def _create_review_draft(
    service: ApprovalLifecycleService,
    *,
    approval_id: str = "approval-001",
) -> ApprovalRecord:
    return await service.create_draft(
        approval_id=approval_id,
        run_id="run-001",
        operation_type=OperationType.SUBMIT_REVIEW,
        original_draft=_ORIGINAL_DRAFT,
        pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
        target_id="TASK-003",
        target_version=0,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_draft_freezes_original_operation_tool_and_target_version() -> None:
    service, _ = _service()
    source: dict[str, Any] = {**_ORIGINAL_DRAFT, "specification_references": []}

    approval = await service.create_draft(
        approval_id=" approval-001 ",
        run_id=" run-001 ",
        operation_type=OperationType.SUBMIT_REVIEW,
        original_draft=source,
        pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
        target_id="TASK-003",
        target_version=0,
    )
    source["specification_references"].append("SPEC-CHANGED")

    assert approval.approval_id == "approval-001"
    assert approval.run_id == "run-001"
    assert approval.status is ApprovalStatus.DRAFT
    assert approval.operation_type is OperationType.SUBMIT_REVIEW
    assert approval.pending_tool_name is PendingToolName.WRITE_REVIEW_RESULT
    assert approval.target_id == "TASK-003"
    assert approval.target_version == 0
    assert approval.original_draft["specification_references"] == []
    assert approval.user_modified_draft is None
    assert approval.confirmed_by_user_id is None
    assert approval.confirmed_at is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_preserves_original_and_executes_user_modified_draft() -> None:
    service, _ = _service()
    approval = await _create_review_draft(service)
    await service.mark_waiting_confirmation(approval.approval_id)
    modified = await service.save_user_modification(
        approval.approval_id,
        modified_draft={**_ORIGINAL_DRAFT, "review_comment": "用户修改后的意见"},
    )
    assert modified.status is ApprovalStatus.WAITING_CONFIRMATION
    confirmed = await service.confirm(
        approval.approval_id,
        confirmed_by_user_id="reviewer-001",
    )
    assert confirmed.status is ApprovalStatus.CONFIRMED
    executing = await service.mark_executing(approval.approval_id)
    assert executing.status is ApprovalStatus.EXECUTING
    succeeded = await service.mark_succeeded(approval.approval_id)

    assert modified.original_draft == _ORIGINAL_DRAFT
    assert service.effective_draft(modified)["review_comment"] == "用户修改后的意见"
    assert service.effective_review_draft(modified).task_id == "TASK-003"
    assert confirmed.confirmed_by_user_id == "reviewer-001"
    assert confirmed.confirmed_at == _NOW
    assert succeeded.status is ApprovalStatus.SUCCEEDED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminal_paths_cover_cancel_expire_stale_and_failure() -> None:
    service, _ = _service()

    cancelled = await _create_review_draft(service, approval_id="approval-cancel")
    assert (await service.cancel(cancelled.approval_id)).status is ApprovalStatus.CANCELLED

    expired = await _create_review_draft(service, approval_id="approval-expire")
    await service.mark_waiting_confirmation(expired.approval_id)
    assert (await service.mark_expired(expired.approval_id)).status is ApprovalStatus.EXPIRED

    stale = await _create_review_draft(service, approval_id="approval-stale")
    await service.mark_waiting_confirmation(stale.approval_id)
    await service.confirm(stale.approval_id, confirmed_by_user_id="reviewer-001")
    assert (await service.mark_stale(stale.approval_id)).status is ApprovalStatus.STALE

    failed = await _create_review_draft(service, approval_id="approval-failed")
    await service.mark_waiting_confirmation(failed.approval_id)
    await service.confirm(failed.approval_id, confirmed_by_user_id="reviewer-001")
    await service.mark_executing(failed.approval_id)
    assert (await service.mark_failed(failed.approval_id)).status is ApprovalStatus.FAILED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_state_machine_blocks_skips_duplicate_confirmation_and_late_edit() -> None:
    service, _ = _service()
    approval = await _create_review_draft(service)

    with pytest.raises(InvalidApprovalTransitionError) as skipped:
        await service.mark_executing(approval.approval_id)
    assert skipped.value.current_status is ApprovalStatus.DRAFT

    await service.mark_waiting_confirmation(approval.approval_id)
    await service.confirm(approval.approval_id, confirmed_by_user_id="reviewer-001")
    with pytest.raises(InvalidApprovalTransitionError):
        await service.confirm(approval.approval_id, confirmed_by_user_id="reviewer-001")
    with pytest.raises(InvalidApprovalTransitionError):
        await service.save_user_modification(
            approval.approval_id,
            modified_draft={"review_comment": "确认后不得修改"},
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compare_and_set_reports_concurrent_status_instead_of_overwriting() -> None:
    service, repository = _service()
    approval = await _create_review_draft(service)
    await service.mark_waiting_confirmation(approval.approval_id)
    repository.concurrent_status = ApprovalStatus.CANCELLED

    with pytest.raises(InvalidApprovalTransitionError) as conflict:
        await service.confirm(approval.approval_id, confirmed_by_user_id="reviewer-001")

    assert conflict.value.current_status is ApprovalStatus.CANCELLED
    assert repository.records[approval.approval_id].confirmed_by_user_id is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_draft_rejects_mismatched_tool_invalid_target_and_json() -> None:
    service, _ = _service()

    with pytest.raises(ApprovalLifecycleValidationError) as mismatched:
        await service.create_draft(
            approval_id="approval-mismatch",
            run_id="run-001",
            operation_type=OperationType.SUBMIT_REVIEW,
            original_draft=_ORIGINAL_DRAFT,
            pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
            target_id="TASK-003",
            target_version=0,
        )
    assert mismatched.value.field_name == "pending_tool_name"

    with pytest.raises(ApprovalLifecycleValidationError) as target:
        await service.create_draft(
            approval_id="approval-target",
            run_id="run-001",
            operation_type=OperationType.CREATE_REWORK,
            original_draft=_ORIGINAL_DRAFT,
            pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
            target_id="ORDER-003",
            target_version=0,
        )
    assert target.value.field_name == "target_id"

    with pytest.raises(ApprovalLifecycleValidationError) as invalid_json:
        await service.create_draft(
            approval_id="approval-json",
            run_id="run-001",
            operation_type=OperationType.CREATE_REWORK,
            original_draft={"score": float("nan")},
            pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
            target_id="TASK-003",
            target_version=0,
        )
    assert invalid_json.value.field_name == "original_draft"

    with pytest.raises(ApprovalLifecycleValidationError) as draft_target:
        await service.create_draft(
            approval_id="approval-draft-target",
            run_id="run-001",
            operation_type=OperationType.SUBMIT_REVIEW,
            original_draft={**_ORIGINAL_DRAFT, "task_id": "TASK-004"},
            pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
            target_id="TASK-003",
            target_version=0,
        )
    assert draft_target.value.field_name == "original_draft.task_id"

    for invalid_version in (True, -1, 9_223_372_036_854_775_808):
        with pytest.raises(ApprovalLifecycleValidationError) as version:
            await service.create_draft(
                approval_id="approval-version",
                run_id="run-001",
                operation_type=OperationType.CREATE_REWORK,
                original_draft=_ORIGINAL_DRAFT,
                pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
                target_id="TASK-003",
                target_version=invalid_version,
            )
        assert version.value.field_name == "target_version"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_modification_must_remain_a_valid_draft_for_same_target() -> None:
    service, _ = _service()
    approval = await _create_review_draft(service)
    await service.mark_waiting_confirmation(approval.approval_id)

    with pytest.raises(ApprovalLifecycleValidationError) as invalid_schema:
        await service.save_user_modification(
            approval.approval_id,
            modified_draft={**_ORIGINAL_DRAFT, "conclusion": "PENDING"},
        )
    assert invalid_schema.value.field_name == "modified_draft"

    with pytest.raises(ApprovalLifecycleValidationError) as changed_target:
        await service.save_user_modification(
            approval.approval_id,
            modified_draft={**_ORIGINAL_DRAFT, "task_id": "TASK-004"},
        )
    assert changed_target.value.field_name == "modified_draft.task_id"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifecycle_rejects_missing_record_and_naive_timestamp() -> None:
    service, _ = _service()
    with pytest.raises(ApprovalNotFoundError):
        await service.mark_waiting_confirmation("approval-missing")

    naive_service = ApprovalLifecycleService(
        _MemoryApprovalRepository(),
        now=lambda: datetime(2026, 8, 26, 10, 0),
    )
    approval = await _create_review_draft(naive_service)
    with pytest.raises(ApprovalLifecycleValidationError) as timestamp:
        await naive_service.mark_waiting_confirmation(approval.approval_id)
    assert timestamp.value.field_name == "timestamp"
