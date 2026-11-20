"""T840经生产诊断和旧查询核对ORDER-003原始事实、根因、建议与运行记录。"""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    ReworkConfirmationRecord,
)
from app.schemas.agent import OrderDiagnosisResponse
from tests.e2e.rework_acceptance_fixtures import isolated_rework
from tests.e2e.test_rework_acceptance_flows import endpoints

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def test_rework_acceptance_golden_old_queries_and_fixed_diagnosis(tmp_path: Path) -> None:
    """只读查询与固定诊断保留初始黄金结论，不通过重置数据达成断言。"""

    db, java = endpoints()
    async with isolated_rework(db, java, case="T840-GOLDEN", storage_root=tmp_path) as fixture:
        before_response = await fixture.java.get("/api/orders/ORDER-003/overview")
        assert before_response.status_code == 200
        before = before_response.json()["data"]
        for path in ("/api/orders/ORDER-003", "/api/tasks/TASK-003", "/api/tasks/TASK-003/review"):
            response = await fixture.java.get(path)
            assert response.status_code == 200 and response.json()["success"] is True
        orders = await fixture.java.get("/api/orders")
        assert orders.status_code == 200
        assert {f"ORDER-{number:03d}" for number in range(1, 31)} <= {
            row["orderId"] for row in orders.json()["data"]["orders"]
        }
        response = await fixture.page.post(
            "/api/agent/order-diagnosis",
            json={
                "order_id": "ORDER-003",
                "user_message": "这个订单为什么还没有交付？",
                "page_context": {
                    "current_system": "production-system",
                    "current_page": "order-detail",
                    "order_id": "ORDER-003",
                    "user_role": "REVIEWER",
                },
            },
        )
        assert response.status_code == 200, response.text
        payload = OrderDiagnosisResponse.model_validate_json(response.content)
        diagnosis = payload.diagnosis
        assert (
            diagnosis.order_id == "ORDER-003" and diagnosis.blocking_stage.value == "QUALITY_REVIEW"
        )
        assert {cause.code for cause in diagnosis.root_causes} == {
            "OPEN_COORDINATE_SYSTEM_ISSUE",
            "REVIEW_PENDING",
        }
        assert {suggestion.action_type for suggestion in diagnosis.suggestions} == {
            "CREATE_COORDINATE_SYSTEM_REWORK",
            "RESUBMIT_REVIEW",
        }
        assert [evidence.value for evidence in diagnosis.evidence] == [
            "COMPLETED",
            "OPEN",
            "PENDING",
            "BLOCKED",
        ]
        assert all(evidence.source_type == "TOOL" for evidence in diagnosis.evidence)
        async with fixture.database.session() as session:
            run = await session.get(AgentRun, payload.run_id)
            assert run is not None and run.status is AgentRunStatus.SUCCEEDED
            assert run.final_result == diagnosis.model_dump(mode="json")
            steps = (
                await session.scalars(
                    select(AgentStep)
                    .where(AgentStep.run_id == payload.run_id)
                    .order_by(AgentStep.sequence_number)
                )
            ).all()
            assert steps and all(step.status is AgentStepStatus.SUCCEEDED for step in steps)
            assert [step.sequence_number for step in steps] == list(range(1, len(steps) + 1))
            assert (
                await session.scalar(select(func.count()).select_from(ReworkConfirmationRecord))
                == 0
            )
        after = await fixture.java.get("/api/orders/ORDER-003/overview")
        assert after.status_code == 200 and after.json()["data"] == before
