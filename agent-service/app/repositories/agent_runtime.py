"""Agent Run 和 Step 的异步 Repository。"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentMessage,
    AgentRun,
    AgentRunStatus,
    AgentSession,
    AgentStep,
    AgentStepStatus,
)


class AgentSessionRepository:
    """封装会话增删查和行锁; 过期与身份策略由服务层决定。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, agent_session: AgentSession) -> AgentSession:
        """加入会话并立即flush, 使标识冲突在当前事务内暴露。"""

        self._session.add(agent_session)
        await self._session.flush()
        return agent_session

    async def get(self, session_id: str) -> AgentSession | None:
        """按会话标识查询, 未找到时返回None。"""

        return await self._session.get(AgentSession, session_id)

    async def get_for_update(self, session_id: str) -> AgentSession | None:
        """锁定会话, 供上下文合并和消息序号分配使用。"""

        statement = (
            select(AgentSession)
            .where(AgentSession.session_id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def delete(self, session_id: str) -> bool:
        """删除会话; 数据库级联清除其Message、Run与Step。"""

        agent_session = await self.get(session_id)
        if agent_session is None:
            return False
        await self._session.delete(agent_session)
        await self._session.flush()
        return True


class AgentMessageRepository:
    """封装会话消息写入和稳定序号查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, message: AgentMessage) -> AgentMessage:
        """保存消息并立即flush。"""

        self._session.add(message)
        await self._session.flush()
        return message

    async def next_sequence_number(self, session_id: str) -> int:
        """返回会话内下一个消息序号; 调用方必须先锁定父会话。"""

        statement = select(func.coalesce(func.max(AgentMessage.sequence_number), 0) + 1).where(
            AgentMessage.session_id == session_id
        )
        return int(await self._session.scalar(statement) or 1)


class AgentRunRepository:
    """封装 Run 增删查; 事务提交或回滚由调用方统一决定。"""
    # 初始化session
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: AgentRun) -> AgentRun:
        """加入一个 Run 并立即 flush, 使数据库约束在当前事务内生效。"""

        self._session.add(run)  # 把对象加入当前Session管理。  
        await self._session.flush()  # 把待执行SQL发送到数据库
        return run

    async def get(self, run_id: str) -> AgentRun | None:
        """按稳定 run_id 查询, 未找到时返回 None。"""

        return await self._session.get(AgentRun, run_id)

    async def get_for_update(self, run_id: str) -> AgentRun | None:
        """锁定并刷新目标 Run, 供关联 Step 前校验当前执行状态。"""

        statement = (
            select(AgentRun)
            .where(AgentRun.run_id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def list_by_session(self, session_id: str) -> list[AgentRun]:
        """按创建时间和 run_id 返回会话内稳定排序的 Run。"""

        statement = (
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at, AgentRun.run_id)
        )
        return list((await self._session.scalars(statement)).all())
    # 列表查询接口
    async def list_for_user(
        self,
        user_id: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[AgentRun], int]:
        """按会话所有者倒序分页Run, 并返回同一权限边界内的总数。"""

        owner_filter = AgentSession.user_id == user_id
        count_statement = (
            select(func.count(AgentRun.run_id))
            .select_from(AgentRun)
            .join(AgentSession, AgentSession.session_id == AgentRun.session_id)
            .where(owner_filter)
        )
        list_statement = (
            select(AgentRun)
            .join(AgentSession, AgentSession.session_id == AgentRun.session_id)
            .where(owner_filter)
            .order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = int(await self._session.scalar(count_statement) or 0)
        runs = list((await self._session.scalars(list_statement)).all())
        return runs, total
    # 详情查询接口
    async def get_for_user(self, run_id: str, user_id: str) -> AgentRun | None:
        """在SQL层同时校验Run身份和Session所有者, 避免泄露他人的Run。"""

        statement = (
            select(AgentRun)
            .join(AgentSession, AgentSession.session_id == AgentRun.session_id)
            .where(
                AgentRun.run_id == run_id, 
                AgentSession.user_id == user_id,  # 需要同样匹配Session所有者才能返回Run
            )
        )
        return (await self._session.scalars(statement)).one_or_none()
    # 定位最近一个带结果的Run
    async def latest_result_by_session(self, session_id: str) -> AgentRun | None:
        """返回会话中最近一个带结果的Run, 不回退到更旧的可审批状态。"""

        statement = (
            select(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.final_result.is_not(None),
                func.json_typeof(AgentRun.final_result) != "null",
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc())
            .limit(1)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def delete(self, run_id: str) -> bool:
        """删除存在的 Run; 数据库级联删除其 Step。"""

        run = await self.get(run_id)
        if run is None:
            return False
        await self._session.delete(run)
        await self._session.flush()
        return True

    async def transition_status(
        self,
        run_id: str,
        *,
        expected_status: AgentRunStatus,
        target_status: AgentRunStatus,
        changes: Mapping[str, Any],
    ) -> AgentRun | None:
        """仅在当前状态符合预期时原子更新 Run, 防止并发终态互相覆盖。"""
        # 限制可修改字段
        allowed_changes = {
            "started_at",
            "finished_at",
            "final_result",
            "error_code",
            "error_step",
            "input_token_count",
            "output_token_count",
            "total_token_count",
            "tool_call_count",
            "duration_ms",
            "termination_reason",
        }
        unexpected_changes = set(changes) - allowed_changes
        if unexpected_changes:
            unexpected_names = ", ".join(sorted(unexpected_changes))
            raise ValueError(f"unsupported run transition fields: {unexpected_names}")
        # 组合更新内容
        values: dict[str, Any] = {"status": target_status, **changes}
        statement = (
            update(AgentRun)
            .where(
                AgentRun.run_id == run_id,
                AgentRun.status == expected_status,
            )
            .values(values)
            .returning(AgentRun)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def save_router_result(
        self,
        run_id: str,
        *,
        router_result: dict[str, Any],
    ) -> AgentRun | None:
        """只允许未结束Run保存当前最终路由结果。"""

        statement = (
            update(AgentRun)
            .where(
                AgentRun.run_id == run_id,
                # 只允许未结束Run保存路由结果
                AgentRun.status.in_((AgentRunStatus.PENDING, AgentRunStatus.RUNNING)),
            )
            .values(router_result=router_result)
            .returning(AgentRun)
        )
        return (await self._session.scalars(statement)).one_or_none()


class AgentStepRepository:
    """封装 Step 增删查; 不在 Repository 内隐式提交事务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, step: AgentStep) -> AgentStep:
        """加入一个 Step 并 flush, 及时暴露序号冲突等约束错误。"""

        self._session.add(step)
        await self._session.flush()
        return step

    async def get(self, step_id: str) -> AgentStep | None:
        """按稳定 step_id 查询, 未找到时返回 None。"""

        return await self._session.get(AgentStep, step_id)

    async def get_fresh(self, step_id: str) -> AgentStep | None:
        """绕过会话中的旧状态缓存, 返回数据库当前 Step。"""

        statement = (
            select(AgentStep)
            .where(AgentStep.step_id == step_id)
            .execution_options(populate_existing=True)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def list_by_run(self, run_id: str) -> list[AgentStep]:
        """按 sequence_number 返回 Run 内确定顺序的 Step。"""

        statement = (
            select(AgentStep)
            .where(AgentStep.run_id == run_id)
            .order_by(AgentStep.sequence_number, AgentStep.step_id)
        )
        return list((await self._session.scalars(statement)).all())

    async def transition_status(
        self,
        step_id: str,
        *,
        expected_status: AgentStepStatus,
        target_status: AgentStepStatus,
        changes: Mapping[str, Any],
    ) -> AgentStep | None:
        """仅在当前状态符合预期时原子更新 Step终态。"""

        allowed_changes = {
            "finished_at",
            "output_summary",
            "error_code",
            "duration_ms",
            "llm_model_name",
            "llm_input_token_count",
            "llm_output_token_count",
            "llm_total_token_count",
            "llm_retry_count",
        }
        unexpected_changes = set(changes) - allowed_changes
        if unexpected_changes:
            unexpected_names = ", ".join(sorted(unexpected_changes))
            raise ValueError(f"unsupported step transition fields: {unexpected_names}")
        values: dict[str, Any] = {"status": target_status, **changes}
        statement = (
            update(AgentStep)
            .where(
                AgentStep.step_id == step_id,
                AgentStep.status == expected_status,
            )
            .values(values)
            .returning(AgentStep)
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def delete(self, step_id: str) -> bool:
        """删除存在的 Step; 不存在时保持幂等并返回 False。"""

        step = await self.get(step_id)
        if step is None:
            return False
        await self._session.delete(step)
        await self._session.flush()
        return True
