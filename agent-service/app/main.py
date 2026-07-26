"""Minimal M0.1 HTTP entry point.

FastAPI and the production application structure are introduced in M1.1. This
dependency-free server keeps the foundation independently startable meanwhile.
"""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# HealthHandler 处理请求
class HealthHandler(BaseHTTPRequestHandler):
    """Serve the foundation health endpoint."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/health":  # 只有 /health 返回成功
            self.send_error(HTTPStatus.NOT_FOUND)  # 其他路径返回 404 Not Found
            return

        body = json.dumps(
            {"service": "agent-service", "status": "UP"},
            separators=(",", ":"),
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"agent-service: {format % args}", flush=True)


def main() -> None:
    """Start the HTTP server on the configured port."""

    port = int(os.getenv("PORT", "8000"))  # 从环境变量读取端口，默认 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)  # 使用 ThreadingHTTPServer 支持并发请求
    print(f"agent-service listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

