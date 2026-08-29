"""固定 Workflow 调用 M2.3 Step 生命周期的短事务适配器。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.database import Database
from app.eventing import RunEventSink
from app.models import AgentStepType
from app.repositories import AgentRunRepository, AgentStepRepository
from app.schemas.events import RunEventType

if TYPE_CHECKING:
    from app.services.step_lifecycle import StepLifecycleService


def _step_lifecycle_service(
    step_repository: AgentStepRepository,
    run_repository: AgentRunRepository,
) -> StepLifecycleService:
    """延迟加载生命周期服务, 避免 Workflow 与服务公开入口循环导入。"""

    from app.services.step_lifecycle import StepLifecycleService

    return StepLifecycleService(step_repository, run_repository)


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
            service = _step_lifecycle_service(
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
            service = _step_lifecycle_service(
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
            service = _step_lifecycle_service(
                AgentStepRepository(session),
                AgentRunRepository(session),
            )
            await service.mark_failed(
                step_id,
                error_code=error_code,
                output_summary=output_summary,
            )


class EventPublishingWorkflowStepRecorder:
    """装饰Step记录器, 在数据库成功后发布对应实时事件。"""

    def __init__(self, delegate: WorkflowStepRecorder, event_sink: RunEventSink) -> None:
        self._delegate = delegate
        self._event_sink = event_sink
        self._steps: dict[str, tuple[str, AgentStepType, str]] = {}

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
        """先持久化Step, 再为Tool步骤发布开始事件。"""

        await self._delegate.start_step(
            step_id=step_id,
            run_id=run_id,
            sequence_number=sequence_number,
            step_type=step_type,
            step_name=step_name,
            input_summary=input_summary,
        )
        self._steps[step_id] = (run_id, step_type, step_name)
        if step_type is AgentStepType.TOOL:
            await self._event_sink.publish(
                RunEventType.TOOL_STARTED,
                run_id=run_id,
                step_id=step_id,
                data={"step_name": step_name, "status": "RUNNING"},
            )

    async def mark_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
    ) -> None:
        """先保存成功终态, 再发布不含原始输出的Tool完成事件。"""

        await self._delegate.mark_succeeded(step_id, output_summary=output_summary)
        await self._publish_tool_completed(step_id, status="SUCCEEDED", error_code=None)

    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
    ) -> None:
        """先保存失败终态, 再发布机器错误码。"""

        await self._delegate.mark_failed(
            step_id,
            error_code=error_code,
            output_summary=output_summary,
        )
        await self._publish_tool_completed(
            step_id,
            status="FAILED",
            error_code=error_code,
        )

    async def _publish_tool_completed(
        self,
        step_id: str,
        *,
        status: str,
        error_code: str | None,
    ) -> None:
        metadata = self._steps.pop(step_id, None)
        if metadata is None:
            return
        run_id, step_type, step_name = metadata
        if step_type is not AgentStepType.TOOL:
            return
        data = {"step_name": step_name, "status": status}
        if error_code is not None:
            data["error_code"] = error_code
        await self._event_sink.publish(
            RunEventType.TOOL_COMPLETED,
            run_id=run_id,
            step_id=step_id,
            data=data,
        )
