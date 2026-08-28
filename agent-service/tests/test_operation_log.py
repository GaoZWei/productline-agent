"""M6.7操作日志摘要、用户差异和失败边界测试。"""

from datetime import UTC, datetime

import pytest

from app.models import ApprovalStatus, OperationType
from app.schemas import ReviewDraft
from app.schemas.write_tools import WriteReviewResultOutput
from app.services.operation_log import (
    OperationFailure,
    build_operation_log_detail,
)

pytestmark = pytest.mark.unit


def _draft(*, review_comment: str) -> ReviewDraft:
    return ReviewDraft.model_validate(
        {
            "task_id": "TASK-003",
            "issue_id": "ISSUE-001",
            "conclusion": "REWORK_REQUIRED",
            "problem_summary": "存在未关闭的坐标系质量问题",
            "review_comment": review_comment,
            "specification_references": [],
            "suggested_rework": {
                "required": True,
                "type": "COORDINATE_SYSTEM_FIX",
            },
        }
    )


def test_build_success_log_uses_effective_draft_and_field_diff() -> None:
    result = WriteReviewResultOutput(
        approval_id="approval-log-003",
        task_id="TASK-003",
        issue_id="ISSUE-001",
        review_id="REVIEW-LOG-003",
        status="REWORK_REQUIRED",
        review_comment="用户确认后的意见",
        task_version=8,
        java_trace_id="trace-java-log-003",
    )

    detail = build_operation_log_detail(
        approval_id="approval-log-003",
        operation_type=OperationType.SUBMIT_REVIEW,
        target_id="TASK-003",
        target_version=7,
        confirmed_by_user_id="reviewer-001",
        original_draft=_draft(review_comment="模型原始意见"),
        effective_draft=_draft(review_comment="用户确认后的意见"),
        outcome=ApprovalStatus.SUCCEEDED,
        result=result,
        failure=None,
        created_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )

    assert detail.operation_log_id.startswith("operation-log-")
    assert detail.before_summary.review_comment == "用户确认后的意见"
    assert detail.before_summary.task_version == 7
    assert detail.after_summary.outcome is ApprovalStatus.SUCCEEDED
    assert detail.after_summary.result is not None
    assert detail.after_summary.result.task_version == 8
    assert detail.java_trace_id == "trace-java-log-003"
    assert [change.field_path for change in detail.user_modification_diff] == [
        "review_comment"
    ]
    assert detail.user_modification_diff[0].before == "模型原始意见"
    assert detail.user_modification_diff[0].after == "用户确认后的意见"


def test_build_failed_log_has_controlled_error_and_no_java_trace() -> None:
    draft = _draft(review_comment="模型原始意见")

    detail = build_operation_log_detail(
        approval_id="approval-log-failed",
        operation_type=OperationType.SUBMIT_REVIEW,
        target_id="TASK-003",
        target_version=7,
        confirmed_by_user_id="reviewer-001",
        original_draft=draft,
        effective_draft=draft,
        outcome=ApprovalStatus.FAILED,
        result=None,
        failure=OperationFailure(
            code="UPSTREAM_UNAVAILABLE",
            status_code=502,
            retryable=True,
        ),
        created_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )

    assert detail.after_summary.outcome is ApprovalStatus.FAILED
    assert detail.after_summary.result is None
    assert detail.after_summary.failure is not None
    assert detail.after_summary.failure.code == "UPSTREAM_UNAVAILABLE"
    assert detail.java_trace_id is None
    assert detail.user_modification_diff == ()
