"""M3.4 模型路由调用、结构化解析、一次重试和安全回退。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Protocol

from pydantic import ValidationError

from app.routing import Intent
from app.routing.prompt import RoutingPrompt, build_routing_prompt
from app.schemas.context import PageContext
from app.schemas.routing import RouterEntities, RouterResult
from app.schemas.session import SessionContext

_LOGGER = logging.getLogger("agent-service.intent-router")

# 模型边界定义
class IntentRoutingModel(Protocol):
    """模型适配器契约; 供应商实现必须返回待校验的结构化对象。"""
    # 不依赖某个具体模型 SDK，只要求调用方实现一个异步 generate() 方法
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
    """执行最多两次模型结构化路由, 失败时不抛出模型内容。"""

    def __init__(self, model: IntentRoutingModel) -> None:
        self._model = model

    async def route(
        self,
        *,
        user_message: str,
        page_context: PageContext | None = None,
        session_context: SessionContext | None = None,
    ) -> RouterResult:
        """首次Schema失败重试一次; 模型异常或二次失败回退UNKNOWN。"""

        for attempt in (1, 2):
            prompt = build_routing_prompt(
                user_message=user_message,
                page_context=page_context,
                session_context=session_context,
                attempt=attempt,
            )
            try:
                raw_output = await self._model.generate(prompt)
            except Exception as error:  # 模型异常，直接回退UNKNOWN
                _LOGGER.error(
                    "intent_router_model_call_failed",
                    extra={
                        "attempt": attempt,
                        "prompt_version": prompt.version,
                        "error_type": type(error).__name__,
                    },
                )
                return unknown_router_result()

            try:
                return parse_router_result(raw_output)  # 格式校验通过
            except InvalidRouterOutputError:
                _LOGGER.warning(
                    "intent_router_output_invalid",
                    extra={"attempt": attempt, "prompt_version": prompt.version},
                )
                if attempt == 2:
                    return unknown_router_result()  # 二次失败回退UNKNOWN

        return unknown_router_result()
