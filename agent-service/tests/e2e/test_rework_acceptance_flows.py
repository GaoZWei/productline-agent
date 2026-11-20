"""T837/T838真实Java人工闭环、多轮历史及旧证据失效验收。"""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import AgentRun, AgentRunStatus, ReworkConfirmationRecord, ReworkOperationLog
from tests.e2e.rework_acceptance_fixtures import (
    ReworkAcceptance,
    inspection_materials,
    isolated_rework,
    result_materials,
)

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


def endpoints() -> tuple[str, str]:
    """只允许既有独占环境入口，缺少环境时明确跳过。"""

    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    java = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or java is None:
        pytest.skip("通过make test-rework-e2e启动独占Java/PostgreSQL")
    return db, java


async def assert_closed_with_delivery_blocker(fixture: ReworkAcceptance) -> None:
    """关闭一个问题只改变对应有效复核，不能清除其他交付条件。"""

    closed = await fixture.detail()
    assert closed.rework_task.status == "COMPLETED" and closed.issue_status == "CLOSED"
    assert closed.review is not None and closed.review.status == "APPROVED"
    conditions = await fixture.conditions()
    task = next(row for row in conditions.tasks if row.task_id == fixture.ids.task)
    assert task.production_status == "COMPLETED" and task.task_version == closed.task_version
    current = next(row for row in task.issues if row.issue.issue_id == fixture.ids.issue)
    assert current.issue.status == "CLOSED"
    assert current.effective_review.rework_task_id == fixture.rework_id
    assert current.effective_review.review == closed.review
    assert conditions.order.status == "QUALITY_CHECKING" and conditions.has_blockers
    assert conditions.delivery_records[0].status == "BLOCKED"
    assert any(
        row.resource_id == conditions.delivery_records[0].delivery_id for row in conditions.blockers
    )
    assert not any(row.resource_id == fixture.ids.issue for row in conditions.blockers)


async def test_rework_acceptance_normal_first_round(tmp_path: Path) -> None:
    """T837每项动作独立确认，材料、历史、回执、Run和审计对应同一首轮。"""

    db, java = endpoints()
    async with isolated_rework(db, java, case="T837-NORMAL", storage_root=tmp_path) as fixture:
        await fixture.apply("START_REWORK")
        await fixture.apply("REGISTER_REWORK_RESULT", **result_materials())
        checked = await fixture.apply("REGISTER_REWORK_INSPECTION", **inspection_materials())
        assert checked.issue_status == "RESOLVED" and checked.review is None
        assert checked.processing is not None and checked.inspection is not None
        assert checked.inspection.processing_revision == checked.processing.processing_revision
        await fixture.apply(
            "SUBMIT_REWORK_REVIEW", status="APPROVED", review_comment="首轮再次复核通过"
        )
        await assert_closed_with_delivery_blocker(fixture)
        for kind in ("results", "inspections", "reviews"):
            assert len(await fixture.history(kind)) == 1
        async with fixture.database.session() as session:
            approvals = (await session.scalars(select(ReworkConfirmationRecord))).all()
            assert len(approvals) == 4 and all(row.status == "SUCCEEDED" for row in approvals)
            assert len({row.execution_key for row in approvals}) == 4
            runs = (await session.scalars(select(AgentRun))).all()
            assert len(runs) == 4 and all(row.status is AgentRunStatus.SUCCEEDED for row in runs)
            audit_count = await session.scalar(select(func.count()).select_from(ReworkOperationLog))
            assert audit_count is not None and audit_count > 4


