"""M6.3最近诊断读取与Approval/Run原子持久化实现。"""

from datetime import UTC, datetime

from app.database import Database
from app.models import OperationType, PendingToolName
from app.repositories import (
    AgentRunRepository,
    AgentSessionRepository,
    ApprovalRecordRepository,
)
from app.schemas.approval import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.services.approval_lifecycle import ApprovalLifecycleService
from app.services.run_lifecycle import RunLifecycleService
from app.services.session_context import SessionContextService
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
            # 定位最近一个带结果的Run
            run = await AgentRunRepository(session).latest_result_by_session(session_id)
            if run is None:
                return None
            return ReviewDraftRunSnapshot(
                run_id=run.run_id,
                status=run.status,
                final_result=run.final_result,
            )
    # 原子保存Approval和Run状态
    async def save_waiting_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        draft: ReviewDraft,
        target_version: int,
    ) -> ReviewDraftPersistenceResult:
        """在同一事务内保存草稿并推进Approval和Run, 任一步失败都回滚。"""

        async with self._database.session() as session, session.begin():
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
            # 来源Run进入等待Approval状态
            run = await RunLifecycleService(AgentRunRepository(session)).mark_waiting_approval(
                run_id
            )
            return ReviewDraftPersistenceResult(
                approval_id=approval.approval_id,
                approval_status=approval.status,
                run_status=run.status,
            )
