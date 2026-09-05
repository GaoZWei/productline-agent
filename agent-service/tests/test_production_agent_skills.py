"""M7.6-E三个只读Skill的生产分发和观测边界测试。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, cast

import httpx
import pytest
from pydantic import AnyHttpUrl, BaseModel

from app.clients.business import BusinessHttpClient
from app.clients.model import (
    ChatMessage,
    ModelClientError,
    ModelErrorCode,
    StructuredModelResult,
)
from app.database import Database
from app.models import AgentStepType
from app.routing import BusinessSkill, Intent
from app.routing.decision import build_routing_decision
from app.routing.entity_merge import merge_routing_entities
from app.schemas.agent_messages import AgentResultKind, OrderStatusResult, OrderStatusSubject
from app.schemas.business import BusinessIdentity
from app.schemas.routing import (
    EntityExtractionResult,
    RouterEntities,
    RouterResult,
    RoutingDecision,
)
from app.schemas.run_observability import LLMStepObservation, RunTokenUsage
from app.services.agent_messages import AgentSkillExecutionError, AgentSkillRequest
from app.services.knowledge_index_capabilities import KnowledgeIndexCapabilityService
from app.services.production_agent_skills import ProductionAgentSkillDispatcher
from app.settings import Settings
from app.tools import create_read_tool_registry


class _CaptureStepRecorder:
    """记录Skill创建的Step顺序和终态。"""

    def __init__(self) -> None:
        self.started: list[tuple[int, AgentStepType, str]] = []
        self.succeeded: list[str] = []
        self.failed: list[tuple[str, str]] = []

    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None,
    ) -> None:
        del step_id, run_id, input_summary
        self.started.append((sequence_number, step_type, step_name))

    async def mark_succeeded(self, step_id: str, *, output_summary: str | None) -> None:
        del output_summary
        self.succeeded.append(step_id)

    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
    ) -> None:
        del output_summary
        self.failed.append((step_id, error_code))

    async def mark_llm_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
        observation: LLMStepObservation,
    ) -> None:
        del output_summary, observation
        self.succeeded.append(step_id)

    async def mark_llm_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
        observation: LLMStepObservation | None,
    ) -> None:
        del output_summary, observation
        self.failed.append((step_id, error_code))


class _SequenceStructuredClient:
    """按顺序返回已经过目标Schema校验的模型结果。"""

    model_name = "skill-test-model"

    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)
        self.call_count = 0

    async def complete_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        del messages
        self.call_count += 1
        output = output_schema.model_validate(next(self._outputs))
        return StructuredModelResult(
            output=output,
            model_name=self.model_name,
            token_usage=RunTokenUsage.from_counts(input_tokens=2, output_tokens=1),
            duration_ms=1,
            retry_count=0,
        )


class _FailingStructuredClient:
    """模拟Router之后的Action模型上游失败。"""

    model_name = "skill-test-model"

    async def complete_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        del messages, output_schema
        raise ModelClientError(
            code=ModelErrorCode.UPSTREAM_UNAVAILABLE,
            message="structured model upstream is unavailable",
            retryable=True,
        )


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://agent:agent-local-only@localhost:5432/remote_sensing_agent",
        business_service_url=AnyHttpUrl("http://business.test"),
    )


def _decision(intent: Intent, entities: RouterEntities) -> RoutingDecision:
    raw = RouterResult(
        intent=intent,
        confidence=0.95,
        entities=entities,
        missing_fields=[],
        need_clarification=False,
    )
    return build_routing_decision(
        raw_result=raw,
        merge_result=merge_routing_entities(extraction=EntityExtractionResult(entities=entities)),
    )


def _request(
    decision: RoutingDecision,
    recorder: _CaptureStepRecorder,
    *,
    message: str,
) -> AgentSkillRequest:
    return AgentSkillRequest(
        run_id="run-skill-test",
        session_id="session-skill-test",
        trace_id="trace-skill-test",
        message=message,
        identity=BusinessIdentity(user_id="reviewer-001", role="REVIEWER"),
        decision=decision,
        page_context=None,
        step_recorder=recorder,
        first_step_sequence=5,
        event_sink=None,
    )


def _success(request: httpx.Request, data: object) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        headers={"X-Trace-Id": "trace-skill-test"},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": data,
            "trace_id": "trace-skill-test",
            "retryable": False,
        },
    )


def _dispatcher(
    registry: object,
    model_client: object,
    *,
    embedding_generator: object | None = None,
) -> ProductionAgentSkillDispatcher:
    return ProductionAgentSkillDispatcher(
        database=cast(Database, object()),
        tool_registry=cast(Any, registry),
        model_client=cast(Any, model_client),
        knowledge_capability_service=cast(KnowledgeIndexCapabilityService, object()),
        embedding_generator=cast(Any, embedding_generator),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_status_skill_returns_only_java_order_and_task_facts() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/orders/ORDER-003":
            return _success(
                request,
                {"orderId": "ORDER-003", "productType": "DOM", "status": "BLOCKED"},
            )
        return _success(
            request,
            {
                "taskId": "TASK-003",
                "orderId": "ORDER-003",
                "status": "COMPLETED",
                "version": 0,
            },
        )

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    registry = create_read_tool_registry(client)
    dispatcher = _dispatcher(registry, _SequenceStructuredClient(()))
    order_recorder = _CaptureStepRecorder()
    task_recorder = _CaptureStepRecorder()
    try:
        order = await dispatcher.dispatch(
            BusinessSkill.ORDER_STATUS,
            _request(
                _decision(Intent.ORDER_QUERY, RouterEntities(order_id="ORDER-003")),
                order_recorder,
                message="查询 ORDER-003 状态",
            ),
        )
        task = await dispatcher.dispatch(
            BusinessSkill.ORDER_STATUS,
            _request(
                _decision(Intent.TASK_TRACKING, RouterEntities(task_id="TASK-003")),
                task_recorder,
                message="查询 TASK-003 状态",
            ),
        )
    finally:
        await client.aclose()

    assert order.result.kind is AgentResultKind.ORDER_STATUS
    assert isinstance(order.result, OrderStatusResult)
    assert order.result.subject is OrderStatusSubject.ORDER
    assert order.result.status == "BLOCKED"
    assert isinstance(task.result, OrderStatusResult)
    assert task.result.subject is OrderStatusSubject.TASK
    assert task.result.order_id == "ORDER-003"
    assert task.result.status == "COMPLETED"
    assert calls == ["/api/orders/ORDER-003", "/api/tasks/TASK-003"]
    assert order.tool_call_count == task.tool_call_count == 1
    assert order_recorder.started == [(5, AgentStepType.TOOL, "get_order_detail")]
    assert task_recorder.started == [(5, AgentStepType.TOOL, "get_task_detail")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dynamic_diagnosis_records_agent_llm_and_tool_steps() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _success(
            request,
            {"orderId": "ORDER-003", "productType": "DOM", "status": "BLOCKED"},
        )

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    registry = create_read_tool_registry(client)
    model = _SequenceStructuredClient(
        (
            {
                "action": "QUERY_ORDER",
                "reason": "先读取订单事实",
                "tool_name": "get_order_detail",
                "tool_arguments": {"order_id": "ORDER-003"},
            },
            {
                "action": "FINISH",
                "reason": "停止并由规则判断信息是否充分",
                "tool_name": None,
                "tool_arguments": {},
            },
        )
    )
    dispatcher = _dispatcher(registry, model)
    recorder = _CaptureStepRecorder()
    try:
        execution = await dispatcher.dispatch(
            BusinessSkill.DIAGNOSIS,
            _request(
                _decision(Intent.ORDER_DIAGNOSIS, RouterEntities(order_id="ORDER-003")),
                recorder,
                message="诊断 ORDER-003",
            ),
        )
    finally:
        await client.aclose()

    assert execution.result.kind is AgentResultKind.DIAGNOSIS
    assert execution.tool_call_count == 1
    assert execution.token_usage == RunTokenUsage.from_counts(input_tokens=4, output_tokens=2)
    assert execution.termination_reason == "INSUFFICIENT_INFORMATION"
    assert calls == ["/api/orders/ORDER-003"]
    assert recorder.started == [
        (5, AgentStepType.AGENT, "choose_diagnosis_action"),
        (6, AgentStepType.LLM, "choose_diagnosis_action_model"),
        (7, AgentStepType.TOOL, "get_order_detail"),
        (8, AgentStepType.AGENT, "choose_diagnosis_action"),
        (9, AgentStepType.LLM, "choose_diagnosis_action_model"),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dynamic_diagnosis_does_not_report_action_model_failure_as_success() -> None:
    client = BusinessHttpClient(
        _settings(),
        transport=httpx.MockTransport(
            lambda request: _success(
                request,
                {"orderId": "ORDER-003", "productType": "DOM", "status": "BLOCKED"},
            )
        ),
    )
    dispatcher = _dispatcher(create_read_tool_registry(client), _FailingStructuredClient())
    recorder = _CaptureStepRecorder()
    try:
        with pytest.raises(AgentSkillExecutionError) as caught:
            await dispatcher.dispatch(
                BusinessSkill.DIAGNOSIS,
                _request(
                    _decision(
                        Intent.ORDER_DIAGNOSIS,
                        RouterEntities(order_id="ORDER-003"),
                    ),
                    recorder,
                    message="诊断 ORDER-003",
                ),
            )
    finally:
        await client.aclose()

    assert caught.value.code == "MODEL_UPSTREAM_UNAVAILABLE"
    assert caught.value.retryable is True
    assert caught.value.error_step == "choose_diagnosis_action_model"
    assert recorder.started == [
        (5, AgentStepType.AGENT, "choose_diagnosis_action"),
        (6, AgentStepType.LLM, "choose_diagnosis_action_model"),
    ]
    assert recorder.failed == [("step-skill-skill-test-6", "MODEL_UPSTREAM_UNAVAILABLE")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_specification_skill_requires_query_embedding_configuration() -> None:
    recorder = _CaptureStepRecorder()
    dispatcher = _dispatcher(object(), _SequenceStructuredClient(()))

    with pytest.raises(AgentSkillExecutionError) as caught:
        await dispatcher.dispatch(
            BusinessSkill.SPECIFICATION,
            _request(
                _decision(Intent.SPEC_QA, RouterEntities()),
                recorder,
                message="坐标系问题应如何处理",
            ),
        )

    assert caught.value.code == "EMBEDDING_NOT_CONFIGURED"
    assert recorder.started == [(5, AgentStepType.RAG, "answer_specification")]
    assert recorder.failed[0][1] == "EMBEDDING_NOT_CONFIGURED"
