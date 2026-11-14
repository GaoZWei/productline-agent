"""T825 Java有效复核投影、快照一致性与新旧诊断规则。"""

import httpx
import pytest
from pydantic import ValidationError

from app.clients.business import BusinessHttpClient
from app.schemas.diagnosis_reviews import DiagnosisReviewResult, project_java_reviews
from app.schemas.rework import EffectiveReworkReviews
from app.schemas.workflow import BlockingStage, OrderDiagnosisState
from app.tools.diagnosis_reviews import create_diagnosis_read_tool_registry
from app.workflows.diagnosis_generation import generate_rule_diagnosis
from app.workflows.diagnosis_rules import evaluate_diagnosis_rules, evaluate_dynamic_diagnosis_rules
from app.workflows.information_gaps import InformationGapDetector
from app.workflows.order_diagnosis import OrderDiagnosisWorkflow
from tests.test_diagnosis_rules import _state
from tests.test_order_diagnosis_workflow import (
    MemoryStepRecorder,
    _context,
    _golden_handler,
    _settings,
    _success,
)

pytestmark = pytest.mark.asyncio


def controlled_state(
    *,
    current_status: str | None = "APPROVED",
    issue_status: str = "CLOSED",
    history_status: str = "REJECTED",
    delivery: str = "READY",
) -> OrderDiagnosisState:
    """旧历史可以与当前复核相反，任务和问题只用确定性独立夹具。"""

    state = _state(
        order_id="ORDER-T825",
        order_status="QUALITY_CHECKING",
        task_status="COMPLETED",
        step_status="COMPLETED",
        issue_status=issue_status,
        review_status=history_status,
        delivery_status=delivery,
    )
    task = state["tasks"][0]
    issue = state["quality_issues"][task.task_id][0]
    review = (
        None
        if current_status is None
        else {
            "reviewId": "REVIEW-CURRENT",
            "reviewSequence": 2,
            "roundNumber": 2,
            "processingRevision": 2,
            "inspectionId": "CHECK-CURRENT",
            "status": current_status,
            "reviewComment": "  当前原样说明  ",
            "reviewedBy": "reviewer-test",
            "reviewedAt": "2026-11-14T00:00:00Z",
        }
    )
    fact = EffectiveReworkReviews.model_validate(
        {
            "taskId": task.task_id,
            "taskVersion": task.version,
            "issues": [
                {
                    "issueId": issue.issue_id,
                    "reworkTaskId": "REWORK-CURRENT",
                    "roundNumber": 2,
                    "processingRevision": 2,
                    "inspectionId": "CHECK-CURRENT",
                    "review": review,
                    "legacyReviews": [],
                }
            ],
        }
    )
    history = state["reviews"][task.task_id]
    assert history is not None
    state["reviews"][task.task_id] = DiagnosisReviewResult(
        task_id=task.task_id,
        reviews=project_java_reviews(fact),
        effective_reviews=fact,
        history_reviews=history.reviews,
    )
    return state


@pytest.mark.parametrize("history", ["PENDING", "REJECTED", "REWORK_REQUIRED", "APPROVED"])
async def test_old_history_cannot_block_java_current_approved_closed_issue(history: str) -> None:
    state = controlled_state(history_status=history)
    for evaluate in [evaluate_diagnosis_rules, evaluate_dynamic_diagnosis_rules]:
        assert evaluate(state).blocking_stage is BlockingStage.NONE
    result = state["reviews"][state["tasks"][0].task_id]
    assert isinstance(result, DiagnosisReviewResult)
    assert result.history_reviews[0].status == history
    assert result.effective_reviews.issues[0].review is not None
    assert result.effective_reviews.issues[0].review.review_comment == "  当前原样说明  "


@pytest.mark.parametrize(
    "current,issue,expected",
    [
        (None, "RESOLVED", BlockingStage.REVIEW),
        (None, "CLOSED", BlockingStage.REVIEW),
        ("REJECTED", "RESOLVED", BlockingStage.REVIEW),
        ("REWORK_REQUIRED", "OPEN", BlockingStage.QUALITY_REVIEW),
        ("APPROVED", "RESOLVED", BlockingStage.REVIEW),
    ],
)
async def test_old_approval_cannot_release_current_missing_or_failed_review(
    current: str | None, issue: str, expected: BlockingStage
) -> None:
    state = controlled_state(current_status=current, issue_status=issue, history_status="APPROVED")
    state["rule_decision"] = evaluate_diagnosis_rules(state)
    assert state["rule_decision"] is not None
    assert state["rule_decision"].blocking_stage is expected
    result = generate_rule_diagnosis(state)
    assert result.blocking_stage is expected and result.root_causes
    if current is None:
        assert any(
            e.field_path == "effective_reviews.issues[0].review" and e.value is None
            for e in result.evidence
        )


async def test_closing_issue_does_not_clear_other_delivery_blockers() -> None:
    state = controlled_state(delivery="BLOCKED")
    assert evaluate_diagnosis_rules(state).blocking_stage is BlockingStage.DELIVERY


