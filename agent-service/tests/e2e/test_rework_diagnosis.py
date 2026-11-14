"""T825独占Java/PostgreSQL两轮返工与固定/动态诊断，不调用真实模型。"""

import os
from datetime import date
from urllib.parse import urlparse

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import create_async_engine

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.schemas.business import BusinessIdentity
from app.schemas.diagnosis_reviews import DiagnosisReviewResult
from app.schemas.knowledge import PermissionScope
from app.schemas.rework import (
    CreateLifecycleReworkRequest,
    RegisterReworkInspectionRequest,
    RegisterReworkResultRequest,
    ReworkReasonRequest,
    ReworkVersionRequest,
    SubmitReworkReviewRequest,
)
from app.schemas.workflow import AgentAction, BlockingStage, OrderDiagnosisState
from app.settings import Settings
from app.tools.diagnosis_reviews import create_diagnosis_read_tool_registry
from app.workflows import (
    ActionDecider,
    AgentExecutionLimits,
    DynamicDiagnosisWorkflow,
    OrderDiagnosisWorkflow,
)
from tests.test_dynamic_diagnosis_paths import (
    SequenceActionModel,
    StubSpecificationWorkflow,
    _context,
    _decision,
)
from tests.test_order_diagnosis_workflow import MemoryStepRecorder

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]
ORDER, TASK, ISSUE = "ORDER-T825-E2E", "TASK-T825-E2E", "ISSUE-T825-E2E"


