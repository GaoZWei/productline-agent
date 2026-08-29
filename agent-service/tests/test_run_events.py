"""M7.3 SSE事件Schema、回放、心跳、隔离和HTTP连接测试。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas import RunEvent, RunEventType
from app.services import (
    EventReplayUnavailableError,
    EventStreamAccessDeniedError,
    RunEventService,
)
from app.settings import Settings

_EVENT_TIME = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)


def _event(**changes: object) -> RunEvent:
    values: dict[str, object] = {
        "event_id": "1",
        "event_type": RunEventType.RUN_STARTED,
        "stream_id": "stream-test-001",
        "run_id": "run-test-001",
        "sequence_number": 1,
        "occurred_at": _EVENT_TIME,
        "trace_id": "trace-test-001",
        "step_id": None,
        "data": {"session_id": "session-test-001"},
    }
    values.update(changes)
    return RunEvent.model_validate(values)


@pytest.mark.unit
def test_run_event_schema_has_complete_types_and_rejects_sensitive_or_large_data() -> None:
    assert tuple(item.value for item in RunEventType) == (
        "run_started",
        "context_loaded",
        "intent_detected",
        "clarification_required",
        "agent_action_selected",
        "tool_started",
        "tool_completed",
        "retrieval_started",
        "retrieval_completed",
        "diagnosis_generated",
        "approval_required",
        "writeback_started",
        "writeback_completed",
        "run_completed",
        "run_failed",
    )
    assert _event().event_type is RunEventType.RUN_STARTED

    with pytest.raises(ValidationError, match="sensitive key"):
        _event(data={"refresh_token": "do-not-stream"})
    with pytest.raises(ValidationError, match="string is too long"):
        _event(data={"summary": "x" * 4097})
    with pytest.raises(ValidationError):
        _event(unsupported=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_service_streams_ordered_events_and_cleans_terminal_subscription() -> None:
    service = RunEventService(now=lambda: _EVENT_TIME)
    await service.open_stream("stream-live-001", owner_user_id="reviewer-001")
    subscription = await service.subscribe(
        "stream-live-001",
        owner_user_id="reviewer-001",
    )
    publisher = await service.publisher(
        "stream-live-001",
        owner_user_id="reviewer-001",
        trace_id="trace-live-001",
    )
    iterator = subscription.iter_sse(_never_disconnected)

    assert await anext(iterator) == ": connected stream-live-001\nretry: 3000\n\n"
    await publisher.publish(
        RunEventType.RUN_STARTED,
        run_id="run-live-001",
        data={"session_id": "session-live-001"},
    )
    await publisher.publish(
        RunEventType.RUN_COMPLETED,
        run_id="run-live-001",
        data={"status": "SUCCEEDED"},
    )

    started_frame = await anext(iterator)
    completed_frame = await anext(iterator)
    assert "id: 1\nevent: run_started\n" in started_frame
    assert '"sequence_number":1' in started_frame
    assert "id: 2\nevent: run_completed\n" in completed_frame
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
    assert await service.active_subscriber_count("stream-live-001") == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_service_emits_heartbeat_and_removes_disconnected_subscriber() -> None:
    service = RunEventService(heartbeat_seconds=0.01, now=lambda: _EVENT_TIME)
    await service.open_stream("stream-heartbeat-001", owner_user_id="reviewer-001")
    subscription = await service.subscribe(
        "stream-heartbeat-001",
        owner_user_id="reviewer-001",
    )
    iterator = subscription.iter_sse(_disconnect_after_first_check())

    assert "connected" in await anext(iterator)
    assert await anext(iterator) == ": heartbeat\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
    assert await service.active_subscriber_count("stream-heartbeat-001") == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_service_replays_after_last_id_and_enforces_owner_and_history() -> None:
    service = RunEventService(history_limit=2, now=lambda: _EVENT_TIME)
    await service.open_stream("stream-replay-001", owner_user_id="reviewer-001")
    publisher = await service.publisher(
        "stream-replay-001",
        owner_user_id="reviewer-001",
        trace_id="trace-replay-001",
    )
    for event_type in (
        RunEventType.RUN_STARTED,
        RunEventType.CONTEXT_LOADED,
        RunEventType.DIAGNOSIS_GENERATED,
        RunEventType.TOOL_STARTED,
    ):
        await publisher.publish(event_type, run_id="run-replay-001")

    replay = await service.subscribe(
        "stream-replay-001",
        owner_user_id="reviewer-001",
        last_event_id=3,
    )
    replay_iterator = replay.iter_sse(_never_disconnected)
    await anext(replay_iterator)
    assert "id: 4" in await anext(replay_iterator)
    await replay.close()

    with pytest.raises(EventReplayUnavailableError):
        await service.subscribe(
            "stream-replay-001",
            owner_user_id="reviewer-001",
            last_event_id=1,
        )
    with pytest.raises(EventStreamAccessDeniedError):
        await service.subscribe(
            "stream-replay-001",
            owner_user_id="reviewer-002",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sse_http_endpoint_replays_terminal_event_with_required_headers() -> None:
    application = create_app(Settings(environment="test"))
    async with application.router.lifespan_context(application):
        service: RunEventService = application.state.run_event_service
        await service.open_stream("stream-http-001", owner_user_id="reviewer-001")
        publisher = await service.publisher(
            "stream-http-001",
            owner_user_id="reviewer-001",
            trace_id="trace-http-001",
        )
        await publisher.publish(
            RunEventType.RUN_FAILED,
            data={"error_code": "TEST_FAILURE", "retryable": False},
        )
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/agent/events/stream-http-001",
                headers={
                    "X-Trace-Id": "trace-http-connect",
                    "X-User-Id": "reviewer-001",
                    "X-User-Role": "REVIEWER",
                },
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert ": connected stream-http-001" in response.text
    assert "event: run_failed" in response.text


async def _never_disconnected() -> bool:
    return False


def _disconnect_after_first_check() -> Callable[[], Awaitable[bool]]:
    checks = 0

    async def check() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    return check
