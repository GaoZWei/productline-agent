"""M6.3复核草稿生成Workflow的事实刷新、引用门禁和零写入测试。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from app.errors import ToolErrorCode
from app.models import AgentRunStatus, ApprovalStatus
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge import Citation, PermissionScope
from app.schemas.specification import SpecificationQaResult, SpecificationQaStatus
from app.schemas.tools import QualityIssueList, TaskDetail
from app.schemas.workflow import DiagnosisResult
from app.tools import ToolContext, ToolError, ToolResult
from app.workflows.review_draft import (
    InvalidReviewDraftOutputError,
    ReviewDraftBusinessFactError,
    ReviewDraftGenerationModelRequest,
    ReviewDraftGenerationWorkflow,
    ReviewDraftPersistenceResult,
    ReviewDraftRunSnapshot,
    ReviewDraftSourceError,
    ReviewDraftSpecificationError,
)


def _diagnosis() -> DiagnosisResult:
    return DiagnosisResult.model_validate_json(
        json.dumps(
            {
                "order_id": "ORDER-003",
                "blocking_stage": "QUALITY_REVIEW",
                "summary": "订单阻塞在质量复核环节。",
                "root_causes": [
                    {
                        "code": "OPEN_COORDINATE_SYSTEM_ISSUE",
                        "description": "关联任务存在未关闭的坐标系质量问题",
                    }
                ],
                "evidence": [
                    {
                        "source_type": "TOOL",
                        "tool_name": "get_quality_issues",
                        "field_path": "issues[0].status",
                        "value": "OPEN",
                        "description": "ISSUE-001问题状态为OPEN",
                    }
                ],
                "suggestions": [
                    {
                        "action_type": "CREATE_COORDINATE_SYSTEM_REWORK",
                        "description": "创建坐标系处理返工任务",
                    }
                ],
                "confidence": 1.0,
            },
            ensure_ascii=False,
        )
    )


def _task() -> TaskDetail:
    return TaskDetail.model_validate(
        {
            "taskId": "TASK-003",
            "orderId": "ORDER-003",
            "status": "COMPLETED",
            "version": 7,
        }
    )


def _issues() -> QualityIssueList:
    return QualityIssueList.model_validate(
        {
            "taskId": "TASK-003",
            "issues": [
                {
                    "issueId": "ISSUE-001",
                    "taskId": "TASK-003",
                    "issueType": "COORDINATE_SYSTEM",
                    "status": "OPEN",
                    "description": "成果坐标参考系与任务要求不一致",
                }
            ],
        }
    )


def _citation(*, chunk_id: str = "CHUNK-COORD-001") -> Citation:
    return Citation(
        document_id="SPEC-COORD-001",
        document_name="坐标系统处理规范",
        document_version="2.0",
        section=("质量复核", "坐标系统"),
        chunk_id=chunk_id,
        chunk_ids=(chunk_id,),
        content="坐标系统问题关闭后方可重新提交复核。",
        relevance_score=0.98,
    )


def _specification_result(
    *, status: SpecificationQaStatus = SpecificationQaStatus.ANSWERED
) -> SpecificationQaResult:
    answered = status is SpecificationQaStatus.ANSWERED
    return SpecificationQaResult(
        status=status,
        question="坐标系统问题应如何复核和处理?",
        rewritten_query="坐标系统问题应如何复核和处理?",
        answer=(
            "坐标系统问题关闭后方可重新提交复核。" if answered else "未检索到足够相关的现行规范。"
        ),
        citations=(_citation(),) if answered else (),
        rerank_degraded=status is SpecificationQaStatus.RERANK_UNAVAILABLE,
    )


def _draft(*, citation: Citation | None = None) -> dict[str, object]:
    return {
        "task_id": "TASK-003",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": "建议完成坐标系统处理后重新提交复核",
        "specification_references": [(citation or _citation()).model_dump(mode="json")],
        "suggested_rework": {
            "required": True,
            "type": "COORDINATE_SYSTEM_FIX",
        },
    }


class _FakeTool:
    def __init__(self, result: ToolResult[Any]) -> None:
        self.result = result
        self.calls: list[tuple[object, bool]] = []

    async def execute(
        self,
        raw_input: object,
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> ToolResult[Any]:
        del context
        self.calls.append((raw_input, force_refresh))
        return self.result


class _FakeRegistry:
    def __init__(self, tools: Mapping[str, _FakeTool]) -> None:
        self.tools = dict(tools)

    def get(self, name: str) -> _FakeTool:
        return self.tools[name]


class _FakeSpecificationWorkflow:
    def __init__(self, result: SpecificationQaResult) -> None:
        self.result = result
        self.questions: list[str] = []

    async def ainvoke(self, question: str, **_: object) -> SpecificationQaResult:
        self.questions.append(question)
        return self.result


class _FakeDraftModel:
    def __init__(self, output: object) -> None:
        self.output = output
        self.requests: list[ReviewDraftGenerationModelRequest] = []

    async def generate(self, request: ReviewDraftGenerationModelRequest) -> object:
        self.requests.append(request)
        return self.output


class _FakeStore:
    def __init__(self, snapshot: ReviewDraftRunSnapshot | None) -> None:
        self.snapshot = snapshot
        self.saved: list[dict[str, object]] = []

    async def latest_diagnosis(
        self,
        session_id: str,
        *,
        identity: BusinessIdentity,
    ) -> ReviewDraftRunSnapshot | None:
        assert session_id == "session-003"
        assert identity.user_id == "reviewer-001"
        return self.snapshot

    async def save_waiting_approval(self, **values: object) -> ReviewDraftPersistenceResult:
        self.saved.append(dict(values))
        return ReviewDraftPersistenceResult(
            approval_id=str(values["approval_id"]),
            approval_status=ApprovalStatus.WAITING_CONFIRMATION,
            run_status=AgentRunStatus.WAITING_APPROVAL,
        )


def _snapshot(
    *,
    status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
    final_result: dict[str, object] | None = None,
) -> ReviewDraftRunSnapshot:
    return ReviewDraftRunSnapshot(
        run_id="run-diagnosis-003",
        status=status,
        final_result=(
            _diagnosis().model_dump(mode="json") if final_result is None else final_result
        ),
    )


def _workflow(
    *,
    store: _FakeStore | None = None,
    task: TaskDetail | None = None,
    specification_result: SpecificationQaResult | None = None,
    draft_output: object | None = None,
) -> tuple[
    ReviewDraftGenerationWorkflow,
    _FakeStore,
    _FakeTool,
    _FakeTool,
    _FakeTool,
    _FakeSpecificationWorkflow,
    _FakeDraftModel,
]:
    task_tool = _FakeTool(ToolResult(success=True, data=task or _task()))
    issue_tool = _FakeTool(ToolResult(success=True, data=_issues()))
    write_tool = _FakeTool(ToolResult(success=True, data=_task()))
    registry = _FakeRegistry(
        {
            "get_task_detail": task_tool,
            "get_quality_issues": issue_tool,
            "write_review_result": write_tool,
        }
    )
    resolved_store = store or _FakeStore(_snapshot())
    specification = _FakeSpecificationWorkflow(specification_result or _specification_result())
    model = _FakeDraftModel(draft_output or _draft())
    workflow = ReviewDraftGenerationWorkflow(
        store=resolved_store,
        tool_registry=registry,
        tool_context=ToolContext(
            identity=BusinessIdentity(user_id="reviewer-001", role="INTERNAL_REVIEWER"),
            permissions=frozenset({"TASK_READ", "QUALITY_ISSUE_READ"}),
            trace_id="trace-draft-003",
            run_id="run-diagnosis-003",
        ),
        specification_workflow=specification,
        draft_model=model,
        effective_at=date(2026, 8, 26),
        permission_scope=PermissionScope.INTERNAL_REVIEWER,
        approval_id_factory=lambda: "approval-draft-003",
    )
    return (
        workflow,
        resolved_store,
        task_tool,
        issue_tool,
        write_tool,
        specification,
        model,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generates_waiting_approval_from_refreshed_facts_without_write_tool() -> None:
    workflow, store, task_tool, issue_tool, write_tool, specification, model = _workflow()

    result = await workflow.ainvoke(session_id="session-003", task_id="TASK-003")

    assert result.approval_id == "approval-draft-003"
    assert result.run_id == "run-diagnosis-003"
    assert result.approval_status is ApprovalStatus.WAITING_CONFIRMATION
    assert result.run_status is AgentRunStatus.WAITING_APPROVAL
    assert result.draft.conclusion.value == "REWORK_REQUIRED"
    assert task_tool.calls == [({"task_id": "TASK-003"}, True)]
    assert issue_tool.calls == [({"task_id": "TASK-003"}, True)]
    assert write_tool.calls == []
    assert "COORDINATE_SYSTEM" in specification.questions[0]
    assert model.requests[0].diagnosis.order_id == "ORDER-003"
    assert model.requests[0].task.version == 7
    assert model.requests[0].quality_issues[0].issue_id == "ISSUE-001"
    assert model.requests[0].citations == (_citation(),)
    assert store.saved[0]["target_version"] == 7
    assert store.saved[0]["draft"] == result.draft


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("snapshot", "expected_message"),
    [
        (None, "recent diagnosis"),
        (_snapshot(status=AgentRunStatus.WAITING_APPROVAL), "SUCCEEDED"),
        (_snapshot(final_result={"unexpected": "shape"}), "invalid"),
    ],
)
async def test_requires_latest_successful_schema_valid_diagnosis(
    snapshot: ReviewDraftRunSnapshot | None,
    expected_message: str,
) -> None:
    store = _FakeStore(snapshot)
    workflow, _, task_tool, _, write_tool, _, _ = _workflow(store=store)

    with pytest.raises(ReviewDraftSourceError, match=expected_message):
        await workflow.ainvoke(session_id="session-003", task_id="TASK-003")

    assert task_tool.calls == []
    assert write_tool.calls == []
    assert store.saved == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rejects_task_from_another_order_before_specification_and_model() -> None:
    mismatched_task = _task().model_copy(update={"order_id": "ORDER-004"})
    workflow, store, _, _, write_tool, specification, model = _workflow(task=mismatched_task)

    with pytest.raises(ReviewDraftBusinessFactError, match="order"):
        await workflow.ainvoke(session_id="session-003", task_id="TASK-003")

    assert specification.questions == []
    assert model.requests == []
    assert write_tool.calls == []
    assert store.saved == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stops_when_current_specification_cannot_supply_citations() -> None:
    workflow, store, _, _, write_tool, _, model = _workflow(
        specification_result=_specification_result(
            status=SpecificationQaStatus.INSUFFICIENT_CONTEXT
        )
    )

    with pytest.raises(ReviewDraftSpecificationError, match="current citations"):
        await workflow.ainvoke(session_id="session-003", task_id="TASK-003")

    assert model.requests == []
    assert write_tool.calls == []
    assert store.saved == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "draft_output",
    [
        {**_draft(), "task_id": "TASK-004"},
        _draft(citation=_citation(chunk_id="CHUNK-INVENTED")),
        {**_draft(), "review_comment": ""},
    ],
)
async def test_rejects_changed_target_invented_citation_and_invalid_schema(
    draft_output: object,
) -> None:
    workflow, store, _, _, write_tool, _, _ = _workflow(draft_output=draft_output)

    with pytest.raises(InvalidReviewDraftOutputError):
        await workflow.ainvoke(session_id="session-003", task_id="TASK-003")

    assert write_tool.calls == []
    assert store.saved == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_failure_stops_before_rag_model_and_persistence() -> None:
    workflow, store, task_tool, _, write_tool, specification, model = _workflow()
    task_tool.result = ToolResult(
        success=False,
        error=ToolError(
            code=ToolErrorCode.UPSTREAM_UNAVAILABLE,
            message="business service unavailable",
            retryable=True,
            trace_id="trace-upstream",
        ),
    )

    with pytest.raises(ReviewDraftBusinessFactError, match="get_task_detail"):
        await workflow.ainvoke(session_id="session-003", task_id="TASK-003")

    assert specification.questions == []
    assert model.requests == []
    assert write_tool.calls == []
    assert store.saved == []
