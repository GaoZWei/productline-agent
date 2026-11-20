"""T830显式内部装配，不注册生产HTTP、Agent路由或前端操作入口。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.database import Database
from app.errors import ToolErrorCode, ToolException
from app.eventing import RunEventSink
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentSession,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    ReworkConfirmationRecord,
    ReworkOperationLog,
)
from app.schemas.events import RunEventType
from app.schemas.rework import MAX_SAFE_INTEGER
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_execution import ReworkExecutionReport
from app.schemas.rework_progress import ReworkProgressSummary
from app.services.rework_confirmation import ReworkConfirmationError, ReworkConfirmationService
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from app.services.rework_execution_service import ReworkExecutionService
from app.services.rework_observation import (
    ReworkStateObserver,
    elapsed_ms,
    validated_rework_replay,
    wait_for_rework_notification,
)
from app.services.rework_observation_mode import (
    ReworkObservationModeError,
    require_rework_creation_mode,
    require_rework_observation_mode,
)
from app.tools.models import ToolContext
from app.tools.readonly import create_read_tool_registry
from app.tools.rework_readonly import create_rework_read_tool_registry
from app.workflows.rework_draft import ReworkDraftWorkflow

_logger = logging.getLogger(__name__)


class ObservedReworkService:
    """单份独立确认使用专属Run，状态与审计原子保存，通知失败不重发写入。"""

    def __init__(
        self,
        database: Database,
        client: BusinessHttpClient,
        *,
        context: ToolContext,
        event_sink: RunEventSink | None = None,
        approval_ttl_seconds: int = 600,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        approval_id_factory: Callable[[], str] = lambda: f"rework-approval-{uuid4().hex}",
    ) -> None:
        """依赖由服务端注入，不接受调用方提供用户、权限或执行键。"""

        self._database, self._client, self._context = database, client, context
        self._sink, self._now = event_sink, now
        self._observer = ReworkStateObserver(event_sink)
        self._confirmation = ReworkConfirmationService(
            store=DatabaseReworkConfirmationStore(database, now=now, observer=self._observer),
            workflow=ReworkDraftWorkflow(
                task_tools=create_read_tool_registry(client),
                rework_tools=create_rework_read_tool_registry(ReworkHttpClient(client)),
            ),
            now=now,
            ttl_seconds=approval_ttl_seconds,
            approval_id_factory=approval_id_factory,
        )

    def _clock(self) -> datetime:
        """观察时钟必须带时区，避免数据库等待与执行耗时失真。"""

        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rework observation clock must have a timezone")
        return now

    async def create(
        self, command: object, *, expected_order_id: str | None = None
    ) -> ReworkConfirmationSnapshot:
        """取证和保存草稿，失败定位到准备Step，绝不调用写Tool。"""

        return await self._invoke(
            "prepare",
            lambda context: self._confirmation.create(
                command, context=context, expected_order_id=expected_order_id
            ),
        )

    async def get_approval(self, approval_id: str) -> ReworkConfirmationSnapshot:
        """按原归属恢复审批供入口检查动作范围，不创建步骤或消费许可。"""

        try:
            snapshot = await self._executor(self._context).store.read(approval_id)
        except ValueError:
            raise ReworkConfirmationError("RESPONSE_VALIDATION_ERROR", status_code=500) from None
        if snapshot is None:
            raise ReworkConfirmationError("RESOURCE_NOT_FOUND", status_code=404)
        ReworkConfirmationService._permissions(snapshot, self._context)
        return snapshot

    async def expire_unclaimed(
        self, snapshot: ReworkConfirmationSnapshot
    ) -> ReworkConfirmationSnapshot:
        """核对已绑定的审批时，只原子终结过期且尚未领取的审批。"""

        if (
            snapshot.status not in {"WAITING_CONFIRMATION", "CONFIRMED"}
            or self._clock() < snapshot.expires_at
        ):
            return snapshot
        if snapshot.status == "WAITING_CONFIRMATION":
            await self._confirmation.expire_waiting(snapshot, context=self._context)
        else:
            await self._executor(self._context).store.invalidate(snapshot, expired=True)
        # 确认或领取可能先于失效提交。重新读取原审批，以持久化状态决定核对结果。
        return await self.get_approval(snapshot.approval_id)

    async def confirm(self, value: object) -> ReworkConfirmationSnapshot:
        """重新取证并确认原草稿，确认通过后仍等待显式执行。"""

        return await self._invoke(
            "confirm", lambda context: self._confirmation.confirm(value, context=context)
        )

    async def cancel(self, approval_id: str) -> ReworkConfirmationSnapshot:
        """取消独立审查，已确认或已领取的操作不能被取消覆盖。"""

        return await self._invoke(
            "cancel", lambda context: self._confirmation.cancel(approval_id, context=context)
        )

    def _executor(self, context: ToolContext) -> ReworkExecutionService:
        """复用唯一执行服务，不新增重试、自动确认或新的业务写通道。"""

        return ReworkExecutionService(
            self._database, self._client, context=context, now=self._now, observer=self._observer
        )

    async def execute(self, value: object) -> ReworkExecutionReport:
        """领取、提交和原回执落库联动到独立写回Step。"""

        return await self._invoke("execute", lambda context: self._executor(context).execute(value))

    async def reconcile(self, value: object) -> ReworkExecutionReport:
        """仅查询原键，未见回执时保留运行中状态，不重发业务写入。"""

        return await self._invoke(
            "reconcile", lambda context: self._executor(context).reconcile(value)
        )

    async def _begin(self, phase: str) -> tuple[str | None, int]:
        """短事务校验真实会话归属并分配调用Step，不锁住网络取证。"""

        now = self._clock()
        async with self._database.session() as session, session.begin():
            run = await session.scalar(
                select(AgentRun)
                .join(AgentSession)
                .where(
                    AgentRun.run_id == self._context.run_id,
                    AgentSession.user_id == self._context.identity.user_id,
                    AgentSession.expires_at > now,
                )
                .with_for_update(of=AgentRun)
            )
            if run is None:
                raise ReworkConfirmationError("RESOURCE_NOT_FOUND", status_code=404)
            approvals = list(
                (
                    await session.scalars(
                        select(ReworkConfirmationRecord)
                        .where(ReworkConfirmationRecord.run_id == run.run_id)
                        .limit(2)
                    )
                ).all()
            )
            if approvals:
                if (
                    len(approvals) != 1
                    or approvals[0].owner_user_id != self._context.identity.user_id
                ):
                    raise ReworkObservationModeError()
                try:
                    stored = DatabaseReworkConfirmationStore._snapshot(approvals[0])
                except ValueError:
                    raise ReworkObservationModeError() from None
                await require_rework_observation_mode(
                    session,
                    stored,
                    observed=True,
                    run=run,
                )
            else:
                await require_rework_creation_mode(session, run, observed=True)
            revision = await session.scalar(
                select(func.max(ReworkOperationLog.revision)).where(
                    ReworkOperationLog.run_id == run.run_id
                )
            )
            # 已结束的重复查询不重启Run或伪造执行Step，仍由原服务检查输入及权限。
            if run.status in {
                AgentRunStatus.SUCCEEDED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            }:
                return None, revision if revision is not None else -1
            if run.status not in {AgentRunStatus.RUNNING, AgentRunStatus.WAITING_APPROVAL}:
                raise ReworkConfirmationError("RUN_NOT_ACTIVE")
            sequence = await session.scalar(
                select(func.max(AgentStep.sequence_number)).where(AgentStep.run_id == run.run_id)
            )
            identity = "rework-call-" + uuid4().hex
            session.add(
                AgentStep(
                    step_id=identity,
                    run_id=run.run_id,
                    sequence_number=(sequence or 0) + 1,
                    step_type=AgentStepType.WORKFLOW,
                    step_name="rework_" + phase,
                    status=AgentStepStatus.RUNNING,
                    input_summary="Controlled rework call",
                    started_at=now,
                )
            )
            run.started_at = run.started_at or now
            return identity, revision if revision is not None else -1

    async def _finish(self, step_id: str | None, *, count: int, error_code: str | None) -> None:
        """调用错误只结束本次Step，未知写结果不能被标记为Run失败。"""

        if step_id is None:
            return
        now = self._clock()
        async with self._database.session() as session, session.begin():
            run = await session.scalar(
                select(AgentRun).where(AgentRun.run_id == self._context.run_id).with_for_update()
            )
            step = await session.get(AgentStep, step_id)
            if run is None or step is None or step.status != AgentStepStatus.RUNNING:
                return
            step.status = AgentStepStatus.FAILED if error_code else AgentStepStatus.SUCCEEDED
            step.error_code, step.finished_at = error_code, now
            step.output_summary = error_code or "Call completed; see persisted rework state"
            step.duration_ms = elapsed_ms(step.started_at or now, now)
            run.tool_call_count += count
            if error_code and run.status != AgentRunStatus.SUCCEEDED:
                run.error_code, run.error_step = error_code, step_id
                bound = await session.scalar(
                    select(ReworkOperationLog.approval_id)
                    .where(ReworkOperationLog.run_id == run.run_id)
                    .limit(1)
                )
                if bound is None and run.status == AgentRunStatus.RUNNING:
                    run.status = (
                        AgentRunStatus.CANCELLED
                        if error_code == "CALL_CANCELLED"
                        else AgentRunStatus.FAILED
                    )
                    run.termination_reason = error_code
                    run.finished_at = now
                    run.duration_ms = elapsed_ms(run.started_at or now, now)
            run.updated_at = now

    async def _invoke[ResultT](
        self, phase: str, action: Callable[[ToolContext], Awaitable[ResultT]]
    ) -> ResultT:
        """每次调用使用新账本计数，取消保留执行权，收尾失败不掩盖原业务结果。"""

        context = ToolContext.model_validate(self._context.model_dump())
        step_id, revision = await self._begin(phase)
        error_code: str | None = None
        try:
            return await action(context)
        except asyncio.CancelledError:
            error_code = "CALL_CANCELLED"
            raise
        except ReworkConfirmationError as error:
            error_code = error.code
            raise
        except ToolException as error:
            error_code = error.code.value
            raise
        except Exception:
            error_code = "INTERNAL_ERROR"
            raise
        finally:
            try:
                await self._finish(
                    step_id,
                    count=context.tool_call_ledger.recorded_call_count,
                    error_code=error_code,
                )
                await wait_for_rework_notification(self.publish_progress(after_revision=revision))
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is None or task.cancelling():
                    raise
                # 收尾或通知子任务的取消不应掩盖主调用已经确定的返回值或原异常。
                _logger.warning("rework_observation_delivery_cancelled")
            except Exception:
                # 仅固定事件名，不记录异常正文、草稿或业务请求，不能因此再次提交。
                _logger.warning("rework_observation_delivery_failed")

    async def publish_progress(self, *, after_revision: int = -1) -> None:
        """提交后补发整批校验过的摘要，游标不能跳过损坏证据或生成虚假终态。"""

        if (
            self._sink is None
            or self._context.identity.role != "REVIEWER"
            or "REWORK_READ" not in self._context.permissions
        ):
            return
        if type(after_revision) is not int or not -1 <= after_revision <= MAX_SAFE_INTEGER:
            raise ReworkConfirmationError("PARAM_VALIDATION_ERROR", status_code=400)
        async with self._database.session() as session, session.begin():
            run = await session.scalar(
                select(AgentRun)
                .join(AgentSession)
                .where(
                    AgentRun.run_id == self._context.run_id,
                    AgentSession.user_id == self._context.identity.user_id,
                    AgentSession.expires_at > self._clock(),
                )
                .with_for_update(of=AgentRun)
            )
            if run is None:
                return
            # 锁等待可能跨过会话期限，取锁后按新时钟重查，不延长补发授权。
            accessible = await session.scalar(
                select(AgentSession.session_id).where(
                    AgentSession.session_id == run.session_id,
                    AgentSession.user_id == self._context.identity.user_id,
                    AgentSession.expires_at > self._clock(),
                )
            )
            if accessible is None:
                return
            try:
                state = await self._replay_state(session, run)
            except (ValueError, TypeError):
                raise ReworkConfirmationError("REWORK_AUDIT_INVALID", status_code=500) from None
            if state is None:
                return
            summaries, status, code = state
            latest_revision = summaries[-1].revision if summaries else -1
            if after_revision > latest_revision:
                raise ReworkConfirmationError("PARAM_VALIDATION_ERROR", status_code=400)
            payloads = [item.event_data() for item in summaries if item.revision > after_revision]
        # 已退出事务并释放Run锁后才发送，坏批次不会先发一半再报告失败。
        for data in payloads:
            await self._sink.publish(
                RunEventType.REWORK_PROGRESS, run_id=self._context.run_id, data=data
            )
        if status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
            await self._sink.publish(
                RunEventType.RUN_COMPLETED
                if status == AgentRunStatus.SUCCEEDED
                else RunEventType.RUN_FAILED,
                run_id=self._context.run_id,
                data={"status": status.value, "error_code": code},
            )

    async def _replay_state(
        self, session: AsyncSession, run: AgentRun
    ) -> tuple[list[ReworkProgressSummary], AgentRunStatus, str | None] | None:
        """在Run锁内读取同一份审查与完整审计，只使用已校验的状态生成终态。"""

        approvals = list(
            (
                await session.scalars(
                    select(ReworkConfirmationRecord)
                    .where(ReworkConfirmationRecord.run_id == run.run_id)
                    .limit(2)
                )
            ).all()
        )
        records = list(
            (
                await session.scalars(
                    select(ReworkOperationLog)
                    .where(ReworkOperationLog.run_id == run.run_id)
                    .order_by(ReworkOperationLog.revision)
                )
            ).all()
        )
        if not approvals and not records:
            # 初次准备失败还没有审批，其他业务Run不能经此入口冒充返工终态。
            step = await session.get(AgentStep, run.error_step) if run.error_step else None
            if step is None or step.run_id != run.run_id or step.step_name != "rework_prepare":
                return None
            safe_codes = {code.value for code in ToolErrorCode} | {
                "CALL_CANCELLED",
                "INTERNAL_ERROR",
                "APPROVAL_NOT_CREATED",
            }
            expected = (
                AgentRunStatus.CANCELLED
                if run.error_code == "CALL_CANCELLED"
                else AgentRunStatus.FAILED
            )
            if (
                step.step_type != AgentStepType.WORKFLOW
                or step.status != AgentStepStatus.FAILED
                or run.error_code not in safe_codes
                or step.error_code != run.error_code
                or run.status != expected
            ):
                raise ValueError("preparation failure is inconsistent")
            return [], expected, run.error_code
        if len(approvals) != 1 or approvals[0].owner_user_id != self._context.identity.user_id:
            raise ValueError("audit approval binding is inconsistent")
        snapshot = DatabaseReworkConfirmationStore._snapshot(approvals[0])
        summaries = validated_rework_replay(records, snapshot=snapshot)
        expected_status = {
            "WAITING_CONFIRMATION": AgentRunStatus.WAITING_APPROVAL,
            "CONFIRMED": AgentRunStatus.WAITING_APPROVAL,
            "EXECUTING": AgentRunStatus.RUNNING,
            "SUCCEEDED": AgentRunStatus.SUCCEEDED,
            "CANCELLED": AgentRunStatus.CANCELLED,
            "EXPIRED": AgentRunStatus.FAILED,
            "STALE": AgentRunStatus.FAILED,
        }[snapshot.status]
        if run.status != expected_status:
            raise ValueError("audit run status is inconsistent")
        code = (
            "APPROVAL_" + snapshot.status
            if snapshot.status in {"CANCELLED", "EXPIRED", "STALE"}
            else None
        )
        return summaries, expected_status, code