async def test_two_real_rework_rounds_use_current_java_review_and_preserve_history_and_golden() -> (
    None
):
    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    url = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or url is None:
        pytest.skip("通过make test-rework-diagnosis-e2e启动独占Java/PostgreSQL")
    assert (
        urlparse(db).hostname == "127.0.0.1"
        and urlparse(db).path == "/business_service_test_rework_query"
    )
    assert urlparse(url).hostname == "127.0.0.1"
    engine = create_async_engine(db.replace("postgresql://", "postgresql+asyncpg://", 1))
    settings = Settings(_env_file=None, environment="test", business_service_url=AnyHttpUrl(url))
    shared = BusinessHttpClient(settings)
    client = ReworkHttpClient(shared)
    identity = BusinessIdentity(user_id="reviewer-t825-e2e", role="REVIEWER")

    async def diagnose(order: str = ORDER, *, dynamic: bool = False) -> OrderDiagnosisState:
        registry = create_diagnosis_read_tool_registry(shared)
        ctx = _context(order, workflow_type="dynamic" if dynamic else "fixed")
        if not dynamic:
            return await OrderDiagnosisWorkflow(
                tool_registry=registry, tool_context=ctx, step_recorder=MemoryStepRecorder()
            ).ainvoke(order)
        actions = [
            AgentAction.QUERY_ORDER,
            AgentAction.QUERY_TASKS,
            AgentAction.QUERY_PROGRESS,
            AgentAction.QUERY_QUALITY,
            AgentAction.QUERY_REVIEW,
            AgentAction.QUERY_DELIVERY,
            AgentAction.RETRIEVE_SPEC,
            AgentAction.FINISH,
        ]
        workflow = DynamicDiagnosisWorkflow(
            action_decider=ActionDecider(
                model=SequenceActionModel(
                    [_decision(action, order_id=order) for action in actions]
                ),
                registry=registry,
            ),
            tool_registry=registry,
            tool_context=ctx,
            specification_workflow=StubSpecificationWorkflow(),
            effective_at=date(2026, 11, 14),
            permission_scope=PermissionScope.INTERNAL_REVIEWER,
            limits=AgentExecutionLimits(max_decision_rounds=10),
        )
        return await workflow.ainvoke(order)

    try:
        golden = await diagnose("ORDER-003")
        assert (
            golden["diagnosis"] is not None
            and golden["diagnosis"].blocking_stage is BlockingStage.QUALITY_REVIEW
        )
        assert {r.code for r in golden["diagnosis"].root_causes} == {
            "OPEN_COORDINATE_SYSTEM_ISSUE",
            "REVIEW_PENDING",
        }
        async with engine.begin() as connection:
            # 仅给本次独占数据库准备确定性夹具，产品Python仍只调用Java。
            await connection.exec_driver_sql(
                "INSERT INTO production_orders VALUES ('ORDER-T825-E2E','DOM','QUALITY_CHECKING')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO production_tasks(task_id,order_id,status,version) "
                "VALUES ('TASK-T825-E2E','ORDER-T825-E2E','COMPLETED',0)"
            )
            await connection.exec_driver_sql(
                "INSERT INTO production_steps "
                "VALUES ('STEP-T825-E2E','TASK-T825-E2E','完成生产',1,'COMPLETED')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO quality_issues "
                "VALUES ('ISSUE-T825-E2E','TASK-T825-E2E','COORDINATE_SYSTEM','OPEN','坐标系返工')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO delivery_records VALUES ('DELIVERY-T825-E2E','ORDER-T825-E2E','READY')"
            )
            await connection.exec_driver_sql(
                "INSERT INTO review_records(review_id,issue_id,status,review_comment) "
                "VALUES ('REVIEW-T825-OLD-PASS','ISSUE-T825-E2E','APPROVED','历史通过'),"
                "('REVIEW-T825-OLD-FAIL','ISSUE-T825-E2E','REJECTED','历史未通过')"
            )
        created = await client.create_first(
            TASK,
            CreateLifecycleReworkRequest(
                source_issue_id=ISSUE, expected_version=0, reason="独立人工确认首轮夹具"
            ),
            identity=identity,
            idempotency_key="t825-first",
        )
        rework_id, version = created.data.rework_task_id, created.data.task_version
        first_id = rework_id
        for round_number in (1, 2):
            started = await client.start(
                TASK,
                rework_id,
                ReworkVersionRequest(expected_version=version),
                identity=identity,
                idempotency_key=f"t825-start-{round_number}",
            )
            result = await client.register_result(
                TASK,
                rework_id,
                RegisterReworkResultRequest.model_validate(
                    {
                        "expectedVersion": started.data.task_version,
                        "artifact": {
                            "artifactId": "成果-T825",
                            "artifactVersion": f"Release-{round_number}",
                        },
                        "processingComment": "人工修正",
                        "evidenceReferences": ["report:t825"],
                    }
                ),
                identity=identity,
                idempotency_key=f"t825-result-{round_number}",
            )
            checked = await client.register_inspection(
                TASK,
                rework_id,
                RegisterReworkInspectionRequest.model_validate(
                    {
                        "expectedVersion": result.data.task_version,
                        "processingRevision": 1,
                        "items": [
                            {
                                "checkItem": "坐标系",
                                "result": "PASSED",
                                "comment": "人工检查",
                                "evidenceReferences": ["report:checked"],
                            }
                        ],
                    }
                ),
                identity=identity,
                idempotency_key=f"t825-check-{round_number}",
            )
            before_review = await diagnose()
            assert (
                before_review["diagnosis"] is not None
                and before_review["diagnosis"].blocking_stage is BlockingStage.REVIEW
            )
            assert checked.data.inspection_id is not None
            reviewed = await client.submit_review(
                TASK,
                rework_id,
                SubmitReworkReviewRequest(
                    expected_version=checked.data.task_version,
                    processing_revision=1,
                    inspection_id=checked.data.inspection_id,
                    status="REWORK_REQUIRED" if round_number == 1 else "APPROVED",
                    review_comment="人工复核",
                ),
                identity=identity,
                idempotency_key=f"t825-review-{round_number}",
            )
            if round_number == 1:
                rejected = await diagnose()
                assert (
                    rejected["diagnosis"] is not None
                    and rejected["diagnosis"].blocking_stage is BlockingStage.QUALITY_REVIEW
                )
                successor = await client.create_next(
                    TASK,
                    rework_id,
                    ReworkReasonRequest(
                        expected_version=reviewed.data.task_version, reason="独立人工确认下一轮夹具"
                    ),
                    identity=identity,
                    idempotency_key="t825-next",
                )
                rework_id, version = successor.data.rework_task_id, successor.data.task_version
        for dynamic in (False, True):
            closed = await diagnose(dynamic=dynamic)
            assert (
                closed["diagnosis"] is not None
                and closed["diagnosis"].blocking_stage is BlockingStage.NONE
            )
            view = closed["reviews"][TASK]
            assert isinstance(view, DiagnosisReviewResult)
            assert len(view.history_reviews) == 2 and {r.status for r in view.history_reviews} == {
                "APPROVED",
                "REJECTED",
            }
            assert len(view.reviews) == 1 and view.reviews[0].status == "APPROVED"
        history = await client.get_reviews(TASK, first_id, identity=identity)
        assert (
            len(history.data.records) == 1 and history.data.records[0].status == "REWORK_REQUIRED"
        )
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "UPDATE delivery_records SET status='BLOCKED' WHERE delivery_id='DELIVERY-T825-E2E'"
            )
        blocked = await diagnose()
        assert (
            blocked["diagnosis"] is not None
            and blocked["diagnosis"].blocking_stage is BlockingStage.DELIVERY
        )
        after = await diagnose("ORDER-003")
        assert after["diagnosis"] == golden["diagnosis"]
    finally:
        await shared.aclose()
        await engine.dispose()
