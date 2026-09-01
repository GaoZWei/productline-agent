"""M7.6-B五个既有模型Protocol的公共Client适配与原门禁测试。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any, cast
from unittest.mock import Mock

import httpx
import pytest
from pydantic import AnyHttpUrl, BaseModel, SecretStr

from app.clients.business import BusinessHttpClient
from app.clients.model import (
    ChatMessage,
    OpenAICompatibleChatClient,
    StructuredModelResult,
)
from app.knowledge import (
    RerankCandidate,
    RerankRequest,
    RerankResponse,
    RerankValidationError,
    RetrievalResult,
    rerank_retrieval_results,
)
from app.model_adapters import (
    ModelProtocolAdapterError,
    StructuredActionDecisionModel,
    StructuredIntentRoutingModel,
    StructuredReranker,
    StructuredReviewDraftGenerationModel,
    StructuredSpecificationAnswerModel,
)
from app.routing.prompt import build_routing_prompt
from app.schemas import (
    ActionDecision,
    AgentAction,
    AgentObservation,
    Citation,
    DiagnosisResult,
    InformationGap,
    OrderDiagnosisState,
    RouterResult,
    RunTokenUsage,
    SpecificationAnswerDraft,
)
from app.schemas.approval import ReviewDraft
from app.schemas.tools import OrderDetail, QualityIssue, TaskDetail
from app.services import IntentRouter
from app.settings import Settings
from app.tools import ToolRegistry, create_read_tool_registry
from app.workflows.action_decision import ActionDecider
from app.workflows.action_prompt import ActionDecisionPrompt, action_decision_json_schema
from app.workflows.review_draft import (
    InvalidReviewDraftOutputError,
    ReviewDraftGenerationModelRequest,
    ReviewDraftGenerationWorkflow,
)
from app.workflows.specification_qa import (
    SpecificationAnswerRequest,
    SpecificationQaValidationError,
    _select_citations,
)


class _CaptureStructuredClient:
    def __init__(self, outputs: Sequence[object]) -> None:
        self._outputs = iter(outputs)
        self.calls: list[tuple[tuple[ChatMessage, ...], type[BaseModel]]] = []

    async def complete_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        self.calls.append((tuple(messages), output_schema))
        output = output_schema.model_validate(next(self._outputs))
        return StructuredModelResult(
            output=output,
            model_name="adapter-test-model",
            token_usage=RunTokenUsage.from_counts(input_tokens=10, output_tokens=5),
            duration_ms=12,
            retry_count=0,
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


def _task() -> TaskDetail:
    return TaskDetail.model_validate(
        {
            "taskId": "TASK-003",
            "orderId": "ORDER-003",
            "status": "COMPLETED",
            "version": 7,
        }
    )


def _issue() -> QualityIssue:
    return QualityIssue.model_validate(
        {
            "issueId": "ISSUE-001",
            "taskId": "TASK-003",
            "issueType": "COORDINATE_SYSTEM",
            "status": "OPEN",
            "description": "成果坐标参考系与任务要求不一致",
        }
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
                        "description": "存在未关闭的坐标系质量问题",
                    }
                ],
                "evidence": [
                    {
                        "source_type": "TOOL",
                        "tool_name": "get_quality_issues",
                        "field_path": "issues[0].status",
                        "value": "OPEN",
                        "description": "ISSUE-001状态为OPEN",
                    }
                ],
                "suggestions": [
                    {
                        "action_type": "CREATE_COORDINATE_SYSTEM_REWORK",
                        "description": "创建坐标系返工任务",
                    }
                ],
                "confidence": 1.0,
            },
            ensure_ascii=False,
        )
    )


def _review_draft(*, task_id: str = "TASK-003", citation: Citation | None = None) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "issue_id": "ISSUE-001",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": "完成坐标系统处理后重新提交复核",
        "specification_references": [(citation or _citation()).model_dump(mode="json")],
        "suggested_rework": {
            "required": True,
            "type": "COORDINATE_SYSTEM_FIX",
        },
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_adapter_preserves_prompt_and_existing_entity_evidence_gate() -> None:
    invented = {
        "intent": "ORDER_DIAGNOSIS",
        "confidence": 0.95,
        "entities": {"order_id": "ORDER-999"},
        "missing_fields": [],
        "need_clarification": False,
    }
    client = _CaptureStructuredClient((invented, invented))
    adapter = StructuredIntentRoutingModel(client)

    result = await IntentRouter(adapter).route(user_message="诊断ORDER-003")

    assert result.intent.value == "UNKNOWN"
    assert result.entities.order_id is None
    assert len(client.calls) == 2
    messages, output_schema = client.calls[0]
    assert output_schema is RouterResult
    assert messages[0].role == "system"
    assert json.loads(messages[1].content)["user_message"] == "诊断ORDER-003"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_adapter_rejects_prompt_schema_drift_before_model_call() -> None:
    client = _CaptureStructuredClient(())
    adapter = StructuredIntentRoutingModel(client)
    prompt = build_routing_prompt(
        user_message="诊断ORDER-003",
        page_context=None,
        session_context=None,
        attempt=1,
    )

    with pytest.raises(ModelProtocolAdapterError, match="RouterResult"):
        await adapter.generate(replace(prompt, response_schema={"type": "object"}))

    assert client.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_action_adapter_keeps_registered_readonly_and_resource_gate() -> None:
    invented = {
        "action": "QUERY_QUALITY",
        "reason": "读取另一个任务的问题",
        "tool_name": "get_quality_issues",
        "tool_arguments": {"task_id": "TASK-999"},
    }
    client = _CaptureStructuredClient((invented, invented))
    adapter = StructuredActionDecisionModel(client)

    result = await ActionDecider(model=adapter, registry=_registry()).decide(_state())

    assert result.action is AgentAction.FINISH
    assert result.tool_name is None
    assert len(client.calls) == 2
    assert all(call[1] is ActionDecision for call in client.calls)
    assert json.loads(client.calls[0][0][1].content)["target_order_id"] == "ORDER-003"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_action_adapter_rejects_prompt_schema_drift() -> None:
    client = _CaptureStructuredClient(())
    adapter = StructuredActionDecisionModel(client)
    prompt = ActionDecisionPrompt(
        version="action-decision-v1",
        attempt=1,
        system_prompt="system",
        user_payload_json="{}",
        response_schema=action_decision_json_schema(),
    )

    with pytest.raises(ModelProtocolAdapterError, match="ActionDecision"):
        await adapter.generate(replace(prompt, response_schema={}))

    assert client.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_specification_adapter_only_returns_existing_citation_ids() -> None:
    citation = _citation()
    client = _CaptureStructuredClient(
        ({"answer": "应先完成坐标系统返工。", "citation_ids": [citation.chunk_id]},)
    )
    adapter = StructuredSpecificationAnswerModel(client)

    raw = await adapter.generate(
        SpecificationAnswerRequest(
            question="坐标系问题如何处理?",
            rewritten_query="坐标系问题如何处理?",
            citations=(citation,),
        )
    )

    assert isinstance(raw, SpecificationAnswerDraft)
    assert raw.citation_ids == (citation.chunk_id,)
    messages, output_schema = client.calls[0]
    assert output_schema.__name__ == "SpecificationAnswerDraft"
    payload = json.loads(messages[1].content)
    assert [item["chunk_id"] for item in payload["citations"]] == [citation.chunk_id]

    unknown_client = _CaptureStructuredClient(
        ({"answer": "编造回答", "citation_ids": ["CHUNK-UNKNOWN"]},)
    )
    unknown = await StructuredSpecificationAnswerModel(unknown_client).generate(
        SpecificationAnswerRequest(
            question="坐标系问题如何处理?",
            rewritten_query="坐标系问题如何处理?",
            citations=(citation,),
        )
    )
    assert isinstance(unknown, SpecificationAnswerDraft)
    with pytest.raises(SpecificationQaValidationError, match="unknown citation"):
        _select_citations((citation,), unknown.citation_ids)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rerank_adapter_passes_every_candidate_and_component_rejects_omission() -> None:
    request = RerankRequest(
        query="坐标系返工",
        candidates=(
            _rerank_candidate("CHUNK-A", "坐标系处理规范"),
            _rerank_candidate("CHUNK-B", "交付规范"),
        ),
    )
    complete_client = _CaptureStructuredClient(
        (
            {
                "scores": [
                    {"candidate_id": "CHUNK-A", "score": 0.95},
                    {"candidate_id": "CHUNK-B", "score": 0.20},
                ]
            },
        )
    )

    response = await StructuredReranker(complete_client).rerank(request)

    assert isinstance(response, RerankResponse)
    assert [item.candidate_id for item in response.scores] == ["CHUNK-A", "CHUNK-B"]
    payload = json.loads(complete_client.calls[0][0][1].content)
    assert [item["candidate_id"] for item in payload["candidates"]] == [
        "CHUNK-A",
        "CHUNK-B",
    ]

    incomplete_client = _CaptureStructuredClient(
        ({"scores": [{"candidate_id": "CHUNK-A", "score": 0.95}]},)
    )
    with pytest.raises(RerankValidationError, match="does not cover every candidate"):
        await rerank_retrieval_results(
            "坐标系返工",
            (_retrieval("CHUNK-A"), _retrieval("CHUNK-B")),
            StructuredReranker(incomplete_client),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_review_adapter_has_no_tool_access_and_component_rejects_changed_target() -> None:
    citation = _citation()
    request = ReviewDraftGenerationModelRequest(
        diagnosis=_diagnosis(),
        task=_task(),
        quality_issues=(_issue(),),
        specification_answer="坐标系统问题关闭后重新提交复核。",
        citations=(citation,),
    )
    client = _CaptureStructuredClient((_review_draft(task_id="TASK-999"),))
    adapter = StructuredReviewDraftGenerationModel(client)

    raw = await adapter.generate(request)

    assert isinstance(raw, ReviewDraft)
    messages, output_schema = client.calls[0]
    assert output_schema is ReviewDraft
    payload = json.loads(messages[1].content)
    assert set(payload) == {
        "diagnosis",
        "task",
        "quality_issues",
        "specification_answer",
        "citations",
    }
    assert "tool_registry" not in payload
    assert "approval_store" not in payload
    with pytest.raises(InvalidReviewDraftOutputError, match="changed the target task"):
        ReviewDraftGenerationWorkflow._validate_draft(
            raw,
            task=request.task,
            issues=list(request.quality_issues),
            citations=request.citations,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_five_adapters_call_public_client_against_local_http_stub() -> None:
    citation = _citation()
    cases: tuple[
        tuple[
            str,
            dict[str, Any],
            Callable[[OpenAICompatibleChatClient], Awaitable[object]],
        ],
        ...,
    ] = (
        (
            "RouterResult",
            {
                "intent": "ORDER_DIAGNOSIS",
                "confidence": 0.95,
                "entities": {"order_id": "ORDER-003"},
                "missing_fields": [],
                "need_clarification": False,
            },
            lambda client: StructuredIntentRoutingModel(client).generate(
                build_routing_prompt(
                    user_message="诊断ORDER-003",
                    page_context=None,
                    session_context=None,
                    attempt=1,
                )
            ),
        ),
        (
            "ActionDecision",
            {
                "action": "FINISH",
                "reason": "已获得足够事实。",
                "tool_name": None,
                "tool_arguments": {},
            },
            lambda client: StructuredActionDecisionModel(client).generate(
                ActionDecisionPrompt(
                    version="action-decision-v1",
                    attempt=1,
                    system_prompt="action-system",
                    user_payload_json="{}",
                    response_schema=action_decision_json_schema(),
                )
            ),
        ),
        (
            "SpecificationAnswerDraft",
            {
                "answer": "坐标系统问题关闭后重新提交复核。",
                "citation_ids": [citation.chunk_id],
            },
            lambda client: StructuredSpecificationAnswerModel(client).generate(
                SpecificationAnswerRequest(
                    question="坐标系问题如何处理?",
                    rewritten_query="坐标系问题如何处理?",
                    citations=(citation,),
                )
            ),
        ),
        (
            "RerankResponse",
            {"scores": [{"candidate_id": "CHUNK-A", "score": 0.95}]},
            lambda client: StructuredReranker(client).rerank(
                RerankRequest(
                    query="坐标系返工",
                    candidates=(_rerank_candidate("CHUNK-A", "坐标系规范"),),
                )
            ),
        ),
        (
            "ReviewDraft",
            _review_draft(),
            lambda client: StructuredReviewDraftGenerationModel(client).generate(
                ReviewDraftGenerationModelRequest(
                    diagnosis=_diagnosis(),
                    task=_task(),
                    quality_issues=(_issue(),),
                    specification_answer="坐标系统问题关闭后重新提交复核。",
                    citations=(citation,),
                )
            ),
        ),
    )

    for expected_schema_name, output, invoke in cases:
        request_bodies: list[dict[str, Any]] = []

        def handler(
            request: httpx.Request,
            request_bodies: list[dict[str, Any]] = request_bodies,
            output: dict[str, Any] = output,
        ) -> httpx.Response:
            request_bodies.append(json.loads(request.content))
            return _chat_response(output)

        client = OpenAICompatibleChatClient(
            _model_settings(),
            transport=httpx.MockTransport(handler),
        )
        try:
            result = await invoke(client)
        finally:
            await client.aclose()

        assert isinstance(result, BaseModel)
        assert len(request_bodies) == 1
        assert request_bodies[0]["response_format"]["json_schema"]["name"] == expected_schema_name


def _registry() -> ToolRegistry:
    client = cast(BusinessHttpClient, Mock(spec=BusinessHttpClient))
    return create_read_tool_registry(client)


def _state() -> OrderDiagnosisState:
    return {
        "run_id": "run-adapter-action",
        "order_id": "ORDER-003",
        "page_context": None,
        "order": OrderDetail(
            order_id="ORDER-003",
            product_type="DOM",
            status="QUALITY_CHECKING",
        ),
        "tasks": [_task()],
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
                summary="已获得订单事实。",
                has_new_information=True,
            )
        ],
        "information_gaps": [
            InformationGap(
                code="QUALITY_ISSUES_REQUIRED",
                description="尚未读取质检问题。",
            )
        ],
        "iteration_count": 1,
        "termination_reason": None,
    }


def _rerank_candidate(candidate_id: str, content: str) -> RerankCandidate:
    return RerankCandidate(
        candidate_id=candidate_id,
        chunk_ids=(candidate_id,),
        document_id=f"DOC-{candidate_id}",
        section_path=("质量复核",),
        content=content,
        rrf_score=0.03,
    )


def _retrieval(chunk_id: str) -> RetrievalResult:
    return RetrievalResult(
        chunk_ids=(chunk_id,),
        document_id=f"DOC-{chunk_id}",
        document_name="测试规范",
        document_version="1.0",
        chunk_indexes=(0,),
        section_path=("质量复核",),
        content="测试规范内容",
        content_hashes=(f"hash-{chunk_id}",),
        keyword_score=1.0,
        vector_score=0.9,
        keyword_rank=1,
        vector_rank=1,
        rrf_score=0.03,
    )


def _model_settings() -> Settings:
    return Settings(
        environment="test",
        model_name="adapter-test-model",
        model_base_url=AnyHttpUrl("https://models.example.test/v1"),
        model_api_key=SecretStr("adapter-test-secret"),
        model_max_retries=0,
    )


def _chat_response(output: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-adapter-test",
            "object": "chat.completion",
            "created": 1_788_220_800,
            "model": "adapter-test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(output, ensure_ascii=False),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        },
    )
