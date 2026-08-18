import json
import logging

import pytest

from app.observability import JsonFormatter, reset_trace_id, set_trace_id


@pytest.mark.unit
def test_json_formatter_includes_trace_and_request_fields() -> None:
    token = set_trace_id("trace-log-001")
    try:
        record = logging.LogRecord(
            name="agent-service.request",
            level=logging.INFO,
            pathname=__file__,
            lineno=15,
            msg="request_completed",
            args=(),
            exc_info=None,
        )
        record.method = "GET"
        record.path = "/health"
        record.status_code = 200

        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_trace_id(token)

    assert payload["level"] == "INFO"
    assert payload["message"] == "request_completed"
    assert payload["trace_id"] == "trace-log-001"
    assert payload["method"] == "GET"
    assert payload["path"] == "/health"
    assert payload["status_code"] == 200


@pytest.mark.unit
def test_json_formatter_includes_tool_failure_fields() -> None:
    token = set_trace_id("trace-tool-log-001")
    try:
        record = logging.LogRecord(
            name="agent-service.tool",
            level=logging.ERROR,
            pathname=__file__,
            lineno=42,
            msg="tool_execution_failed",
            args=(),
            exc_info=None,
        )
        record.tool_name = "get_order_detail"
        record.run_id = "run-tool-log-001"
        record.error_code = "UNKNOWN_TOOL_ERROR"
        record.trace_id = "trace-tool-context-001"

        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_trace_id(token)

    assert payload["trace_id"] == "trace-tool-context-001"
    assert payload["tool_name"] == "get_order_detail"
    assert payload["run_id"] == "run-tool-log-001"
    assert payload["error_code"] == "UNKNOWN_TOOL_ERROR"


@pytest.mark.unit
def test_json_formatter_includes_tool_retry_fields() -> None:
    record = logging.LogRecord(
        name="agent-service.tool",
        level=logging.WARNING,
        pathname=__file__,
        lineno=70,
        msg="tool_retry_scheduled",
        args=(),
        exc_info=None,
    )
    record.tool_name = "get_order_detail"
    record.run_id = "run-retry-log-001"
    record.error_code = "TOOL_TIMEOUT"
    record.retry_number = 1
    record.retry_delay_ms = 100.0
    record.trace_id = "trace-retry-log-001"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["trace_id"] == "trace-retry-log-001"
    assert payload["tool_name"] == "get_order_detail"
    assert payload["run_id"] == "run-retry-log-001"
    assert payload["error_code"] == "TOOL_TIMEOUT"
    assert payload["retry_number"] == 1
    assert payload["retry_delay_ms"] == 100.0


@pytest.mark.unit
def test_json_formatter_includes_embedding_retry_fields() -> None:
    record = logging.LogRecord(
        name="app.knowledge.embeddings",
        level=logging.WARNING,
        pathname=__file__,
        lineno=96,
        msg="embedding_retry_scheduled",
        args=(),
        exc_info=None,
    )
    record.embedding_provider = "openai_compatible"
    record.embedding_model = "text-embedding-3-small"
    record.index_version = "text-embedding-3-small-1536-v1"
    record.batch_number = 2
    record.retry_number = 1
    record.retry_delay_ms = 200.0
    record.error_code = "EMBEDDING_RATE_LIMITED"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["embedding_provider"] == "openai_compatible"
    assert payload["embedding_model"] == "text-embedding-3-small"
    assert payload["index_version"] == "text-embedding-3-small-1536-v1"
    assert payload["batch_number"] == 2
    assert payload["retry_number"] == 1
    assert payload["retry_delay_ms"] == 200.0
    assert payload["error_code"] == "EMBEDDING_RATE_LIMITED"
