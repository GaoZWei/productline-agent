"""M3.5 实体来源、参数优先级和冲突检测测试。"""

import pytest
from pydantic import ValidationError

from app.routing.entity_merge import InvalidEntityCandidateError, merge_routing_entities
from app.schemas import (
    EntityExtractionResult,
    EntitySource,
    PageContext,
    PageType,
    RouterEntities,
    RoutingEntityName,
    SessionContext,
)


def _page_context(**updates: object) -> PageContext:
    values: dict[str, object] = {
        "current_system": "production-system",
        "current_page": PageType.TASK_DETAIL,
        "order_id": "ORDER-003",
        "task_id": "TASK-003",
        "product_type": "DOM",
        "satellite_type": "GF",
        "user_role": "REVIEWER",
    }
    values.update(updates)
    return PageContext.model_validate(values)


def _extraction(**entities: object) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=RouterEntities.model_validate(entities),
    )


def test_entity_extraction_result_is_strict_and_contains_only_typed_entities() -> None:
    extraction = _extraction(order_id="ORDER-003", product_type="DOM")

    assert extraction.entities.order_id == "ORDER-003"
    assert extraction.entities.product_type == "DOM"
    with pytest.raises(ValidationError):
        EntityExtractionResult.model_validate(
            {
                "entities": {"order_id": "TASK-003"},
                "model_reasoning": "不要保存模型推理",
            }
        )


def test_merge_marks_each_selected_entity_with_its_source() -> None:
    result = merge_routing_entities(
        extraction=_extraction(task_id="TASK-009"),
        page_context=_page_context(),
        session_context=SessionContext(
            confirmed_entities={"order_id": "ORDER-002"},
            candidate_entities={"batch_id": ["BATCH-001"]},
        ),
    )

    assert result.entities[RoutingEntityName.TASK_ID].value == "TASK-009"
    assert (
        result.entities[RoutingEntityName.TASK_ID].source
        is EntitySource.USER_MESSAGE
    )
    assert result.entities[RoutingEntityName.ORDER_ID].value == "ORDER-002"
    assert (
        result.entities[RoutingEntityName.ORDER_ID].source
        is EntitySource.CONFIRMED_SESSION
    )
    assert result.entities[RoutingEntityName.PRODUCT_TYPE].value == "DOM"
    assert (
        result.entities[RoutingEntityName.PRODUCT_TYPE].source
        is EntitySource.PAGE_CONTEXT
    )
    assert result.entities[RoutingEntityName.BATCH_ID].value == "BATCH-001"
    assert (
        result.entities[RoutingEntityName.BATCH_ID].source
        is EntitySource.SESSION_CANDIDATE
    )


def test_priority_is_user_then_confirmed_then_page_then_session_candidate() -> None:
    result = merge_routing_entities(
        extraction=_extraction(order_id="ORDER-004"),
        page_context=_page_context(order_id="ORDER-002"),
        session_context=SessionContext(
            current_order_id="ORDER-003",
            confirmed_entities={"order_id": "ORDER-003"},
            candidate_entities={"order_id": ["ORDER-001"]},
        ),
    )

    selected = result.entities[RoutingEntityName.ORDER_ID]
    assert selected.value == "ORDER-004"
    assert selected.source is EntitySource.USER_MESSAGE
    assert result.has_unresolved_conflicts is False
    assert len(result.conflicts) == 1
    assert result.conflicts[0].resolved_by_priority is True
    assert {candidate.value for candidate in result.conflicts[0].candidates} == {
        "ORDER-001",
        "ORDER-002",
        "ORDER-003",
        "ORDER-004",
    }


def test_confirmed_session_value_overrides_page_and_temporary_candidate() -> None:
    result = merge_routing_entities(
        extraction=_extraction(),
        page_context=_page_context(task_id="TASK-002"),
        session_context=SessionContext(
            current_order_id="ORDER-003",
            current_task_id="TASK-004",
            confirmed_entities={"task_id": "TASK-004"},
            candidate_entities={"task_id": ["TASK-001"]},
        ),
    )

    selected = result.entities[RoutingEntityName.TASK_ID]
    assert selected.value == "TASK-004"
    assert selected.source is EntitySource.CONFIRMED_SESSION


def test_page_value_overrides_previous_temporary_candidate() -> None:
    result = merge_routing_entities(
        extraction=_extraction(),
        page_context=_page_context(task_id="TASK-003"),
        session_context=SessionContext(
            candidate_entities={"task_id": ["TASK-001", "TASK-002"]},
        ),
    )

    selected = result.entities[RoutingEntityName.TASK_ID]
    assert selected.value == "TASK-003"
    assert selected.source is EntitySource.PAGE_CONTEXT
    assert result.conflicts[0].resolved_by_priority is True


def test_same_value_from_multiple_sources_uses_highest_source_without_conflict() -> None:
    result = merge_routing_entities(
        extraction=_extraction(order_id="ORDER-003"),
        page_context=_page_context(),
        session_context=SessionContext(
            current_order_id="ORDER-003",
            confirmed_entities={"order_id": "ORDER-003"},
            candidate_entities={"order_id": ["ORDER-003"]},
        ),
    )

    assert result.entities[RoutingEntityName.ORDER_ID].source is EntitySource.USER_MESSAGE
    assert result.conflicts == ()


def test_multiple_temporary_candidates_stay_unresolved_instead_of_being_guessed() -> None:
    result = merge_routing_entities(
        extraction=_extraction(),
        session_context=SessionContext(
            candidate_entities={"task_id": ["TASK-003", "TASK-004"]},
        ),
    )

    assert RoutingEntityName.TASK_ID not in result.entities
    assert result.unresolved_fields == (RoutingEntityName.TASK_ID,)
    assert result.has_unresolved_conflicts is True
    assert result.conflicts[0].resolved_by_priority is False
    assert result.to_router_entities().task_id is None


def test_conflicting_confirmed_values_are_not_overridden_by_lower_page_hint() -> None:
    result = merge_routing_entities(
        extraction=_extraction(),
        page_context=_page_context(order_id="ORDER-001"),
        session_context=SessionContext(
            current_order_id="ORDER-002",
            confirmed_entities={"order_id": "ORDER-003"},
        ),
    )

    assert RoutingEntityName.ORDER_ID not in result.entities
    assert result.unresolved_fields == (RoutingEntityName.ORDER_ID,)
    assert result.conflicts[0].resolved_by_priority is False


def test_invalid_supported_session_entity_fails_without_exposing_its_value() -> None:
    with pytest.raises(InvalidEntityCandidateError) as error:
        merge_routing_entities(
            extraction=_extraction(),
            session_context=SessionContext(
                confirmed_entities={"order_id": "TASK-003"},
            ),
        )

    assert error.value.field is RoutingEntityName.ORDER_ID
    assert error.value.source is EntitySource.CONFIRMED_SESSION
    assert "TASK-003" not in str(error.value)


def test_unrelated_session_context_keys_are_ignored() -> None:
    result = merge_routing_entities(
        extraction=_extraction(),
        session_context=SessionContext(
            confirmed_entities={"workflow_stage": "QUALITY_REVIEW"},
            candidate_entities={"operator_name": ["user-a"]},
        ),
    )

    assert result.entities == {}
    assert result.conflicts == ()
    assert result.unresolved_fields == ()
