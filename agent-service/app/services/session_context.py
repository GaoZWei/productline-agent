"""M3.2 会话上下文持久化、身份隔离和过期策略。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError

from app.database import Database
from app.models import AgentSession
from app.repositories import AgentSessionRepository
from app.schemas.business import BusinessIdentity
from app.schemas.context import PageContext
from app.schemas.session import SessionContext, context_from_page


def _utc_now() -> datetime:
    """返回带时区的UTC时间, 允许测试注入确定性时钟。"""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """API和诊断编排可安全消费的会话快照。"""

    session_id: str
    context: SessionContext
    expires_at: datetime


class SessionContextError(Exception):
    """会话服务可转换为稳定HTTP字段的错误。"""

    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class SessionNotFoundError(SessionContextError):
    """目标会话不存在。"""

    def __init__(self) -> None:
        super().__init__(code="SESSION_NOT_FOUND", message="agent session was not found")


class SessionAccessDeniedError(SessionContextError):
    """当前身份不拥有目标会话。"""

    def __init__(self) -> None:
        super().__init__(code="PERMISSION_DENIED", message="agent session access is denied")


class SessionExpiredError(SessionContextError):
    """会话已超过服务端过期时间。"""

    def __init__(self) -> None:
        super().__init__(code="SESSION_EXPIRED", message="agent session has expired")


class InvalidStoredSessionContextError(SessionContextError):
    """数据库中的会话上下文不符合当前Schema。"""

    def __init__(self) -> None:
        super().__init__(
            code="SESSION_CONTEXT_INVALID",
            message="stored agent session context is invalid",
        )

# 会话服务层, 管理会话上下文的创建、读取、更新和过期策略
class SessionContextService:
    """管理最小会话上下文, 不把上下文当作Java业务事实。"""

    def __init__(
        self,
        database: Database,
        *,
        ttl_seconds: int,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._database = database
        self._ttl = timedelta(seconds=ttl_seconds)
        self._now = now
    # 创建会话
    async def create(
        self,
        *,
        identity: BusinessIdentity,
        page_context: PageContext | None = None,
    ) -> SessionSnapshot:
        """创建属于当前用户的会话, 可选保存页面业务指代。"""

        if page_context is not None and page_context.user_role != identity.role:
            raise SessionAccessDeniedError()
        now = self._now()
        # 可选地把 PageContext 转成 SessionContext
        context = context_from_page(page_context) if page_context is not None else SessionContext()
        agent_session = AgentSession(
            session_id=f"session-{uuid4().hex}",
            user_id=identity.user_id,
            context=context.model_dump(mode="json"),
            expires_at=now + self._ttl,
        )
        async with self._database.session() as session, session.begin():
            await AgentSessionRepository(session).create(agent_session)
        # 返回不可变 SessionSnapshot
        return self.snapshot(agent_session)
    # 读取会话
    async def get_active(
        self,
        *,
        session_id: str,
        identity: BusinessIdentity,
    ) -> SessionSnapshot:
        """读取当前用户尚未过期的会话, 不因只读查询延长TTL。"""

        async with self._database.session() as session:
            agent_session = await AgentSessionRepository(session).get(session_id)
            self.ensure_access(agent_session, identity=identity, now=self._now())
            assert agent_session is not None
            return self.snapshot(agent_session)
    # 更新会话
    async def replace_context(
        self,
        *,
        session_id: str,
        identity: BusinessIdentity,
        context: SessionContext,
    ) -> SessionSnapshot:
        """供后续路由节点保存已确认参数、候选对象和待确认操作。"""

        now = self._now()
        async with self._database.session() as session, session.begin():
            agent_session = await AgentSessionRepository(session).get_for_update(session_id)
            self.ensure_access(agent_session, identity=identity, now=now)
            assert agent_session is not None
            agent_session.context = context.model_dump(mode="json")
            agent_session.expires_at = now + self._ttl
            await session.flush()
        return self.snapshot(agent_session)
    # 删除过期会话
    async def delete(
        self,
        *,
        session_id: str,
        identity: BusinessIdentity,
    ) -> None:
        """清除当前用户会话及其级联运行记录; 过期会话仍允许所有者清理。"""

        async with self._database.session() as session, session.begin():
            repository = AgentSessionRepository(session)
            agent_session = await repository.get_for_update(session_id)
            self.ensure_owner(agent_session, identity=identity)
            await repository.delete(session_id)

    @staticmethod
    def ensure_owner(
        agent_session: AgentSession | None,
        *,
        identity: BusinessIdentity,
    ) -> None:
        """区分不存在与跨用户访问, 避免服务层遗漏身份校验。"""

        if agent_session is None:
            raise SessionNotFoundError()
        if agent_session.user_id != identity.user_id:
            raise SessionAccessDeniedError()

    @classmethod
    def ensure_access(
        cls,
        agent_session: AgentSession | None,
        *,
        identity: BusinessIdentity,
        now: datetime,
    ) -> None:
        """校验会话所有者和服务端过期时间。"""

        cls.ensure_owner(agent_session, identity=identity)
        assert agent_session is not None
        if agent_session.expires_at <= now:
            raise SessionExpiredError()

    @staticmethod
    def context(agent_session: AgentSession) -> SessionContext:
        """把数据库JSON重新约束为严格SessionContext。"""

        try:
            return SessionContext.model_validate(agent_session.context)
        except ValidationError as error:
            raise InvalidStoredSessionContextError() from error

    @classmethod
    def snapshot(cls, agent_session: AgentSession) -> SessionSnapshot:
        """从持久化模型构建不可变会话快照。"""

        return SessionSnapshot(
            session_id=agent_session.session_id,
            context=cls.context(agent_session),
            expires_at=agent_session.expires_at,
        )
