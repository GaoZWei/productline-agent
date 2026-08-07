"""Tool 调用上下文和标准结果 Schema。"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity

ContextIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
PermissionName = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_.:-]*$"),
]


class ToolContext(BaseModel):
    """保存一次 Tool 调用所需的身份、权限和链路标识。"""
    # Pydantic 配置
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    identity: BusinessIdentity
    permissions: frozenset[PermissionName] = Field(default_factory=frozenset) # Java 的不可变 Set<String> 权限名称只能使用大写稳定标识
    trace_id: ContextIdentifier # 关联一次分布式请求
    run_id: ContextIdentifier # 关联一次 Tool 调用

# 不是 Python 异常，而是可以放入 ToolResult 的结构化错误数据
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

# 约束对 Agent 很重要
class ToolResult[DataT](BaseModel):
    """使用互斥的 data 和 error 表示一次 Tool 调用结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    success: bool
    data: DataT | None = None  # 可选的任意类型，或 None  = None表示默认值
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """保证成功结果有 data 且失败结果只有 error。"""

        if self.success and (self.data is None or self.error is not None): # success=true→ 必须有data →不能有error
            raise ValueError("successful tool result must contain data and no error")
        if not self.success and (self.data is not None or self.error is None): # success=false→ 不能有data →必须有error
            raise ValueError("failed tool result must contain error and no data")
        return self
