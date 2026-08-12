"""诊断 API 的 Run、Workflow 和终态持久化编排。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

from app.database import Database
from app.models import AgentMessage, AgentMessageRole, AgentSession
from app.repositories import AgentRunRepository
from app.schemas.business import BusinessIdentity
from app.schemas.workflow import DiagnosisResult, StepError
from app.services.run_lifecycle import RunLifecycleService
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
    diagnosis: DiagnosisResult


class OrderDiagnosisExecutionError(Exception):
    """表示已经转换为安全 API 字段的诊断执行失败。"""

    def __init__(
        self,
        *,
        run_id: str,
        code: str,
        message: str,
        retryable: bool,
        error_step: str,
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

    def __init__(self, database: Database, tool_registry: ToolRegistry) -> None:
        self._database = database
        self._tool_registry = tool_registry

    async def diagnose(
        self,
        *,
        order_id: str,
        user_message: str,
        identity: BusinessIdentity,
        trace_id: str,
    ) -> OrderDiagnosisExecution:
        """执行一次诊断并把 Run 从 PENDING 推进到唯一终态。"""

        request_id = uuid4().hex
        session_id = f"session-{request_id}"
        message_id = f"message-{request_id}"
        run_id = f"run-{request_id}"
        await self._create_running_run(
            session_id=session_id,
            message_id=message_id,
            run_id=run_id,
            user_id=identity.user_id,
            user_message=user_message,
        )
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
            state = await workflow.ainvoke(order_id)
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
        return OrderDiagnosisExecution(run_id=run_id, diagnosis=diagnosis)
    # 创建一次性Session和Message
    async def _create_running_run(
        self,
        *,
        session_id: str,
        message_id: str,
        run_id: str,
        user_id: str,
        user_message: str,
    ) -> None:
        """在一个事务中保存一次性请求上下文并提交 RUNNING Run。"""

        async with self._database.session() as session, session.begin():
            session.add(AgentSession(session_id=session_id, user_id=user_id))
            # 保存用户消息到数据库
            session.add(
                AgentMessage(
                    message_id=message_id,
                    session_id=session_id,
                    sequence_number=1,
                    role=AgentMessageRole.USER,
                    content=user_message,
                )
            )
            lifecycle = RunLifecycleService(AgentRunRepository(session))
            await lifecycle.create_run(
                run_id=run_id,
                session_id=session_id,
                request_message_id=message_id,
            )
            await lifecycle.mark_running(run_id)

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
