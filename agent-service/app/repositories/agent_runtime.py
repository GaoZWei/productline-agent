"""Agent Run 和 Step 的异步 Repository。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, AgentStep


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

    async def list_by_session(self, session_id: str) -> list[AgentRun]:
        """按创建时间和 run_id 返回会话内稳定排序的 Run。"""

        statement = (
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at, AgentRun.run_id)
        )
        return list((await self._session.scalars(statement)).all())

    async def delete(self, run_id: str) -> bool:
        """删除存在的 Run; 数据库级联删除其 Step。"""

        run = await self.get(run_id)
        if run is None:
            return False
        await self._session.delete(run)
        await self._session.flush()
        return True


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

    async def list_by_run(self, run_id: str) -> list[AgentStep]:
        """按 sequence_number 返回 Run 内确定顺序的 Step。"""

        statement = (
            select(AgentStep)
            .where(AgentStep.run_id == run_id)
            .order_by(AgentStep.sequence_number, AgentStep.step_id)
        )
        return list((await self._session.scalars(statement)).all())

    async def delete(self, step_id: str) -> bool:
        """删除存在的 Step; 不存在时保持幂等并返回 False。"""

        step = await self.get(step_id)
        if step is None:
            return False
        await self._session.delete(step)
        await self._session.flush()
        return True
