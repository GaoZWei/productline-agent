"""写Tool读取已确认Approval并持久化Java成功结果的短事务边界。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.database import Database
from app.models import ApprovalStatus, PendingToolName
from app.repositories import ApprovalRecordRepository
from app.schemas import ReviewDraft
from app.services.approval_lifecycle import ApprovalLifecycleService

# 只包含写Tool执行所需的最小数据
@dataclass(frozen=True, slots=True)
class ApprovalExecutionSnapshot:
    """写Tool所需的最小不可变Approval快照。"""

    approval_id: str
    status: ApprovalStatus
    pending_tool_name: PendingToolName
    target_id: str
    target_version: int
    confirmed_by_user_id: str | None
    draft: ReviewDraft


class ApprovalExecutionStore(Protocol):
    """隔离写Tool与数据库会话生命周期。"""

    async def get_execution_snapshot(
        self,
        approval_id: str,
    ) -> ApprovalExecutionSnapshot | None: ...

    async def save_execution_result(
        self,
        approval_id: str,
        *,
        result: dict[str, Any],
    ) -> bool: ...


class DatabaseApprovalExecutionStore:
    """使用独立短事务读取Approval并以比较更新保存首次执行结果。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_execution_snapshot(
        self,
        approval_id: str,
    ) -> ApprovalExecutionSnapshot | None:
        async with self._database.session() as session:
            approval = await ApprovalRecordRepository(session).get(approval_id)
            if approval is None:
                return None
            return ApprovalExecutionSnapshot(
                approval_id=approval.approval_id,
                status=approval.status,
                pending_tool_name=approval.pending_tool_name,
                target_id=approval.target_id,
                target_version=approval.target_version,
                confirmed_by_user_id=approval.confirmed_by_user_id,
                draft=ApprovalLifecycleService.effective_review_draft(approval),
            )

    async def save_execution_result(
        self,
        approval_id: str,
        *,
        result: dict[str, Any],
    ) -> bool:
        async with self._database.session() as session, session.begin():
            repository = ApprovalRecordRepository(session)
            updated = await repository.save_execution_result(
                approval_id,
                expected_status=ApprovalStatus.EXECUTING,
                result=result,
                updated_at=datetime.now(UTC),
            )
            if updated is not None:
                return True
            current = await repository.get(approval_id)
            # Java幂等重放会生成新的请求Trace; 业务结果相同则保留首次Trace并视为成功。
            return current is not None and _same_idempotent_result(
                current.execution_result,
                result,
            )


def _same_idempotent_result(
    stored: dict[str, Any] | None,
    replayed: dict[str, Any],
) -> bool:
    """比较Java资源结果并忽略每次HTTP请求都会变化的Trace ID。"""

    if stored is None:
        return False
    stored_business_result = dict(stored)
    replayed_business_result = dict(replayed)
    stored_business_result.pop("java_trace_id", None)
    replayed_business_result.pop("java_trace_id", None)
    return stored_business_result == replayed_business_result
