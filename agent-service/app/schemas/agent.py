"""Agent 对外诊断 API 的严格请求、成功响应和错误响应契约。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.context import PageContext
from app.schemas.session import RunIdentifier, SessionIdentifier
from app.schemas.tools import OrderIdentifier
from app.schemas.workflow import DiagnosisResult, StableCode, TraceIdentifier

UserMessage = Annotated[str, Field(min_length=1, max_length=2000)]


class AgentApiSchema(BaseModel):
    """为 Agent HTTP 契约提供严格且禁止额外字段的共同配置。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 订单诊断请求Schema
class OrderDiagnosisRequest(AgentApiSchema):
    """请求对一个明确订单执行固定诊断 Workflow。"""

    session_id: SessionIdentifier | None = None
    order_id: OrderIdentifier | None = None
    user_message: UserMessage
    page_context: PageContext | None = None

    @model_validator(mode="after")
    def require_initial_context(self) -> "OrderDiagnosisRequest":
        """新会话必须给出订单和页面; 已有会话允许继承。"""

        if self.session_id is None and (
            self.order_id is None or self.page_context is None
        ):
            raise ValueError("new diagnosis requires order_id and page_context")
        return self

# 订单诊断成功响应Schema
class OrderDiagnosisResponse(AgentApiSchema):
    """返回本次 Run 标识、Trace 标识和完整诊断结果。"""

    run_id: RunIdentifier
    session_id: SessionIdentifier
    trace_id: TraceIdentifier
    diagnosis: DiagnosisResult

# 订单诊断错误响应Schema
class OrderDiagnosisErrorResponse(AgentApiSchema):
    """返回安全机器错误及可定位的 Run 和失败步骤。"""

    run_id: RunIdentifier | None
    trace_id: TraceIdentifier
    code: StableCode
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    retryable: bool
    error_step: Annotated[str, Field(min_length=1, max_length=128)] | None
