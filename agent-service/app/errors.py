"""供后续 Tool 层使用的稳定错误契约。"""

from enum import StrEnum


# 定义了9类稳定机器错误码并使用枚举防止错误码拼写错误。
class ToolErrorCode(StrEnum):
    """供 Tool 和 Workflow 分支判断的机器可读错误分类。"""

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
    """安全的结构化异常。调用方无需解析文案即可选择分支。"""

    def __init__(
        self,
        *,
        code: ToolErrorCode,  # 给程序判断的稳定错误码
        message: str,  # 给用户或开发人员阅读的错误信息
        retryable: bool,  # 表示故障在技术上是否可能恢复
        trace_id: str | None = None,  # 用于关联Python请求、Java请求和日志
        status_code: int | None = None,  # 保留原始 HTTP 语义以便调试和记录日志
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.trace_id = trace_id
        self.status_code = status_code
        super().__init__(f"{code.value}: {message}")
