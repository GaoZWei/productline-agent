"""M3.6 置信度分级、澄清问题和补参恢复测试。"""

import pytest

from app.routing import Intent, RoutingParameter
from app.routing.decision import (
    InvalidClarificationSelectionError,
    build_routing_decision,
    confidence_level_for,
    confirm_routing_intent,
    resume_routing_after_selection,
)
from app.routing.entity_merge import merge_routing_entities
from app.schemas import (
    ClarificationReason,
    ConfidenceLevel,
    EntityExtractionResult,
    EntityMergeResult,
    EntitySelection,
    EntitySource,
    PageContext,
    PageType,
    RouterEntities,
    RouterResult,
    RoutingDecisionStatus,
    RoutingEntityName,
    SessionContext,
)


def _router_result(
    *,
    intent: Intent = Intent.ORDER_DIAGNOSIS,
    confidence: float = 0.9,
    entities: RouterEntities | None = None,
    need_clarification: bool | None = None,
) -> RouterResult:
    selected_entities = entities or RouterEntities()
    missing = [
        parameter
        for parameter in (
            RoutingParameter.ORDER_ID
            if intent in {Intent.ORDER_QUERY, Intent.ORDER_DIAGNOSIS}
            else RoutingParameter.TASK_ID
            if intent in {Intent.TASK_TRACKING, Intent.REVIEW_GENERATION}
            else None,
        )
        if parameter is not None and not selected_entities.contains(parameter)
    ]
    clarification = (
        bool(missing) or intent is Intent.UNKNOWN
        if need_clarification is None
        else need_clarification
    )
    return RouterResult(
        intent=intent,
        confidence=confidence,
        entities=selected_entities,
        missing_fields=missing,
        need_clarification=clarification,
    )


def _merge(
    result: RouterResult,
    *,
    page_context: PageContext | None = None,
    session_context: SessionContext | None = None,
) -> EntityMergeResult:
    return merge_routing_entities(
        extraction=EntityExtractionResult(entities=result.entities),
        page_context=page_context,
        session_context=session_context,
    )


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1.0, ConfidenceLevel.HIGH),
        (0.85, ConfidenceLevel.HIGH),
        (0.849999, ConfidenceLevel.MEDIUM),
        (0.60, ConfidenceLevel.MEDIUM),
        (0.599999, ConfidenceLevel.LOW),
        (0.0, ConfidenceLevel.LOW),
    ],
)
def test_confidence_level_boundaries(
    confidence: float,
    expected: ConfidenceLevel,
) -> None:
    assert confidence_level_for(confidence) is expected


def test_high_confidence_complete_route_is_ready() -> None:
    raw = _router_result(entities=RouterEntities(order_id="ORDER-003"))

    decision = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    assert decision.status is RoutingDecisionStatus.READY
    assert decision.confidence_level is ConfidenceLevel.HIGH
    assert decision.missing_fields == ()
    assert decision.clarification is None
    assert decision.can_dispatch is True


def test_page_context_can_fill_model_missing_parameter_before_decision() -> None:
    raw = _router_result()
    page = PageContext(
        current_system="production-system",
        current_page=PageType.ORDER_DETAIL,
        order_id="ORDER-003",
        user_role="REVIEWER",
    )

    decision = build_routing_decision(
        raw_result=raw,
        merge_result=_merge(raw, page_context=page),
    )

    assert decision.status is RoutingDecisionStatus.READY
    assert decision.entities.entities[RoutingEntityName.ORDER_ID].source is (
        EntitySource.PAGE_CONTEXT
    )
    assert decision.missing_fields == ()


def test_medium_confidence_requires_confirmation_then_resumes_same_intent() -> None:
    raw = _router_result(
        confidence=0.7,
        entities=RouterEntities(order_id="ORDER-003"),
    )
    pending = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    assert pending.status is RoutingDecisionStatus.NEEDS_CLARIFICATION
    assert pending.clarification is not None
    assert pending.clarification.reason is ClarificationReason.CONFIRM_INTENT
    assert "订单诊断" in pending.clarification.question

    resumed = confirm_routing_intent(pending)

    assert resumed.intent is Intent.ORDER_DIAGNOSIS
    assert resumed.intent_confirmed is True
    assert resumed.status is RoutingDecisionStatus.READY
    assert resumed.can_dispatch is True


