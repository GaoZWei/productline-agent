"""Minimal JSON logging and request Trace ID propagation."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

TRACE_ID_HEADER = "X-Trace-Id"
TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# 该变量用于保存“当前异步请求的 Trace ID”
# 简单全局变量不可以,因为多个请求并发执行时会互相覆盖
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_LOG_EXTRA_FIELDS = (
    "service",
    "environment",
    "method",
    "path",
    "status_code",
    "duration_ms",
)


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(trace_id: str) -> Token[str]:
    return _trace_id.set(trace_id)


def reset_trace_id(token: Token[str]) -> None:
    _trace_id.reset(token)

# Trace ID 校验函数
def resolve_trace_id(candidate: str | None) -> str:
    """Accept a bounded safe caller ID or replace it with a generated value."""

    if candidate and TRACE_ID_PATTERN.fullmatch(candidate):
        return candidate
    return f"trace-{uuid4()}"

# JSON 格式化器方便后续日志系统按字段查询日志。
class JsonFormatter(logging.Formatter):
    """Serialize stable log fields without leaking arbitrary object state."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_trace_id(),
        }
        for field in _LOG_EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Install one process-wide JSON handler in an idempotent way."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

# Trace ID 中间件为每个请求绑定一个 Trace ID。
class TraceIdMiddleware(BaseHTTPMiddleware):
    """Bind one safe Trace ID to the response and every request log."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # 中间件读取 Header 中的 Trace ID
        trace_id = resolve_trace_id(request.headers.get(TRACE_ID_HEADER))
        # 然后写入 ContextVar
        token = set_trace_id(trace_id)
        started_at = perf_counter()
        try:
            response = await call_next(request)
            response.headers[TRACE_ID_HEADER] = trace_id
            logging.getLogger("agent-service.request").info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
            return response
        except Exception:
            logging.getLogger("agent-service.request").exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
            raise
        finally:
            reset_trace_id(token)
