"""Stable error contract exposed by the future Tool layer."""

from enum import StrEnum

# 定义了9类稳定机器错误码，使用枚举的原因是防止错误码拼写错误
class ToolErrorCode(StrEnum):
    """Machine-readable failure categories used by Tool and Workflow branches."""

    PARAM_VALIDATION_ERROR = "PARAM_VALIDATION_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    BUSINESS_CONFLICT = "BUSINESS_CONFLICT"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RESPONSE_VALIDATION_ERROR = "RESPONSE_VALIDATION_ERROR"
    DUPLICATE_CALL = "DUPLICATE_CALL"
    UNKNOWN_TOOL_ERROR = "UNKNOWN_TOOL_ERROR"

# 类似Java自定义异常
class ToolException(Exception):
    """A safe, structured failure that callers may branch on without parsing text."""

    def __init__(
        self,
        *,
        code: ToolErrorCode,  # 给程序判断的稳定错误码
        message: str,  # 给用户或开发人员阅读的错误信息
        retryable: bool,  # 表示故障在技术上是否可能恢复
        trace_id: str | None = None,  # 用于关联Python请求、Java请求和日志
        status_code: int | None = None,  # 保留原始HTTP语义，方便调试和日志记录
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.trace_id = trace_id
        self.status_code = status_code
        super().__init__(f"{code.value}: {message}")
