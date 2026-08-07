"""Tool 的统一元数据、校验和执行边界。"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ValidationError

from app.errors import ToolErrorCode, ToolException
from app.tools.models import ToolContext, ToolError, ToolResult

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PERMISSION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
_LOGGER = logging.getLogger("agent-service.tool")


class ToolRiskLevel(StrEnum):
    """描述 Tool 的静态风险等级。具体执行策略由后续阶段实现。"""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

# 所有 Tool 的公共模板
class BaseTool[InputT: BaseModel, OutputT: BaseModel](ABC):
    """在具体业务实现外统一输入、权限、超时、输出和错误处理。"""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[InputT],
        output_model: type[OutputT],
        risk_level: ToolRiskLevel,
        required_permissions: frozenset[str],  # 不能为空， Python 会先做快速权限检查，但它不能替代 Java 的权限检查
        timeout: float,  # 整个 _execute + 输出校验的耗时上限
        max_retries: int,
    ) -> None:
        self._validate_metadata(
            name=name,
            description=description,
            input_model=input_model,
            output_model=output_model,
            risk_level=risk_level,
            required_permissions=required_permissions,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._name = name
        self._description = description.strip()
        self._input_model = input_model
        self._output_model = output_model
        self._risk_level = risk_level
        self._required_permissions = required_permissions
        self._timeout = float(timeout)
        self._max_retries = max_retries

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_model(self) -> type[InputT]:
        return self._input_model

    @property
    def output_model(self) -> type[OutputT]:
        return self._output_model

    @property
    def risk_level(self) -> ToolRiskLevel:
        return self._risk_level

    @property
    def required_permissions(self) -> frozenset[str]:
        return self._required_permissions

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def max_retries(self) -> int:
        return self._max_retries
    
    # 完整执行顺序
    async def execute(
        self,
        raw_input: InputT | Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult[OutputT]:
        """执行固定门禁并把所有预期失败收敛为 ToolResult。"""
        # 第一步：权限检查
        if not self.required_permissions.issubset(context.permissions):
            return self._failure(
                ToolError(
                    code=ToolErrorCode.PERMISSION_DENIED,
                    message="tool permission denied",
                    retryable=False,
                    trace_id=context.trace_id,
                )
            )
        # 第二步：输入Schema校验
        try:
            validated_input = self.input_model.model_validate(raw_input)
        except ValidationError:
            return self._failure(
                ToolError(
                    code=ToolErrorCode.PARAM_VALIDATION_ERROR,
                    message="tool input validation failed",
                    retryable=False,
                    trace_id=context.trace_id,
                )
            )
        # 第三步：执行超时控制
        try:
            async with asyncio.timeout(self.timeout):  # 这个异步代码块必须在指定时间内完成
                # 第四步：调用具体 _execute()
                raw_output = await self._execute(validated_input, context)
                try:  # 第五步：输出Schema校验
                    validated_output = self.output_model.model_validate(raw_output)
                except ValidationError:
                    return self._failure(
                        ToolError(
                            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                            message="tool output validation failed",
                            retryable=False,
                            trace_id=context.trace_id,
                        )
                    )
        # 第七步：异常处理
        # 1. 标准 ToolException
        except ToolException as exception:
            return self._failure(
                ToolError.from_exception(
                    exception,
                    fallback_trace_id=context.trace_id,
                )
            )
        # 2. Tool整体超时
        except TimeoutError:
            return self._failure(
                ToolError(
                    code=ToolErrorCode.TOOL_TIMEOUT,
                    message="tool execution timed out",
                    retryable=True,
                    trace_id=context.trace_id,
                )
            )
        # 3. 未知异常
        except Exception:
            _LOGGER.exception(
                "tool_execution_failed",
                extra={
                    "tool_name": self.name,
                    "run_id": context.run_id,
                    "error_code": ToolErrorCode.UNKNOWN_TOOL_ERROR.value,
                    "trace_id": context.trace_id,
                },
            )
            return self._failure(
                ToolError(
                    code=ToolErrorCode.UNKNOWN_TOOL_ERROR,
                    message="tool execution failed unexpectedly",
                    retryable=False,
                    trace_id=context.trace_id,
                )
            )
        # 第六步：返回成功结果
        return ToolResult[OutputT](success=True, data=validated_output)

    # 第四步：调用具体 _execute()  execute()负责通用规则  _execute()只负责业务接口调用和必要转换
    # _execute() 才是未来真正调用 Java Client 的地方。
    @abstractmethod
    async def _execute(
        self,
        tool_input: InputT,
        context: ToolContext,
    ) -> OutputT | Mapping[str, object]:
        """由具体 Tool 实现一次调用且不自行处理通用执行策略。"""

    @staticmethod
    def _failure(error: ToolError) -> ToolResult[OutputT]:
        return ToolResult[OutputT](success=False, error=error)

    @staticmethod
    def _validate_metadata(
        *,
        name: str,
        description: str,
        input_model: type[InputT],
        output_model: type[OutputT],
        risk_level: ToolRiskLevel,
        required_permissions: frozenset[str],
        timeout: float,
        max_retries: int,
    ) -> None:
        """在 Tool 注册或执行前拒绝不稳定的元数据。"""

        if not isinstance(name, str) or not _TOOL_NAME_PATTERN.fullmatch(name):
            raise ValueError("tool name must use stable lower_snake_case")
        if not isinstance(description, str) or not 1 <= len(description.strip()) <= 500:
            raise ValueError("tool description must contain 1-500 characters")
        if not isinstance(input_model, type) or not issubclass(input_model, BaseModel):
            raise ValueError("input_model must be a Pydantic BaseModel type")
        if not isinstance(output_model, type) or not issubclass(output_model, BaseModel):
            raise ValueError("output_model must be a Pydantic BaseModel type")
        if not isinstance(risk_level, ToolRiskLevel):
            raise ValueError("risk_level must be a ToolRiskLevel")
        if not isinstance(required_permissions, frozenset) or any(
            not isinstance(permission, str)
            or not _PERMISSION_PATTERN.fullmatch(permission)
            for permission in required_permissions
        ):
            raise ValueError("required permission names must use stable uppercase identifiers")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("tool timeout must be a positive finite number")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("tool max_retries must be a non-negative integer")