async def test_dynamic_review_scene_cannot_skip_quality_facts_for_current_binding() -> None:
    state = controlled_state()
    assert state["order"] is not None
    state["order"] = state["order"].model_copy(update={"status": "REVIEWING"})
    state["quality_issues"] = {}
    assert any(g.code == "QUALITY_ISSUES_REQUIRED" for g in InformationGapDetector().detect(state))
    assert (
        evaluate_dynamic_diagnosis_rules(state).blocking_stage
        is BlockingStage.INSUFFICIENT_INFORMATION
    )


@pytest.mark.parametrize("kind", ["version", "missing-issue", "wrong-task", "mutated-projection"])
async def test_mixed_snapshot_never_yields_complete_diagnosis(kind: str) -> None:
    state = controlled_state()
    task = state["tasks"][0]
    result = state["reviews"][task.task_id]
    assert isinstance(result, DiagnosisReviewResult)
    if kind == "version":
        state["tasks"][0] = task.model_copy(update={"version": 1})
    elif kind == "missing-issue":
        state["quality_issues"][task.task_id] = []
    elif kind == "wrong-task":
        state["reviews"][task.task_id] = result.model_copy(update={"task_id": "TASK-OTHER"})
    else:
        result.reviews.clear()
    assert evaluate_diagnosis_rules(state).blocking_stage is BlockingStage.INSUFFICIENT_INFORMATION
    assert (
        evaluate_dynamic_diagnosis_rules(state).blocking_stage
        is BlockingStage.INSUFFICIENT_INFORMATION
    )
    if kind != "missing-issue":
        assert any(
            g.code == "REVIEW_RESULT_REQUIRED" for g in InformationGapDetector().detect(state)
        )


async def test_unmanaged_legacy_keeps_its_java_records_and_existing_rule() -> None:
    state = controlled_state()
    task = state["tasks"][0]
    result = state["reviews"][task.task_id]
    assert isinstance(result, DiagnosisReviewResult)
    raw = result.effective_reviews.model_dump(mode="python", by_alias=True)
    raw["issues"] = [
        {
            "issueId": state["quality_issues"][task.task_id][0].issue_id,
            "reworkTaskId": None,
            "roundNumber": None,
            "processingRevision": None,
            "inspectionId": None,
            "review": None,
            "legacyReviews": [r.model_dump(by_alias=True) for r in result.history_reviews],
        }
    ]
    snapshot = EffectiveReworkReviews.model_validate(raw)
    state["reviews"][task.task_id] = DiagnosisReviewResult(
        task_id=task.task_id,
        reviews=project_java_reviews(snapshot),
        effective_reviews=snapshot,
        history_reviews=result.history_reviews,
    )
    assert evaluate_diagnosis_rules(state).blocking_stage is BlockingStage.REVIEW


async def test_cannot_construct_projection_from_history_instead_of_current_facts() -> None:
    state = controlled_state()
    result = state["reviews"][state["tasks"][0].task_id]
    assert isinstance(result, DiagnosisReviewResult)
    raw = result.model_dump(mode="python")
    raw["reviews"] = raw["history_reviews"]
    with pytest.raises(ValidationError):
        DiagnosisReviewResult.model_validate(raw)


@pytest.mark.parametrize("fault", [None, "missing-effective", "bad-version-shape", "trace"])
async def test_fixed_workflow_uses_new_registry_and_never_falls_back_after_effective_error(
    fault: str | None,
) -> None:
    calls: list[str] = []
    original = _golden_handler(calls)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/effective-reviews"):
            calls.append(request.url.path)
            if fault == "missing-effective":
                return httpx.Response(
                    404,
                    json={
                        "success": False,
                        "code": "RESOURCE_NOT_FOUND",
                        "message": "missing",
                        "data": None,
                        "trace_id": "trace-workflow-003",
                        "retryable": False,
                    },
                )
            fact = {
                "taskId": "TASK-003",
                "taskVersion": "0" if fault == "bad-version-shape" else 0,
                "issues": [
                    {
                        "issueId": "ISSUE-001",
                        "reworkTaskId": None,
                        "roundNumber": None,
                        "processingRevision": None,
                        "inspectionId": None,
                        "review": None,
                        "legacyReviews": [
                            {
                                "reviewId": "REVIEW-001",
                                "issueId": "ISSUE-001",
                                "status": "PENDING",
                                "reviewComment": None,
                            }
                        ],
                    }
                ],
            }
            return _success(fact, "trace-other" if fault == "trace" else "trace-workflow-003")
        return await original.handle_async_request(request)

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    recorder = MemoryStepRecorder()
    try:
        state = await OrderDiagnosisWorkflow(
            tool_registry=create_diagnosis_read_tool_registry(client),
            tool_context=_context(),
            step_recorder=recorder,
        ).ainvoke("ORDER-003")
        if fault is None:
            assert (
                state["diagnosis"] is not None
                and state["diagnosis"].blocking_stage is BlockingStage.QUALITY_REVIEW
            )
            assert isinstance(state["reviews"]["TASK-003"], DiagnosisReviewResult)
            assert {c.code for c in state["diagnosis"].root_causes} == {
                "OPEN_COORDINATE_SYSTEM_ISSUE",
                "REVIEW_PENDING",
            }
        else:
            assert state["diagnosis"] is None and state["errors"]
            assert not any("delivery-status" in path for path in calls)
        assert calls.count("/api/tasks/TASK-003/effective-reviews") == 1
    finally:
        await client.aclose()
