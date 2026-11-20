"""自然语言返工引导只查询Java并定位现有页面确认流程。"""

import re
from dataclasses import dataclass

from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.schemas.agent_messages import ReworkGuidanceResult, ReworkGuidanceTarget
from app.schemas.rework import ReworkAction
from app.tools.models import ToolContext, ToolResult
from app.tools.rework_readonly import GetDeliveryConditionsTool, GetReworkDetailTool

_PHRASES: dict[str, ReworkAction | None] = {
    "查询返工状态": None,
    "查看返工状态": None,
    "查询返工进度": None,
    "查看返工进度": None,
    "查询返工": None,
    "查看返工": None,
    "开始返工": "START_REWORK",
    "登记阻塞": "BLOCK_REWORK",
    "登记失败": "FAIL_REWORK",
    "恢复处理": "RESUME_REWORK",
    "登记成果": "REGISTER_REWORK_RESULT",
    "登记人工检查": "REGISTER_REWORK_INSPECTION",
    "再次复核": "SUBMIT_REWORK_REVIEW",
    "创建下一轮返工": "CREATE_NEXT_REWORK",
}
_COMMAND = re.compile(r"^(?:请\s*(?:帮我\s*)?|帮我\s*|我想\s*)?(" + "|".join(_PHRASES) + r")")
_IDENTIFIER = re.compile(r"(ORDER|TASK|REWORK)-[A-Z0-9][A-Z0-9-]*", re.IGNORECASE | re.ASCII)


@dataclass(frozen=True, slots=True)
class ReworkEntryCommand:
    """只抽取动作与定位编号，忽略模型及会话的历史候选。"""

    operation: ReworkAction | None
    order_id: str | None
    task_id: str | None
    rework_id: str | None
    valid: bool


def parse_rework_entry(message: str) -> ReworkEntryCommand | None:
    """接受明确短句，多余内容或重复定位必须由用户重述。"""

    match = _COMMAND.match(message)
    if match is None:
        return None
    tokens = re.split(r"[\s，,]+", message[match.end() :].strip(" \t：:。？\uff01?!"))
    ids: dict[str, str] = {}
    for token in filter(None, tokens):
        identifier = _IDENTIFIER.fullmatch(token)
        if identifier is None or len(token) > 64 or identifier[1].upper() in ids:
            return ReworkEntryCommand(_PHRASES[match[1]], None, None, None, False)
        ids[identifier[1].upper()] = token.upper()
    return ReworkEntryCommand(
        _PHRASES[match[1]], ids.get("ORDER"), ids.get("TASK"), ids.get("REWORK"), True
    )


def _fact[FactT](result: ToolResult[FactT]) -> FactT:
    """保留稳定Tool错误分类，避免透传上游文本。"""

    if result.data is not None:
        return result.data
    assert result.error is not None
    raise ToolException(
        code=result.error.code,
        message="rework facts could not be read",
        retryable=result.error.retryable,
        status_code=result.error.status_code,
    )


class ReworkAgentEntry:
    """能力只包含两个只读Tool，产出可重查的页面引导。"""

    def __init__(self, client: ReworkHttpClient) -> None:
        """复用T822只读Tool及其响应绑定检查。"""

        self._conditions = GetDeliveryConditionsTool(client)
        self._detail = GetReworkDetailTool(client)

    async def resolve(
        self, command: ReworkEntryCommand, *, page_order_id: str | None, context: ToolContext
    ) -> ReworkGuidanceResult:
        """先核对订单和任务，再定位唯一返工及当前允许动作。"""

        order_id = command.order_id or page_order_id
        if (
            not command.valid
            or order_id is None
            or (page_order_id is not None and order_id != page_order_id)
        ):
            return ReworkGuidanceResult(
                state="NEEDS_INPUT", order_id=None, operation=command.operation
            )
        snapshot = _fact(await self._conditions.execute({"order_id": order_id}, context))
        if snapshot.order.order_id != order_id:
            raise ToolException(
                code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                message="rework order binding differs",
                retryable=False,
            )
        candidates: set[tuple[str, str]] = set()
        for task in snapshot.tasks:
            if command.task_id is not None and task.task_id != command.task_id:
                continue
            if command.task_id is not None and command.rework_id is not None:
                # 显式给出同订单任务与历史返工时，由详情Tool核验真实父子关系。
                candidates.add((task.task_id, command.rework_id))
                continue
            ids = {row.rework_task_id for row in task.active_reworks}
            ids.update(
                review_id
                for row in task.issues
                if (review_id := row.effective_review.rework_task_id) is not None
            )
            candidates.update(
                (task.task_id, key)
                for key in ids
                if command.rework_id is None or key == command.rework_id
            )
        if not candidates:
            return ReworkGuidanceResult(
                state="NOT_FOUND", order_id=order_id, operation=command.operation
            )
        targets = tuple(
            ReworkGuidanceTarget(task_id=task_id, rework_task_id=rework_id)
            for task_id, rework_id in sorted(candidates)[:20]
        )
        if len(targets) > 1:
            return ReworkGuidanceResult(
                state="CHOOSE_TARGET",
                order_id=order_id,
                operation=command.operation,
                candidates=targets,
            )
        target = targets[0]
        lookup = await self._detail.execute(target.model_dump(), context)
        if lookup.error is not None and lookup.error.code == ToolErrorCode.RESOURCE_NOT_FOUND:
            # 候选列表与详情分开读取。详情确认不存在时，请用户重新定位原目标。
            return ReworkGuidanceResult(
                state="NOT_FOUND", order_id=order_id, operation=command.operation
            )
        detail = _fact(lookup)
        if (
            detail.rework_task.task_id != target.task_id
            or detail.rework_task.rework_task_id != target.rework_task_id
        ):
            raise ToolException(
                code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                message="rework target binding differs",
                retryable=False,
            )
        task_version = next(
            task.task_version for task in snapshot.tasks if task.task_id == target.task_id
        )
        if detail.task_version != task_version:
            raise ToolException(
                code=ToolErrorCode.BUSINESS_CONFLICT,
                message="rework facts changed during lookup",
                retryable=False,
            )
        can_prepare = command.operation is None or (
            context.identity.role == "REVIEWER" and command.operation in detail.allowed_actions
        )
        return ReworkGuidanceResult(
            state="READY" if can_prepare else "ACTION_UNAVAILABLE",
            order_id=order_id,
            operation=command.operation,
            candidates=targets,
            status=detail.rework_task.status,
            round_number=detail.round_number,
        )
