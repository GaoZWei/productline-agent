"""M7.6-D统一消息Schema、API和严格错误边界测试。"""

from __future__ import annotations

from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api import agent_messages as agent_messages_api
from app.main import create_app
from app.routing import Intent
from app.schemas.agent_messages import (
    AgentMessageRequest,
    AgentResultKind,
    ClarificationAgentResult,
    ClarificationChoice,
    OrderStatusResult,
    OrderStatusSubject,
)
from app.schemas.routing import (
    ClarificationReason,
    ClarificationRequest,
    EntitySelection,
    RoutingEntityName,
)
from app.services.agent_messages import (
    AgentMessageExecution,
    AgentMessageExecutionError,
    AgentMessageService,
)
from app.settings import Settings


def _headers(trace_id: str = "trace-agent-message") -> dict[str, str]:
    return {
        "X-Trace-Id": trace_id,
        "X-User-Id": "reviewer-001",
        "X-User-Role": "REVIEWER",
    }


@pytest.mark.unit
def test_message_request_requires_bounded_message_and_session_bound_clarification() -> None:
    request = AgentMessageRequest(message="查询 ORDER-003 的状态")

    assert request.session_id is None
    with pytest.raises(ValidationError):
        AgentMessageRequest.model_validate({"message": " "})
    with pytest.raises(ValidationError):
        AgentMessageRequest.model_validate(
            {
                "message": "选择这个订单",
                "clarification": {
                    "source_run_id": "run-source",
                    "selection": {"field": "order_id", "value": "ORDER-003"},
                },
            }
        )
    with pytest.raises(ValidationError):
        ClarificationChoice(
            source_run_id="run-source",
            selection=EntitySelection(
                field=RoutingEntityName.ORDER_ID,
                value="ORDER-003",
            ),
            confirm_intent=True,
        )


@pytest.mark.unit
def test_result_envelopes_use_stable_kind_and_subject_identifier_gate() -> None:
    result = OrderStatusResult(
        subject=OrderStatusSubject.ORDER,
        order_id="ORDER-003",
        status="QUALITY_CHECKING",
        summary="订单处于质量检查阶段。",
    )
    clarification = ClarificationAgentResult(
        intent=Intent.ORDER_QUERY,
        confidence=0.95,
        clarification=ClarificationRequest(
            reason=ClarificationReason.MISSING_PARAMETER,
            question="请提供要处理的订单编号。",
            field=RoutingEntityName.ORDER_ID,
        ),
    )

    assert result.kind is AgentResultKind.ORDER_STATUS
    assert clarification.kind is AgentResultKind.CLARIFICATION
    with pytest.raises(ValidationError):
        OrderStatusResult(
            subject=OrderStatusSubject.TASK,
            order_id="ORDER-003",
            status="COMPLETED",
            summary="任务完成。",
        )


class _FakeMessageService:
    def __init__(self, outcome: AgentMessageExecution | AgentMessageExecutionError) -> None:
        self._outcome = outcome

    async def execute(self, *_: object, **__: object) -> AgentMessageExecution:
        if isinstance(self._outcome, AgentMessageExecutionError):
            raise self._outcome
        return self._outcome


@pytest.mark.integration
def test_unified_agent_api_is_registered_with_five_result_contracts() -> None:
    openapi = create_app(Settings(environment="test")).openapi()

    assert "/api/agent/messages" in openapi["paths"]
    assert "/api/agent/capabilities" in openapi["paths"]
    schemas = openapi["components"]["schemas"]
    assert "AgentMessageRequest" in schemas
    assert "AgentMessageResponse" in schemas
    assert "ClarificationAgentResult" in schemas
    assert "ApprovalAgentResult" in schemas


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unified_agent_api_returns_result_and_stable_model_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(Settings(environment="test"))
    success = AgentMessageExecution(
        run_id="run-agent-success",
        session_id="session-agent-success",
        result=OrderStatusResult(
            subject=OrderStatusSubject.ORDER,
            order_id="ORDER-003",
            status="QUALITY_CHECKING",
            summary="订单处于质量检查阶段。",
        ),
    )
    service = _FakeMessageService(success)
    monkeypatch.setattr(
        agent_messages_api,
        "_message_service",
        lambda _request, _publisher: cast(AgentMessageService, service),
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        missing_identity = await client.post(
            "/api/agent/messages",
            json={"message": "查询 ORDER-003 的状态"},
        )
        response = await client.post(
            "/api/agent/messages",
            json={"message": "查询 ORDER-003 的状态"},
            headers=_headers(),
        )

    assert missing_identity.status_code == 401
    assert response.status_code == 200
    assert response.json()["result"]["kind"] == "ORDER_STATUS"

    failed_service = _FakeMessageService(
        AgentMessageExecutionError(
            run_id="run-agent-failed",
            code="MODEL_NOT_CONFIGURED",
            message="structured model is not configured",
            retryable=False,
            error_step="route_intent",
        )
    )
    monkeypatch.setattr(
        agent_messages_api,
        "_message_service",
        lambda _request, _publisher: cast(AgentMessageService, failed_service),
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        failed = await client.post(
            "/api/agent/messages",
            json={"message": "查询 ORDER-003 的状态"},
            headers=_headers("trace-agent-model-missing"),
        )

    assert failed.status_code == 503
    assert failed.json() == {
        "run_id": "run-agent-failed",
        "trace_id": "trace-agent-model-missing",
        "code": "MODEL_NOT_CONFIGURED",
        "message": "structured model is not configured",
        "retryable": False,
        "error_step": "route_intent",
    }
