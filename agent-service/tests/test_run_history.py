"""M7.5 Run列表摘要映射和服务权限边界测试。"""

from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError

from app.database import Database
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    ApprovalRecord,
    ApprovalStatus,
    OperationType,
    PendingToolName,
)
from app.schemas.business import BusinessIdentity
from app.schemas.run_history import RunSummary
from app.services.run_history import (
    DatabaseRunHistoryService,
    RunHistoryAccessError,
    approval_history_from_record,
    run_summary_from_record,
    step_summary_from_record,
)


@pytest.mark.unit
def test_run_summary_projects_only_safe_fields_and_hides_invalid_resource_hint() -> None:
    run = AgentRun(
        run_id="run-history-safe",
        session_id="session-history-safe",
        status=AgentRunStatus.SUCCEEDED,
        version_snapshot={"private": "not returned"},
        page_context_snapshot={
            "order_id": "ORDER-003",
            "task_id": "not-a-task-id",
            "user_role": "REVIEWER",
        },
        final_result={"summary": "not returned"},
        router_result={"intent": "not returned"},
        tool_call_count=6,
        total_token_count=0,
        created_at=datetime(2026, 8, 30, 1, 0, tzinfo=UTC),
    )

    summary = run_summary_from_record(run)

    assert summary.order_id == "ORDER-003"
    assert summary.task_id is None
    assert summary.tool_call_count == 6
    assert set(summary.model_dump()) == {
        "run_id",
        "session_id",
        "status",
        "order_id",
        "task_id",
        "tool_call_count",
        "total_token_count",
        "duration_ms",
        "termination_reason",
        "error_code",
        "error_step",
        "created_at",
        "started_at",
        "finished_at",
    }


@pytest.mark.unit
def test_run_summary_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        RunSummary(
            run_id="run-history-naive",
            session_id="session-history-naive",
            status=AgentRunStatus.RUNNING,
            tool_call_count=0,
            total_token_count=0,
            created_at=datetime(2026, 8, 30, 1, 0),
        )


@pytest.mark.unit
def test_step_summary_accepts_existing_workflow_step_identifier() -> None:
    step = AgentStep(
        step_id="workflow-step-58901d61ca1017f32a16451d21a9b99e",
        run_id="run-history-safe",
        sequence_number=1,
        step_type=AgentStepType.WORKFLOW,
        step_name="validate_input",
        status=AgentStepStatus.SUCCEEDED,
        created_at=datetime(2026, 8, 30, 1, 0, tzinfo=UTC),
    )

    assert step_summary_from_record(step).step_id.startswith("workflow-step-")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_history_service_rejects_non_reviewer_before_database_access() -> None:
    service = DatabaseRunHistoryService(cast(Database, object()))

    with pytest.raises(RunHistoryAccessError) as captured:
        await service.list_runs(
            identity=BusinessIdentity(user_id="operator-001", role="OPERATOR"),
            page=1,
            page_size=20,
        )

    assert captured.value.code == "PERMISSION_DENIED"
    assert captured.value.status_code == 403


@pytest.mark.unit
def test_step_summary_keeps_only_controlled_tool_input_and_output() -> None:
    step = AgentStep(
        step_id="step-history-tool",
        run_id="run-history-safe",
        sequence_number=2,
        step_type=AgentStepType.TOOL,
        step_name="get_quality_issues",
        status=AgentStepStatus.SUCCEEDED,
        input_summary="task_id=TASK-003",
        output_summary="issue_count=1",
        duration_ms=12,
        created_at=datetime(2026, 8, 30, 1, 0, tzinfo=UTC),
    )

    summary = step_summary_from_record(step)

    assert summary.step_type is AgentStepType.TOOL
    assert summary.input_summary == "task_id=TASK-003"
    assert summary.output_summary == "issue_count=1"
    assert "run_id" not in summary.model_dump()


@pytest.mark.unit
def test_approval_history_preserves_original_and_effective_draft_with_diff() -> None:
    original = _review_draft("Agent原始意见")
    modified = _review_draft("用户确认先完成返工")
    approval = ApprovalRecord(
        approval_id="approval-history-003",
        run_id="run-history-safe",
        status=ApprovalStatus.SUCCEEDED,
        operation_type=OperationType.SUBMIT_REVIEW,
        original_draft=original,
        user_modified_draft=modified,
        pending_tool_name=PendingToolName.WRITE_REVIEW_RESULT,
        target_id="TASK-003",
        target_version=7,
        created_at=datetime(2026, 8, 30, 1, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 30, 1, 1, tzinfo=UTC),
    )

    history = approval_history_from_record(approval)

    assert history.original_draft.review_comment == "Agent原始意见"
    assert history.effective_draft.review_comment == "用户确认先完成返工"
    assert [item.field_path for item in history.user_modification_diff] == ["review_comment"]
    assert history.effective_draft.specification_references[0].document_version == "2.0"


def _review_draft(comment: str) -> dict[str, object]:
    return {
        "task_id": "TASK-003",
        "issue_id": "ISSUE-001",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": comment,
        "specification_references": [
            {
                "document_id": "SPEC-COORD-001",
                "document_name": "坐标系统处理规范",
                "document_version": "2.0",
                "section": ["质量复核", "坐标系统"],
                "chunk_id": "CHUNK-COORD-001",
                "chunk_ids": ["CHUNK-COORD-001"],
                "content": "坐标系统问题关闭后方可重新提交复核。",
                "relevance_score": 0.98,
            }
        ],
        "suggested_rework": {"required": True, "type": "COORDINATE_SYSTEM_FIX"},
    }
