"""M3.3 意图目录、路由结果和UNKNOWN安全回退测试。"""

import pytest
from pydantic import ValidationError

from app.routing import (
    INTENT_DEFINITIONS,
    BusinessSkill,
    Intent,
    RoutingParameter,
    required_parameters_for,
    skill_for_intent,
)
from app.schemas import RouterResult, SessionContext


def test_intent_catalog_defines_every_first_batch_intent() -> None:
    assert tuple(Intent) == (
        Intent.ORDER_QUERY,
        Intent.ORDER_DIAGNOSIS,
        Intent.TASK_TRACKING,
        Intent.SPEC_QA,
        Intent.REVIEW_GENERATION,
        Intent.UNKNOWN,
    )
    assert set(INTENT_DEFINITIONS) == set(Intent)


@pytest.mark.parametrize(
    ("intent", "required", "skill"),
    [
        (Intent.ORDER_QUERY, (RoutingParameter.ORDER_ID,), BusinessSkill.ORDER_STATUS),
        (Intent.ORDER_DIAGNOSIS, (RoutingParameter.ORDER_ID,), BusinessSkill.DIAGNOSIS),
        (Intent.TASK_TRACKING, (RoutingParameter.TASK_ID,), BusinessSkill.ORDER_STATUS),
        (Intent.SPEC_QA, (), BusinessSkill.SPECIFICATION),
        (Intent.REVIEW_GENERATION, (RoutingParameter.TASK_ID,), BusinessSkill.REVIEW),
        (Intent.UNKNOWN, (), None),
    ],
)
def test_intent_definitions_expose_required_parameters_and_skill(
    intent: Intent,
    required: tuple[RoutingParameter, ...],
    skill: BusinessSkill | None,
) -> None:
    assert required_parameters_for(intent) == required
    assert skill_for_intent(intent) is skill


def test_router_result_accepts_complete_known_intent_from_json_values() -> None:
    result = RouterResult.model_validate(
        {
            "intent": "ORDER_DIAGNOSIS",
            "confidence": 0.93,
            "entities": {"order_id": "ORDER-003"},
            "missing_fields": [],
            "need_clarification": False,
        }
    )

    assert result.intent is Intent.ORDER_DIAGNOSIS
    assert result.can_dispatch is True


def test_missing_required_parameter_must_be_declared_and_clarified() -> None:
    result = RouterResult.model_validate(
        {
            "intent": "TASK_TRACKING",
            "confidence": 0.9,
            "entities": {},
            "missing_fields": ["task_id"],
            "need_clarification": True,
        }
    )

    assert result.missing_fields == [RoutingParameter.TASK_ID]
    assert result.can_dispatch is False
    with pytest.raises(ValidationError):
        RouterResult.model_validate(
            {
                "intent": "TASK_TRACKING",
                "confidence": 0.9,
                "entities": {},
                "missing_fields": [],
                "need_clarification": False,
            }
        )


def test_router_result_rejects_false_or_duplicate_missing_fields() -> None:
    base = {
        "intent": "ORDER_QUERY",
        "confidence": 0.8,
        "entities": {"order_id": "ORDER-003"},
        "need_clarification": True,
    }
    with pytest.raises(ValidationError):
        RouterResult.model_validate({**base, "missing_fields": ["order_id"]})
    with pytest.raises(ValidationError):
        RouterResult.model_validate(
            {
                **base,
                "entities": {},
                "missing_fields": ["order_id", "order_id"],
            }
        )


def test_unknown_never_maps_to_skill_or_dispatches() -> None:
    result = RouterResult.model_validate(
        {
            "intent": "UNKNOWN",
            "confidence": 0.2,
            "entities": {},
            "missing_fields": [],
            "need_clarification": True,
        }
    )

    assert skill_for_intent(result.intent) is None
    assert result.can_dispatch is False
    with pytest.raises(ValidationError):
        RouterResult.model_validate(
            {
                **result.model_dump(mode="json"),
                "need_clarification": False,
            }
        )


def test_router_contract_rejects_extra_fields_and_invalid_entity_ids() -> None:
    with pytest.raises(ValidationError):
        RouterResult.model_validate(
            {
                "intent": "ORDER_QUERY",
                "confidence": 0.9,
                "entities": {"order_id": "TASK-003", "raw_tool_result": {}},
                "missing_fields": [],
                "need_clarification": False,
            }
        )


def test_session_previous_intent_uses_stable_enum_contract() -> None:
    context = SessionContext(previous_intent=Intent.ORDER_DIAGNOSIS)

    assert context.previous_intent is Intent.ORDER_DIAGNOSIS
    with pytest.raises(ValidationError):
        SessionContext.model_validate({"previous_intent": "UNPLANNED_INTENT"})
