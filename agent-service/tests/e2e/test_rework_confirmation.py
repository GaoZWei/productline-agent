"""T828独占Java和分离测试Agent库，真实成果变化使原确认STALE，不调用新写Tool。"""

import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import asyncpg  # type: ignore[import-untyped]
import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.database import Base, Database
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentSession,
)
from app.schemas.business import BusinessIdentity
from app.schemas.rework import (
    CreateLifecycleReworkRequest,
    RegisterReworkResultRequest,
    ReworkVersionRequest,
)
from app.services.rework_confirmation import ReworkConfirmationError, ReworkConfirmationService
from app.services.rework_confirmation_store import DatabaseReworkConfirmationStore
from app.settings import Settings
from app.tools.models import ToolContext
from app.tools.readonly import create_read_tool_registry
from app.tools.rework_readonly import create_rework_read_tool_registry
from app.workflows.rework_draft import ReworkDraftWorkflow

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]
TASK, ISSUE, ORDER = "TASK-T828-E2E", "ISSUE-T828-E2E", "ORDER-T828-E2E"


async def test_real_java_changed_artifact_stales_persisted_confirmation_without_writing() -> None:
    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    url = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or url is None:
        pytest.skip("通过make test-rework-confirmation-e2e启动独占Java/PostgreSQL")
    assert urlparse(db).hostname == "127.0.0.1"
    assert urlparse(db).path == "/business_service_test_rework_query"
    assert urlparse(url).hostname == "127.0.0.1"
    admin_url = make_url(db).set(database="postgres")
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    agent_name = "agent_t828_confirmation_e2e"
    await admin.execute(f'CREATE DATABASE "{agent_name}"')
    agent_db = Database(
        str(make_url(db).set(database=agent_name).render_as_string(hide_password=False))
    )
    business_fixture = create_async_engine(db.replace("postgresql://", "postgresql+asyncpg://", 1))
    shared = BusinessHttpClient(
        Settings(_env_file=None, environment="test", business_service_url=AnyHttpUrl(url))
    )
    java = ReworkHttpClient(shared)
    identity = BusinessIdentity(user_id="reviewer-t828-e2e", role="REVIEWER")
    ctx = ToolContext(
        identity=identity,
        permissions=frozenset({"TASK_READ", "REWORK_READ", "REWORK_WRITE", "REVIEW_WRITE"}),
        trace_id="trace-t828-e2e",
        run_id="run-t828-e2e",
    )
    now = datetime.now(UTC)
    store = DatabaseReworkConfirmationStore(agent_db)
    flow = ReworkDraftWorkflow(
        task_tools=create_read_tool_registry(shared),
        rework_tools=create_rework_read_tool_registry(java),
    )
    service = ReworkConfirmationService(store=store, workflow=flow)
    try:
        # 此库仅建本场景所需Agent表。完整升级/降级另由隔离迁移测试验证。
        async with agent_db.engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(
                    sync,
                    tables=[
                        Base.metadata.tables["agent_sessions"],
                        Base.metadata.tables["agent_messages"],
                        Base.metadata.tables["agent_runs"],
                        Base.metadata.tables["rework_confirmation_records"],
                    ],
                )
            )
        async with agent_db.session() as session, session.begin():
            session.add(
                AgentSession(
                    session_id="session-t828-e2e",
                    user_id=identity.user_id,
                    expires_at=now + timedelta(days=1),
                )
            )
            await session.flush()
            session.add(
                AgentRun(
                    run_id=ctx.run_id,
                    session_id="session-t828-e2e",
                    status=AgentRunStatus.RUNNING,
                    version_snapshot={},
                )
            )
        golden = (await java.get_effective_reviews("TASK-003", identity=identity)).data
        golden_delivery = (await java.get_delivery_conditions("ORDER-003", identity=identity)).data
        async with business_fixture.begin() as connection:
            # 仅建立独占Java测试库中的确定性场景，产品Python不访问业务表。
            await connection.exec_driver_sql(
                "INSERT INTO production_orders VALUES ('ORDER-T828-E2E','DOM','QUALITY_CHECKING')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO production_tasks(task_id,order_id,status,version) "
                "VALUES ('TASK-T828-E2E','ORDER-T828-E2E','COMPLETED',0)"
            )
            await connection.exec_driver_sql(
                "INSERT INTO quality_issues "
                "VALUES ('ISSUE-T828-E2E','TASK-T828-E2E','COORDINATE_SYSTEM','OPEN','返工检查')"
            )
        # 直接Java写入只推进验收夹具，不冒充新人工确认执行入口。
        created = (
            await java.create_first(
                TASK,
                CreateLifecycleReworkRequest(
                    expected_version=0, source_issue_id=ISSUE, reason="建立人工返工夹具"
                ),
                identity=identity,
                idempotency_key="t828-first",
            )
        ).data
        rework = created.rework_task_id
        started = (
            await java.start(
                TASK,
                rework,
                ReworkVersionRequest(expected_version=created.task_version),
                identity=identity,
                idempotency_key="t828-start",
            )
        ).data
        version = started.task_version
        for revision in (1, 2):
            result = RegisterReworkResultRequest.model_validate(
                {
                    "expectedVersion": version,
                    "artifact": {
                        "artifactId": "成果-T828",
                        "artifactVersion": f"Release-{revision}",
                    },
                    "processingComment": "  人工修正🚀  ",
                    "evidenceReferences": ["report:t828-result"],
                }
            )
            registered = (
                await java.register_result(
                    TASK,
                    rework,
                    result,
                    identity=identity,
                    idempotency_key=f"t828-result-{revision}",
                )
            ).data
            version = registered.task_version
            if revision == 1:
                pending = await service.create(
                    {
                        "operation": "REGISTER_REWORK_INSPECTION",
                        "task_id": TASK,
                        "rework_task_id": rework,
                        "items": [
                            {
                                "checkItem": "坐标系",
                                "result": "PASSED",
                                "comment": "人工待审检查项",
                                "evidenceReferences": ["report:t828-check"],
                            }
                        ],
                    },
                    context=ctx,
                )
                assert pending.prepared.review.draft.target.processing_revision == 1
        with pytest.raises(ReworkConfirmationError, match="APPROVAL_STALE"):
            await service.confirm(
                {"approval_id": pending.approval_id, "draft": pending.prepared.review.draft},
                context=ctx,
            )
        stored = await store.get(pending.approval_id, context=ctx, now=datetime.now(UTC))
        assert stored is not None and stored.status == "STALE"
        assert (
            stored.prepared.review.draft.target.processing_revision == 1
            and stored.confirmed_draft is None
        )
        current = await service.create(
            {
                "operation": "REGISTER_REWORK_INSPECTION",
                "task_id": TASK,
                "rework_task_id": rework,
                "items": [
                    {
                        "checkItem": "坐标系",
                        "result": "FAILED",
                        "comment": "仍需人工处理",
                        "evidenceReferences": ["report:t828-failed"],
                    }
                ],
            },
            context=ctx,
        )
        confirmed = await service.confirm(
            {"approval_id": current.approval_id, "draft": current.prepared.review.draft},
            context=ctx,
        )
        assert confirmed.status == "CONFIRMED" and confirmed.confirmed_draft is not None
        assert confirmed.confirmed_draft.target.processing_revision == 2
        detail = (await java.get_detail(TASK, rework, identity=identity)).data
        assert detail.task_version == version and detail.inspection is None
        assert detail.rework_task.status == "RUNNING" and detail.issue_status == "PROCESSING"
        assert (await java.get_effective_reviews("TASK-003", identity=identity)).data == golden
        assert (
            await java.get_delivery_conditions("ORDER-003", identity=identity)
        ).data == golden_delivery
    finally:
        await shared.aclose()
        await business_fixture.dispose()
        await agent_db.dispose()
        await admin.execute(f'DROP DATABASE "{agent_name}" WITH (FORCE)')
        await admin.close()
