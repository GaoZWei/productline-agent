"""M6.3最近诊断读取与Approval/Run原子持久化实现。"""

from datetime import UTC, datetime

from pydantic import ValidationError

from app.database import Database
from app.models import AgentRunStatus, AgentStepType, ApprovalStatus, OperationType, PendingToolName
from app.repositories import (
    AgentRunRepository,
    AgentSessionRepository,
    AgentStepRepository,
    ApprovalRecordRepository,
)
from app.schemas.agent_messages import ApprovalAgentResult, DiagnosisAgentResult
from app.schemas.approval import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.workflow import DiagnosisResult
from app.services.approval_lifecycle import ApprovalLifecycleService
from app.services.approval_run_lifecycle import approval_step_id
from app.services.run_lifecycle import RunLifecycleService
from app.services.session_context import SessionContextService
from app.services.step_lifecycle import StepLifecycleService
from app.workflows.review_draft import (
    ReviewDraftPersistenceResult,
    ReviewDraftRunSnapshot,
)


class DatabaseReviewDraftStore:
    """使用短事务读取诊断, 并原子保存Approval与等待确认Run状态。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def latest_diagnosis(
        self,
        session_id: str,
        *,
        identity: BusinessIdentity,
    ) -> ReviewDraftRunSnapshot | None:
        """校验会话所有权和有效期后读取最近诊断Run快照。"""

        async with self._database.session() as session:
            agent_session = await AgentSessionRepository(session).get(session_id)
            SessionContextService.ensure_access(
                agent_session,
                identity=identity,
                now=datetime.now(UTC),
            )
            # 只选择能恢复为诊断Schema的最近成功Run, 不把规范问答或旧Approval当来源。
            runs = await AgentRunRepository(session).recent_successful_results_by_session(
                session_id
            )
            for run in runs:
                try:
                    DiagnosisAgentResult.model_validate(run.final_result, strict=False)
                except ValidationError:
                    try:
                        DiagnosisResult.model_validate(run.final_result, strict=False)
                    except ValidationError:
                        continue
                return ReviewDraftRunSnapshot(
                    run_id=run.run_id,
                    status=run.status,
                    final_result=run.final_result,
                )
            return None
    # 原子保存Approval和Run状态
    async def save_waiting_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        source_run_id: str,
        draft: ReviewDraft,
        target_version: int,
    ) -> ReviewDraftPersistenceResult:
        """在同一事务内保存草稿并推进Approval和Run, 任一步失败都回滚。"""

        async with self._database.session() as session, session.begin():
            runs = AgentRunRepository(session)
            steps = AgentStepRepository(session)
            current_run = await runs.get_for_update(run_id)
            source_run = await runs.get(source_run_id)
            if (
                current_run is None
                or current_run.status is not AgentRunStatus.RUNNING
                or source_run is None
                or source_run.status is not AgentRunStatus.SUCCEEDED
                or source_run.session_id != current_run.session_id
            ):
                raise ValueError("review and source Run relationship is invalid")
            approval_lifecycle = ApprovalLifecycleService(ApprovalRecordRepository(session))
            # 创建Approval草稿
            approval = await approval_lifecycle.create_draft(
                approval_id=approval_id,
                run_id=run_id,
                operation_type=OperationType.SUBMIT_REVIEW,
                original_draft=draft,
                pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
                target_id=draft.task_id,
                target_version=target_version,
            )
            # Approval进入等待用户确认状态
            approval = await approval_lifecycle.mark_waiting_confirmation(approval.approval_id)
            await StepLifecycleService(steps, runs).start_step(
                step_id=approval_step_id(approval_id),
                run_id=run_id,
                sequence_number=await steps.next_sequence_number(run_id),
                step_type=AgentStepType.APPROVAL,
                step_name="wait_for_review_confirmation",
                input_summary=f"approval={approval_id};operation=SUBMIT_REVIEW",
            )
            result = ApprovalAgentResult(
                approval_id=approval_id,
                run_id=run_id,
                source_run_id=source_run_id,
                status=ApprovalStatus.WAITING_CONFIRMATION,
                operation_type=OperationType.SUBMIT_REVIEW,
                target_id=draft.task_id,
                target_version=target_version,
                draft=draft,
            )
            # 当前Review Run等待确认; 最近诊断Run继续保持SUCCEEDED。
            run = await RunLifecycleService(runs).mark_waiting_approval(
                run_id,
                source_run_id=source_run_id,
                final_result=result.model_dump(mode="json"),
            )
            return ReviewDraftPersistenceResult(
                approval_id=approval.approval_id,
                approval_status=approval.status,
                run_status=run.status,
            )
