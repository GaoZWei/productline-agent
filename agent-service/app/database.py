"""Agent 自有运行数据的 SQLAlchemy 基础设施。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.settings import Settings


# 异步数据库
class Base(DeclarativeBase):
    """Agent Session、Message、Run、Step 和后续 Approval 表的元数据根类。"""


class Database:
    """管理异步引擎和会话。模块导入时不建立数据库连接。"""

    def __init__(self, database_url: str) -> None:
        settings = Settings(database_url=database_url)
        # Engine代表数据库驱动和连接池配置。
        self.engine: AsyncEngine = create_async_engine(
            settings.async_database_url,
            pool_pre_ping=True,
        )
        # 创建一个会话的工厂
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """为一次请求或工作流步骤提供不预设事务策略的会话。"""

        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """在应用关闭时释放数据库引擎资源。"""

        await self.engine.dispose()
