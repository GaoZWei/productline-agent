"""Async HTTP client for the Java business fact and write APIs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from app.observability import get_trace_id, resolve_trace_id
from app.schemas.business import (
    BusinessIdentity,
    BusinessResponse,
    BusinessSuccessEnvelope,
)
from app.settings import Settings

DataT = TypeVar("DataT")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class BusinessResponseValidationError(ValueError):
    """Signal an invalid Java success response without exposing its body."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(f"Java response validation failed: {reason}")
        self.status_code = status_code
        self.reason = reason

# Client 构造过程：BusinessHttpClient 持有一个共享 httpx.AsyncClient
class BusinessHttpClient:
    """Share one pooled httpx client and strictly validate every success response."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        timeout = httpx.Timeout(
            connect=settings.business_connect_timeout_seconds,
            read=settings.business_read_timeout_seconds,
            write=settings.business_write_timeout_seconds,
            pool=settings.business_pool_timeout_seconds,
        ) 
        # 创建共享的 httpx.AsyncClient
        self._client = httpx.AsyncClient(
            base_url=str(settings.business_service_url),
            timeout=timeout,
            transport=transport,
            trust_env=False,
        )

    @property
    def timeout(self) -> httpx.Timeout:
        return self._client.timeout

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def aclose(self) -> None:
        await self._client.aclose()
    # 封装 GET、查询参数、身份和 Trace ID
    async def get(
        self,
        path: str,
        response_type: type[DataT],  # data 应满足的 Pydantic Schema
        *,
        identity: BusinessIdentity | None = None,  # 用户、角色和可选 Token
        trace_id: str | None = None,
        params: Mapping[str, str] | None = None,  # 查询参数
    ) -> BusinessResponse[DataT]:
        # httpx 真正发请求
        response = await self._client.get(
            self._validate_path(path),
            headers=self._build_headers(identity=identity, trace_id=trace_id),
            params=params,
        )
        return self._validate_success_response(response, response_type)
    # 封装 POST、JSON Body、身份和强制幂等键
    async def post(
        self,
        path: str,
        response_type: type[DataT],
        *,
        json_body: Mapping[str, object],
        identity: BusinessIdentity,
        trace_id: str | None = None,
        idempotency_key: str,
    ) -> BusinessResponse[DataT]:
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise ValueError(
                "idempotency_key must contain 1-128 safe letters, numbers, '.', '_', ':' or '-'"
            )
        headers = self._build_headers(identity=identity, trace_id=trace_id)
        headers["Idempotency-Key"] = idempotency_key
        response = await self._client.post(
            self._validate_path(path),
            headers=headers,
            json=dict(json_body),
        )
        return self._validate_success_response(response, response_type)
    # 校验业务 API路径是否符合要求
    @staticmethod
    def _validate_path(path: str) -> str:
        if not path.startswith("/api/") or "://" in path:
            raise ValueError("business API path must be a relative /api/ path")
        return path
    # 构造身份 Header
    @staticmethod
    def _build_headers(
        *,
        identity: BusinessIdentity | None,
        trace_id: str | None,
    ) -> dict[str, str]:
        candidate_trace_id = trace_id or get_trace_id()
        resolved_trace_id = resolve_trace_id(
            None if candidate_trace_id == "-" else candidate_trace_id
        )
        headers = {"X-Trace-Id": resolved_trace_id}
        if identity is not None:
            headers["X-User-Id"] = identity.user_id
            headers["X-User-Role"] = identity.role
            if identity.token is not None:
                headers["Authorization"] = (
                    f"Bearer {identity.token.get_secret_value()}"
                )
        return headers
    # 依次校验 HTTP、信封、data Schema 和 Trace ID
    @staticmethod
    def _validate_success_response(
        response: httpx.Response,
        response_type: type[DataT],
    ) -> BusinessResponse[DataT]:
        # HTTP 状态校验
        response.raise_for_status()
        try:
            # 统一信封 Schema 校验
            envelope = BusinessSuccessEnvelope.model_validate_json(response.content)
            # 具体 data Schema 校验
            data = TypeAdapter(response_type).validate_python(envelope.data)
        except ValidationError as exc:
            raise BusinessResponseValidationError(
                response.status_code,
                "invalid JSON, envelope or data schema",
            ) from exc
        # Trace 是否一致校验
        response_trace_id = response.headers.get("X-Trace-Id")
        if response_trace_id != envelope.trace_id:
            raise BusinessResponseValidationError(
                response.status_code,
                "X-Trace-Id header does not match response body",
            )
        # 最终返回 BusinessResponse 对象
        return BusinessResponse(
            data=data,
            trace_id=envelope.trace_id,
            message=envelope.message,
        )
