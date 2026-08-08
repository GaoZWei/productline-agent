"""只读 Tool 的有限重试判定和指数退避策略。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.errors import ToolErrorCode, ToolException

_RETRYABLE_ERROR_CODES = frozenset(
    {
        ToolErrorCode.TOOL_TIMEOUT,
        ToolErrorCode.UPSTREAM_UNAVAILABLE,
    }
)
_MAX_RETRIES_LIMIT = 10


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """限制重试错误、次数和指数退避但不决定 Tool 是否只读。

    frozen 阻止运行时修改策略。slots 限制对象只能保存声明过的字段。
    """

    max_retries: int
    initial_backoff_seconds: float = 0.1
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        """拒绝可能造成无界调用或无效等待的策略配置。"""
        # 重试次数必须在 0 到 10 之间。
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or not 0 <= self.max_retries <= _MAX_RETRIES_LIMIT
        ):
            raise ValueError(f"max_retries must be an integer between 0 and {_MAX_RETRIES_LIMIT}")
        self._require_positive_finite(
            self.initial_backoff_seconds,
            "initial_backoff_seconds",
        )
        self._require_positive_finite(self.backoff_multiplier, "backoff_multiplier")
        self._require_positive_finite(self.max_backoff_seconds, "max_backoff_seconds")
        # 指数退避倍数必须大于等于 1.0
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be greater than or equal to 1")
        # 上限不能小于初始值
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError(
                "max_backoff_seconds must be greater than or equal to initial_backoff_seconds"
            )

    def should_retry(
        self,
        exception: ToolException,
        *,
        retries_completed: int,
    ) -> bool:
        """仅在次数未耗尽且错误明确可恢复时允许再次调用。"""

        if (
            isinstance(retries_completed, bool)
            or not isinstance(retries_completed, int)
            or retries_completed < 0
        ):
            raise ValueError("retries_completed must be a non-negative integer")
        return (
            retries_completed < self.max_retries  #  还有剩余次数
            and exception.retryable  #  retryable 表示故障在技术上是否可能恢复
            and exception.code in _RETRYABLE_ERROR_CODES  #  错误码必须进入白名单   
        )
    
    # 指数退避时间
    def backoff_seconds(self, retry_number: int) -> float:
        """返回从一开始编号且受上限保护的指数退避时间。"""

        if (
            isinstance(retry_number, bool)
            or not isinstance(retry_number, int)
            or not 1 <= retry_number <= self.max_retries
        ):
            raise ValueError("retry_number must be between 1 and max_retries")

        delay = self.initial_backoff_seconds
        for _ in range(retry_number - 1):
            delay = min(delay * self.backoff_multiplier, self.max_backoff_seconds)
        return delay
    
    # 时间参数必须是有限正数
    @staticmethod
    def _require_positive_finite(value: float, name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{name} must be a positive finite number")
