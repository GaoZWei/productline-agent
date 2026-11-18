"""T829已确认返工的唯一执行与原键核对，未接生产HTTP或动态Agent。"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.database import Database
from app.errors import ToolErrorCode, ToolException
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_execution import ReworkExecutionInput, ReworkExecutionReport
from app.services.rework_confirmation import ReworkConfirmationError, ReworkConfirmationService
from app.services.rework_execution_store import DatabaseReworkExecutionStore
from app.tools.models import ToolContext
from app.tools.readonly import create_read_tool_registry
from app.tools.rework_operation_query import QueryReworkOperationTool
from app.tools.rework_readonly import create_rework_read_tool_registry
from app.tools.rework_write import create_rework_write_tool_registry
from app.workflows.rework_draft import ReworkDraftWorkflow


class ReworkExecutionService:
    """只处理原确认，不自动确认、换目标、换键或重发结果未知的请求。"""

    def __init__(
        self,
        database: Database,
        client: BusinessHttpClient,
        *,
        context: ToolContext,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """显式装配已验证只读、写入和回执Tool，始终绑定服务端上下文。"""

        rework = ReworkHttpClient(client)
        self.store = DatabaseReworkExecutionStore(database, rework, context=context, now=now)
        self._context = context
        self._workflow = ReworkDraftWorkflow(
            task_tools=create_read_tool_registry(client),
            rework_tools=create_rework_read_tool_registry(rework),
        )
        self._writes = create_rework_write_tool_registry(rework, self.store)
        self._query = QueryReworkOperationTool(rework, self.store)

    async def _require(
        self, value: object, *, read_only: bool = False
    ) -> ReworkConfirmationSnapshot:
        """只允许审查ID输入，恢复后校验当前服务端角色和操作权限。"""

        try:
            parsed = ReworkExecutionInput.model_validate(value)
        except ValueError:
            raise ReworkConfirmationError("PARAM_VALIDATION_ERROR", status_code=400) from None
        try:
            snapshot = await self.store.read(parsed.approval_id)
        except ValueError:
            raise ReworkConfirmationError("RESPONSE_VALIDATION_ERROR", status_code=500) from None
        if snapshot is None:
            raise ReworkConfirmationError("RESOURCE_NOT_FOUND", status_code=404)
        if read_only:
            if (
                self._context.identity.role != "REVIEWER"
                or "REWORK_READ" not in self._context.permissions
            ):
                raise ReworkConfirmationError("PERMISSION_DENIED", status_code=403)
        else:
            ReworkConfirmationService._permissions(snapshot, self._context)
        return snapshot

    async def execute(self, value: object) -> ReworkExecutionReport:
        """提交前再读Java，原子领取后仅调用一次写Tool，已有状态绝不重领。"""

        snapshot = await self._require(value)
        if snapshot.status in {"EXECUTING", "SUCCEEDED"}:
            return self._report(snapshot)
        if snapshot.status != "CONFIRMED" or snapshot.confirmed_draft is None:
            raise ReworkConfirmationError(f"APPROVAL_{snapshot.status}")
        if self.store.clock() >= snapshot.expires_at:
            return await self._invalidate(snapshot)
        draft = snapshot.confirmed_draft
        try:
            current = await self._workflow.ainvoke(
                ReworkConfirmationService._command(draft), context=self._context
            )
        except ToolException as error:
            if error.code in {ToolErrorCode.BUSINESS_CONFLICT, ToolErrorCode.RESOURCE_NOT_FOUND}:
                return await self._invalidate(snapshot)
            raise ReworkConfirmationError(
                error.code.value, status_code=error.status_code or 502, retryable=error.retryable
            ) from None
        if current.review.draft != draft or ReworkConfirmationService._facts(
            current
        ) != ReworkConfirmationService._facts(snapshot.prepared):
            return await self._invalidate(snapshot)
        claimed = await self.store.claim(snapshot)
        if claimed is None:
            latest = await self._require(value)
            if latest.status == "CONFIRMED":
                if self.store.clock() >= latest.expires_at:
                    return await self._invalidate(latest)
                raise ReworkConfirmationError("APPROVAL_CHANGED")
            return self._report(latest)
        tool = self._writes.get(claimed.prepared.review.pending_tool)
        assert claimed.execution_key is not None
        try:
            result = await tool.execute(
                {"approval_id": claimed.approval_id, "idempotency_key": claimed.execution_key},
                self._context,
                force_refresh=True,
            )
        except asyncio.CancelledError:
            # 提交可能已发生，保留EXECUTING与原键供只读核对，绝不释放执行权。
            raise
        if result.error is not None:
            await self.store.unknown(claimed.approval_id, result.error)
        return self._report(await self._require(value))

    async def _invalidate(self, snapshot: ReworkConfirmationSnapshot) -> ReworkExecutionReport:
        """确认变化或到期时只转换原状态，竞争失败不能覆盖已领取执行。"""

        expired = self.store.clock() >= snapshot.expires_at
        if not await self.store.invalidate(snapshot, expired=expired):
            latest = await self._require({"approval_id": snapshot.approval_id})
            if latest.status in {"EXECUTING", "SUCCEEDED"}:
                return self._report(latest)
            raise ReworkConfirmationError("APPROVAL_CHANGED")
        raise ReworkConfirmationError(
            "APPROVAL_EXPIRED" if expired else "APPROVAL_STALE", status_code=410 if expired else 409
        )

    async def reconcile(self, value: object) -> ReworkExecutionReport:
        """只查询曾领取的原键，不轮询、不创建新确认、不提交任何业务写入。"""

        snapshot = await self._require(value, read_only=True)
        if snapshot.status == "SUCCEEDED":
            return self._report(snapshot)
        if snapshot.status != "EXECUTING" or snapshot.execution_key is None:
            raise ReworkConfirmationError("APPROVAL_NOT_EXECUTED")
        expected = self.store.projection(snapshot)
        assert expected is not None
        result = await self._query.execute(
            {"approval_id": snapshot.approval_id, "idempotency_key": snapshot.execution_key},
            self._context,
            force_refresh=True,
        )
        if not result.success:
            assert result.error is not None
            raise ReworkConfirmationError(
                result.error.code.value,
                status_code=result.error.status_code or 502,
                retryable=result.error.retryable,
            )
        assert result.data is not None
        if result.data.receipt is not None:
            if not await self.store.save_resolution(expected, result.data):
                latest = await self._require(value, read_only=True)
                if latest.status != "SUCCEEDED":
                    raise ReworkConfirmationError("APPROVAL_CHANGED")
        latest = await self._require(value, read_only=True)
        return self._report(latest, unknown=True)

    @staticmethod
    def _report(
        snapshot: ReworkConfirmationSnapshot, *, unknown: bool = False
    ) -> ReworkExecutionReport:
        """成功只来自已保存原回执，异常和进程中断均不推测业务失败。"""

        outcome: Literal["SUCCEEDED", "IN_PROGRESS", "UNKNOWN"]
        if snapshot.status == "SUCCEEDED":
            outcome = "SUCCEEDED"
        elif snapshot.status == "EXECUTING":
            outcome = (
                "UNKNOWN" if unknown or snapshot.execution_error is not None else "IN_PROGRESS"
            )
        else:
            raise ReworkConfirmationError(f"APPROVAL_{snapshot.status}")
        return ReworkExecutionReport(
            approval_id=snapshot.approval_id,
            outcome=outcome,
            receipt_evidence=snapshot.receipt_evidence,
            error=snapshot.execution_error,
        )
