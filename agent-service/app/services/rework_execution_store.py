"""T829数据库执行Store：原子领取、一次提交、首次回执保留，不读Java业务表。"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.rework import ReworkHttpClient
from app.database import Database
from app.models import AgentRun, AgentSession, ApprovalStatus, ReworkConfirmationRecord
from app.schemas.rework import ReworkWriteReceipt
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_execution import ReworkReceiptEvidence
from app.schemas.rework_operation_query import ReworkOperationResolution
from app.schemas.rework_write_tools import ReworkExecutionSnapshot, ReworkWriteOutput
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from app.services.rework_observation import ReworkStateObserver
from app.services.rework_receipts import validate_rework_receipt_binding
from app.tools.models import ToolContext, ToolError


class DatabaseReworkExecutionStore:
    """每个实例绑定服务端上下文，不从Tool参数取得用户、Run或业务请求。"""

    def __init__(
        self,
        database: Database,
        client: ReworkHttpClient,
        *,
        context: ToolContext,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        observer: ReworkStateObserver | None = None,
    ) -> None:
        self._database, self._client, self.context, self._now = database, client, context, now
        self._observer = observer

    def clock(self) -> datetime:
        """所有提交前时钟必须有时区，拒绝错误扩大执行窗口。"""

        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution clock must have a timezone")
        return value

    async def _owner(self, session: AsyncSession, *, allow_expired: bool = False) -> bool:
        """查询需要有效会话，已提交后的保存可跨会话到期，不能因此丢弃成功证据。"""

        query = (
            select(AgentRun.run_id)
            .join(AgentSession)
            .where(
                AgentRun.run_id == self.context.run_id,
                AgentSession.user_id == self.context.identity.user_id,
            )
        )
        if not allow_expired:
            query = query.where(AgentSession.expires_at > self.clock())
        return await session.scalar(query) is not None

    async def read(
        self, approval_id: str, *, allow_expired_session: bool = False
    ) -> ReworkConfirmationSnapshot | None:
        """恢复完整记录，旧终态可读取，错误归属和损坏数据不生成执行快照。"""

        async with self._database.session() as session:
            if not await self._owner(session, allow_expired=allow_expired_session):
                return None
            row = await session.get(ReworkConfirmationRecord, approval_id)
            if (
                row is None
                or row.run_id != self.context.run_id
                or row.owner_user_id != self.context.identity.user_id
            ):
                return None
            return DatabaseReworkConfirmationStore._snapshot(row)

    async def _change(
        self,
        expected: ReworkConfirmationSnapshot,
        updates: dict[str, object],
        *,
        before_submit: bool = False,
    ) -> ReworkConfirmationSnapshot | None:
        """完整比较原快照，网络不在事务中，取锁后检查实际时钟和Run状态。"""

        expected = ReworkConfirmationSnapshot.model_validate_json(expected.model_dump_json())
        if (
            expected.run_id != self.context.run_id
            or expected.owner_user_id != self.context.identity.user_id
        ):
            return None
        if before_submit and (
            self.context.identity.role != "REVIEWER"
            or not {
                "TASK_READ",
                "REWORK_READ",
                expected.prepared.review.required_permission,
            }.issubset(self.context.permissions)
        ):
            return None
        async with self._database.session() as session, session.begin():
            if not await self._owner(session, allow_expired=not before_submit):
                return None
            if self._observer is not None:
                await session.scalar(
                    select(AgentRun).where(AgentRun.run_id == expected.run_id).with_for_update()
                )
            row = await session.scalar(
                select(ReworkConfirmationRecord)
                .where(
                    ReworkConfirmationRecord.approval_id == expected.approval_id,
                )
                .with_for_update()
            )
            if row is None or DatabaseReworkConfirmationStore._snapshot(row) != expected:
                return None
            now = self.clock()
            if before_submit and (
                now >= expected.expires_at
                or not await DatabaseReworkConfirmationStore._accessible(session, self.context, now)
            ):
                return None
            raw = expected.model_dump(mode="python")
            raw.update(updates)
            raw["revision"] = expected.revision + 1
            if updates.get("status") == "EXECUTING":
                raw["claimed_at"] = now
            if "submission_started_at" in updates:
                raw["submission_started_at"] = now
            updated = ReworkConfirmationSnapshot.model_validate(raw)
            row.snapshot = updated.model_dump(mode="json")
            row.status, row.revision, row.execution_key = (
                updated.status,
                updated.revision,
                updated.execution_key,
            )
            if self._observer is not None:
                await self._observer.record(session, updated, now=now)
        if self._observer is not None:
            await self._observer.publish(updated)
        return updated

    async def claim(
        self, expected: ReworkConfirmationSnapshot
    ) -> ReworkConfirmationSnapshot | None:
        """仅CONFIRMED领取一次，键由原审查身份确定并在同一事务冻结。"""

        if (
            expected.status != "CONFIRMED"
            or expected.confirmed_by_user_id != self.context.identity.user_id
        ):
            return None
        key = "rework:v1:" + hashlib.sha256(expected.approval_id.encode()).hexdigest()
        return await self._change(
            expected, {"status": "EXECUTING", "execution_key": key}, before_submit=True
        )

    async def invalidate(self, expected: ReworkConfirmationSnapshot, *, expired: bool) -> bool:
        """领取前变化只失效原确认，保留人工确认事实，不签发键。"""

        if expected.status != "CONFIRMED":
            return False
        if expired != (self.clock() >= expected.expires_at):
            return False
        return (
            await self._change(expected, {"status": "EXPIRED" if expired else "STALE"}) is not None
        )

    @staticmethod
    def projection(snapshot: ReworkConfirmationSnapshot) -> ReworkExecutionSnapshot | None:
        """执行快照完全来自原确认，保留最终请求和原轮次/材料，不推测当前状态。"""

        draft = snapshot.confirmed_draft
        if draft is None or snapshot.execution_key is None:
            return None
        target = draft.target
        return ReworkExecutionSnapshot(
            approval_id=snapshot.approval_id,
            run_id=snapshot.run_id,
            owner_user_id=snapshot.owner_user_id,
            confirmed_by_user_id=snapshot.confirmed_by_user_id,
            confirmed_at=snapshot.confirmed_at,
            expires_at=snapshot.expires_at,
            status=ApprovalStatus(snapshot.status),
            operation=draft.operation,
            idempotency_key=snapshot.execution_key,
            task_id=target.task_id,
            task_version=target.task_version,
            source_issue_id=target.source_issue_id,
            rework_task_id=target.rework_task_id,
            round_number=target.round_number,
            previous_rework_task_id=target.previous_rework_task_id,
            processing_revision=target.processing_revision,
            inspection_id=target.inspection_id,
            review_id=target.review_id,
            request=draft.request,
        )

    async def get_execution_snapshot(self, approval_id: str) -> ReworkExecutionSnapshot | None:
        """只读恢复供写Tool及原键查询使用，提交仍须单独消费许可。"""

        snapshot = await self.read(approval_id)
        return self.projection(snapshot) if snapshot else None

    async def begin_submission(self, expected: ReworkExecutionSnapshot) -> bool:
        """强制刷新、跨实例及并发调用也只能有一个实际Java提交。"""

        expected = ReworkExecutionSnapshot.model_validate_json(expected.model_dump_json())
        current = await self.read(expected.approval_id)
        if (
            current is None
            or current.status != "EXECUTING"
            or self.projection(current) != expected
            or current.submission_started_at is not None
        ):
            return False
        return (
            await self._change(current, {"submission_started_at": self.clock()}, before_submit=True)
            is not None
        )

    def _receipt(
        self, expected: ReworkExecutionSnapshot, receipt: ReworkWriteReceipt, trace: str
    ) -> None:
        """复用已验证Client的纯校验及轮次绑定，不在Store发送HTTP。"""

        self._client.check_write_receipt(
            expected.task_id,
            expected.rework_task_id,
            expected.operation,
            expected.request,
            receipt,
            trace,
        )
        validate_rework_receipt_binding(expected, receipt, trace)

    async def _save_receipt(
        self, expected: ReworkExecutionSnapshot, evidence: ReworkReceiptEvidence
    ) -> bool:
        """首次成功不可覆盖，写响应与查询回执竞争时只接受同一原业务回执。"""

        expected = ReworkExecutionSnapshot.model_validate_json(expected.model_dump_json())
        evidence = ReworkReceiptEvidence.model_validate_json(evidence.model_dump_json())
        self._receipt(
            expected,
            evidence.receipt,
            evidence.write_java_trace_id or evidence.lookup_java_trace_id or "invalid",
        )
        current = await self.read(expected.approval_id, allow_expired_session=True)
        if current is None or evidence.approval_id != current.approval_id:
            return False
        if current.status == "SUCCEEDED":
            actual = self.projection(current)
            return (
                actual is not None
                and actual.model_dump(exclude={"status"}) == expected.model_dump(exclude={"status"})
                and current.receipt_evidence is not None
                and current.receipt_evidence.receipt == evidence.receipt
            )
        if (
            current.status != "EXECUTING"
            or self.projection(current) != expected
            or current.submission_started_at is None
        ):
            return False
        return (
            await self._change(
                current,
                {
                    "status": "SUCCEEDED",
                    "receipt_evidence": evidence.model_dump(mode="python"),
                    "execution_error": None,
                },
            )
            is not None
        )

    async def save_execution_result(
        self, expected: ReworkExecutionSnapshot, result: ReworkWriteOutput
    ) -> bool:
        """原响应成功即原子保存终态，已过审批期限不丢弃真实已提交结果。"""

        return await self._save_receipt(
            expected,
            ReworkReceiptEvidence(
                approval_id=result.approval_id,
                receipt=result.receipt,
                source="WRITE",
                write_java_trace_id=result.java_trace_id,
                lookup_java_trace_id=None,
            ),
        )

    async def save_resolution(
        self, expected: ReworkExecutionSnapshot, result: ReworkOperationResolution
    ) -> bool:
        """只接受原键的匹配成功回执，缺失仍未知，查询Trace不冒充首次写Trace。"""

        if result.receipt is None:
            return False
        return await self._save_receipt(
            expected,
            ReworkReceiptEvidence(
                approval_id=result.approval_id,
                receipt=result.receipt,
                source="LOOKUP",
                write_java_trace_id=None,
                lookup_java_trace_id=result.java_trace_id,
            ),
        )

    async def unknown(self, approval_id: str, error: ToolError) -> None:
        """提交失败不证明未提交，不把已保存成功降级或重置成可执行。"""

        current = await self.read(approval_id, allow_expired_session=True)
        if current is not None and current.status == "EXECUTING":
            safe = ToolError(
                code=error.code,
                message="write result is unknown; query the original key",
                retryable=False,
                trace_id=error.trace_id,
                status_code=error.status_code,
            )
            await self._change(current, {"execution_error": safe.model_dump(mode="python")})
