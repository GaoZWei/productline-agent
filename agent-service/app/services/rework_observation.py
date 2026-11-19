"""返工状态、Run/Step和审计同事务保存，事件仅在事务提交后发送。"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Coroutine, Sequence
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.eventing import RunEventSink
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    ReworkConfirmationRecord,
    ReworkOperationLog,
)
from app.schemas.events import RunEventType
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot
from app.schemas.rework_progress import ReworkProgressSummary


def rework_summary(snapshot: ReworkConfirmationSnapshot) -> dict[str, str | int | None]:
    """只输出固定字段，不透传草稿、证据、错误正文、身份或幂等键。"""

    phase: str = snapshot.status
    if snapshot.status == "EXECUTING":
        phase = "CLAIMED"
        if snapshot.submission_started_at is not None:
            phase = "SUBMITTING"
        if snapshot.execution_error is not None:
            phase = "UNKNOWN"
    result: dict[str, str | int | None] = {
        "approval_id": snapshot.approval_id,
        "revision": snapshot.revision,
        "operation": snapshot.prepared.review.draft.operation,
        "status": snapshot.status,
        "phase": phase,
        "error_code": snapshot.execution_error.code if snapshot.execution_error else None,
    }
    evidence = snapshot.receipt_evidence
    if evidence is not None:
        # 核对Trace与首次写Trace分开，检查失败是已接受的业务事实，不是调用失败。
        result.update(
            receipt_source=evidence.source,
            receipt_operation_id=evidence.receipt.operation_id,
            receipt_status=evidence.receipt.status,
            write_java_trace_id=evidence.write_java_trace_id,
            lookup_java_trace_id=evidence.lookup_java_trace_id,
        )
    validated = ReworkProgressSummary.model_validate_json(json.dumps(result))
    return validated.model_dump(mode="json", exclude_unset=True)


def validated_rework_replay(
    records: Sequence[ReworkOperationLog], *, snapshot: ReworkConfirmationSnapshot
) -> list[ReworkProgressSummary]:
    """整批校验后才允许补发，损坏记录不能被跳过或带出当前审批绑定。"""

    try:
        if len(records) != snapshot.revision + 1:
            raise ValueError("audit revisions are incomplete")
        result: list[ReworkProgressSummary] = []
        for revision, record in enumerate(records):
            summary = ReworkProgressSummary.model_validate_json(json.dumps(record.summary))
            if (
                record.run_id != snapshot.run_id
                or record.approval_id != snapshot.approval_id
                or record.revision != revision
                or summary.approval_id != record.approval_id
                or summary.revision != record.revision
                or summary.phase != record.phase
                or summary.operation != snapshot.prepared.review.draft.operation
            ):
                raise ValueError("audit identity is inconsistent")
            result.append(summary)
        if result[-1].event_data() != rework_summary(snapshot):
            raise ValueError("latest audit differs from the confirmation")
        return result
    except (ValueError, TypeError):
        # 不传播Pydantic错误详情或原JSON，避免损坏材料进入日志和调用栈文案。
        raise ValueError("rework audit history is inconsistent") from None


def rework_step_id(approval_id: str, phase: str) -> str:
    """持久步骤身份由审批和职责确定，重建服务不会重复创建步骤。"""

    return "rework-" + hashlib.sha256(f"{approval_id}:{phase}".encode()).hexdigest()


def elapsed_ms(start: datetime, end: datetime) -> int:
    """系统时钟回拨时耗时仍保持非负，不将等待时间当作写入耗时。"""

    return max(0, int((end - start).total_seconds() * 1000))


async def wait_for_rework_notification(notification: Coroutine[object, object, None]) -> None:
    """独立Task承载通知并在退出前回收，避免发送端取消直接落到请求Task上。"""

    delivery = asyncio.create_task(notification)
    try:
        await asyncio.wait_for(delivery, timeout=1.0)
    finally:
        if not delivery.done():
            delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)


class ReworkStateObserver:
    """仅供显式内部装配使用，一个专属Run承载一份独立审查。"""

    def __init__(self, event_sink: RunEventSink | None = None) -> None:
        """仅绑定事件协议，禁止在记录事务中发布事件。"""

        self._sink = event_sink

    async def publish(self, snapshot: ReworkConfirmationSnapshot) -> None:
        """事务提交后尽力通知，超时或异常不改变数据库结果、不重发业务写入。"""

        if self._sink is None:
            return
        try:
            data: dict[str, JsonValue] = {
                key: value for key, value in rework_summary(snapshot).items()
            }
            await wait_for_rework_notification(
                self._sink.publish(RunEventType.REWORK_PROGRESS, run_id=snapshot.run_id, data=data)
            )
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is None or task.cancelling():
                # 调用者真实取消仍须传播，不能用通知隔离吞掉请求的取消信号。
                raise
            # 子任务取消不代表业务被取消，更不能覆盖已提交的状态或原回执。
            logging.getLogger(__name__).warning("rework_progress_delivery_cancelled")
        except Exception:
            logging.getLogger(__name__).warning("rework_progress_delivery_failed")

    async def record(
        self, session: AsyncSession, snapshot: ReworkConfirmationSnapshot, *, now: datetime
    ) -> None:
        """由Store在同一短事务内调用，审计失败须一并回滚状态转换。"""

        run = await session.scalar(
            select(AgentRun).where(AgentRun.run_id == snapshot.run_id).with_for_update()
        )
        if run is None:
            raise ValueError("rework observation requires an existing run")
        previous = await session.scalar(
            select(func.max(ReworkOperationLog.revision)).where(
                ReworkOperationLog.approval_id == snapshot.approval_id
            )
        )
        if snapshot.revision == 0:
            other = await session.scalar(
                select(ReworkConfirmationRecord.approval_id)
                .where(
                    ReworkConfirmationRecord.run_id == snapshot.run_id,
                    ReworkConfirmationRecord.approval_id != snapshot.approval_id,
                )
                .limit(1)
            )
            if other is not None or run.status != AgentRunStatus.RUNNING or run.final_result:
                raise ValueError("rework observation requires a dedicated running run")
        elif previous != snapshot.revision - 1:
            raise ValueError("rework observation cannot attach to an unobserved approval")
        summary = rework_summary(snapshot)
        phase = str(summary["phase"])
        session.add(
            ReworkOperationLog(
                approval_id=snapshot.approval_id,
                revision=snapshot.revision,
                run_id=snapshot.run_id,
                phase=phase,
                summary=summary,
                recorded_at=now,
            )
        )
        run.started_at = run.started_at or snapshot.created_at
        run.final_result = {"kind": "REWORK_APPROVAL", **summary}
        run.error_code, run.error_step = None, None
        if snapshot.status == "WAITING_CONFIRMATION":
            await self._step(session, snapshot, "approval", AgentStepType.APPROVAL, now=now)
            run.status = AgentRunStatus.WAITING_APPROVAL
            run.termination_reason = "REWORK_WAITING_CONFIRMATION"
        elif snapshot.status == "CONFIRMED":
            await self._complete(session, snapshot, "approval", now=now)
            run.status = AgentRunStatus.WAITING_APPROVAL
            run.termination_reason = "REWORK_CONFIRMED"
        elif snapshot.status == "EXECUTING":
            execution = await self._step(
                session, snapshot, "execution", AgentStepType.WRITEBACK, now=now
            )
            execution.output_summary = phase
            execution.error_code = (
                snapshot.execution_error.code if snapshot.execution_error else None
            )
            run.status = AgentRunStatus.RUNNING
            run.termination_reason = "REWORK_" + phase
        elif snapshot.status == "SUCCEEDED":
            await self._complete(session, snapshot, "execution", now=now)
            run.status = AgentRunStatus.SUCCEEDED
            run.termination_reason = "REWORK_SUCCEEDED"
        else:
            code = "APPROVAL_" + snapshot.status
            phase = "approval"
            waiting = await session.get(AgentStep, rework_step_id(snapshot.approval_id, phase))
            if waiting is not None and waiting.status == AgentStepStatus.SUCCEEDED:
                phase = "invalidation"
                await self._step(session, snapshot, phase, AgentStepType.WORKFLOW, now=now)
            await self._complete(session, snapshot, phase, now=now, error_code=code)
            run.status = (
                AgentRunStatus.CANCELLED
                if snapshot.status == "CANCELLED"
                else AgentRunStatus.FAILED
            )
            run.termination_reason = code
            run.error_code = code
            run.error_step = rework_step_id(snapshot.approval_id, phase)
        terminal = run.status in {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
        run.finished_at = now if terminal else None
        run.duration_ms = elapsed_ms(run.started_at, now) if terminal else None
        run.updated_at = now

    @staticmethod
    async def _step(
        session: AsyncSession,
        snapshot: ReworkConfirmationSnapshot,
        phase: str,
        kind: AgentStepType,
        *,
        now: datetime,
    ) -> AgentStep:
        """Run行锁保护序号分配，等待和写入使用不同的持久步骤。"""

        identity = rework_step_id(snapshot.approval_id, phase)
        step = await session.get(AgentStep, identity)
        if step is not None:
            return step
        sequence = await session.scalar(
            select(func.max(AgentStep.sequence_number)).where(AgentStep.run_id == snapshot.run_id)
        )
        step = AgentStep(
            step_id=identity,
            run_id=snapshot.run_id,
            sequence_number=(sequence or 0) + 1,
            step_type=kind,
            step_name="rework_" + phase,
            status=AgentStepStatus.RUNNING,
            input_summary="Independent rework operation",
            started_at=now,
        )
        session.add(step)
        await session.flush()
        return step

    @staticmethod
    async def _complete(
        session: AsyncSession,
        snapshot: ReworkConfirmationSnapshot,
        phase: str,
        *,
        now: datetime,
        error_code: str | None = None,
    ) -> None:
        """终结已有职责Step，不覆盖已结束的人工确认记录。"""

        step = await session.get(AgentStep, rework_step_id(snapshot.approval_id, phase))
        if step is None:
            raise ValueError("rework observation step is missing")
        if step.status != AgentStepStatus.RUNNING:
            return
        step.status = AgentStepStatus.FAILED if error_code else AgentStepStatus.SUCCEEDED
        step.output_summary = error_code or "Completed"
        step.error_code, step.finished_at = error_code, now
        step.duration_ms = elapsed_ms(step.started_at or now, now)
