"""T828独立人工确认前重读事实，变化失效、取消和到期均不能进入业务写入。"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.errors import ToolErrorCode, ToolException
from app.schemas.rework_approval import ReworkApprovalDraft, validate_rework_draft_edit
from app.schemas.rework_confirmation import (
    ReworkConfirmationRequest,
    ReworkConfirmationSnapshot,
    ReworkConfirmationStatus,
)
from app.schemas.rework_draft import PreparedReworkDraft
from app.services.rework_confirmation_store import ReworkConfirmationStore
from app.tools.models import ToolContext
from app.workflows.rework_draft import ReworkDraftWorkflow


class ReworkConfirmationError(Exception):
    """安全机器分类，不包含草稿、证据、令牌或底层异常正文。"""

    def __init__(self, code: str, *, status_code: int = 409, retryable: bool = False) -> None:
        self.code, self.status_code, self.retryable = code, status_code, retryable
        super().__init__(f"rework confirmation stopped: {code}")


class ReworkConfirmationService:
    """保存独立审查，明确人工确认后重校验，最多进入CONFIRMED而非EXECUTING。"""

    def __init__(
        self,
        *,
        store: ReworkConfirmationStore,
        workflow: ReworkDraftWorkflow,
        ttl_seconds: int = 600,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        approval_id_factory: Callable[[], str] = lambda: f"rework-approval-{uuid4().hex}",
    ) -> None:
        """只依赖审查Store和只读Workflow，没有模型、写Tool或执行凭证生成器。"""

        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86400:
            raise ValueError("confirmation ttl must be between 60 and 86400 seconds")
        self._store, self._workflow = store, workflow
        self._ttl, self._now, self._id = timedelta(seconds=ttl_seconds), now, approval_id_factory

    async def create(
        self, command: object, *, context: ToolContext, expected_order_id: str | None = None
    ) -> ReworkConfirmationSnapshot:
        """只将本次Java取证结果存为独立待确认记录，不继承其他动作确认。"""

        self._clock()
        prepared = await self._workflow.ainvoke(command, context=context)
        if expected_order_id is not None and prepared.order_id != expected_order_id:
            raise ReworkConfirmationError("RESOURCE_NOT_FOUND", status_code=404)
        now = self._clock()
        snapshot = ReworkConfirmationSnapshot(
            approval_id=self._id(),
            run_id=context.run_id,
            owner_user_id=context.identity.user_id,
            revision=0,
            status="WAITING_CONFIRMATION",
            prepared=prepared,
            created_at=now,
            expires_at=now + self._ttl,
        )
        if not await self._store.create(snapshot, context=context, now=now):
            raise ReworkConfirmationError("APPROVAL_NOT_CREATED")
        return snapshot

    async def confirm(self, value: object, *, context: ToolContext) -> ReworkConfirmationSnapshot:
        """由独立人工确认入口调用，重读原对象且比较原绑定，禁止自动换绑或更新版本。"""

        try:
            raw = (
                value.model_dump(mode="python")
                if isinstance(value, ReworkConfirmationRequest)
                else value
            )
            request = ReworkConfirmationRequest.model_validate(raw)
        except ValueError:
            raise ReworkConfirmationError("PARAM_VALIDATION_ERROR", status_code=400) from None
        snapshot = await self._require(request.approval_id, context)
        await self._waiting(snapshot, context)
        self._permissions(snapshot, context)
        try:
            draft = validate_rework_draft_edit(snapshot.prepared.review.draft, request.draft)
        except ValueError:
            raise ReworkConfirmationError("APPROVAL_DRAFT_MISMATCH") from None
        try:
            current = await self._workflow.ainvoke(self._command(draft), context=context)
        except ToolException as error:
            if error.code in {ToolErrorCode.BUSINESS_CONFLICT, ToolErrorCode.RESOURCE_NOT_FOUND}:
                await self._finish(snapshot, "STALE", context)
                raise ReworkConfirmationError("APPROVAL_STALE") from None
            raise ReworkConfirmationError(
                error.code.value, status_code=error.status_code or 502, retryable=error.retryable
            ) from None
        if current.review.draft != draft or self._facts(current) != self._facts(snapshot.prepared):
            await self._finish(snapshot, "STALE", context)
            raise ReworkConfirmationError("APPROVAL_STALE")
        # 再读确认记录和时间，网络等待期间的取消、过期或并发确认都不能被覆盖。
        return await self._finish(snapshot, "CONFIRMED", context, draft=draft)

    async def cancel(self, approval_id: str, *, context: ToolContext) -> ReworkConfirmationSnapshot:
        """取消只操作审查记录，权限撤销后所有者仍可取消，没有Java写入。"""

        snapshot = await self._require(approval_id, context)
        return await self._finish(snapshot, "CANCELLED", context)

    async def _require(self, approval_id: str, context: ToolContext) -> ReworkConfirmationSnapshot:
        """按所有者和Run隔离，损坏记录拒绝恢复而非猜测状态。"""

        now = self._clock()
        try:
            snapshot = await self._store.get(approval_id, context=context, now=now)
            if snapshot is not None:
                snapshot = ReworkConfirmationSnapshot.model_validate_json(
                    snapshot.model_dump_json()
                )
        except ValueError:
            raise ReworkConfirmationError("RESPONSE_VALIDATION_ERROR", status_code=500) from None
        if (
            snapshot is None
            or snapshot.owner_user_id != context.identity.user_id
            or snapshot.run_id != context.run_id
        ):
            raise ReworkConfirmationError("RESOURCE_NOT_FOUND", status_code=404)
        return snapshot

    async def expire_waiting(
        self, snapshot: ReworkConfirmationSnapshot, *, context: ToolContext
    ) -> bool:
        """确认和结果核对共用待确认审批的到期转换，保留已提交的并发状态。"""

        now = self._clock()
        if snapshot.status != "WAITING_CONFIRMATION" or now < snapshot.expires_at:
            return False
        updated = self._updated(snapshot, "EXPIRED")
        return await self._store.transition(snapshot, updated, context=context, now=now)

    async def _waiting(self, snapshot: ReworkConfirmationSnapshot, context: ToolContext) -> None:
        """终态先拒绝，到期精确使用>=边界，失败不恢复旧状态。"""

        if snapshot.status != "WAITING_CONFIRMATION":
            raise ReworkConfirmationError(f"APPROVAL_{snapshot.status}")
        if self._clock() >= snapshot.expires_at:
            if not await self.expire_waiting(snapshot, context=context):
                raise ReworkConfirmationError("APPROVAL_CHANGED")
            raise ReworkConfirmationError("APPROVAL_EXPIRED", status_code=410)

    async def _finish(
        self,
        expected: ReworkConfirmationSnapshot,
        status: ReworkConfirmationStatus,
        context: ToolContext,
        *,
        draft: ReworkApprovalDraft | None = None,
    ) -> ReworkConfirmationSnapshot:
        """短事务前重新比较完整原始快照，CAS失败不覆盖最新取消或终态。"""

        current = await self._require(expected.approval_id, context)
        await self._waiting(current, context)
        if current != expected:
            raise ReworkConfirmationError("APPROVAL_CHANGED")
        now = self._clock()
        if now >= current.expires_at:
            await self._waiting(current, context)
        updated = self._updated(current, status, draft=draft, now=now)
        if not await self._store.transition(current, updated, context=context, now=now):
            raise ReworkConfirmationError("APPROVAL_CHANGED")
        return updated

    @staticmethod
    def _updated(
        snapshot: ReworkConfirmationSnapshot,
        status: ReworkConfirmationStatus,
        *,
        draft: ReworkApprovalDraft | None = None,
        now: datetime | None = None,
    ) -> ReworkConfirmationSnapshot:
        """状态更新必须重新过严格Schema，不借用未校验的model_copy更新。"""

        raw = snapshot.model_dump(mode="python")
        raw.update(status=status, revision=snapshot.revision + 1)
        if status == "CONFIRMED":
            raw.update(
                confirmed_draft=draft, confirmed_by_user_id=snapshot.owner_user_id, confirmed_at=now
            )
        return ReworkConfirmationSnapshot.model_validate(raw)

    @staticmethod
    def _command(draft: ReworkApprovalDraft) -> dict[str, object]:
        """仅从最终审查内容还原T827人工材料，新读目标绝不替换原审查目标。"""

        raw = draft.request.model_dump(mode="python")
        for key in ("expected_version", "processing_revision", "inspection_id"):
            raw.pop(key, None)
        raw.update(operation=draft.operation, task_id=draft.target.task_id)
        if draft.operation != "CREATE_LIFECYCLE_REWORK":
            raw["rework_task_id"] = draft.target.rework_task_id
        return raw

    @staticmethod
    def _facts(prepared: PreparedReworkDraft) -> object:
        """比较本动作相关的完整登记材料，其他订单交付阻塞不构成返工授权。"""

        issue_id = prepared.review.draft.target.source_issue_id
        return (
            prepared.order_id,
            prepared.current_task.task_id,
            prepared.current_task.task_version,
            prepared.current_task.production_status,
            [row for row in prepared.current_task.issues if row.issue.issue_id == issue_id],
            sorted(
                (
                    row
                    for row in prepared.current_task.active_reworks
                    if row.source_issue_id == issue_id
                ),
                key=lambda row: row.rework_task_id,
            ),
            prepared.current_rework,
        )

    @staticmethod
    def _permissions(snapshot: ReworkConfirmationSnapshot, context: ToolContext) -> None:
        """确认沿用服务端实时权限，Java只读和最终写入还会再检查实际身份。"""

        permission = snapshot.prepared.review.required_permission
        if context.identity.role != "REVIEWER" or not {
            "TASK_READ",
            "REWORK_READ",
            permission,
        }.issubset(context.permissions):
            raise ReworkConfirmationError("PERMISSION_DENIED", status_code=403)

    def _clock(self) -> datetime:
        """拒绝无时区时钟，避免错误扩大确认窗口。"""

        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmation clock must have a timezone")
        return value
