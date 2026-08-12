"""固定 Workflow 调用 M2.3 Step 生命周期的短事务适配器。"""

from __future__ import annotations

from typing import Protocol

from app.database import Database
from app.models import AgentStepType
from app.repositories import AgentRunRepository, AgentStepRepository
from app.services.step_lifecycle import StepLifecycleService


class WorkflowStepRecorder(Protocol):
    """定义 Workflow 与 Step 持久化之间可替换的最小边界。"""

    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None,
    ) -> None:
        """在执行节点动作前保存 RUNNING Step。"""

        ...

    async def mark_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
    ) -> None:
        """在独立短事务中把 Step 标记为成功。"""

        ...

    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
    ) -> None:
        """在独立短事务中把 Step 标记为失败。"""

        ...


class DatabaseWorkflowStepRecorder:
    """使用独立数据库会话记录每个 Workflow Step, 避免跨网络调用持锁。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None,
    ) -> None:
        """创建并提交 RUNNING Step 后立即释放父 Run 行锁。"""

        async with self._database.session() as session, session.begin():
            service = StepLifecycleService(
                AgentStepRepository(session),
                AgentRunRepository(session),
            )
            await service.start_step(
                step_id=step_id,
                run_id=run_id,
                sequence_number=sequence_number,
                step_type=step_type,
                step_name=step_name,
                input_summary=input_summary,
            )

    async def mark_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
    ) -> None:
        """使用新事务保存成功摘要和耗时。"""

        async with self._database.session() as session, session.begin():
            service = StepLifecycleService(
                AgentStepRepository(session),
                AgentRunRepository(session),
            )
            await service.mark_succeeded(step_id, output_summary=output_summary)

    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
    ) -> None:
        """使用新事务保存失败码、安全摘要和耗时。"""

        async with self._database.session() as session, session.begin():
            service = StepLifecycleService(
                AgentStepRepository(session),
                AgentRunRepository(session),
            )
            await service.mark_failed(
                step_id,
                error_code=error_code,
                output_summary=output_summary,
            )
