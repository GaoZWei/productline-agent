"""T836验证独立场景夹具可用及资源释放，不替代T837至T840场景验收。"""

import os
from contextlib import nullcontext
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from sqlalchemy import func, select

from app.models import AgentRun, ReworkConfirmationRecord
from app.schemas.rework import ReworkAction
from tests.e2e.rework_acceptance_fixtures import (
    AcceptanceIds,
    inspection_materials,
    isolated_rework,
    result_materials,
    validate_isolated_endpoints,
)

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


class _FixtureBodyFailure(Exception):
    """仅用于验证夹具体异常退出后的清理，不冒充真实业务故障。"""


@pytest.mark.parametrize("state", ["PENDING", "CHECKED", "INTERRUPTED"])
async def test_rework_acceptance_independent_fixture(state: str, tmp_path: Path) -> None:
    """不同状态使用各自命名空间，单项或逆序执行都不依赖另一项结果。"""

    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    java = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or java is None:
        pytest.skip("通过make test-rework-e2e启动独占Java/PostgreSQL")
    case = f"T836-{state}"
    expected = pytest.raises(_FixtureBodyFailure) if state == "INTERRUPTED" else nullcontext()
    with expected:
        async with isolated_rework(db, java, case=case, storage_root=tmp_path) as fixture:
            original = await fixture.detail()
            assert original.round_number == 1 and original.task_version == 1
            assert original.rework_task.status == "PENDING" and original.issue_status == "OPEN"
            assert original.processing is None
            assert original.inspection is None
            assert original.review is None
            async with fixture.database.session() as session:
                assert await session.scalar(select(func.count()).select_from(AgentRun)) == 0
            if state == "INTERRUPTED":
                await fixture.preview("START_REWORK")
                assert await fixture.detail() == original
                raise _FixtureBodyFailure()
            if state == "PENDING":
                preview = await fixture.preview("START_REWORK")
                assert await fixture.detail() == original
                await fixture.cancel(preview)
                assert await fixture.detail() == original
            else:
                steps: tuple[tuple[ReworkAction, dict[str, object]], ...] = (
                    ("START_REWORK", {}),
                    ("REGISTER_REWORK_RESULT", result_materials()),
                    ("REGISTER_REWORK_INSPECTION", inspection_materials()),
                )
                for operation, materials in steps:
                    # 每项测试材料经独立预览和明确确认，不从夹具直接写业务生命周期。
                    await fixture.confirm(await fixture.preview(operation, **materials))
                current = await fixture.detail()
                assert current.task_version == 4 and current.rework_task.status == "COMPLETED"
                assert current.issue_status == "RESOLVED" and current.review is None
                assert current.processing is not None and current.inspection is not None
                assert current.processing.artifact.artifact_version == "001.0"
                assert current.inspection.result == "PASSED"
                async with fixture.database.session() as session:
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(ReworkConfirmationRecord)
                        )
                        == 3
                    )
    # 连接池已关闭，必须只删除自己创建的Agent库，业务夹具随独占容器整体回收。
    admin = await asyncpg.connect(db)
    try:
        assert not await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=$1)",
            AcceptanceIds(case).agent_database,
        )
    finally:
        await admin.close()


async def test_rework_acceptance_existing_database_is_preserved(tmp_path: Path) -> None:
    """同名库已存在时夹具拒绝启动，不能删除非本次创建的库或写业务初始数据。"""

    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    java = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or java is None:
        pytest.skip("通过make test-rework-e2e启动独占Java/PostgreSQL")
    validate_isolated_endpoints(db, java)
    ids = AcceptanceIds("T836-EXISTS")
    admin = await asyncpg.connect(db)
    created = False
    try:
        await admin.execute(f'CREATE DATABASE "{ids.agent_database}"')
        created = True
        with pytest.raises(asyncpg.DuplicateDatabaseError):
            async with isolated_rework(db, java, case=ids.case, storage_root=tmp_path):
                pytest.fail("must not take over existing database")
        assert await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=$1)", ids.agent_database
        )
        assert not await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM production_orders WHERE order_id=$1)", ids.order
        )
    finally:
        try:
            if created:
                await admin.execute(f'DROP DATABASE "{ids.agent_database}"')
        finally:
            await admin.close()
