"""T827确定性只读取证→动作前提→独立审查草稿，不持久化或执行写入。"""

import asyncio
import math
from typing import NoReturn

from pydantic import BaseModel

from app.errors import ToolErrorCode, ToolException
from app.schemas.rework import MAX_SAFE_INTEGER, ReworkDetail
from app.schemas.rework_approval import review_rework_approval_draft
from app.schemas.rework_delivery import DeliveryConditions, DeliveryIssueCondition
from app.schemas.rework_draft import (
    CreateReworkDraftCommand,
    PreparedReworkDraft,
    ReworkDraftCommand,
    ReworkInspectionDraftCommand,
    ReworkReviewDraftCommand,
    parse_rework_draft_command,
)
from app.schemas.tools import TaskDetail
from app.tools.base import ToolRiskLevel
from app.tools.models import ToolContext
from app.tools.registry import ToolNotRegisteredError, ToolRegistry


class ReworkDraftWorkflow:
    """仅持有只读注册表，生产装配、确认前重验和持久化执行由后续阶段接入。"""

    def __init__(
        self,
        *,
        task_tools: ToolRegistry,
        rework_tools: ToolRegistry,
        timeout_seconds: float = 15.0,
    ) -> None:
        """总预算覆盖全部取证和草稿生成，重试仍只由各只读Tool控制。"""

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("draft workflow timeout must be positive and finite")
        self._tasks = task_tools
        self._reworks = rework_tools
        self._timeout = float(timeout_seconds)

    async def ainvoke(self, command: object, *, context: ToolContext) -> PreparedReworkDraft:
        """重新读取事实，不接受现成目标快照，失败不生成可确认草稿或任何写入。"""

        try:
            parsed = parse_rework_draft_command(command)
        except ValueError:
            self._fail(ToolErrorCode.PARAM_VALIDATION_ERROR, context, "draft command is invalid")
        write_permission = (
            "REVIEW_WRITE" if parsed.operation == "SUBMIT_REWORK_REVIEW" else "REWORK_WRITE"
        )
        if not {"TASK_READ", "REWORK_READ", write_permission}.issubset(context.permissions):
            self._fail(ToolErrorCode.PERMISSION_DENIED, context, "draft permission denied")
        try:
            async with asyncio.timeout(self._timeout):
                return await self._prepare(parsed, context)
        except TimeoutError:
            raise ToolException(
                code=ToolErrorCode.TOOL_TIMEOUT,
                message="draft fact reading budget exhausted",
                retryable=False,
                trace_id=context.trace_id,
            ) from None

    async def _prepare(
        self, command: ReworkDraftCommand, context: ToolContext
    ) -> PreparedReworkDraft:
        """按任务确定真实订单，再用订单只读快照核对当前问题、活动返工及有效复核。"""

        task = await self._read(
            self._tasks, "get_task_detail", {"task_id": command.task_id}, TaskDetail, context
        )
        if task.task_id != command.task_id:
            self._response_error(context)
        conditions = await self._read(
            self._reworks,
            "get_delivery_conditions",
            {"order_id": task.order_id},
            DeliveryConditions,
            context,
        )
        if conditions.order.order_id != task.order_id:
            self._response_error(context)
        selected = next(
            (entry for entry in conditions.tasks if entry.task_id == task.task_id), None
        )
        if selected is None:
            self._response_error(context)
        if selected.task_version != task.version or selected.production_status != task.status:
            self._conflict(context, "task facts changed during draft preparation")
        if task.status != "COMPLETED" or selected.task_version >= MAX_SAFE_INTEGER:
            self._conflict(context, "draft requires a completed task and an incrementable version")
        detail: ReworkDetail | None = None
        if isinstance(command, CreateReworkDraftCommand):
            issue_id = command.source_issue_id
        else:
            detail = await self._read(
                self._reworks,
                "get_rework_detail",
                {"task_id": task.task_id, "rework_task_id": command.rework_task_id},
                ReworkDetail,
                context,
            )
            if (
                detail.rework_task.task_id != task.task_id
                or detail.rework_task.rework_task_id != command.rework_task_id
            ):
                self._response_error(context)
            if detail.round_number is None or detail.rework_task.source_issue_id is None:
                self._conflict(
                    context, "legacy rework without lifecycle cannot create an action draft"
                )
            if detail.task_version != selected.task_version:
                self._conflict(context, "rework version changed during draft preparation")
            issue_id = detail.rework_task.source_issue_id
        issue = next((entry for entry in selected.issues if entry.issue.issue_id == issue_id), None)
        if issue is None:
            self._fail(
                ToolErrorCode.RESOURCE_NOT_FOUND,
                context,
                "source issue is unavailable for this task",
            )
        active = [entry for entry in selected.active_reworks if entry.source_issue_id == issue_id]
        if detail is None:
            if (
                issue.issue.status != "OPEN"
                or issue.effective_review.round_number is not None
                or active
            ):
                self._conflict(
                    context,
                    "first creation requires an open issue "
                    "without a controlled chain or active rework",
                )
        else:
            self._check_binding(detail, issue, context)
            if detail.rework_task.status in {"PENDING", "RUNNING", "BLOCKED", "FAILED"}:
                if detail.rework_task not in active:
                    self._conflict(context, "active rework facts changed during draft preparation")
            self._check_action(command, detail, active_count=len(active), context=context)
        raw = command.model_dump(mode="python")
        request: dict[str, object] = {"expectedVersion": selected.task_version}
        if isinstance(command, CreateReworkDraftCommand):
            request["sourceIssueId"] = issue_id
        for field in (
            "reason",
            "artifact",
            "processing_comment",
            "evidence_references",
            "items",
            "status",
            "review_comment",
        ):
            if field in raw:
                request[field] = raw[field]
        if isinstance(command, ReworkInspectionDraftCommand | ReworkReviewDraftCommand):
            if detail is None or detail.processing is None:
                self._conflict(context, "current processing evidence is required")
            request["processingRevision"] = detail.processing.processing_revision
        if isinstance(command, ReworkReviewDraftCommand):
            if detail is None or detail.inspection is None:
                self._conflict(context, "current passed inspection is required")
            request["inspectionId"] = detail.inspection.inspection_id
        target = {
            "task_id": task.task_id,
            "task_version": selected.task_version,
            "source_issue_id": issue_id,
            "rework_task_id": None if detail is None else detail.rework_task.rework_task_id,
            "round_number": None if detail is None else detail.round_number,
            "previous_rework_task_id": None if detail is None else detail.previous_rework_task_id,
            "processing_revision": None
            if detail is None or detail.processing is None
            else detail.processing.processing_revision,
            "artifact": None
            if detail is None or detail.processing is None
            else detail.processing.artifact,
            "inspection_id": None
            if detail is None or detail.inspection is None
            else detail.inspection.inspection_id,
            "review_id": None
            if detail is None or detail.review is None
            else detail.review.review_id,
        }
        try:
            review = review_rework_approval_draft(
                {"operation": command.operation, "target": target, "request": request}
            )
            # 再序列化复制，审查输出不借用Tool结果或命令中的可变列表。
            return PreparedReworkDraft.model_validate(
                {
                    "review": review.model_dump(mode="python"),
                    "order_id": task.order_id,
                    "current_task": selected.model_dump(mode="python", by_alias=True),
                    "current_rework": None
                    if detail is None
                    else detail.model_dump(mode="python", by_alias=True),
                }
            )
        except ValueError:
            self._response_error(context)

    def _check_binding(
        self, detail: ReworkDetail, issue: DeliveryIssueCondition, context: ToolContext
    ) -> None:
        """跨GET不是SQL快照，版本、问题状态和完整当前绑定不同即停止，不自动拼接。"""

        effective = issue.effective_review
        if (
            issue.issue.status != detail.issue_status
            or effective.rework_task_id != detail.rework_task.rework_task_id
            or effective.round_number != detail.round_number
            or effective.processing_revision
            != (None if detail.processing is None else detail.processing.processing_revision)
            or effective.inspection_id
            != (None if detail.inspection is None else detail.inspection.inspection_id)
            or effective.review != detail.review
        ):
            self._conflict(
                context, "current round or material facts changed during draft preparation"
            )

    def _check_action(
        self,
        command: ReworkDraftCommand,
        detail: ReworkDetail,
        *,
        active_count: int,
        context: ToolContext,
    ) -> None:
        """检查Java允许动作和明确状态前提，允许动作仍不是权限或人工确认凭证。"""

        operation = command.operation
        if operation not in detail.allowed_actions:
            self._conflict(context, "current Java facts do not allow this draft action")
        pair = (detail.rework_task.status, detail.issue_status)
        allowed = {
            "START_REWORK": {("PENDING", "OPEN")},
            "BLOCK_REWORK": {("RUNNING", "PROCESSING")},
            "FAIL_REWORK": {("RUNNING", "PROCESSING")},
            "RESUME_REWORK": {("BLOCKED", "PROCESSING"), ("FAILED", "PROCESSING")},
            "REGISTER_REWORK_RESULT": {("RUNNING", "PROCESSING")},
            "REGISTER_REWORK_INSPECTION": {("RUNNING", "PROCESSING")},
            "SUBMIT_REWORK_REVIEW": {("COMPLETED", "RESOLVED")},
            "CREATE_NEXT_REWORK": {("COMPLETED", "OPEN")},
        }
        if pair not in allowed.get(operation, set()):
            self._conflict(
                context, "current rework or source issue state does not allow this draft"
            )
        if isinstance(command, ReworkInspectionDraftCommand) and detail.processing is None:
            self._conflict(context, "inspection requires current processing evidence")
        if isinstance(command, ReworkReviewDraftCommand) or operation == "CREATE_NEXT_REWORK":
            if (
                detail.processing is None
                or detail.inspection is None
                or detail.inspection.result != "PASSED"
            ):
                self._conflict(context, "review and next round require a current passed inspection")
        if operation == "CREATE_NEXT_REWORK" and (
            detail.review is None
            or detail.review.status not in {"REJECTED", "REWORK_REQUIRED"}
            or active_count
            or detail.round_number is None
            or detail.round_number >= MAX_SAFE_INTEGER
        ):
            self._conflict(
                context, "next round requires a current returned review and no active rework"
            )

    async def _read[FactT: BaseModel](
        self,
        registry: ToolRegistry,
        name: str,
        arguments: dict[str, object],
        model: type[FactT],
        context: ToolContext,
    ) -> FactT:
        """显式刷新只读事实，不把旧Run去重结果或读取失败当作事实缺失。"""

        try:
            tool = registry.get(name)
        except ToolNotRegisteredError:
            self._fail(
                ToolErrorCode.UNKNOWN_TOOL_ERROR, context, "required read tool is unavailable"
            )
        if tool.risk_level != ToolRiskLevel.LOW or tool.output_model is not model:
            self._fail(
                ToolErrorCode.UNKNOWN_TOOL_ERROR, context, "required read tool is misconfigured"
            )
        result = await tool.execute(arguments, context, force_refresh=True)
        if not result.success:
            if result.error is None:
                self._response_error(context)
            raise ToolException(
                code=result.error.code,
                message="latest Java facts could not be read",
                retryable=result.error.retryable,
                trace_id=context.trace_id,
                status_code=result.error.status_code,
            )
        if not isinstance(result.data, BaseModel):
            self._response_error(context)
        try:
            return model.model_validate(result.data.model_dump(mode="python", by_alias=True))
        except ValueError:
            self._response_error(context)

    @staticmethod
    def _fail(code: ToolErrorCode, context: ToolContext, message: str) -> NoReturn:
        """统一安全错误，不在文案或日志中回显人工证据和上游原始正文。"""

        raise ToolException(
            code=code,
            message=message,
            retryable=False,
            trace_id=context.trace_id,
        ) from None

    def _conflict(self, context: ToolContext, message: str) -> NoReturn:
        """过时或不适用的事实不生成待审查草稿。"""

        self._fail(ToolErrorCode.BUSINESS_CONFLICT, context, message)

    def _response_error(self, context: ToolContext) -> NoReturn:
        """响应不自洽时拒绝合成事实。"""

        self._fail(
            ToolErrorCode.RESPONSE_VALIDATION_ERROR, context, "Java draft facts are inconsistent"
        )
