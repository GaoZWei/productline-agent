"""诊断 API 的 Run、Workflow 和终态持久化编排。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.database import Database
from app.models import AgentMessage, AgentMessageRole, AgentSession
from app.repositories import (
    AgentMessageRepository,
    AgentRunRepository,
    AgentSessionRepository,
)
from app.schemas.business import BusinessIdentity
from app.schemas.context import PageContext
from app.schemas.session import (
    context_from_page,
    page_context_from_session,
)
from app.schemas.workflow import DiagnosisResult, StepError
from app.services.run_lifecycle import RunLifecycleService
from app.services.session_context import (
    SessionAccessDeniedError,
    SessionContextError,
    SessionContextService,
)
from app.tools import ToolContext, ToolRegistry
from app.workflows import DatabaseWorkflowStepRecorder, OrderDiagnosisWorkflow

_LOGGER = logging.getLogger("agent-service.order-diagnosis")
_ORDER_DIAGNOSIS_PERMISSIONS = frozenset(
    {
        "ORDER_READ",
        "TASK_READ",
        "QUALITY_ISSUE_READ",
        "REVIEW_READ",
        "DELIVERY_READ",
    }
)
_WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"


@dataclass(frozen=True, slots=True)
class OrderDiagnosisExecution:
    """一次成功诊断的 Run 标识与结果。"""

    run_id: str
    session_id: str
    diagnosis: DiagnosisResult


class OrderDiagnosisExecutionError(Exception):
    """表示已经转换为安全 API 字段的诊断执行失败。"""

    def __init__(
        self,
        *,
        run_id: str | None,
        code: str,
        message: str,
        retryable: bool,
        error_step: str | None,
    ) -> None:
        self.run_id = run_id
        self.code = code
        self.message = message
        self.retryable = retryable
        self.error_step = error_step
        super().__init__(f"{code}: {message}")

# 订单诊断服务, 负责完整的请求级生命周期
class OrderDiagnosisService:
    """为一次 HTTP 请求创建运行上下文并收口固定 Workflow。"""

    def __init__(
        self,
        database: Database,
        tool_registry: ToolRegistry,
        *,
        session_ttl_seconds: int,
    ) -> None:
        self._database = database
        self._tool_registry = tool_registry
        self._session_ttl = timedelta(seconds=session_ttl_seconds)

    async def diagnose(
        self,
        *,
        session_id: str | None,
        order_id: str | None,
        user_message: str,
        page_context: PageContext | None,
        identity: BusinessIdentity,
        trace_id: str,
    ) -> OrderDiagnosisExecution:
        """执行一次诊断并把 Run 从 PENDING 推进到唯一终态。"""

        request_id = uuid4().hex
        message_id = f"message-{request_id}"
        run_id = f"run-{request_id}"
        try:
            resolved_session_id, resolved_order_id, resolved_page_context = (
                await self._create_running_run(
                    requested_session_id=session_id,
                    order_id=order_id,
                    page_context=page_context,
                    message_id=message_id,
                    run_id=run_id,
                    identity=identity,
                    user_message=user_message,
                )
            )
        except SessionContextError as context_error:
            raise OrderDiagnosisExecutionError(
                run_id=None,
                code=context_error.code,
                message=context_error.message,
                retryable=False,
                error_step=None,
            ) from context_error
        except ValueError as context_error:
            raise OrderDiagnosisExecutionError(
                run_id=None,
                code="SESSION_CONTEXT_INCOMPLETE",
                message="agent session does not contain a current order",
                retryable=False,
                error_step=None,
            ) from context_error
        # 创建工具上下文
        context = ToolContext(
            identity=identity,
            permissions=_ORDER_DIAGNOSIS_PERMISSIONS,
            trace_id=trace_id,
            run_id=run_id,
        )
        # workflow接入数据库Step
        workflow = OrderDiagnosisWorkflow(
            tool_registry=self._tool_registry,  # 找到七个只读Tool节点
            tool_context=context,  # 提供身份、权限、Trace和RunID
            # 把每个Workflow节点记录为数据库Step
            step_recorder=DatabaseWorkflowStepRecorder(self._database),
        )
        # 执行Workflow
        try:
            state = await workflow.ainvoke(
                resolved_order_id,
                page_context=resolved_page_context,
            )
        except Exception as exception:
            await self._mark_failed_safely(
                run_id,
                error_code=_WORKFLOW_EXECUTION_ERROR,
                error_step="order_diagnosis_workflow",
            )
            raise OrderDiagnosisExecutionError(
                run_id=run_id,
                code=_WORKFLOW_EXECUTION_ERROR,
                message="order diagnosis workflow execution failed",
                retryable=False,
                error_step="order_diagnosis_workflow",
            ) from exception
        # 标准Tool错误不会直接抛出原始异常, 而是写入state["errors"]
        if state["errors"]:
            error = state["errors"][0]
            await self._mark_failed(
                run_id,
                error_code=error.code.value,
                error_step=error.step_name,
            )
            raise self._execution_error(run_id, error)
        # 成功时 保存Run成功结果
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            await self._mark_failed(
                run_id,
                error_code=_WORKFLOW_EXECUTION_ERROR,
                error_step="generate_diagnosis",
            )
            raise OrderDiagnosisExecutionError(
                run_id=run_id,
                code=_WORKFLOW_EXECUTION_ERROR,
                message="order diagnosis workflow produced no result",
                retryable=False,
                error_step="generate_diagnosis",
            )

        async with self._database.session() as session, session.begin():
            lifecycle = RunLifecycleService(AgentRunRepository(session))
            # 新事务结束Run
            await lifecycle.mark_succeeded(
                run_id,
                final_result=diagnosis.model_dump(mode="json"),
            )
        # 最后返回诊断结果
        return OrderDiagnosisExecution(
            run_id=run_id,
            session_id=resolved_session_id,
            diagnosis=diagnosis,
        )

    async def _create_running_run(
        self,
        *,
        requested_session_id: str | None,
        order_id: str | None,
        page_context: PageContext | None,
        message_id: str,
        run_id: str,
        identity: BusinessIdentity,
        user_message: str,
    ) -> tuple[str, str, PageContext]:
        """原子创建或复用会话、追加消息并提交RUNNING Run。"""

        now = datetime.now(UTC)
        async with self._database.session() as session, session.begin():
            session_repository = AgentSessionRepository(session)
            message_repository = AgentMessageRepository(session)
            if requested_session_id is None:
                if order_id is None or page_context is None:
                    raise ValueError("new diagnosis requires page context")
                resolved_session_id = f"session-{uuid4().hex}"
                stored_context = context_from_page(page_context)
                agent_session = AgentSession(
                    session_id=resolved_session_id,
                    user_id=identity.user_id,
                    context=stored_context.model_dump(mode="json"),
                    expires_at=now + self._session_ttl,
                )
                await session_repository.create(agent_session)
                sequence_number = 1
            else:
                resolved_session_id = requested_session_id
                existing_session = await session_repository.get_for_update(
                    resolved_session_id
                )
                SessionContextService.ensure_access(
                    existing_session,
                    identity=identity,
                    now=now,
                )
                assert existing_session is not None
                agent_session = existing_session
                stored_context = SessionContextService.context(agent_session)
                sequence_number = await message_repository.next_sequence_number(
                    resolved_session_id
                )

            if page_context is not None:
                if page_context.user_role != identity.role:
                    raise SessionAccessDeniedError()
                resolved_page_context = page_context
                resolved_order_id = order_id or page_context.order_id
                if order_id is None or order_id == page_context.order_id:
                    stored_context = context_from_page(
                        page_context,
                        base=stored_context,
                    )
            else:
                resolved_page_context = page_context_from_session(
                    stored_context,
                    user_role=identity.role,
                )
                resolved_order_id = order_id or resolved_page_context.order_id

            stored_context = stored_context.model_copy(
                update={
                    "previous_intent": "ORDER_DIAGNOSIS",
                    "recent_diagnosis_run_id": run_id,
                }
            )
            agent_session.context = stored_context.model_dump(mode="json")
            agent_session.expires_at = now + self._session_ttl
            await message_repository.create(
                AgentMessage(
                    message_id=message_id,
                    session_id=resolved_session_id,
                    sequence_number=sequence_number,
                    role=AgentMessageRole.USER,
                    content=user_message,
                )
            )
            lifecycle = RunLifecycleService(AgentRunRepository(session))
            await lifecycle.create_run(
                run_id=run_id,
                session_id=resolved_session_id,
                request_message_id=message_id,
            )
            await lifecycle.mark_running(run_id)
        return resolved_session_id, resolved_order_id, resolved_page_context

    async def _mark_failed(
        self,
        run_id: str,
        *,
        error_code: str,
        error_step: str,
    ) -> None:
        """在独立事务中保存可预期 Workflow 失败。"""

        async with self._database.session() as session, session.begin():
            lifecycle = RunLifecycleService(AgentRunRepository(session))
            await lifecycle.mark_failed(
                run_id,
                error_code=error_code,
                error_step=error_step,
            )

    async def _mark_failed_safely(
        self,
        run_id: str,
        *,
        error_code: str,
        error_step: str,
    ) -> None:
        """异常路径尽力结束 Run, 但不让二次持久化异常覆盖原始故障。"""

        try:
            await self._mark_failed(
                run_id,
                error_code=error_code,
                error_step=error_step,
            )
        except Exception:
            _LOGGER.exception(
                "order_diagnosis_run_finalization_failed",
                extra={"run_id": run_id, "error_code": error_code},
            )

    @staticmethod
    def _execution_error(run_id: str, error: StepError) -> OrderDiagnosisExecutionError:
        return OrderDiagnosisExecutionError(
            run_id=run_id,
            code=error.code.value,
            message=error.message,
            retryable=error.retryable,
            error_step=error.step_name,
        )
