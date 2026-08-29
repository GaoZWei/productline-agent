"""Agent 会话与执行过程的 SQLAlchemy 持久化模型。"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.approval import ApprovalRecord


# Message角色
class AgentMessageRole(StrEnum):
    """会话消息发送方; 当前只持久化用户和助手消息。"""

    USER = "USER"
    ASSISTANT = "ASSISTANT"

# Run状态
class AgentRunStatus(StrEnum):
    """一次 Agent 请求在生命周期中的稳定状态集合。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"  # 等待用户确认写操作
    CANCELLED = "CANCELLED"  # 被取消

# Step类型
class AgentStepType(StrEnum):
    """Run内部从上下文到写回的稳定可观测步骤类型。"""

    CONTEXT = "CONTEXT"  # 读取、解析、校验执行上下文
    ROUTER = "ROUTER"  # 判断用户意图和后续路径
    WORKFLOW = "WORKFLOW"  # 确定性流程节点或规则计算
    AGENT = "AGENT"  # 动态Agent选择下一个动作
    TOOL = "TOOL"  # 调用外部业务Tool
    RAG = "RAG"  # 规范检索、融合、重排
    LLM = "LLM"  # 单独的一次模型调用
    APPROVAL = "APPROVAL"  # 人工确认相关动作
    WRITEBACK = "WRITEBACK"  # 确认后的真实业务写入

# Step状态
class AgentStepStatus(StrEnum):
    """单个执行步骤的最小生命周期状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


def _enum_column(enum_type: type[StrEnum], constraint_name: str, length: int) -> Enum:
    """使用带 Check Constraint 的字符串枚举, 避免数据库私有枚举难以演进。"""

    return Enum(
        enum_type,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=length,
    )


def _default_session_expiration() -> datetime:
    """为非HTTP内部调用提供30分钟默认TTL; 生产服务会显式覆盖。"""

    return datetime.now(UTC) + timedelta(minutes=30)

# 对应agent_sessions表 保存会话信息
class AgentSession(Base):
    """一次连续对话的归属信息, 不保存 Java 业务事实。"""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint("char_length(session_id) > 0", name="ck_agent_sessions_id_not_blank"),
        CheckConstraint("char_length(user_id) > 0", name="ck_agent_sessions_user_not_blank"),
        Index("ix_agent_sessions_user_created", "user_id", "created_at"),
        Index("ix_agent_sessions_expires_at", "expires_at"),
    )

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 时间字段
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # 关联消息
    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_default_session_expiration, nullable=False
    )

# 对应agent_messages表 保存一条会话消息信息
class AgentMessage(Base):
    """会话中的一条用户或助手消息, 序号保证同会话内顺序稳定。"""

    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("char_length(message_id) > 0", name="ck_agent_messages_id_not_blank"),
        CheckConstraint("sequence_number > 0", name="ck_agent_messages_sequence_positive"),
        CheckConstraint("char_length(content) > 0", name="ck_agent_messages_content_not_blank"),
        # 序号唯一性约束
        UniqueConstraint(
            "session_id", "sequence_number", name="uq_agent_messages_session_sequence"
        ),
    )

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    # 序号
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 角色
    role: Mapped[AgentMessageRole] = mapped_column(
        _enum_column(AgentMessageRole, "ck_agent_messages_role", 16), nullable=False
    )
    # 内容
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[AgentSession] = relationship(back_populates="messages")
    # 表示一条用户消息可能关联若干Run
    requested_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="request_message",
        foreign_keys="AgentRun.request_message_id",
    )

# 对应agent_runs表 保存Agent处理一次用户请求的完整执行记录
class AgentRun(Base):
    """一次用户请求对应的 Agent 执行记录与最终结果。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("char_length(run_id) > 0", name="ck_agent_runs_id_not_blank"),
        CheckConstraint(
            "input_token_count >= 0 AND output_token_count >= 0 "
            "AND total_token_count = input_token_count + output_token_count",
            name="ck_agent_runs_token_counts",
        ),
        CheckConstraint(
            "tool_call_count >= 0",
            name="ck_agent_runs_tool_call_count_nonnegative",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_runs_duration_nonnegative",
        ),
        CheckConstraint(
            "termination_reason IS NULL OR char_length(termination_reason) > 0",
            name="ck_agent_runs_termination_not_blank",
        ),
        Index("ix_agent_runs_session_created", "session_id", "created_at"),
    )

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 删除Session时, 其Run也删除
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    # 删除用户消息时, Run不会删除, 只把request_message_id设为NULL。 为了保留历史运行证据
    request_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_messages.message_id", ondelete="SET NULL"), nullable=True
    )
    # 状态
    status: Mapped[AgentRunStatus] = mapped_column(
        _enum_column(AgentRunStatus, "ck_agent_runs_status", 32),
        default=AgentRunStatus.PENDING,
        server_default=AgentRunStatus.PENDING.value,
        nullable=False,
    )
    # 创建时冻结跨组件版本; 迁移前历史Run只能明确标记为不可恢复, 不能补造版本。
    version_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,  # 所有新 Run 必须有关联版本信息
    )
    # 页面和路由只保存经过严格Schema校验的安全快照, 不保存用户消息或Java业务响应.
    page_context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 保存本次路由结果(当前固定订单诊断未经过统一Router, 因此路由结果为null)
    router_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Token统计(当前固定诊断没有装配文案模型, 因此三个值都是0)
    input_token_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    output_token_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    total_token_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    # 表示本次Run中真正获准执行的逻辑Tool调用次数
    tool_call_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    # 表示整个Run的耗时
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 为什么这次Run结束
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 保存的是“本次Run当时得到的诊断结果”, 订单最新状态仍要重新调用Java Tool获取
    final_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 错误字段
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 时间字段(创建时间、更新时间、开始时间、结束时间)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[AgentSession] = relationship(back_populates="runs")
    request_message: Mapped[AgentMessage | None] = relationship(
        back_populates="requested_runs",
        foreign_keys=[request_message_id],
    )
    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    approvals: Mapped[list["ApprovalRecord"]] = relationship(
        back_populates="run",
        passive_deletes=True,
    )

