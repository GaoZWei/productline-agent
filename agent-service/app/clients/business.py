"""用于调用 Java 业务事实与写入接口的异步 HTTP 客户端。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import NoReturn, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from app.errors import ToolErrorCode, ToolException
from app.observability import get_trace_id, resolve_trace_id
from app.schemas.business import (
    BusinessErrorEnvelope,
    BusinessIdentity,
    BusinessResponse,
    BusinessSuccessEnvelope,
)
from app.settings import Settings

DataT = TypeVar("DataT")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_JAVA_ERROR_MAPPING: dict[int, tuple[str, ToolErrorCode]] = {
    400: ("PARAM_VALIDATION_ERROR", ToolErrorCode.PARAM_VALIDATION_ERROR),
    401: ("PERMISSION_DENIED", ToolErrorCode.PERMISSION_DENIED),
    403: ("PERMISSION_DENIED", ToolErrorCode.PERMISSION_DENIED),
    404: ("RESOURCE_NOT_FOUND", ToolErrorCode.RESOURCE_NOT_FOUND),
    409: ("BUSINESS_CONFLICT", ToolErrorCode.BUSINESS_CONFLICT),
    500: ("INTERNAL_SERVER_ERROR", ToolErrorCode.UPSTREAM_UNAVAILABLE),
}


class BusinessResponseValidationError(ValueError):
    """表示 Java 响应不合法并避免泄露原始响应体。"""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(f"Java response validation failed: {reason}")
        self.status_code = status_code
        self.reason = reason


# Client 构造过程: BusinessHttpClient 持有一个共享 httpx.AsyncClient
class BusinessHttpClient:
    """共享一个带连接池的 httpx 客户端并严格校验每个响应。"""

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
        # 只在 Python 内部使用的输入。Java 响应中的 data 应该按照 OrderData 进行校验。
        response_type: type[DataT],
        *,
        identity: BusinessIdentity | None = None,  # 用户、角色和可选 Token
        trace_id: str | None = None,
        params: Mapping[str, str] | None = None,  # 查询参数
    ) -> BusinessResponse[DataT]:
        validated_path = self._validate_path(path)
        headers = self._build_headers(identity=identity, trace_id=trace_id)
        try:
            # httpx 真正发请求
            response = await self._client.get(
                validated_path,
                headers=headers,
                params=params,
            )
        except httpx.RequestError as exc:  # 捕获的是“HTTP请求没有正常完成”
            self._raise_request_error(exc, headers["X-Trace-Id"])
        return self._validate_response(response, response_type, headers["X-Trace-Id"])

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
        # 路径校验（只允许相对 /api/ 路径）
        validated_path = self._validate_path(path)
        # 构造请求 Header
        headers = self._build_headers(identity=identity, trace_id=trace_id)
        headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._client.post(
                validated_path,
                headers=headers,
                json=dict(json_body),
            )
        except httpx.RequestError as exc:  # 请求阶段统一捕获 httpx.RequestError 异常
            self._raise_request_error(exc, headers["X-Trace-Id"])
        return self._validate_response(response, response_type, headers["X-Trace-Id"])

    # 校验业务 API路径是否符合要求（只允许相对 /api/ 路径）
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

    @staticmethod
    def _raise_request_error(exc: httpx.RequestError, trace_id: str) -> NoReturn:
        if isinstance(exc, httpx.TimeoutException):  # 四种 timeout 统一转为 TOOL_TIMEOUT
            raise ToolException(
                code=ToolErrorCode.TOOL_TIMEOUT,
                message="business service request timed out",
                retryable=True,
                trace_id=trace_id,
            ) from exc
        raise ToolException(  # 其他网络错误转为 UPSTREAM_UNAVAILABLE
            code=ToolErrorCode.UPSTREAM_UNAVAILABLE,
            message="business service is unavailable",
            retryable=True,
            trace_id=trace_id,
        ) from exc

    # 收到HTTP响应后的分流
    @classmethod
    def _validate_response(
        cls,
        response: httpx.Response,
        response_type: type[DataT],
        request_trace_id: str,
    ) -> BusinessResponse[DataT]:
        if response.status_code >= 400:  # 进入Java错误处理
            cls._raise_java_error(response, request_trace_id)
        if not 200 <= response.status_code < 300:  # 当前Client不允许重定向结果作为业务事实
            cls._raise_response_validation_error(
                response.status_code,
                request_trace_id,
                "unexpected HTTP status",
            )
        # 进入成功响应校验
        return cls._validate_success_response(response, response_type, request_trace_id)
    
    # Java错误响应映射
    @classmethod
    def _raise_java_error(
        cls,
        response: httpx.Response,
        request_trace_id: str,
    ) -> NoReturn:
        # 校验失败信封Schema
        try:
            envelope = BusinessErrorEnvelope.model_validate_json(response.content)
        except ValidationError as exc:
            cls._raise_response_validation_error(
                response.status_code,
                request_trace_id,
                "invalid JSON or error envelope",
                cause=exc,
            )
        # 查找对应的HTTP和错误码映射
        mapping = _JAVA_ERROR_MAPPING.get(response.status_code)
        response_trace_id = response.headers.get("X-Trace-Id")
        # 三项一致性检查
        if (
            mapping is None
            or envelope.code != mapping[0]
            or response_trace_id != envelope.trace_id
        ):
            cls._raise_response_validation_error(
                response.status_code,
                request_trace_id,
                "HTTP status, error code or Trace ID does not match the Java contract",
            )
        # 抛出标准异常
        raise ToolException(
            code=mapping[1],
            message=envelope.message,
            retryable=envelope.retryable,
            trace_id=envelope.trace_id,
            status_code=response.status_code,
        )
    # 成功响应校验（校验最外层和最内层 Schema）
    @staticmethod
    def _validate_success_response(
        response: httpx.Response,
        response_type: type[DataT],
        request_trace_id: str,
    ) -> BusinessResponse[DataT]:
        try:
            # 统一信封 Schema 校验（校验最外层）
            envelope = BusinessSuccessEnvelope.model_validate_json(response.content)
            # 具体 data Schema 校验（校验最内层业务数据格式）
            data = TypeAdapter(response_type).validate_python(envelope.data)
        except ValidationError as exc:
            BusinessHttpClient._raise_response_validation_error(
                response.status_code,
                request_trace_id,
                "invalid JSON, envelope or data schema",
                cause=exc,
            )
        # Trace 是否一致校验
        response_trace_id = response.headers.get("X-Trace-Id")
        if response_trace_id != envelope.trace_id:
            BusinessHttpClient._raise_response_validation_error(
                response.status_code,
                request_trace_id,
                "X-Trace-Id header does not match response body",
            )
        # 最终返回 BusinessResponse 对象
        return BusinessResponse(
            data=data,
            trace_id=envelope.trace_id,
            message=envelope.message,
        )
    # JSON、信封、data 和 Trace 异常统一转换为 RESPONSE_VALIDATION_ERROR。
    # 异常文案中不泄露原始响应体。
    @staticmethod
    def _raise_response_validation_error(
        status_code: int,
        trace_id: str,
        reason: str,
        *,
        cause: Exception | None = None,
    ) -> NoReturn:
        validation_error = BusinessResponseValidationError(status_code, reason)
        if cause is not None:
            validation_error.__cause__ = cause
        raise ToolException(
            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            message="business service returned an invalid response",
            retryable=False,
            trace_id=trace_id,
            status_code=status_code,
        ) from validation_error
