"""T830显式内部装配；不注册生产HTTP、Agent路由或前端操作入口。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import func, select

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.database import Database
from app.errors import ToolException
from app.eventing import RunEventSink
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentSession,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    ReworkOperationLog,
)
from app.schemas.events import RunEventType
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_execution import ReworkExecutionReport
from app.services.rework_confirmation import ReworkConfirmationError, ReworkConfirmationService
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from app.services.rework_execution_service import ReworkExecutionService
from app.services.rework_observation import ReworkStateObserver, elapsed_ms
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
            approval_id_factory=approval_id_factory,
        )

    def _clock(self) -> datetime:
        """观察时钟必须带时区，避免数据库等待与执行耗时失真。"""

        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rework observation clock must have a timezone")
        return now

    async def create(self, command: object) -> ReworkConfirmationSnapshot:
        """取证和保存草稿，失败定位到准备Step，绝不调用写Tool。"""

        return await self._invoke(
            "prepare", lambda context: self._confirmation.create(command, context=context)
        )

    async def confirm(self, value: object) -> ReworkConfirmationSnapshot:
        """重新取证并确认原草稿，确认通过后仍等待显式执行。"""

        return await self._invoke(
            "confirm", lambda context: self._confirmation.confirm(value, context=context)
        )

    async def cancel(self, approval_id: str) -> ReworkConfirmationSnapshot:
        """取消独立审查；已确认或已领取的操作不能被取消覆盖。"""

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
        """仅查询原键；未见回执时保留运行中状态，不重发业务写入。"""

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

    async def _finish(
        self, step_id: str | None, *, count: int, error_code: str | None
    ) -> None:
        """调用错误只结束本次Step；未知写结果不能被标记为Run失败。"""

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
                    step_id, count=context.tool_call_ledger.recorded_call_count, error_code=error_code
                )
                await asyncio.wait_for(self.publish_progress(after_revision=revision), timeout=1.0)
            except Exception:
                # 仅固定事件名，不记录异常正文、草稿或业务请求；不能因此再次提交。
                _logger.warning("rework_observation_delivery_failed")

    async def publish_progress(self, *, after_revision: int = -1) -> None:
        """提交后按审查修订发送白名单事件；可重放，消费者按approval/revision去重。"""

        if (
            self._sink is None
            or self._context.identity.role != "REVIEWER"
            or "REWORK_READ" not in self._context.permissions
        ):
            return
        async with self._database.session() as session:
            run = await session.scalar(
                select(AgentRun)
                .join(AgentSession)
                .where(
                    AgentRun.run_id == self._context.run_id,
                    AgentSession.user_id == self._context.identity.user_id,
                    AgentSession.expires_at > self._clock(),
                )
            )
            if run is None:
                return
            records = list(
                (
                    await session.scalars(
                        select(ReworkOperationLog)
                        .where(
                            ReworkOperationLog.run_id == run.run_id,
                            ReworkOperationLog.revision > after_revision,
                        )
                        .order_by(ReworkOperationLog.revision)
                    )
                ).all()
            )
            status, code = run.status, run.error_code
        for record in records:
            data: dict[str, JsonValue] = {key: value for key, value in record.summary.items()}
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
