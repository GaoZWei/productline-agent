"""M3.4 模型路由调用、结构化解析、一次重试和安全回退。"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable
from typing import Protocol

from pydantic import ValidationError

from app.clients.model import ModelClientError, ModelErrorCode
from app.eventing import RunEventSink
from app.routing import Intent
from app.routing.prompt import RoutingPrompt, build_routing_prompt
from app.schemas.context import PageContext
from app.schemas.events import RunEventType
from app.schemas.routing import RouterEntities, RouterResult
from app.schemas.session import SessionContext

_LOGGER = logging.getLogger("agent-service.intent-router")

# 模型边界定义
class IntentRoutingModel(Protocol):
    """模型适配器契约; 供应商实现必须返回待校验的结构化对象。"""
    # 不依赖某个具体模型 SDK, 只要求调用方实现一个异步 generate() 方法
    def generate(self, prompt: RoutingPrompt) -> Awaitable[object]:
        """根据受控Prompt和JSON Schema生成一次路由候选。"""


class InvalidRouterOutputError(ValueError):
    """模型返回内容无法通过RouterResult结构化校验。"""

# 格式错误处理
def parse_router_result(raw_output: object) -> RouterResult:
    """同时接受JSON文本或对象, 并收口为严格RouterResult。"""

    try:
        if isinstance(raw_output, (str, bytes, bytearray)):
            return RouterResult.model_validate_json(raw_output)
        return RouterResult.model_validate(raw_output)
    except ValidationError as error:
        raise InvalidRouterOutputError("router output schema validation failed") from error

# 实体原文证据校验
def validate_user_message_entity_evidence(
    user_message: str,
    result: RouterResult,
) -> RouterResult:
    """要求每个模型实体都能在本轮用户原文中找到独立文本证据。"""
    # 遍历模型返回的实体字段, 构造正则
    for field, value in result.entities.model_dump(exclude_none=True).items():
        pattern = rf"(?<![A-Za-z0-9]){re.escape(str(value))}(?![A-Za-z0-9])"
        if re.search(pattern, user_message, flags=re.IGNORECASE) is None:
            raise InvalidRouterOutputError(
                f"router entity {field} lacks user-message evidence"
            )
    return result

# 降级处理
def unknown_router_result() -> RouterResult:
    """返回不携带模型实体的安全UNKNOWN结果。"""

    return RouterResult(
        intent=Intent.UNKNOWN,
        confidence=0.0,
        entities=RouterEntities(),
        missing_fields=[],
        need_clarification=True,
    )

# 解析、重试和 UNKNOWN 降级处理
class IntentRouter:
    """执行最多两次结构化路由, 可选择安全UNKNOWN或显式错误边界。"""

    def __init__(
        self,
        model: IntentRoutingModel,
        *,
        event_sink: RunEventSink | None = None,
        run_id: str | None = None,
        strict_model_errors: bool = False, # 严格模型错误
    ) -> None:
        self._model = model
        self._event_sink = event_sink
        self._run_id = run_id
        self._strict_model_errors = strict_model_errors

    async def route(
        self,
        *,
        user_message: str,
        page_context: PageContext | None = None,
        session_context: SessionContext | None = None,
    ) -> RouterResult:
        """首次Schema失败重试一次; 严格模式保留模型错误供统一入口处理。"""

        for attempt in (1, 2):
            prompt = build_routing_prompt(
                user_message=user_message,
                page_context=page_context,
                session_context=session_context,
                attempt=attempt,
            )
            try:
                raw_output = await self._model.generate(prompt)
            except ModelClientError as error:
                if error.code is ModelErrorCode.INVALID_OUTPUT:
                    _LOGGER.warning(
                        "intent_router_output_invalid",
                        extra={"attempt": attempt, "prompt_version": prompt.version},
                    )
                    if attempt == 1:
                        continue
                    if self._strict_model_errors:
                        raise InvalidRouterOutputError(
                            "router output schema validation failed twice"
                        ) from error
                    return await self._publish_result(unknown_router_result())
                _LOGGER.error(
                    "intent_router_model_call_failed",
                    extra={
                        "attempt": attempt,
                        "prompt_version": prompt.version,
                        "error_code": error.code.value,
                    },
                )
                if self._strict_model_errors:
                    raise
                return await self._publish_result(unknown_router_result())
            except Exception as error:  # 兼容旧调用方的安全UNKNOWN降级。
                _LOGGER.error(
                    "intent_router_model_call_failed",
                    extra={
                        "attempt": attempt,
                        "prompt_version": prompt.version,
                        "error_type": type(error).__name__,
                    },
                )
                if self._strict_model_errors:
                    raise
                return await self._publish_result(unknown_router_result())

            try:
                parsed = parse_router_result(raw_output)
                validated = validate_user_message_entity_evidence(user_message, parsed)
                return await self._publish_result(validated)
            except InvalidRouterOutputError:
                _LOGGER.warning(
                    "intent_router_output_invalid",
                    extra={"attempt": attempt, "prompt_version": prompt.version},
                )
                if attempt == 2:
                    if self._strict_model_errors:
                        raise
                    return await self._publish_result(
                        unknown_router_result()
                    )  # 二次失败回退UNKNOWN

        return await self._publish_result(unknown_router_result())

    async def _publish_result(self, result: RouterResult) -> RouterResult:
        """发布路由结论和澄清缺口, 不发送用户原文或模型原始输出。"""

        if self._event_sink is None:
            return result
        await self._event_sink.publish(
            RunEventType.INTENT_DETECTED,
            run_id=self._run_id,
            data={
                "intent": result.intent.value,
                "confidence": result.confidence,
                "need_clarification": result.need_clarification,
            },
        )
        if result.need_clarification:
            await self._event_sink.publish(
                RunEventType.CLARIFICATION_REQUIRED,
                run_id=self._run_id,
                data={"missing_fields": list(result.missing_fields)},
            )
        return result
