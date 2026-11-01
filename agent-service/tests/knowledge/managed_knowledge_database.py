"""管理模型与应用测试共用的隔离PostgreSQL，不迁移配置地址对应的原数据库。"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_alembic(database_url: str, *arguments: str) -> None:
    """只在本测试创建的数据库运行迁移，子进程沿用当前虚拟环境。"""

    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest_asyncio.fixture
async def managed_database() -> AsyncIterator[Database]:
    """建立独立测试库，前序版本用旧表哨兵表示，绝不迁移传入地址对应的库。"""

    configured = os.environ.get("AGENT_PERSISTENCE_TEST_DATABASE_URL")
    if configured is None:
        pytest.skip("需要AGENT_PERSISTENCE_TEST_DATABASE_URL提供隔离PostgreSQL")
    url = make_url(configured)
    name = f"agent_kb024_{uuid4().hex}"
    admin_url = url.set(drivername="postgresql", database="postgres")
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    database = Database(url.set(database=name).render_as_string(hide_password=False))
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        async with database.engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(
                text("CREATE TABLE knowledge_documents (document_id text PRIMARY KEY, body text)")
            )
            await connection.execute(
                text("CREATE TABLE knowledge_chunks (chunk_id text PRIMARY KEY, content text)")
            )
            await connection.execute(
                text("INSERT INTO knowledge_documents VALUES ('legacy-doc', '旧规范哨兵')")
            )
            await connection.execute(
                text("INSERT INTO knowledge_chunks VALUES ('legacy-chunk', '旧引用哨兵')")
            )
        migration_url = url.set(database=name, drivername="postgresql").render_as_string(
            hide_password=False
        )
        run_alembic(migration_url, "stamp", "0014_review_source_run")
        run_alembic(migration_url, "upgrade", "head")
        yield database
    finally:
        await database.dispose()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
