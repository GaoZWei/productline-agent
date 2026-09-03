"""统一Agent消息入口的请求、结果Envelope和安全错误契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import ApprovalStatus, OperationType
from app.routing import Intent
from app.schemas.approval import ReviewDraft
from app.schemas.context import PageContext
from app.schemas.knowledge_index import KnowledgeIndexCapabilitiesResponse
from app.schemas.model_capabilities import ModelCapabilitiesResponse
from app.schemas.routing import ClarificationRequest, EntitySelection
from app.schemas.session import RunIdentifier, SessionIdentifier
from app.schemas.specification import SpecificationQaResult
from app.schemas.tools import OrderIdentifier, TaskIdentifier
from app.schemas.workflow import DiagnosisResult, StableCode, TraceIdentifier
from app.schemas.write_tools import ApprovalIdentifier


class AgentMessageSchema(BaseModel):
    """统一消息契约共同使用严格、不可变且去除首尾空白的配置。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 澄清选择模型
class ClarificationChoice(AgentMessageSchema):
    """引用上一轮澄清Run, 并提交实体选择或意图确认中的一种。"""

    source_run_id: RunIdentifier # 必须提供 source_run_id，不能是None
    selection: EntitySelection | None = None
    confirm_intent: bool = False

    @model_validator(mode="after")
    def require_exactly_one_choice(self) -> Self:
        """实体选择与意图确认互斥, 防止一次请求绕过多个澄清门禁。"""
        # selection 和 confirm_intent 必须二选一提供
        if self.confirm_intent == (self.selection is not None):
            raise ValueError("clarification choice must contain exactly one user decision")
        return self

# 严格请求模型
class AgentMessageRequest(AgentMessageSchema):
    """一轮统一Agent请求, 可创建会话或续接本人已有会话。"""

    message: Annotated[str, Field(min_length=1, max_length=2000)] # 当前用户消息
    session_id: SessionIdentifier | None = None # 没有则创建新 Session
    page_context: PageContext | None = None # 当前页面提供的提示
    clarification: ClarificationChoice | None = None # 用户对上一轮澄清的回答

    @model_validator(mode="after")
    def require_session_for_clarification(self) -> Self:
        """澄清只能在明确会话内续接, 来源Run还会由服务端校验归属。"""

        if self.clarification is not None and self.session_id is None:
            raise ValueError("clarification continuation requires session_id")
        return self

# 结果类型模型
class AgentResultKind(StrEnum):
    """统一入口和历史记录能够稳定区分的五类结果。"""

    ORDER_STATUS = "ORDER_STATUS"
    DIAGNOSIS = "DIAGNOSIS"
    SPECIFICATION_ANSWER = "SPECIFICATION_ANSWER"
    CLARIFICATION = "CLARIFICATION"
    APPROVAL = "APPROVAL"


class OrderStatusSubject(StrEnum):
    """状态结果描述订单还是任务。"""

    ORDER = "ORDER"
    TASK = "TASK"


class AgentResultEnvelope(AgentMessageSchema):
    """可持久化结果的共同基类, kind是唯一分派判别字段。"""


class OrderStatusResult(AgentResultEnvelope):
    """确定性状态Skill未来返回的最小业务事实投影。"""

    kind: Literal[AgentResultKind.ORDER_STATUS] = AgentResultKind.ORDER_STATUS
    subject: OrderStatusSubject = Field(strict=False)
    order_id: OrderIdentifier
    task_id: TaskIdentifier | None = None
    status: Annotated[str, Field(min_length=1, max_length=128)]
    summary: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def require_subject_identifier(self) -> Self:
        """订单结果不能伪带任务, 任务结果必须明确任务标识。"""

        if self.subject is OrderStatusSubject.ORDER and self.task_id is not None:
            raise ValueError("order status result must not contain task_id")
        if self.subject is OrderStatusSubject.TASK and self.task_id is None:
            raise ValueError("task status result requires task_id")
        return self


class DiagnosisAgentResult(AgentResultEnvelope):
    """动态或兼容固定诊断的强类型结果。"""

    kind: Literal[AgentResultKind.DIAGNOSIS] = AgentResultKind.DIAGNOSIS
    diagnosis: DiagnosisResult


class SpecificationAnswerAgentResult(AgentResultEnvelope):
    """携带版本和Chunk引用的规范问答结果。"""

    kind: Literal[AgentResultKind.SPECIFICATION_ANSWER] = AgentResultKind.SPECIFICATION_ANSWER
    specification_answer: SpecificationQaResult


class ClarificationAgentResult(AgentResultEnvelope):
    """路由门禁未通过时返回的受控问题及候选。"""

    kind: Literal[AgentResultKind.CLARIFICATION] = AgentResultKind.CLARIFICATION
    intent: Intent = Field(strict=False)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    clarification: ClarificationRequest


class ApprovalAgentResult(AgentResultEnvelope):
    """Review Skill未来返回的可审查草稿, 不代表已经确认或写入。"""

    kind: Literal[AgentResultKind.APPROVAL] = AgentResultKind.APPROVAL
    approval_id: ApprovalIdentifier
    status: ApprovalStatus = Field(strict=False)
    operation_type: OperationType = Field(strict=False)
    draft: ReviewDraft


type AgentMessageResult = Annotated[
    OrderStatusResult
    | DiagnosisAgentResult
    | SpecificationAnswerAgentResult
    | ClarificationAgentResult
    | ApprovalAgentResult,
    Field(discriminator="kind"),
]


class AgentMessageResponse(AgentMessageSchema):
    """统一返回Run、Session、Trace及五类之一的强类型结果。"""

    run_id: RunIdentifier
    session_id: SessionIdentifier
    trace_id: TraceIdentifier
    result: AgentMessageResult


class AgentMessageErrorResponse(AgentMessageSchema):
    """统一入口不泄露模型正文、密钥或内部异常的稳定错误。"""

    run_id: RunIdentifier | None
    trace_id: TraceIdentifier
    code: StableCode
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    retryable: bool
    error_step: Annotated[str, Field(min_length=1, max_length=128)] | None


class AgentCapabilitiesResponse(AgentMessageSchema):
    """统一入口运行前可读取的模型、知识索引和结果类型能力。"""

    message_api_enabled: Literal[True] = True
    result_kinds: tuple[AgentResultKind, ...]
    model: ModelCapabilitiesResponse
    knowledge_index: KnowledgeIndexCapabilitiesResponse

    @model_validator(mode="after")
    def require_all_result_kinds(self) -> Self:
        """能力响应必须按枚举顺序完整声明五类结果且不得重复。"""

        if self.result_kinds != tuple(AgentResultKind):
            raise ValueError("agent capabilities must expose every result kind in order")
        return self


__all__ = [
    "AgentCapabilitiesResponse",
    "AgentMessageErrorResponse",
    "AgentMessageRequest",
    "AgentMessageResponse",
    "AgentMessageResult",
    "AgentResultKind",
    "ApprovalAgentResult",
    "ClarificationAgentResult",
    "ClarificationChoice",
    "DiagnosisAgentResult",
    "OrderStatusResult",
    "OrderStatusSubject",
    "SpecificationAnswerAgentResult",
]
