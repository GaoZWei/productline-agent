"""Agent Run 的最小、可验证生命周期服务。"""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from app.models import AgentRun, AgentRunStatus
from app.repositories import AgentRunRepository


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
    """执行 PENDING 到 RUNNING 再到成功或失败的原子状态流转。"""

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
        request_message_id: str | None = None,
    ) -> AgentRun:
        """创建初始 PENDING Run, 父 Session 和可选 Message 必须已经存在。"""
        # 第一步：校验ID是否有效
        normalized_run_id = self._require_identifier(run_id, "run_id", 128)
        normalized_session_id = self._require_identifier(session_id, "session_id", 128)
        normalized_message_id = (
            self._require_identifier(request_message_id, "request_message_id", 128)
            if request_message_id is not None
            else None
        )
        # 第二步：构造ORM对象 
        return await self._repository.create(
            AgentRun(
                run_id=normalized_run_id,
                session_id=normalized_session_id,
                request_message_id=normalized_message_id,
                status=AgentRunStatus.PENDING,  # 初始状态为PENDING
            )
        )
    # 标记为RUNNING
    async def mark_running(self, run_id: str) -> AgentRun:
        """仅允许 PENDING Run 开始执行并记录 started_at。"""
        # 只有当前状态是PENDING，才能进入RUNNING
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
            },
        )
    # 标记为SUCCEEDED
    async def mark_succeeded(self, run_id: str, *, final_result: dict[str, Any]) -> AgentRun:
        """仅允许 RUNNING Run 成功结束并保存本次执行结果快照。"""

        return await self._transition(
            run_id,
            expected_status=AgentRunStatus.RUNNING,
            target_status=AgentRunStatus.SUCCEEDED,
            changes={
                "finished_at": self._timestamp(),
                "final_result": self._json_snapshot(final_result),
                "error_code": None,
                "error_step": None,
            },
        )
    # 标记为FAILED
    async def mark_failed(
        self,
        run_id: str,
        *,
        error_code: str,
        error_step: str,
    ) -> AgentRun:
        """仅允许 RUNNING Run 失败结束并保存机器错误码和失败步骤。"""

        normalized_error_code = self._require_identifier(error_code, "error_code", 64)
        normalized_error_step = self._require_identifier(error_step, "error_step", 128)
        return await self._transition(
            run_id,
            expected_status=AgentRunStatus.RUNNING,
            target_status=AgentRunStatus.FAILED,
            changes={
                "finished_at": self._timestamp(),
                "final_result": None,
                "error_code": normalized_error_code,
                "error_step": normalized_error_step,
            },
        )
    # 公共状态转换逻辑（三个状态操作）
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
    def _json_snapshot(value: dict[str, Any]) -> dict[str, Any]:
        """验证并复制标准 JSON 结果, 避免延迟到 commit 才发现不可序列化数据。"""

        try:  # 验证JSON数据是不是标准JSON。创建结果副本，避免修改原始数据。
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            return cast(dict[str, Any], json.loads(serialized))
        except (TypeError, ValueError) as exception:
            raise RunLifecycleValidationError(
                field_name="final_result",
                message="must contain only standard JSON values",
            ) from exception
