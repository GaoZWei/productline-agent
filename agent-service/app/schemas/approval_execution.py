"""人工确认执行HTTP入口的严格请求、成功和错误契约。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import AgentRunStatus, ApprovalStatus
from app.schemas.agent_messages import ApprovalAgentResult
from app.schemas.approval import ReviewDraft
from app.schemas.workflow import StableCode, TraceIdentifier
from app.schemas.write_tools import (
    ApprovalIdentifier,
    CreateReworkTaskOutput,
    WriteReviewResultOutput,
)


class ApprovalExecutionApiSchema(BaseModel):
    """确认执行API统一拒绝额外字段和隐式类型转换。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class ApprovalConfirmationRequest(ApprovalExecutionApiSchema):
    """提交用户在确认卡片中最终看到和授权的完整草稿。"""

    draft: ReviewDraft


class ApprovalConfirmationResponse(ApprovalExecutionApiSchema):
    """返回Approval成功终态和Java写入结果。"""

    approval_id: ApprovalIdentifier
    status: ApprovalStatus
    trace_id: TraceIdentifier
    result: WriteReviewResultOutput | CreateReworkTaskOutput


class ApprovalConfirmationErrorResponse(ApprovalExecutionApiSchema):
    """返回可安全展示的确认失败和当时Approval状态。"""

    approval_id: ApprovalIdentifier | None
    status: ApprovalStatus | None
    trace_id: TraceIdentifier
    code: StableCode
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    retryable: bool


class ApprovalCancellationResponse(ApprovalExecutionApiSchema):
    """返回取消后的Approval和所属Run终态。"""

    approval_id: ApprovalIdentifier
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    status: ApprovalStatus
    run_status: AgentRunStatus
    trace_id: TraceIdentifier


class ReworkApprovalCreationResponse(ApprovalExecutionApiSchema):
    """返回显式创建的独立返工Run和待确认草稿。"""

    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    trace_id: TraceIdentifier
    result: ApprovalAgentResult
