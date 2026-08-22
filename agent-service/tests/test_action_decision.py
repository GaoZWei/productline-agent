"""M5.2 动态诊断动作Schema、Prompt和安全回退测试。"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import cast
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.clients.business import BusinessHttpClient
from app.schemas import (
    ActionDecision,
    AgentAction,
    AgentObservation,
    InformationGap,
    OrderDiagnosisState,
)
from app.schemas.tools import OrderDetail, TaskDetail
from app.tools import ToolRegistry, create_read_tool_registry
from app.workflows.action_decision import (
    ActionDecider,
    InvalidActionDecisionOutputError,
    parse_action_decision,
)
from app.workflows.action_prompt import (
    ACTION_DECISION_PROMPT_VERSION,
    ACTION_DECISION_SYSTEM_PROMPT,
    ActionDecisionPrompt,
    action_decision_json_schema,
    build_action_decision_prompt,
)


class StubActionDecisionModel:
    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)
        self.prompts: list[ActionDecisionPrompt] = []

    async def generate(self, prompt: ActionDecisionPrompt) -> object:
        self.prompts.append(prompt)
        output = next(self._outputs)
        if isinstance(output, Exception):
            raise output
        return output


def _registry() -> ToolRegistry:
    client = cast(BusinessHttpClient, Mock(spec=BusinessHttpClient))
    return create_read_tool_registry(client)


def _state() -> OrderDiagnosisState:
    return {
        "run_id": "run-m5-2",
        "order_id": "ORDER-003",
        "page_context": None,
        "order": OrderDetail(
            order_id="ORDER-003",
            product_type="DOM",
            status="QUALITY_CHECKING",
        ),
        "tasks": [
            TaskDetail(
                task_id="TASK-003",
                order_id="ORDER-003",
                status="COMPLETED",
                version=0,
            )
        ],
        "progress": {},
        "quality_issues": {},
        "reviews": {},
        "delivery": None,
        "rule_decision": None,
        "diagnosis": None,
        "errors": [],
        "tool_history": [
            AgentObservation(
                action=AgentAction.QUERY_ORDER,
                call_fingerprint="a" * 64,
                success=True,
                summary="已获得订单基础事实。",
                has_new_information=True,
            )
        ],
        "information_gaps": [
            InformationGap(
                code="RELATED_TASKS_REQUIRED",
                description="尚未读取订单关联任务。",
            )
        ],
        "iteration_count": 1,
        "termination_reason": None,
    }


def _quality_decision() -> dict[str, object]:
    return {
        "action": "QUERY_QUALITY",
        "reason": "需要确认任务是否存在未关闭质检问题。",
        "tool_name": "get_quality_issues",
        "tool_arguments": {"task_id": "TASK-003"},
    }


@pytest.mark.unit
def test_action_decision_enforces_action_tool_and_argument_mapping() -> None:
    decision = ActionDecision.model_validate(_quality_decision())

    assert decision.action is AgentAction.QUERY_QUALITY
    assert decision.tool_name == "get_quality_issues"
    assert decision.tool_arguments == {"task_id": "TASK-003"}

    invalid_payloads = (
        {**_quality_decision(), "tool_name": "get_delivery_status"},
        {**_quality_decision(), "tool_arguments": {"order_id": "ORDER-003"}},
        {**_quality_decision(), "tool_arguments": {"task_id": "TASK-003", "extra": "x"}},
        {
            "action": "RETRIEVE_SPEC",
            "reason": "需要规范依据。",
            "tool_name": "get_quality_issues",
            "tool_arguments": {"question": "坐标系问题应如何处理"},
        },
        {
            "action": "FINISH",
            "reason": "信息已经充分。",
            "tool_name": "get_order_detail",
            "tool_arguments": {"order_id": "ORDER-003"},
        },
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            ActionDecision.model_validate(payload)


@pytest.mark.unit
def test_retrieve_spec_and_finish_have_distinct_non_business_boundaries() -> None:
    retrieve = ActionDecision(
        action=AgentAction.RETRIEVE_SPEC,
        reason="业务根因已经明确且需要补充规范依据。",
        tool_name="retrieve_spec",
        tool_arguments={"question": "坐标系质量问题应如何处理"},
    )
    finish = ActionDecision(
        action=AgentAction.FINISH,
        reason="现有事实足以生成诊断结果。",
        tool_name=None,
        tool_arguments={},
    )

    assert retrieve.tool_name == "retrieve_spec"
    assert finish.tool_name is None
    assert finish.tool_arguments == {}


@pytest.mark.unit
def test_action_prompt_injects_only_validated_facts_and_selectable_tools() -> None:
    prompt = build_action_decision_prompt(state=_state(), registry=_registry(), attempt=1)
    payload = json.loads(prompt.user_payload_json)

    assert prompt.version == ACTION_DECISION_PROMPT_VERSION == "action-decision-v1"
    assert prompt.response_schema == action_decision_json_schema()
    assert payload["target_order_id"] == "ORDER-003"
    assert payload["known_facts"]["order"] == {
        "order_id": "ORDER-003",
        "product_type": "DOM",
        "status": "QUALITY_CHECKING",
    }
    assert payload["tool_history"][0]["action"] == "QUERY_ORDER"
    assert payload["information_gaps"][0]["code"] == "RELATED_TASKS_REQUIRED"
    assert payload["iteration_count"] == 1
    assert "page_context" not in payload
    assert "diagnosis" not in payload["known_facts"]

    descriptors = {item["tool_name"]: item for item in payload["available_tools"]}
    assert set(descriptors) == {
        "get_order_detail",
        "get_related_tasks",
        "get_production_progress",
        "get_quality_issues",
        "get_review_result",
        "get_delivery_status",
        "retrieve_spec",
    }
    assert "get_task_detail" not in descriptors
    assert descriptors["get_quality_issues"]["description"] == (
        "根据任务 ID 查询全部质检问题及当前状态"
    )
    assert descriptors["get_quality_issues"]["input_schema"]["additionalProperties"] is False
    assert "只读动作" in ACTION_DECISION_SYSTEM_PROMPT
    assert "绝不能编造" in ACTION_DECISION_SYSTEM_PROMPT
    assert "业务事实" in ACTION_DECISION_SYSTEM_PROMPT


@pytest.mark.unit
def test_parser_accepts_object_and_plain_json_but_rejects_markdown() -> None:
    from_object = parse_action_decision(_quality_decision())
    from_json = parse_action_decision(json.dumps(_quality_decision()))

    assert from_object == from_json
    with pytest.raises(InvalidActionDecisionOutputError):
        parse_action_decision(f"```json\n{json.dumps(_quality_decision())}\n```")


@pytest.mark.asyncio
async def test_action_decider_returns_first_valid_available_action() -> None:
    model = StubActionDecisionModel([_quality_decision()])

    result = await ActionDecider(model=model, registry=_registry()).decide(_state())

    assert result.action is AgentAction.QUERY_QUALITY
    assert [prompt.attempt for prompt in model.prompts] == [1]


@pytest.mark.asyncio
async def test_action_decider_retries_invalid_output_with_same_facts() -> None:
    model = StubActionDecisionModel(
        [
            {**_quality_decision(), "tool_name": "get_delivery_status"},
            _quality_decision(),
        ]
    )

    result = await ActionDecider(model=model, registry=_registry()).decide(_state())

    assert result.action is AgentAction.QUERY_QUALITY
    assert [prompt.attempt for prompt in model.prompts] == [1, 2]
    assert "上一次响应不符合动作契约" in model.prompts[1].system_prompt
    assert model.prompts[0].user_payload_json == model.prompts[1].user_payload_json


@pytest.mark.asyncio
async def test_invalid_or_unavailable_action_falls_back_to_safe_finish() -> None:
    invalid_model = StubActionDecisionModel(
        [{"action": "DELETE_ORDER"}, {"action": "UNKNOWN_ACTION"}]
    )

    invalid_result = await ActionDecider(
        model=invalid_model,
        registry=_registry(),
    ).decide(_state())

    assert invalid_result.action is AgentAction.FINISH
    assert invalid_result.tool_name is None
    assert invalid_result.tool_arguments == {}

    unavailable_model = StubActionDecisionModel([_quality_decision(), _quality_decision()])
    unavailable_result = await ActionDecider(
        model=unavailable_model,
        registry=ToolRegistry(),
    ).decide(_state())

    assert unavailable_result.action is AgentAction.FINISH
    assert len(unavailable_model.prompts) == 2

    invented_task = {
        **_quality_decision(),
        "tool_arguments": {"task_id": "TASK-999"},
    }
    invented_model = StubActionDecisionModel([invented_task, invented_task])
    invented_result = await ActionDecider(
        model=invented_model,
        registry=_registry(),
    ).decide(_state())

    assert invented_result.action is AgentAction.FINISH
    assert len(invented_model.prompts) == 2


@pytest.mark.asyncio
async def test_model_exception_falls_back_without_leaking_provider_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = StubActionDecisionModel([RuntimeError("provider secret response")])

    with caplog.at_level(logging.ERROR, logger="agent-service.action-decider"):
        result = await ActionDecider(model=model, registry=_registry()).decide(_state())

    assert result.action is AgentAction.FINISH
    assert len(model.prompts) == 1
    assert "provider secret response" not in caplog.text
