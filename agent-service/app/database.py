"""SQLAlchemy foundation for Agent-owned runtime data."""

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
    """Metadata root for future Agent Run, Step and Approval tables."""


class Database:
    """Own the async engine and sessions without connecting during import."""
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
        """Provide one transaction-neutral session to a request or workflow step."""

        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """Release engine resources during application shutdown."""

        await self.engine.dispose()
