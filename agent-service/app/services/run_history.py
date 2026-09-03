"""按当前用户读取Run列表、详情和Step时间线。"""

from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.database import Database
from app.models import AgentRun, AgentStep, ApprovalRecord
from app.repositories import AgentRunRepository, AgentStepRepository, ApprovalRecordRepository
from app.schemas.agent_messages import (
    AgentMessageResult,
    AgentResultKind,
    DiagnosisAgentResult,
)
from app.schemas.approval import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.run_history import (
    ApprovalHistory,
    RunDetailResponse,
    RunListResponse,
    RunSummary,
    StepListResponse,
    StepSummary,
)
from app.schemas.tools import OrderIdentifier, TaskIdentifier
from app.schemas.workflow import DiagnosisResult
from app.services.operation_log import draft_diff

_ORDER_ID_ADAPTER = TypeAdapter(OrderIdentifier)
_TASK_ID_ADAPTER = TypeAdapter(TaskIdentifier)
_AGENT_RESULT_ADAPTER: TypeAdapter[AgentMessageResult] = TypeAdapter(AgentMessageResult)


class RunHistoryAccessError(Exception):
    """当前身份没有Run历史读取权限。"""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DatabaseRunHistoryService:
    """从Agent数据库读取当前用户自己的Run, 并输出受控历史视图。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_runs(
        self,
        *,
        identity: BusinessIdentity,
        page: int,
        page_size: int,
    ) -> RunListResponse:
        """执行用户隔离分页; REVIEWER不能查看其他会话所有者的Run。"""

        _require_reviewer(identity)
        offset = (page - 1) * page_size
        async with self._database.session() as session:
            runs, total = await AgentRunRepository(session).list_for_user(
                identity.user_id,
                offset=offset,
                limit=page_size,
            )
        return RunListResponse(
            items=tuple(run_summary_from_record(run) for run in runs),
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_run_detail(
        self,
        *,
        identity: BusinessIdentity,
        run_id: str,
    ) -> RunDetailResponse:
        """重新校验Run所有权, 并返回结果、引用和Approval修改记录。"""

        _require_reviewer(identity)
        async with self._database.session() as session:
            run = await AgentRunRepository(session).get_for_user(run_id, identity.user_id)
            if run is None:
                raise _run_not_found()
            approvals = await ApprovalRecordRepository(session).list_by_run(run_id)
        agent_result = agent_result_from_record(run)
        return RunDetailResponse(
            run=run_summary_from_record(run),
            input_token_count=run.input_token_count,
            output_token_count=run.output_token_count,
            agent_result=agent_result,
            result=(
                agent_result.diagnosis
                if agent_result is not None and agent_result.kind is AgentResultKind.DIAGNOSIS
                else None
            ),
            approvals=tuple(approval_history_from_record(item) for item in approvals),
        )

    async def list_steps(
        self,
        *,
        identity: BusinessIdentity,
        run_id: str,
    ) -> StepListResponse:
        """先校验Run归属, 再读取按序号排列的安全Step摘要。"""

        _require_reviewer(identity)
        async with self._database.session() as session:
            run = await AgentRunRepository(session).get_for_user(run_id, identity.user_id)
            if run is None:
                raise _run_not_found()
            steps = await AgentStepRepository(session).list_by_run(run_id)
        return StepListResponse(
            run_id=run.run_id,
            items=tuple(step_summary_from_record(step) for step in steps),
        )

# 列表转换函数，将AgentRun模型转换为RunSummary模型，白名单投影安全字段
def run_summary_from_record(run: AgentRun) -> RunSummary:
    """只投影列表需要的安全字段, 避免复制完整上下文、结果和版本信息。"""

    page_context = run.page_context_snapshot if isinstance(run.page_context_snapshot, dict) else {}
    return RunSummary(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        order_id=_optional_identifier(page_context.get("order_id"), _ORDER_ID_ADAPTER),
        task_id=_optional_identifier(page_context.get("task_id"), _TASK_ID_ADAPTER),
        tool_call_count=run.tool_call_count,
        total_token_count=run.total_token_count,
        duration_ms=run.duration_ms,
        termination_reason=run.termination_reason,
        error_code=run.error_code,
        error_step=run.error_step,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )

# Step详情映射
def step_summary_from_record(step: AgentStep) -> StepSummary:
    """投影Step已收敛摘要, 绝不返回Tool原始载荷。"""

    return StepSummary(
        step_id=step.step_id,
        sequence_number=step.sequence_number,
        step_type=step.step_type,
        step_name=step.step_name,
        status=step.status,
        input_summary=step.input_summary,
        output_summary=step.output_summary,
        error_code=step.error_code,
        duration_ms=step.duration_ms,
        model_name=step.llm_model_name,
        input_token_count=step.llm_input_token_count,
        output_token_count=step.llm_output_token_count,
        total_token_count=step.llm_total_token_count,
        retry_count=step.llm_retry_count,
        created_at=step.created_at,
        started_at=step.started_at,
        finished_at=step.finished_at,
    )


def approval_history_from_record(approval: ApprovalRecord) -> ApprovalHistory:
    """恢复强类型Approval草稿并计算模型原稿到用户最终稿的差异。"""

    original = ReviewDraft.model_validate(approval.original_draft)
    effective = ReviewDraft.model_validate(approval.user_modified_draft or approval.original_draft)
    return ApprovalHistory(
        approval_id=approval.approval_id,
        status=approval.status,
        operation_type=approval.operation_type,
        target_id=approval.target_id,
        target_version=approval.target_version,
        original_draft=original,
        effective_draft=effective,
        user_modification_diff=draft_diff(original, effective),
        confirmed_at=approval.confirmed_at,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def agent_result_from_record(run: AgentRun) -> AgentMessageResult | None:
    """恢复统一Envelope, 并把既有固定诊断快照安全包装为DIAGNOSIS。"""

    if run.final_result is None:
        return None
    try:
        return _AGENT_RESULT_ADAPTER.validate_python(run.final_result, strict=False)
    except ValidationError:
        try:
            diagnosis = DiagnosisResult.model_validate(run.final_result, strict=False)
        except ValidationError:
            return None
        return DiagnosisAgentResult(diagnosis=diagnosis)


def _require_reviewer(identity: BusinessIdentity) -> None:
    """Run历史当前只开放给本人REVIEWER。"""

    if identity.role != "REVIEWER":
        raise RunHistoryAccessError(
            code="PERMISSION_DENIED",
            message="reviewer permission is required",
            status_code=403,
        )

# 他人Run和不存在Run都返回404 错误
def _run_not_found() -> RunHistoryAccessError:
    """不存在和不属于当前用户共用404, 避免资源枚举。"""

    return RunHistoryAccessError(
        code="RUN_NOT_FOUND",
        message="run was not found",
        status_code=404,
    )

# 订单ID也需要重新验证，避免资源枚举
def _optional_identifier(value: Any, adapter: TypeAdapter[Any]) -> str | None:
    """历史快照缺失或损坏时隐藏资源提示, 不让一行坏数据泄露或阻断整个列表。"""

    if value is None:
        return None
    try:
        validated = adapter.validate_python(value, strict=True)
    except ValidationError:
        return None
    return str(validated)