def test_low_confidence_requests_rephrasing_and_cannot_dispatch() -> None:
    raw = _router_result(
        confidence=0.4,
        entities=RouterEntities(order_id="ORDER-003"),
    )

    decision = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    assert decision.clarification is not None
    assert decision.clarification.reason is ClarificationReason.LOW_CONFIDENCE
    assert decision.can_dispatch is False


def test_missing_parameter_generates_deterministic_question() -> None:
    raw = _router_result()

    decision = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    assert decision.missing_fields == (RoutingParameter.ORDER_ID,)
    assert decision.clarification is not None
    assert decision.clarification.reason is ClarificationReason.MISSING_PARAMETER
    assert decision.clarification.field is RoutingEntityName.ORDER_ID
    assert decision.clarification.options == ()
    assert decision.clarification.question == "请提供要处理的订单编号。"


def test_unresolved_task_candidates_generate_selection_options() -> None:
    raw = _router_result(intent=Intent.TASK_TRACKING)
    merged = _merge(
        raw,
        session_context=SessionContext(
            candidate_entities={"task_id": ["TASK-003", "TASK-004"]},
        ),
    )

    decision = build_routing_decision(raw_result=raw, merge_result=merged)

    assert decision.clarification is not None
    assert decision.clarification.reason is ClarificationReason.ENTITY_CONFLICT
    assert decision.clarification.field is RoutingEntityName.TASK_ID
    assert decision.clarification.question == "检测到多个任务候选, 请选择一个任务。"
    assert tuple(option.value for option in decision.clarification.options) == (
        "TASK-003",
        "TASK-004",
    )


def test_user_candidate_selection_resumes_pending_route_without_model_call() -> None:
    raw = _router_result(intent=Intent.TASK_TRACKING)
    pending = build_routing_decision(
        raw_result=raw,
        merge_result=_merge(
            raw,
            session_context=SessionContext(
                candidate_entities={"task_id": ["TASK-003", "TASK-004"]},
            ),
        ),
    )

    resumed = resume_routing_after_selection(
        pending,
        EntitySelection(field=RoutingEntityName.TASK_ID, value="TASK-004"),
    )

    selected = resumed.entities.entities[RoutingEntityName.TASK_ID]
    assert selected.value == "TASK-004"
    assert selected.source is EntitySource.USER_MESSAGE
    assert resumed.missing_fields == ()
    assert resumed.status is RoutingDecisionStatus.READY
    assert resumed.can_dispatch is True


def test_user_can_supply_a_previously_missing_parameter_and_resume() -> None:
    raw = _router_result()
    pending = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    resumed = resume_routing_after_selection(
        pending,
        EntitySelection(field=RoutingEntityName.ORDER_ID, value="ORDER-004"),
    )

    assert resumed.entities.to_router_entities().order_id == "ORDER-004"
    assert resumed.intent is Intent.ORDER_DIAGNOSIS
    assert resumed.status is RoutingDecisionStatus.READY


def test_selection_must_match_offered_field_and_candidate_values() -> None:
    raw = _router_result(intent=Intent.TASK_TRACKING)
    pending = build_routing_decision(
        raw_result=raw,
        merge_result=_merge(
            raw,
            session_context=SessionContext(
                candidate_entities={"task_id": ["TASK-003", "TASK-004"]},
            ),
        ),
    )

    with pytest.raises(InvalidClarificationSelectionError):
        resume_routing_after_selection(
            pending,
            EntitySelection(field=RoutingEntityName.TASK_ID, value="TASK-009"),
        )
    with pytest.raises(InvalidClarificationSelectionError):
        resume_routing_after_selection(
            pending,
            EntitySelection(field=RoutingEntityName.ORDER_ID, value="ORDER-003"),
        )


def test_unknown_intent_always_requests_intent_clarification() -> None:
    raw = _router_result(intent=Intent.UNKNOWN, confidence=0.0)

    decision = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    assert decision.status is RoutingDecisionStatus.NEEDS_CLARIFICATION
    assert decision.clarification is not None
    assert decision.clarification.reason is ClarificationReason.UNKNOWN_INTENT
    assert decision.can_dispatch is False


def test_high_confidence_model_requested_clarification_is_preserved() -> None:
    raw = _router_result(
        entities=RouterEntities(order_id="ORDER-003"),
        need_clarification=True,
    )

    decision = build_routing_decision(raw_result=raw, merge_result=_merge(raw))

    assert decision.clarification is not None
    assert decision.clarification.reason is ClarificationReason.MODEL_REQUEST
    assert decision.can_dispatch is False
