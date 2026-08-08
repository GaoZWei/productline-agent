"""Tool 调用上下文和标准结果 Schema。"""

from __future__ import annotations

from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity
from app.tools.deduplication import RunToolCallLedger

ContextIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
PermissionName = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_.:-]*$"),
]


class ToolContext(BaseModel):
    """保存同一次 Run 共享的身份、权限、链路标识和调用记录。"""

    # Pydantic 配置
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    identity: BusinessIdentity
    # 对应 Java 的不可变 Set<String>, 权限名称只能使用大写稳定标识。
    permissions: frozenset[PermissionName] = Field(default_factory=frozenset)
    trace_id: ContextIdentifier  # 关联一次分布式请求
    run_id: ContextIdentifier  # 关联一次 Agent Run
    _tool_call_ledger: RunToolCallLedger = PrivateAttr()  # 运行时内部状态, 不是 API 数据

    def model_post_init(self, __context: Any) -> None:
        """为本次 Run 创建不参与序列化的进程内调用账本。"""

        object.__setattr__(self, "_tool_call_ledger", RunToolCallLedger(run_id=self.run_id))

    @property
    def tool_call_ledger(self) -> RunToolCallLedger:
        """返回同一 ToolContext 复用的 Run 级调用账本。"""

        return self._tool_call_ledger


# 不是 Python 异常, 而是可以放入 ToolResult 的结构化错误数据。
class ToolError(BaseModel):
    """供 Workflow 稳定分支且可安全展示的 Tool 错误。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: ToolErrorCode
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    retryable: bool
    trace_id: ContextIdentifier | None = None
    status_code: Annotated[int, Field(ge=100, le=599)] | None = None

    @classmethod
    def from_exception(
        cls,
        exception: ToolException,
        *,
        fallback_trace_id: str,
    ) -> ToolError:
        """将标准异常转换为结果错误并补全缺失的 Trace ID。"""

        return cls(
            code=exception.code,
            message=exception.message,
            retryable=exception.retryable,
            trace_id=exception.trace_id or fallback_trace_id,
            status_code=exception.status_code,
        )


# 该约束对 Agent 很重要, 用于定义 Tool 调用结果的结构。
class ToolResult[DataT](BaseModel):
    """使用互斥的 data 和 error 表示一次 Tool 调用结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    success: bool
    data: DataT | None = None  # 可选的任意类型或 None; None 表示默认值。
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """保证成功结果有 data 且失败结果只有 error。"""

        # success=true 时必须有 data 且不能有 error。
        if self.success and (self.data is None or self.error is not None):
            raise ValueError("successful tool result must contain data and no error")
        # success=false 时不能有 data 且必须有 error。
        if not self.success and (self.data is not None or self.error is None):
            raise ValueError("failed tool result must contain error and no data")
        return self
