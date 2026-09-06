"""Approval取消和独立返工授权的生产编排。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.database import Database
from app.models import (
    AgentRunStatus,
    AgentSession,
    AgentStepType,
    ApprovalStatus,
    OperationType,
    PendingToolName,
)
from app.repositories import (
    AgentRunRepository,
    AgentSessionRepository,
    AgentStepRepository,
    ApprovalRecordRepository,
)
from app.schemas.agent_messages import ApprovalAgentResult
from app.schemas.business import BusinessIdentity
from app.schemas.context import PageContext
from app.schemas.versioning import RunVersionSnapshot
from app.schemas.write_tools import WriteReviewResultOutput
from app.services.approval_lifecycle import ApprovalLifecycleService
from app.services.approval_run_lifecycle import approval_step_id, finish_waiting_approval
from app.services.run_lifecycle import RunLifecycleService
from app.services.session_context import SessionContextError, SessionContextService
from app.services.step_lifecycle import StepLifecycleService


class ApprovalOrchestrationError(Exception):
    """取消或创建返工授权无法安全完成。"""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ApprovalCancellation:
    """取消后返回的Approval和Run终态。"""

    approval_id: str
    run_id: str
    status: ApprovalStatus
    run_status: AgentRunStatus


@dataclass(frozen=True, slots=True)
class ReworkApprovalCreation:
    """显式返工请求创建的独立Run和Approval。"""

    run_id: str
    result: ApprovalAgentResult


class ApprovalOrchestrationService:
    """在Agent数据库内取消待确认单, 或从成功复核创建第二份返工授权。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def cancel(
        self,
        approval_id: str,
        *,
        identity: BusinessIdentity,
    ) -> ApprovalCancellation:
        """只有会话所有者可取消WAITING_CONFIRMATION, 且不会调用Java写Tool。"""

        _require_reviewer(identity)
        async with self._database.session() as session, session.begin():
            approvals = ApprovalRecordRepository(session)
            approval = await approvals.get(approval_id)
            if approval is None:
                raise _not_found()
            approval_run_id = _require_run_id(approval.run_id)
            run = await AgentRunRepository(session).get(approval_run_id)
            if run is None:
                raise _not_found()
            owner = await AgentSessionRepository(session).get(run.session_id)
            _ensure_owner(owner, identity)
            if approval.status is ApprovalStatus.CANCELLED:
                return ApprovalCancellation(
                    approval_id=approval.approval_id,
                    run_id=run.run_id,
                    status=approval.status,
                    run_status=run.status,
                )
            if approval.status is not ApprovalStatus.WAITING_CONFIRMATION:
                raise ApprovalOrchestrationError(
                    code="APPROVAL_NOT_CANCELLABLE",
                    message=f"approval cannot be cancelled from {approval.status.value}",
                    status_code=409,
                )
            cancelled = await ApprovalLifecycleService(approvals).cancel(approval_id)
            await finish_waiting_approval(
                session,
                run_id=approval_run_id,
                approval_id=cancelled.approval_id,
                approval_status=ApprovalStatus.CANCELLED,
            )
            finished_run = await AgentRunRepository(session).get(approval_run_id)
            assert finished_run is not None
            return ApprovalCancellation(
                approval_id=cancelled.approval_id,
                run_id=approval_run_id,
                status=cancelled.status,
                run_status=finished_run.status,
            )

    async def create_rework(
        self,
        source_approval_id: str,
        *,
        identity: BusinessIdentity,
    ) -> ReworkApprovalCreation:
        """从已成功提交且明确要求返工的复核, 创建全新的待确认Approval Run。"""

        _require_reviewer(identity)
        async with self._database.session() as session, session.begin():
            approvals = ApprovalRecordRepository(session)
            source = await approvals.get(source_approval_id)
            if source is None:
                raise _not_found()
            runs = AgentRunRepository(session)
            source_run = await runs.get_for_update(_require_run_id(source.run_id))
            if source_run is None:
                raise _not_found()
            owner = await AgentSessionRepository(session).get(source_run.session_id)
            _ensure_owner(owner, identity)
            if (
                source.operation_type is not OperationType.SUBMIT_REVIEW
                or source.status is not ApprovalStatus.SUCCEEDED
                or source_run.status is not AgentRunStatus.SUCCEEDED
            ):
                raise ApprovalOrchestrationError(
                    code="REWORK_SOURCE_NOT_READY",
                    message="rework approval requires a succeeded SUBMIT_REVIEW approval",
                    status_code=409,
                )
            existing = await self._existing_rework(approvals, runs, source_run.run_id)
            if existing is not None:
                return existing
            draft = ApprovalLifecycleService.effective_review_draft(source)
            if not draft.suggested_rework.required:
                raise ApprovalOrchestrationError(
                    code="REWORK_NOT_REQUESTED",
                    message="confirmed review does not require rework",
                    status_code=409,
                )
            try:
                review_result = WriteReviewResultOutput.model_validate(source.execution_result)
                version_snapshot = RunVersionSnapshot.model_validate(
                    source_run.version_snapshot,
                    strict=False,
                )
                page_context = (
                    PageContext.model_validate(source_run.page_context_snapshot, strict=False)
                    if source_run.page_context_snapshot is not None
                    else None
                )
            except ValidationError as error:
                raise ApprovalOrchestrationError(
                    code="REWORK_SOURCE_INVALID",
                    message="succeeded review evidence cannot create a rework approval",
                    status_code=409,
                ) from error

            run_id = f"run-rework-{uuid4().hex}"
            approval_id = f"approval-rework-{uuid4().hex}"
            run_lifecycle = RunLifecycleService(runs)
            await run_lifecycle.create_run(
                run_id=run_id,
                session_id=source_run.session_id,
                version_snapshot=version_snapshot,
                page_context_snapshot=page_context,
            )
            await run_lifecycle.mark_running(run_id)
            created = await ApprovalLifecycleService(approvals).create_draft(
                approval_id=approval_id,
                run_id=run_id,
                operation_type=OperationType.CREATE_REWORK,
                original_draft=draft,
                pending_tool_name=PendingToolName.CREATE_REWORK_TASK,
                target_id=draft.task_id,
                target_version=review_result.task_version,
            )
            waiting = await ApprovalLifecycleService(approvals).mark_waiting_confirmation(
                created.approval_id
            )
            steps = AgentStepRepository(session)
            await StepLifecycleService(steps, runs).start_step(
                step_id=approval_step_id(approval_id),
                run_id=run_id,
                sequence_number=await steps.next_sequence_number(run_id),
                step_type=AgentStepType.APPROVAL,
                step_name="wait_for_rework_confirmation",
                input_summary=f"approval={approval_id};operation=CREATE_REWORK",
            )
            result = ApprovalAgentResult(
                approval_id=approval_id,
                run_id=run_id,
                source_run_id=source_run.run_id,
                status=waiting.status,
                operation_type=OperationType.CREATE_REWORK,
                target_id=draft.task_id,
                target_version=review_result.task_version,
                draft=draft,
            )
            await run_lifecycle.mark_waiting_approval(
                run_id,
                source_run_id=source_run.run_id,
                final_result=result.model_dump(mode="json"),
            )
            return ReworkApprovalCreation(run_id=run_id, result=result)

    @staticmethod
    async def _existing_rework(
        approvals: ApprovalRecordRepository,
        runs: AgentRunRepository,
        source_run_id: str,
    ) -> ReworkApprovalCreation | None:
        """同一成功复核的重复请求复用活动授权, 已结束授权允许重新创建。"""

        for child in await runs.list_by_source_run(source_run_id):
            try:
                result = ApprovalAgentResult.model_validate(child.final_result)
            except ValidationError:
                continue
            if result.operation_type is not OperationType.CREATE_REWORK:
                continue
            approval = await approvals.get(result.approval_id)
            if approval is None:
                continue
            if approval.status in {
                ApprovalStatus.CANCELLED,
                ApprovalStatus.EXPIRED,
                ApprovalStatus.STALE,
                ApprovalStatus.FAILED,
            }:
                continue
            return ReworkApprovalCreation(
                run_id=child.run_id,
                result=result.model_copy(update={"status": approval.status}),
            )
        return None


def _require_reviewer(identity: BusinessIdentity) -> None:
    if identity.role != "REVIEWER":
        raise ApprovalOrchestrationError(
            code="PERMISSION_DENIED",
            message="reviewer permission is required",
            status_code=403,
        )


def _ensure_owner(owner: AgentSession | None, identity: BusinessIdentity) -> None:
    try:
        SessionContextService.ensure_access(owner, identity=identity, now=datetime.now(UTC))
    except SessionContextError as error:
        raise _not_found() from error


def _not_found() -> ApprovalOrchestrationError:
    return ApprovalOrchestrationError(
        code="APPROVAL_NOT_FOUND",
        message="approval was not found",
        status_code=404,
    )


def _require_run_id(run_id: str | None) -> str:
    if run_id is None:
        raise _not_found()
    return run_id
