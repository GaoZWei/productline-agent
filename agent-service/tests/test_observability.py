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
