"""Agent Step 的最小记录、摘要保护和生命周期服务。"""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.models import AgentRunStatus, AgentStep, AgentStepStatus, AgentStepType
from app.repositories import AgentRunRepository, AgentStepRepository

STEP_SUMMARY_MAX_LENGTH = 1000
_SUMMARY_REDACTION = "[REDACTED]"
_CREDENTIAL_PATTERNS = (
    # 保留Authorization头
    re.compile(
        r"(?i)\b(authorization\s*[:=]\s*(?:bearer|basic)\s+)([^\s,;]+)"
    ),
    # 保留其他敏感字段
    re.compile(
        r"(?i)\b((?:[a-z0-9]{1,32}[_-](?:token|secret)|token|secret|"
        r"api[_-]?key|password)\s*[:=]\s*)([^\s,;]+)"
    ),
)


class StepLifecycleError(Exception):
    """Step 生命周期内部错误基类, 暂不绑定 HTTP 或 Tool 错误协议。"""


class StepNotFoundError(StepLifecycleError):
    """目标 Step 不存在。"""

    def __init__(self, step_id: str) -> None:
        self.step_id = step_id
        super().__init__(f"step '{step_id}' was not found")


class InvalidStepTransitionError(StepLifecycleError):
    """Step 当前状态不允许进入目标状态。"""

    def __init__(
        self,
        *,
        step_id: str,
        current_status: AgentStepStatus,
        target_status: AgentStepStatus,
    ) -> None:
        self.step_id = step_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"step '{step_id}' cannot transition from "
            f"{current_status.value} to {target_status.value}"
        )


class StepRunUnavailableError(StepLifecycleError):
    """父 Run 不存在或当前不是 RUNNING, 不能关联新 Step。"""

    def __init__(self, *, run_id: str, current_status: AgentRunStatus | None) -> None:
        self.run_id = run_id
        self.current_status = current_status
        status = current_status.value if current_status is not None else "NOT_FOUND"
        super().__init__(f"run '{run_id}' is unavailable for a new step: {status}")


class StepLifecycleValidationError(StepLifecycleError):
    """Step 生命周期调用参数不满足最小持久化约束。"""

    def __init__(self, *, field_name: str, message: str) -> None:
        self.field_name = field_name
        self.message = message
        super().__init__(f"{field_name}: {message}")


def _utc_now() -> datetime:
    """返回带时区的 UTC 时间, 便于测试替换确定性时钟。"""

    return datetime.now(UTC)

