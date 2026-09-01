"""Run历史列表、详情和Step时间线的安全只读契约。"""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import (
    AgentRunStatus,
    AgentStepStatus,
    AgentStepType,
    ApprovalStatus,
    OperationType,
)
from app.schemas.approval import ReviewDraft
from app.schemas.operation_log import OperationFieldChange
from app.schemas.session import RunIdentifier, SessionIdentifier
from app.schemas.tools import OrderIdentifier, TaskIdentifier
from app.schemas.workflow import DiagnosisResult
from app.schemas.write_tools import ApprovalIdentifier

RunHistoryCount = Annotated[int, Field(ge=0, le=2_147_483_647)]
RunHistoryPage = Annotated[int, Field(ge=1, le=1_000_000)]
RunHistoryPageSize = Annotated[int, Field(ge=1, le=100)]
RunHistoryCode = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
StepIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]+$"),
]


class RunHistorySchema(BaseModel):
    """列表契约严格、只读且禁止未声明字段。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class RunSummary(RunHistorySchema):
    """一个Run的列表级摘要, 不暴露消息、完整结果或内部配置快照。"""

    run_id: RunIdentifier
    session_id: SessionIdentifier
    status: AgentRunStatus
    order_id: OrderIdentifier | None = None
    task_id: TaskIdentifier | None = None
    tool_call_count: RunHistoryCount
    total_token_count: RunHistoryCount
    duration_ms: RunHistoryCount | None = None
    termination_reason: RunHistoryCode | None = None
    error_code: RunHistoryCode | None = None
    error_step: RunHistoryCode | None = None
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class RunListResponse(RunHistorySchema):
    """当前用户的Run分页结果。"""

    items: tuple[RunSummary, ...]
    page: RunHistoryPage
    page_size: RunHistoryPageSize
    total: RunHistoryCount

# Approval确认历史结构模型
class ApprovalHistory(RunHistorySchema):
    """Run产生的人工确认记录, 保留原稿、最终稿和受控修改差异。"""

    approval_id: ApprovalIdentifier
    status: ApprovalStatus
    operation_type: OperationType
    target_id: TaskIdentifier
    target_version: RunHistoryCount
    original_draft: ReviewDraft  # 模型最初生成了什么草稿
    effective_draft: ReviewDraft  # 最终用户修改后的草稿或原始草稿
    user_modification_diff: tuple[OperationFieldChange, ...]  # 用户具体改了哪些字段
    confirmed_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class RunDetailResponse(RunHistorySchema):
    """单个Run的受控执行详情, 不返回消息和内部上下文快照。"""

    run: RunSummary
    input_token_count: RunHistoryCount
    output_token_count: RunHistoryCount
    result: DiagnosisResult | None = None
    approvals: tuple[ApprovalHistory, ...]


class StepSummary(RunHistorySchema):
    """Step时间线节点, 只公开持久化时已收敛的输入输出摘要。"""

    step_id: StepIdentifier
    sequence_number: Annotated[int, Field(ge=1, le=2_147_483_647)]
    step_type: AgentStepType
    step_name: RunHistoryCode
    status: AgentStepStatus
    input_summary: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    output_summary: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    error_code: RunHistoryCode | None = None
    duration_ms: RunHistoryCount | None = None
    model_name: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    input_token_count: RunHistoryCount | None = None
    output_token_count: RunHistoryCount | None = None
    total_token_count: RunHistoryCount | None = None
    retry_count: RunHistoryCount | None = None
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class StepListResponse(RunHistorySchema):
    """一个已授权Run内按执行序号排序的完整Step时间线。"""

    run_id: RunIdentifier
    items: tuple[StepSummary, ...]


class RunHistoryErrorResponse(RunHistorySchema):
    """Run历史查询使用的稳定安全错误。"""

    trace_id: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ]
    code: RunHistoryCode
    message: Annotated[str, Field(min_length=1, max_length=2048)]