@pytest.mark.parametrize("changed", ["processing", "inspection"])
async def test_rework_acceptance_changed_evidence_and_second_round(
    changed: str, tmp_path: Path
) -> None:
    """T838旧成果或检查证据失效后停止旧审批，失败历史及退回在第二轮关闭后保留。"""

    db, java = endpoints()
    async with isolated_rework(
        db, java, case=f"T838-{changed.upper()}", storage_root=tmp_path
    ) as fixture:
        await fixture.apply("START_REWORK")
        await fixture.apply("REGISTER_REWORK_RESULT", **result_materials())
        if changed == "inspection":
            await fixture.apply("REGISTER_REWORK_INSPECTION", **inspection_materials("FAILED"))
        old = await fixture.preview("REGISTER_REWORK_INSPECTION", **inspection_materials())
        if changed == "processing":
            await fixture.apply("REGISTER_REWORK_RESULT", **result_materials("002.0"))
        else:
            changed_check = inspection_materials("FAILED")
            changed_check["items"] = [
                {
                    "checkItem": "坐标系统一",
                    "result": "FAILED",
                    "comment": "检查证据已变化",
                    "evidenceReferences": ["fixture://changed"],
                }
            ]
            await fixture.apply("REGISTER_REWORK_INSPECTION", **changed_check)
        latest = await fixture.detail()
        stale = await fixture.page.post(
            f"{fixture.approval_path(old)}/confirm", json={"decision": "CONFIRM"}
        )
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "APPROVAL_STALE"
        assert await fixture.detail() == latest
        if changed == "processing":
            latest = await fixture.apply(
                "REGISTER_REWORK_INSPECTION", **inspection_materials("FAILED")
            )
        assert latest.inspection is not None and latest.inspection.result == "FAILED"
        assert latest.rework_task.status == "RUNNING" and latest.issue_status == "PROCESSING"
        failed_history = await fixture.history("inspections")
        rejected = await fixture.page.post(
            "/api/agent/rework-actions/preview",
            json={
                "order_id": fixture.ids.order,
                "command": {
                    "operation": "SUBMIT_REWORK_REVIEW",
                    "task_id": fixture.ids.task,
                    "rework_task_id": fixture.rework_id,
                    "status": "APPROVED",
                    "review_comment": "失败后不能提前复核",
                },
            },
        )
        assert (
            rejected.status_code == 409 and rejected.json()["detail"]["code"] == "BUSINESS_CONFLICT"
        )
        assert await fixture.detail() == latest
        await fixture.apply("REGISTER_REWORK_INSPECTION", **inspection_materials())
        returned = await fixture.apply(
            "SUBMIT_REWORK_REVIEW", status="REWORK_REQUIRED", review_comment="退回第二轮"
        )
        assert returned.issue_status == "OPEN" and returned.review is not None
        next_preview = await fixture.preview("CREATE_NEXT_REWORK", reason="第二轮独立处理")
        receipt = await fixture.confirm(next_preview)
        assert receipt.next_rework_task_id is not None
        second = replace(fixture, rework_id=receipt.next_rework_task_id)
        empty = await second.detail()
        assert empty.round_number == 2 and empty.previous_rework_task_id == fixture.rework_id
        assert empty.processing is None and empty.inspection is None and empty.review is None
        before = await second.detail()
        retry_old = await fixture.page.post(
            f"{fixture.approval_path(old)}/confirm", json={"decision": "CONFIRM"}
        )
        # 首次失效已结束原Run，确认端口按不可再操作返回404，不重新进入确认。
        assert retry_old.status_code == 404
        assert retry_old.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"
        async with fixture.database.session() as session:
            stale_record = await session.get(ReworkConfirmationRecord, old.approval_id)
            assert stale_record is not None and stale_record.status == "STALE"
        reconciled = await fixture.page.post(
            f"{fixture.approval_path(old)}/reconcile",
            json={
                "order_id": fixture.ids.order,
                "task_id": fixture.ids.task,
                "rework_task_id": fixture.rework_id,
            },
        )
        assert reconciled.status_code == 200 and reconciled.json()["outcome"] == "NOT_SUBMITTED"
        assert await second.detail() == before
        await second.apply("START_REWORK")
        await second.apply("REGISTER_REWORK_RESULT", **result_materials("003.0"))
        await second.apply("REGISTER_REWORK_INSPECTION", **inspection_materials())
        await second.apply(
            "SUBMIT_REWORK_REVIEW", status="APPROVED", review_comment="第二轮复核通过"
        )
        await assert_closed_with_delivery_blocker(second)
        assert (await fixture.detail()).review == returned.review
        all_old_checks = await fixture.history("inspections")
        assert all_old_checks[: len(failed_history)] == failed_history
        assert all_old_checks[-1]["result"] == "PASSED"
        assert len(await second.history("results")) == len(await second.history("inspections")) == 1
