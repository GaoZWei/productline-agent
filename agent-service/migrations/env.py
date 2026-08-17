"""Agent 服务异步 SQLAlchemy 元数据使用的 Alembic 运行环境。"""
# Alembic每次执行迁移时加载的环境代码
from asyncio import run
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models import AgentSession
from app.settings import get_settings

config = context.config
# 导入一个映射类会加载模型包, 并让Alembic看见全部Agent自有表。
target_metadata = AgentSession.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().async_database_url,
        target_metadata=target_metadata,
        version_table="agent_alembic_version",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="agent_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section: dict[str, Any] = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_settings().async_database_url
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
