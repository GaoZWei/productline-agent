"""人工确认执行HTTP入口的严格请求、成功和错误契约。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import ApprovalStatus
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
