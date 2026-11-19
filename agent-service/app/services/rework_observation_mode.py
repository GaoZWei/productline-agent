"""用持久审计及Run绑定约束内部装配，禁止通过省略观察器降级操作。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolErrorCode, ToolException
from app.models import AgentRun, ReworkConfirmationRecord, ReworkOperationLog
from app.schemas.rework_confirmation import ReworkConfirmationSnapshot


class ReworkObservationModeError(ToolException):
    """装配与已保存模式冲突时关闭失败，不包含对象、草稿或执行键。"""

    def __init__(self) -> None:
        """固定为不可重试的内部校验错误，调用者应恢复正确装配而非重发。"""

        super().__init__(
            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            message="rework observation mode does not match stored approval",
            retryable=False,
            status_code=500,
        )


def _reserved(run: AgentRun) -> bool:
    """已有返工观测Run不能再承载未观测的另一份审查。"""

    if not isinstance(run.final_result, dict):
        return False
    return bool(run.final_result.get("kind") == "REWORK_APPROVAL")


async def require_rework_creation_mode(
    session: AsyncSession, run: AgentRun, *, observed: bool
) -> None:
    """在Run锁内检查新审查的模式和专属绑定，不自动接管旧记录。"""

    audit = await session.scalar(
        select(ReworkOperationLog.approval_id)
        .where(ReworkOperationLog.run_id == run.run_id)
        .limit(1)
    )
    if audit is not None or _reserved(run):
        raise ReworkObservationModeError()
    if observed:
        existing = await session.scalar(
            select(ReworkConfirmationRecord.approval_id)
            .where(ReworkConfirmationRecord.run_id == run.run_id)
            .limit(1)
        )
        if existing is not None or run.final_result:
            raise ReworkObservationModeError()


async def require_rework_observation_mode(
    session: AsyncSession,
    snapshot: ReworkConfirmationSnapshot,
    *,
    observed: bool,
    run: AgentRun | None = None,
) -> None:
    """归属校验后读取模式，写事务须先锁Run再锁审批并在更新前重验。"""

    if run is None:
        run = await session.get(AgentRun, snapshot.run_id)
    if run is None or run.run_id != snapshot.run_id:
        raise ReworkObservationModeError()
    audit = await session.scalar(
        select(ReworkOperationLog.approval_id)
        .where(ReworkOperationLog.approval_id == snapshot.approval_id)
        .limit(1)
    )
    if observed:
        if (
            audit is None
            or not _reserved(run)
            or run.final_result is None
            or run.final_result.get("approval_id") != snapshot.approval_id
        ):
            raise ReworkObservationModeError()
    elif audit is not None or _reserved(run):
        # 即使审计被删光，已有Run绑定仍禁止回退成未观测模式。
        raise ReworkObservationModeError()