# 主类
class StepLifecycleService:
    """记录 RUNNING Step并原子完成为成功或失败。"""

    def __init__(
        self,
        step_repository: AgentStepRepository,
        run_repository: AgentRunRepository,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._step_repository = step_repository
        self._run_repository = run_repository
        self._now = now
    # 完整流程
    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None = None,
    ) -> AgentStep:
        """在 RUNNING Run下创建并自动关联一个已开始的 Step。"""
        # 第一步: 校验技术字段
        normalized_step_id = self._require_identifier(step_id, "step_id", 128)
        normalized_run_id = self._require_identifier(run_id, "run_id", 128)
        normalized_step_name = self._require_identifier(step_name, "step_name", 128)
        if isinstance(sequence_number, bool) or not isinstance(sequence_number, int):
            raise StepLifecycleValidationError(
                field_name="sequence_number",
                message="must be an integer",
            )
        if sequence_number <= 0:
            raise StepLifecycleValidationError(
                field_name="sequence_number",
                message="must be greater than zero",
            )
        if not isinstance(step_type, AgentStepType):
            raise StepLifecycleValidationError(
                field_name="step_type",
                message="must be an AgentStepType",
            )
        # 第二步: 处理输入摘要
        normalized_input_summary = self._normalize_summary(input_summary, "input_summary")
        # 第三步: 锁定并校验父Run
        run = await self._run_repository.get_for_update(normalized_run_id)
        if run is None or run.status is not AgentRunStatus.RUNNING:
            raise StepRunUnavailableError(
                run_id=normalized_run_id,
                current_status=run.status if run is not None else None,
            )
        # 第四步: 创建RUNNING Step
        return await self._step_repository.create(
            AgentStep(
                step_id=normalized_step_id,
                run_id=normalized_run_id,
                sequence_number=sequence_number,
                step_type=step_type,
                step_name=normalized_step_name,
                status=AgentStepStatus.RUNNING,
                input_summary=normalized_input_summary,
                started_at=self._timestamp(),
            )
        )
    # 标记成功
    async def mark_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None = None,
    ) -> AgentStep:
        """仅允许 RUNNING Step成功结束并保存受控输出摘要。"""

        return await self._finish(
            step_id,
            target_status=AgentStepStatus.SUCCEEDED,
            changes={
                "output_summary": self._normalize_summary(output_summary, "output_summary"),
                "error_code": None,
            },
        )
    # 标记失败
    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None = None,
    ) -> AgentStep:
        """仅允许 RUNNING Step失败结束并保存机器错误码和受控摘要。"""

        normalized_error_code = self._require_identifier(error_code, "error_code", 64)
        return await self._finish(
            step_id,
            target_status=AgentStepStatus.FAILED,
            changes={
                "output_summary": self._normalize_summary(output_summary, "output_summary"),
                "error_code": normalized_error_code,
            },
        )
    # 公共结束逻辑
    async def _finish(
        self,
        step_id: str,
        *,
        target_status: AgentStepStatus,
        changes: Mapping[str, Any],
    ) -> AgentStep:
        """计算耗时并以 compare-and-set原子抢占唯一终态。"""

        normalized_step_id = self._require_identifier(step_id, "step_id", 128)
        # 第一步: 读取数据库最新状态
        current = await self._step_repository.get_fresh(normalized_step_id)
        # 第二步: 校验状态是否为RUNNING
        if current is None:
            raise StepNotFoundError(normalized_step_id)
        if current.status is not AgentStepStatus.RUNNING:
            raise InvalidStepTransitionError(
                step_id=normalized_step_id,
                current_status=current.status,
                target_status=target_status,
            )
        if current.started_at is None:
            raise StepLifecycleValidationError(
                field_name="started_at",
                message="must exist before finishing a step",
            )
        # 第三步: 计算耗时
        finished_at = self._timestamp()
        if finished_at < current.started_at:
            raise StepLifecycleValidationError(
                field_name="finished_at",
                message="must not be earlier than started_at",
            )
        duration_ms = int((finished_at - current.started_at).total_seconds() * 1000)
        transitioned = await self._step_repository.transition_status(
            normalized_step_id,
            expected_status=AgentStepStatus.RUNNING,
            target_status=target_status,
            changes={
                **changes,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
            },
        )
        if transitioned is not None:
            return transitioned

        latest = await self._step_repository.get_fresh(normalized_step_id)
        if latest is None:
            raise StepNotFoundError(normalized_step_id)
        raise InvalidStepTransitionError(
            step_id=normalized_step_id,
            current_status=latest.status,
            target_status=target_status,
        )

    def _timestamp(self) -> datetime:
        """拒绝无时区时间, 避免不同部署环境产生含糊执行时间。"""

        timestamp = self._now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise StepLifecycleValidationError(
                field_name="timestamp",
                message="must include timezone information",
            )
        return timestamp

    @staticmethod
    def _require_identifier(value: str, field_name: str, max_length: int) -> str:
        """拒绝空白或超长技术标识, 并返回去除首尾空白后的值。"""

        normalized = value.strip()
        if not normalized:
            raise StepLifecycleValidationError(
                field_name=field_name,
                message="must not be blank",
            )
        if len(normalized) > max_length:
            raise StepLifecycleValidationError(
                field_name=field_name,
                message=f"must contain at most {max_length} characters",
            )
        return normalized
    # 摘要: 摘要处理（写入step前进行处理）
    @staticmethod
    def _normalize_summary(value: str | None, field_name: str) -> str | None:
        """压缩空白、遮盖常见凭据并截断摘要, 但不保存原始载荷。"""

        if value is None:
            return None
        if not isinstance(value, str):
            raise StepLifecycleValidationError(
                field_name=field_name,
                message="must be a string or null",
            )
        normalized = " ".join(value.split())
        if not normalized:
            return None
        for pattern in _CREDENTIAL_PATTERNS:
            normalized = pattern.sub(rf"\1{_SUMMARY_REDACTION}", normalized)
        if len(normalized) > STEP_SUMMARY_MAX_LENGTH:
            return normalized[: STEP_SUMMARY_MAX_LENGTH - 3] + "..."
        return normalized
