"""M3.2 会话上下文Schema、页面合并和继承测试。"""

import pytest
from pydantic import ValidationError

from app.schemas import PageContext, PageType, PendingActionContext, SessionContext
from app.schemas.session import context_from_page, page_context_from_session


def _quality_page() -> PageContext:
    return PageContext(
        current_system="production-system",
        current_page=PageType.QUALITY_ISSUE,
        order_id="ORDER-003",
        task_id="TASK-003",
        issue_id="ISSUE-001",
        user_role="REVIEWER",
    )


def test_session_context_carries_only_bounded_business_references() -> None:
    context = SessionContext(
        current_order_id="ORDER-003",
        current_task_id="TASK-003",
        previous_intent="ORDER_DIAGNOSIS",
        confirmed_entities={"order_id": "ORDER-003", "task_id": "TASK-003"},
        candidate_entities={"task_id": ["TASK-003", "TASK-004"]},
        recent_diagnosis_run_id="run-order-003",
        pending_action=PendingActionContext(
            action_type="CREATE_COORDINATE_SYSTEM_REWORK",
            parameters={"task_id": "TASK-003"},
            source_run_id="run-order-003",
        ),
    )

    assert context.current_task_id == "TASK-003"
    assert context.pending_action is not None
    with pytest.raises(ValidationError):
        SessionContext(current_task_id="TASK-003")
    with pytest.raises(ValidationError):
        SessionContext.model_validate({**context.model_dump(), "raw_tool_result": {}})


def test_page_context_merge_replaces_stale_child_references() -> None:
    quality_context = context_from_page(_quality_page())
    order_page = _quality_page().model_copy(
        update={
            "current_page": PageType.ORDER_DETAIL,
            "task_id": None,
            "issue_id": None,
        }
    )

    merged = context_from_page(order_page, base=quality_context)

    assert merged.current_order_id == "ORDER-003"
    assert merged.current_task_id is None
    assert merged.confirmed_entities == {"order_id": "ORDER-003"}


def test_session_task_is_restored_as_page_hint_for_java_revalidation() -> None:
    context = context_from_page(_quality_page())

    inherited = page_context_from_session(context, user_role="REVIEWER")

    assert inherited.current_page is PageType.TASK_DETAIL
    assert inherited.order_id == "ORDER-003"
    assert inherited.task_id == "TASK-003"
    assert inherited.issue_id is None
