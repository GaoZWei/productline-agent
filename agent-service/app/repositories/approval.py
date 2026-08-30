"""人工确认记录的异步持久化访问。"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRecord, ApprovalStatus


class ApprovalRecordRepository:
    """只封装Approval的创建、查询和compare-and-set更新。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, approval: ApprovalRecord) -> ApprovalRecord:
        """保存草稿并立即flush, 及时暴露主键、外键和检查约束错误。"""

        self._session.add(approval)
        await self._session.flush()
        return approval

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        """按审批标识查询记录。"""

        return await self._session.get(ApprovalRecord, approval_id)

    async def list_by_run(self, run_id: str) -> list[ApprovalRecord]:
        """按创建时间稳定返回Run产生的人工确认记录。"""

        statement = (
            select(ApprovalRecord)
            .where(ApprovalRecord.run_id == run_id)
            .order_by(ApprovalRecord.created_at, ApprovalRecord.approval_id)
        )
        return list((await self._session.scalars(statement)).all())
    # 防止重复确认或重复执行
    async def transition_status(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        target_status: ApprovalStatus,
        changes: Mapping[str, Any],
    ) -> ApprovalRecord | None:
        """原子比较当前状态后更新, 防止重复确认或重复执行。"""

        allowed_changes = {
            "confirmed_by_user_id",
            "confirmed_at",
            "updated_at",
        }
        unexpected = set(changes) - allowed_changes
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(f"unsupported approval transition fields: {names}")
        statement = (
            update(ApprovalRecord)
            .where(
                ApprovalRecord.approval_id == approval_id,
                ApprovalRecord.status == expected_status,
            )
            .values(status=target_status, **changes)
            .returning(ApprovalRecord)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def save_user_modified_draft(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        draft: dict[str, Any],
        updated_at: datetime,
    ) -> ApprovalRecord | None:
        """只在预期状态下覆盖用户修改副本, 永远不改原始草稿。"""

        statement = (
            update(ApprovalRecord)
            .where(
                ApprovalRecord.approval_id == approval_id,
                ApprovalRecord.status == expected_status,
            )
            .values(user_modified_draft=draft, updated_at=updated_at)
            .returning(ApprovalRecord)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def save_execution_result(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        result: dict[str, Any],
        updated_at: datetime,
    ) -> ApprovalRecord | None:
        """只为执行中的Approval首次保存Java成功结果, 不覆盖既有证据。"""

        statement = (
            update(ApprovalRecord)
            .where(
                ApprovalRecord.approval_id == approval_id,
                ApprovalRecord.status == expected_status,
                ApprovalRecord.execution_result.is_(None),
            )
            .values(execution_result=result, updated_at=updated_at)
            .returning(ApprovalRecord)
        )
        return (await self._session.scalars(statement)).one_or_none()
