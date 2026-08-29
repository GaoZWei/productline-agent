"""Agent Run 的最小、可验证生命周期服务。"""

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from app.models import AgentRun, AgentRunStatus
from app.repositories import AgentRunRepository
from app.schemas.context import PageContext
from app.schemas.routing import RouterResult, RoutingDecision
from app.schemas.run_observability import RunTokenUsage
from app.schemas.versioning import RunVersionSnapshot, VersionCaptureStatus

_STABLE_REASON_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class RunLifecycleError(Exception):
    """Run 生命周期内部错误基类, 暂不绑定 HTTP 或 Tool 错误协议。"""


# run_id不存在错误
class RunNotFoundError(RunLifecycleError):
    """目标 Run 不存在。"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"run '{run_id}' was not found")


class InvalidRunTransitionError(RunLifecycleError):
    """Run 当前状态不允许进入目标状态。"""

    def __init__(
        self,
        *,
        run_id: str,
        current_status: AgentRunStatus,
        target_status: AgentRunStatus,
    ) -> None:
        self.run_id = run_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"run '{run_id}' cannot transition from "
            f"{current_status.value} to {target_status.value}"
        )


class RunLifecycleValidationError(RunLifecycleError):
    """生命周期调用参数不满足最小持久化约束。"""

    def __init__(self, *, field_name: str, message: str) -> None:
        self.field_name = field_name
        self.message = message
        super().__init__(f"{field_name}: {message}")


def _utc_now() -> datetime:
    """返回带时区的 UTC 时间, 便于测试替换确定性时钟。"""

    return datetime.now(UTC)


class RunLifecycleService:
    """执行Run启动、诊断终态及成功诊断进入人工确认的原子流转。"""

    def __init__(
        self,
        repository: AgentRunRepository,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository  # 负责数据库访问
        self._now = now  # 负责取得当前时间

    # 创建Run
    async def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        version_snapshot: RunVersionSnapshot,
        request_message_id: str | None = None,
        page_context_snapshot: PageContext | None = None,  # 保存页面上下文信息
    ) -> AgentRun:
        """创建初始 PENDING Run, 父 Session 和可选 Message 必须已经存在。"""
        # 第一步: 校验ID是否有效
        normalized_run_id = self._require_identifier(run_id, "run_id", 128)
        normalized_session_id = self._require_identifier(session_id, "session_id", 128)
        normalized_message_id = (
            self._require_identifier(request_message_id, "request_message_id", 128)
            if request_message_id is not None
            else None
        )
        # 校验版本快照是否完整
        if version_snapshot.capture_status is not VersionCaptureStatus.CAPTURED:
            raise RunLifecycleValidationError(
                field_name="version_snapshot",
                message="must contain a complete captured component snapshot",
            )
        # 第二步: 构造ORM对象
        return await self._repository.create(
            AgentRun(
                run_id=normalized_run_id,
                session_id=normalized_session_id,
                request_message_id=normalized_message_id,
                status=AgentRunStatus.PENDING,  # 初始状态为PENDING
                version_snapshot=self._json_snapshot(
                    version_snapshot.model_dump(mode="json"),  #  转换成标准JSON字符串
                    field_name="version_snapshot",
                ),
                page_context_snapshot=(
                    # 进行标准JSON序列化和反序列化，确保数据格式一致
                    self._json_snapshot(
                        page_context_snapshot.model_dump(mode="json"),
                        field_name="page_context_snapshot",
                    )
                    if page_context_snapshot is not None
                    else None
                ),
            )
        )
    # 记录路由结果
    async def record_router_result(
        self,
        run_id: str,
        *,
        router_result: RouterResult | RoutingDecision,
    ) -> AgentRun:
        """为尚未结束的Run保存经过严格Schema校验的最终路由结果。"""

        normalized_run_id = self._require_identifier(run_id, "run_id", 128)
        updated = await self._repository.save_router_result(
            normalized_run_id,
            router_result=self._json_snapshot(
                router_result.model_dump(mode="json"),
                field_name="router_result",
            ),
        )
        if updated is not None:
            return updated
        current = await self._repository.get(normalized_run_id)
        if current is None:
            raise RunNotFoundError(normalized_run_id)
        raise RunLifecycleValidationError(
            field_name="router_result",
            message=f"cannot update a run in {current.status.value}",
        )

    # 标记为RUNNING
    async def mark_running(self, run_id: str) -> AgentRun:
        """仅允许 PENDING Run 开始执行并记录 started_at。"""
        # 只有当前状态是PENDING, 才能进入RUNNING
        return await self._transition(
            run_id,
            expected_status=AgentRunStatus.PENDING,
            target_status=AgentRunStatus.RUNNING,
            changes={
                "started_at": self._timestamp(),
                "finished_at": None,
                "final_result": None,
                "error_code": None,
                "error_step": None,
                "input_token_count": 0,  # 开始时重置指标为0
                "output_token_count": 0,
                "total_token_count": 0,
                "tool_call_count": 0,
                "duration_ms": None,
                "termination_reason": None,
            },
        )

    # 标记为SUCCEEDED
    async def mark_succeeded(
        self,
        run_id: str,
        *,
        final_result: dict[str, Any],
        token_usage: RunTokenUsage | None = None,
        tool_call_count: int = 0,
        termination_reason: str = "COMPLETED",
    ) -> AgentRun:
        """仅允许 RUNNING Run 成功结束并保存本次执行结果快照。"""

        result_snapshot = self._json_snapshot(final_result)
        terminal_changes = await self._terminal_changes(
            run_id,
            token_usage=token_usage,
            tool_call_count=tool_call_count,
            termination_reason=termination_reason,
        )
        return await self._transition(
            run_id,
            expected_status=AgentRunStatus.RUNNING,
            target_status=AgentRunStatus.SUCCEEDED,
            changes={
                **terminal_changes,
                "final_result": result_snapshot,
                "error_code": None,
                "error_step": None,
            },
        )

    async def mark_waiting_approval(self, run_id: str) -> AgentRun:
        """仅允许带结果的成功诊断进入等待人工确认状态。"""

        return await self._transition(
            run_id,
            expected_status=AgentRunStatus.SUCCEEDED,
            target_status=AgentRunStatus.WAITING_APPROVAL,
            changes={},
        )

    # 标记为FAILED
    async def mark_failed(
        self,
        run_id: str,
        *,
        error_code: str,
        error_step: str,
        token_usage: RunTokenUsage | None = None,
        tool_call_count: int = 0,
        termination_reason: str = "EXECUTION_ERROR",
    ) -> AgentRun:
        """仅允许 RUNNING Run 失败结束并保存机器错误码和失败步骤。"""

        normalized_error_code = self._require_identifier(error_code, "error_code", 64)
        normalized_error_step = self._require_identifier(error_step, "error_step", 128)
        terminal_changes = await self._terminal_changes(
            run_id,
            token_usage=token_usage,
            tool_call_count=tool_call_count,
            termination_reason=termination_reason,
        )
        return await self._transition(
            run_id,
            expected_status=AgentRunStatus.RUNNING,
            target_status=AgentRunStatus.FAILED,
            changes={
                **terminal_changes,
                "final_result": None,
                "error_code": normalized_error_code,
                "error_step": normalized_error_step,
            },
        )
    # 保证成功和失败的以下字段使用完全相同的计算规则
    async def _terminal_changes(
        self,
        run_id: str,
        *,
        token_usage: RunTokenUsage | None,
        tool_call_count: int,
        termination_reason: str,
    ) -> dict[str, Any]:
        """计算终态时间和用量; 状态竞争仍由后续数据库CAS裁决。"""

        normalized_run_id = self._require_identifier(run_id, "run_id", 128)
        # 校验Tool调用数
        if isinstance(tool_call_count, bool) or not isinstance(tool_call_count, int):
            raise RunLifecycleValidationError(
                field_name="tool_call_count",
                message="must be an integer",
            )
        # 校验非负整数
        if tool_call_count < 0:
            raise RunLifecycleValidationError(
                field_name="tool_call_count",
                message="must be nonnegative",
            )
        # 校验终止原因
        normalized_reason = termination_reason.strip()
        if not _STABLE_REASON_PATTERN.fullmatch(normalized_reason):
            raise RunLifecycleValidationError(
                field_name="termination_reason",
                message="must be an uppercase stable code of at most 64 characters",
            )
        usage = token_usage or RunTokenUsage()
        # 取得结束时间
        finished_at = self._timestamp()
        current = await self._repository.get(normalized_run_id)
        duration_ms = 0
        if current is not None and current.status is AgentRunStatus.RUNNING:
            if current.started_at is None:
                raise RunLifecycleValidationError(
                    field_name="started_at",
                    message="running run must contain a start timestamp",
                )
            # 计算执行时间
            duration_ms = int((finished_at - current.started_at).total_seconds() * 1000)
            if duration_ms < 0:
                raise RunLifecycleValidationError(
                    field_name="timestamp",
                    message="finish timestamp must not precede start timestamp",
                )
        return {
            "finished_at": finished_at,
            "input_token_count": usage.input_tokens,
            "output_token_count": usage.output_tokens,
            "total_token_count": usage.total_tokens,
            "tool_call_count": tool_call_count,
            "duration_ms": duration_ms,
            "termination_reason": normalized_reason,
        }

    # 公共状态转换逻辑(三个状态操作)
    async def _transition(
        self,
        run_id: str,
        *,
        expected_status: AgentRunStatus,
        target_status: AgentRunStatus,
        changes: Mapping[str, Any],
    ) -> AgentRun:
        """执行 compare-and-set; 更新失败后区分不存在与状态冲突。"""

        normalized_run_id = self._require_identifier(run_id, "run_id", 128)
        transitioned = await self._repository.transition_status(
            normalized_run_id,
            expected_status=expected_status,
            target_status=target_status,
            changes=changes,
        )
        if transitioned is not None:
            return transitioned

        current = await self._repository.get(normalized_run_id)
        if current is None:
            raise RunNotFoundError(normalized_run_id)
        raise InvalidRunTransitionError(
            run_id=normalized_run_id,
            current_status=current.status,
            target_status=target_status,
        )

    def _timestamp(self) -> datetime:
        """拒绝无时区时间, 避免不同时区环境产生含糊执行时间。"""

        timestamp = self._now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise RunLifecycleValidationError(
                field_name="timestamp",
                message="must include timezone information",
            )
        return timestamp

    @staticmethod
    def _require_identifier(value: str, field_name: str, max_length: int) -> str:
        """拒绝空白或超长技术标识, 并返回去除首尾空白后的值。"""

        normalized = value.strip()
        if not normalized:
            raise RunLifecycleValidationError(
                field_name=field_name,
                message="must not be blank",
            )
        if len(normalized) > max_length:
            raise RunLifecycleValidationError(
                field_name=field_name,
                message=f"must contain at most {max_length} characters",
            )
        return normalized

    # 校验JSON结果是否有效
    @staticmethod
    def _json_snapshot(
        value: dict[str, Any],
        *,
        field_name: str = "final_result",
    ) -> dict[str, Any]:
        """验证并复制标准 JSON 结果, 避免延迟到 commit 才发现不可序列化数据。"""

        try:  # 验证JSON数据是不是标准JSON。创建结果副本, 避免修改原始数据。
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            return cast(dict[str, Any], json.loads(serialized))
        except (TypeError, ValueError) as exception:
            raise RunLifecycleValidationError(
                field_name=field_name,
                message="must contain only standard JSON values",
            ) from exception
