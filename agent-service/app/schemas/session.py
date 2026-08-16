"""M3.2 会话上下文、会话API与持久化传输契约。"""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing import Intent
from app.schemas.context import PageContext, PageType
from app.schemas.tools import OrderIdentifier, TaskIdentifier

SessionIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^session-[a-zA-Z0-9._:-]+$"),
]
RunIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^run-[a-zA-Z0-9._:-]+$"),
]
ContextKey = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
]
ContextText = Annotated[str, Field(min_length=1, max_length=256)]
IntentCode = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
IntentValue = Annotated[Intent, Field(strict=False)]
ActionType = IntentCode
type ContextValue = ContextText | int | float | bool | None


class SessionSchema(BaseModel):
    """为会话契约提供严格、不可变且禁止额外字段的共同配置。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class PendingActionContext(SessionSchema):
    """只保存待确认动作草稿, 不代表已经授权或执行。"""

    action_type: ActionType
    parameters: dict[ContextKey, ContextValue] = Field(default_factory=dict)
    source_run_id: RunIdentifier | None = None

    @model_validator(mode="after")
    def limit_parameters(self) -> Self:
        """限制会话草稿大小, 避免把任意业务响应塞入上下文。"""

        if len(self.parameters) > 32:
            raise ValueError("pending action parameters must contain at most 32 items")
        return self

# 会话上下文保存的是“用户现在在谈什么”, 不是“业务现在是什么状态” (防止会话过大)
class SessionContext(SessionSchema):
    """跨轮次保存最小业务指代, 不复制Java业务事实。"""

    current_order_id: OrderIdentifier | None = None
    current_task_id: TaskIdentifier | None = None
    previous_intent: IntentValue | None = None
    confirmed_entities: dict[ContextKey, ContextValue] = Field(default_factory=dict)
    candidate_entities: dict[ContextKey, list[ContextText]] = Field(default_factory=dict)
    recent_diagnosis_run_id: RunIdentifier | None = None
    pending_action: PendingActionContext | None = None
    
    # 限制会话上下文大小, 避免把任意业务响应塞入上下文
    @model_validator(mode="after")
    def validate_context_limits(self) -> Self:
        """保证任务具有父订单, 并限制可持久化实体数量。"""

        if self.current_task_id is not None and self.current_order_id is None:
            raise ValueError("current task requires current order")
        if len(self.confirmed_entities) > 32:
            raise ValueError("confirmed entities must contain at most 32 items")
        if len(self.candidate_entities) > 16:
            raise ValueError("candidate entity groups must contain at most 16 items")
        if any(len(candidates) > 20 for candidates in self.candidate_entities.values()):
            raise ValueError("each candidate entity group must contain at most 20 items")
        return self


class SessionCreateRequest(SessionSchema):
    """创建会话时可选地接收已经过页面Schema校验的上下文提示。"""

    page_context: PageContext | None = None


class SessionResponse(SessionSchema):
    """返回会话标识、最小上下文和服务端过期时间。"""

    session_id: SessionIdentifier
    context: SessionContext
    expires_at: datetime


class SessionErrorResponse(SessionSchema):
    """会话API使用的稳定安全错误结构。"""

    trace_id: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ]
    code: IntentCode
    message: Annotated[str, Field(min_length=1, max_length=2048)]

# PageContext 合并到 SessionContext
def context_from_page(
    page_context: PageContext,
    *,
    base: SessionContext | None = None,
) -> SessionContext:
    """把页面业务指代合并进会话, 同时清除已经失效的下级实体。"""

    current = base or SessionContext()
    confirmed = dict(current.confirmed_entities)
    confirmed["order_id"] = page_context.order_id
    # 清除旧的下级引用实体 (例如: 用户回到订单页, 合并函数会主动删除旧的下级引用)
    if page_context.task_id is None:
        confirmed.pop("task_id", None)
        confirmed.pop("issue_id", None)
    else:
        confirmed["task_id"] = page_context.task_id
        if page_context.issue_id is None:
            confirmed.pop("issue_id", None)
        else:
            confirmed["issue_id"] = page_context.issue_id
    return current.model_copy(
        update={
            "current_order_id": page_context.order_id,
            "current_task_id": page_context.task_id,
            "confirmed_entities": confirmed,
        }
    )
# SessionContext 恢复到 PageContext
def page_context_from_session(
    context: SessionContext,
    *,
    user_role: str,
) -> PageContext:
    """从已保存的当前订单/任务恢复页面提示, 后续仍需Java事实重校验。"""

    if context.current_order_id is None:
        raise ValueError("session context does not contain current order")
    current_page = (
        PageType.TASK_DETAIL
        if context.current_task_id is not None
        else PageType.ORDER_DETAIL
    )
    return PageContext(
        current_system="production-system",
        current_page=current_page,
        order_id=context.current_order_id,
        task_id=context.current_task_id,
        user_role=user_role,
    )
