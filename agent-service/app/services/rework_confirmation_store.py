"""T828审查快照持久化和短事务状态比较，不实现写Tool执行Store。"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.models import AgentRun, AgentRunStatus, AgentSession, ReworkConfirmationRecord
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.tools.models import ToolContext


class ReworkConfirmationStore(Protocol):
    """只对归属当前用户/Run且会话未过期的审查记录操作。"""

    async def create(
        self, snapshot: ReworkConfirmationSnapshot, *, context: ToolContext, now: datetime
    ) -> bool:
        """原始快照只插入一次，冲突不覆盖。"""
        ...

    async def get(
        self, approval_id: str, *, context: ToolContext, now: datetime
    ) -> ReworkConfirmationSnapshot | None:
        """归属不符和不存在统一返回None，不泄露其他用户材料。"""
        ...

    async def transition(
        self,
        expected: ReworkConfirmationSnapshot,
        updated: ReworkConfirmationSnapshot,
        *,
        context: ToolContext,
        now: datetime,
    ) -> bool:
        """完整快照比较后转换一次，取消、到期及并发变动不得被覆盖。"""
        ...


class DatabaseReworkConfirmationStore:
    """只读写Agent自有表，Java网络查询不放入数据库事务。"""

    def __init__(
        self, database: Database, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._database = database
        self._now = now

    @staticmethod
    async def _accessible(session: AsyncSession, context: ToolContext, now: datetime) -> bool:
        """从真实Run/Session关系检查归属、会话有效期及Run仍可操作。"""

        return (
            await session.scalar(
                select(AgentRun.run_id)
                .join(AgentSession)
                .where(
                    AgentRun.run_id == context.run_id,
                    AgentRun.status.in_([AgentRunStatus.RUNNING, AgentRunStatus.WAITING_APPROVAL]),
                    AgentSession.user_id == context.identity.user_id,
                    AgentSession.expires_at > now,
                )
            )
        ) is not None

    async def create(
        self, snapshot: ReworkConfirmationSnapshot, *, context: ToolContext, now: datetime
    ) -> bool:
        """拒绝越权、复用身份及非初始快照，保留原审查内容。"""

        snapshot = ReworkConfirmationSnapshot.model_validate_json(snapshot.model_dump_json())
        if (
            snapshot.owner_user_id != context.identity.user_id
            or snapshot.run_id != context.run_id
            or snapshot.status != "WAITING_CONFIRMATION"
            or snapshot.revision != 0
            or snapshot.expires_at <= now
        ):
            return False
        try:
            async with self._database.session() as session, session.begin():
                if not await self._accessible(session, context, now):
                    return False
                session.add(
                    ReworkConfirmationRecord(
                        approval_id=snapshot.approval_id,
                        run_id=snapshot.run_id,
                        owner_user_id=snapshot.owner_user_id,
                        revision=snapshot.revision,
                        status=snapshot.status,
                        snapshot=snapshot.model_dump(mode="json"),
                        created_at=snapshot.created_at,
                        expires_at=snapshot.expires_at,
                    )
                )
                await session.flush()
            return True
        except IntegrityError:
            return False

    async def get(
        self, approval_id: str, *, context: ToolContext, now: datetime
    ) -> ReworkConfirmationSnapshot | None:
        """短事务读取并严格恢复快照，损坏数据不降级成不存在。"""

        async with self._database.session() as session:
            if not await self._accessible(session, context, now):
                return None
            row = await session.get(ReworkConfirmationRecord, approval_id)
            if (
                row is None
                or row.run_id != context.run_id
                or row.owner_user_id != context.identity.user_id
            ):
                return None
            return self._snapshot(row)

    async def transition(
        self,
        expected: ReworkConfirmationSnapshot,
        updated: ReworkConfirmationSnapshot,
        *,
        context: ToolContext,
        now: datetime,
    ) -> bool:
        """只允许WAITING到确认/取消/过期/失效，不领取任何执行权。"""

        expected = ReworkConfirmationSnapshot.model_validate_json(expected.model_dump_json())
        updated = ReworkConfirmationSnapshot.model_validate_json(updated.model_dump_json())
        immutable = {
            "approval_id",
            "run_id",
            "owner_user_id",
            "prepared",
            "created_at",
            "expires_at",
        }
        if (
            expected.status != "WAITING_CONFIRMATION"
            or updated.status not in {"CONFIRMED", "CANCELLED", "EXPIRED", "STALE"}
            or updated.revision != expected.revision + 1
            or any(getattr(expected, key) != getattr(updated, key) for key in immutable)
            or expected.run_id != context.run_id
            or expected.owner_user_id != context.identity.user_id
            or (
                updated.status == "CONFIRMED"
                and (updated.confirmed_at != now or now >= expected.expires_at)
            )
            or (updated.status == "EXPIRED" and now < expected.expires_at)
        ):
            return False
        async with self._database.session() as session, session.begin():
            if not await self._accessible(session, context, now):
                return False
            row = await session.scalar(
                select(ReworkConfirmationRecord)
                .where(
                    ReworkConfirmationRecord.approval_id == expected.approval_id,
                )
                .with_for_update()
            )
            if row is None or self._snapshot(row) != expected:
                return False
            # 等待数据库锁也可能耗尽确认窗口，取锁后必须用新时钟再次检查。
            current_time = self._now()
            if current_time.tzinfo is None or current_time.utcoffset() is None:
                raise ValueError("confirmation store clock must have a timezone")
            if (updated.status != "EXPIRED" and current_time >= expected.expires_at) or (
                updated.status == "EXPIRED" and current_time < expected.expires_at
            ):
                return False
            if not await self._accessible(session, context, current_time):
                return False
            row.snapshot = updated.model_dump(mode="json")
            row.status, row.revision = updated.status, updated.revision
            return True

    @staticmethod
    def _snapshot(row: ReworkConfirmationRecord) -> ReworkConfirmationSnapshot:
        """重复索引字段必须与完整审查JSON一致，损坏时关闭失败。"""

        snapshot = ReworkConfirmationSnapshot.model_validate_json(json.dumps(row.snapshot))
        if (
            snapshot.approval_id != row.approval_id
            or snapshot.run_id != row.run_id
            or snapshot.owner_user_id != row.owner_user_id
            or snapshot.revision != row.revision
            or snapshot.status != row.status
            or snapshot.created_at != row.created_at
            or snapshot.expires_at != row.expires_at
            or snapshot.execution_key != row.execution_key
        ):
            raise ValueError("stored rework confirmation is inconsistent")
        return snapshot
