"""复用Java连接池并对知识授权查询执行有界重试与请求身份绑定。"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Mapping

from pydantic import ValidationError

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode, ToolException
from app.observability import get_trace_id, resolve_trace_id
from app.schemas.business import BusinessIdentity, BusinessResponse
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeAuthorizationResponse,
)
from app.tools.retry import RetryPolicy

_LOGGER = logging.getLogger("agent-service.knowledge-authorization")
_DEFAULT_RETRY_POLICY = RetryPolicy(max_retries=1)


class KnowledgeAuthorizationClient:
    """只查询授权，总预算覆盖全部请求与退避，不缓存或签发执行凭证。"""

    def __init__(
        self,
        business_client: BusinessHttpClient,
        *,
        timeout_seconds: float = 5.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """借用外层管理的连接池，默认至多额外重试一次瞬时故障。"""

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise ValueError("retry_policy must be a RetryPolicy or None")
        self._business_client = business_client
        self._timeout_seconds = float(timeout_seconds)
        self._retry_policy = retry_policy if retry_policy is not None else _DEFAULT_RETRY_POLICY

    async def authorize(
        self,
        request: KnowledgeAuthorizationRequest | Mapping[str, object],
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> BusinessResponse[KnowledgeAuthorizationResponse]:
        """校验动作并查询Java，任何拒绝、响应不匹配或预算耗尽均抛出明确异常。"""

        candidate_trace_id = trace_id or get_trace_id()
        # Java要求首字符为字母或数字，缺省上下文“-”必须在重试前只生成一次新标识。
        request_trace_id = resolve_trace_id(
            candidate_trace_id
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", candidate_trace_id)
            else None
        )
        try:
            validated = KnowledgeAuthorizationRequest.model_validate(request)
        except ValidationError:
            raise ToolException(
                code=ToolErrorCode.PARAM_VALIDATION_ERROR,
                message="knowledge authorization input is invalid",
                retryable=False,
                trace_id=request_trace_id,
            ) from None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._query_with_retry(validated, identity, request_trace_id)
        except TimeoutError:
            raise ToolException(
                code=ToolErrorCode.TOOL_TIMEOUT,
                message="knowledge authorization total budget exhausted",
                retryable=False,
                trace_id=request_trace_id,
            ) from None

    async def _query_with_retry(
        self,
        request: KnowledgeAuthorizationRequest,
        identity: BusinessIdentity,
        trace_id: str,
    ) -> BusinessResponse[KnowledgeAuthorizationResponse]:
        """沿用只读错误白名单，成功结果还必须绑定本次用户与动作。"""

        retries_completed = 0
        while True:
            try:
                response = await self._business_client.post_readonly(
                    "/api/knowledge/authorize",
                    KnowledgeAuthorizationResponse,
                    json_body=request.model_dump(mode="json"),
                    identity=identity,
                    trace_id=trace_id,
                )
                if (
                    response.data.user_id != identity.user_id
                    or response.data.action != request.action
                    or response.trace_id != trace_id
                ):
                    raise ToolException(
                        code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                        message="knowledge authorization actor, action or trace does not match",
                        retryable=False,
                        trace_id=response.trace_id,
                        status_code=200,
                    )
                return response
            except ToolException as exc:
                if not self._retry_policy.should_retry(exc, retries_completed=retries_completed):
                    raise
                retries_completed += 1
                delay = self._retry_policy.backoff_seconds(retries_completed)
                _LOGGER.warning(
                    "knowledge_authorization_retry_scheduled",
                    extra={
                        "trace_id": trace_id,
                        "error_code": exc.code.value,
                        "retry_number": retries_completed,
                        "retry_delay_ms": round(delay * 1000),
                    },
                )
                await asyncio.sleep(delay)
