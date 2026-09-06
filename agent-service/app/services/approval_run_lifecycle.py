"""把Approval状态变化投影到所属Run和人工确认/写回Step。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRunStatus, AgentStepStatus, AgentStepType, ApprovalStatus
from app.repositories import AgentRunRepository, AgentStepRepository
from app.services.run_lifecycle import RunLifecycleService
from app.services.step_lifecycle import StepLifecycleService


def approval_step_id(approval_id: str) -> str:
    """生成草稿阶段和确认阶段共享的稳定Approval Step身份。"""

    return f"step-approval-{approval_id[-100:]}"


def writeback_step_id(approval_id: str) -> str:
    """生成一次Approval唯一对应的写回Step身份。"""

    return f"step-writeback-{approval_id[-99:]}"


async def begin_approval_execution(
    session: AsyncSession,
    *,
    run_id: str,
    approval_id: str,
    tool_name: str,
) -> None:
    """执行锁成功后恢复Run、结束等待Step并开始WRITEBACK Step。"""

    runs = AgentRunRepository(session)
    steps = AgentStepRepository(session)
    await RunLifecycleService(runs).resume_approval_execution(run_id)
    await StepLifecycleService(steps, runs).mark_succeeded(
        approval_step_id(approval_id),
        output_summary="approval=confirmed",
    )
    await StepLifecycleService(steps, runs).start_step(
        step_id=writeback_step_id(approval_id),
        run_id=run_id,
        sequence_number=await steps.next_sequence_number(run_id),
        step_type=AgentStepType.WRITEBACK,
        step_name=tool_name,
        input_summary=f"approval={approval_id}",
    )


async def finish_waiting_approval(
    session: AsyncSession,
    *,
    run_id: str,
    approval_id: str,
    approval_status: ApprovalStatus,
) -> None:
    """在写入前取消或失效时结束等待Step和WAITING Run。"""

    runs = AgentRunRepository(session)
    steps = AgentStepRepository(session)
    step_service = StepLifecycleService(steps, runs)
    if approval_status is ApprovalStatus.CANCELLED:
        await step_service.mark_succeeded(
            approval_step_id(approval_id),
            output_summary="approval=cancelled",
        )
        target_status = AgentRunStatus.CANCELLED
        error_code = None
    else:
        await step_service.mark_failed(
            approval_step_id(approval_id),
            error_code=f"APPROVAL_{approval_status.value}",
            output_summary=f"approval={approval_status.value.lower()}",
        )
        target_status = AgentRunStatus.FAILED
        error_code = f"APPROVAL_{approval_status.value}"
    await RunLifecycleService(runs).finish_approval_run(
        run_id,
        target_status=target_status,
        approval_status=approval_status,
        error_code=error_code,
        error_step=("wait_for_confirmation" if error_code is not None else None),
        expected_status=AgentRunStatus.WAITING_APPROVAL,
    )


async def finish_approval_execution(
    session: AsyncSession,
    *,
    run_id: str,
    approval_id: str,
    approval_status: ApprovalStatus,
    error_code: str | None = None,
) -> None:
    """写Tool结束后同步WRITEBACK Step与Run唯一终态。"""

    runs = AgentRunRepository(session)
    steps = AgentStepRepository(session)
    step = await steps.get_fresh(writeback_step_id(approval_id))
    if step is None or step.status is not AgentStepStatus.RUNNING:
        raise ValueError("approval writeback step is not running")
    step_service = StepLifecycleService(steps, runs)
    if approval_status is ApprovalStatus.SUCCEEDED:
        await step_service.mark_succeeded(
            step.step_id,
            output_summary="writeback=succeeded",
        )
        run_status = AgentRunStatus.SUCCEEDED
        run_error = None
    else:
        stable_error = error_code or f"APPROVAL_{approval_status.value}"
        await step_service.mark_failed(
            step.step_id,
            error_code=stable_error,
            output_summary=f"writeback={approval_status.value.lower()}",
        )
        run_status = AgentRunStatus.FAILED
        run_error = stable_error
    await RunLifecycleService(runs).finish_approval_run(
        run_id,
        target_status=run_status,
        approval_status=approval_status,
        error_code=run_error,
        error_step=(step.step_name if run_error is not None else None),
    )