# 对应agent_steps表 保存Agent处理一次Run内部的具体执行步骤
class AgentStep(Base):
    """Run 内一个可定位的执行步骤, 只保存受控摘要而非完整敏感载荷。"""

    __tablename__ = "agent_steps"
    __table_args__ = (
        CheckConstraint("char_length(step_id) > 0", name="ck_agent_steps_id_not_blank"),
        CheckConstraint("sequence_number > 0", name="ck_agent_steps_sequence_positive"),
        CheckConstraint("char_length(step_name) > 0", name="ck_agent_steps_name_not_blank"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_steps_duration_nonnegative"
        ),
        # 保证同一个Run内步骤顺序唯一
        UniqueConstraint("run_id", "sequence_number", name="uq_agent_steps_run_sequence"),
    )
    # 唯一标识
    step_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 属于哪一次Run
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    # 在Run里的执行顺序
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 表示步骤在Agent整体执行链路中的职责分类
    step_type: Mapped[AgentStepType] = mapped_column(
        _enum_column(AgentStepType, "ck_agent_steps_type", 16), nullable=False
    )
    # 表示具体动作
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 当前状态  PENDING/STARTED/FINISHED/FAILED
    status: Mapped[AgentStepStatus] = mapped_column(
        _enum_column(AgentStepStatus, "ck_agent_steps_status", 16),
        default=AgentStepStatus.PENDING,
        server_default=AgentStepStatus.PENDING.value,
        nullable=False,
    )
    # 摘要 只保存可排障的受控摘要
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 执行耗时 步骤未完成时可以是NULL, 完成后必须是非负数
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="steps")
