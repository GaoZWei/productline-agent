import asyncio
import logging
from collections.abc import Mapping

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity
from app.tools import (
    BaseTool,
    DuplicateToolRegistrationError,
    ToolContext,
    ToolError,
    ToolNotRegisteredError,
    ToolRegistry,
    ToolResult,
    ToolRiskLevel,
)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    echoed: str


class EchoTool(BaseTool[EchoInput, EchoOutput]):
    def __init__(
        self,
        *,
        required_permissions: frozenset[str] = frozenset({"ORDER_READ"}),
        timeout: float = 0.1,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            name="echo_order",
            description="返回经过校验的测试文本",
            input_model=EchoInput,
            output_model=EchoOutput,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=required_permissions,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.calls = 0

    async def _execute(
        self,
        tool_input: EchoInput,
        context: ToolContext,
    ) -> EchoOutput | Mapping[str, object]:
        self.calls += 1
        return EchoOutput(echoed=f"{context.identity.user_id}:{tool_input.text}")


def tool_context(
    *,
    permissions: frozenset[str] = frozenset({"ORDER_READ"}),
) -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(
            user_id="agent-user-001",
            role="REVIEWER",
            token=SecretStr("secret-token-001"),
        ),
        permissions=permissions,
        trace_id="trace-tool-001",
        run_id="run-tool-001",
    )


@pytest.mark.unit
def test_tool_context_is_strict_immutable_and_hides_token() -> None:
    context = tool_context()

    assert context.identity.user_id == "agent-user-001"
    assert context.permissions == frozenset({"ORDER_READ"})
    assert context.trace_id == "trace-tool-001"
    assert context.run_id == "run-tool-001"
    assert "secret-token-001" not in repr(context)

    with pytest.raises(ValidationError):
        ToolContext.model_validate(
            {
                **context.model_dump(),
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError):
        context.run_id = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_tool_result_enforces_success_and_failure_invariants() -> None:
    success = ToolResult[EchoOutput](
        success=True,
        data=EchoOutput(echoed="ok"),
    )
    failure = ToolResult[EchoOutput](
        success=False,
        error=ToolError(
            code=ToolErrorCode.RESOURCE_NOT_FOUND,
            message="order not found",
            retryable=False,
            trace_id="trace-tool-001",
            status_code=404,
        ),
    )

    assert success.data == EchoOutput(echoed="ok")
    assert success.error is None
    assert failure.data is None
    assert failure.error is not None
    assert failure.error.code is ToolErrorCode.RESOURCE_NOT_FOUND

    with pytest.raises(ValidationError):
        ToolResult[EchoOutput](success=True)

    with pytest.raises(ValidationError):
        ToolResult[EchoOutput](
            success=False,
            data=EchoOutput(echoed="unexpected"),
            error=failure.error,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_base_tool_exposes_metadata_and_returns_validated_output() -> None:
    tool = EchoTool()

    result = await tool.execute({"text": "ORDER-003"}, tool_context())

    assert tool.name == "echo_order"
    assert tool.description == "返回经过校验的测试文本"
    assert tool.input_model is EchoInput
    assert tool.output_model is EchoOutput
    assert tool.risk_level is ToolRiskLevel.LOW
    assert tool.required_permissions == frozenset({"ORDER_READ"})
    assert tool.timeout == 0.1
    assert tool.max_retries == 2
    assert result.success is True
    assert result.data == EchoOutput(echoed="agent-user-001:ORDER-003")
    assert result.error is None
    assert tool.calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_input_returns_parameter_error_without_calling_tool() -> None:
    tool = EchoTool()

    result = await tool.execute({"text": "", "extra": "invalid"}, tool_context())

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.PARAM_VALIDATION_ERROR
    assert result.error.retryable is False
    assert result.error.trace_id == "trace-tool-001"
    assert tool.calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_permission_returns_permission_error_before_execution() -> None:
    tool = EchoTool()

    result = await tool.execute({"text": "ORDER-003"}, tool_context(permissions=frozenset()))

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.PERMISSION_DENIED
    assert result.error.retryable is False
    assert tool.calls == 0


class ExceptionTool(EchoTool):
    async def _execute(
        self,
        tool_input: EchoInput,
        context: ToolContext,
    ) -> EchoOutput | Mapping[str, object]:
        self.calls += 1
        raise ToolException(
            code=ToolErrorCode.RESOURCE_NOT_FOUND,
            message=f"order not found: {tool_input.text}",
            retryable=False,
            trace_id=context.trace_id,
            status_code=404,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_exception_is_converted_to_standard_failure_result() -> None:
    result = await ExceptionTool().execute({"text": "ORDER-999"}, tool_context())

    assert result.success is False
    assert result.error == ToolError(
        code=ToolErrorCode.RESOURCE_NOT_FOUND,
        message="order not found: ORDER-999",
        retryable=False,
        trace_id="trace-tool-001",
        status_code=404,
    )


class InvalidOutputTool(EchoTool):
    async def _execute(
        self,
        tool_input: EchoInput,
        context: ToolContext,
    ) -> EchoOutput | Mapping[str, object]:
        self.calls += 1
        return {"wrong_field": tool_input.text}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_output_is_blocked_before_it_reaches_workflow() -> None:
    result = await InvalidOutputTool().execute({"text": "ORDER-003"}, tool_context())

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.RESPONSE_VALIDATION_ERROR
    assert result.error.retryable is False
    assert result.error.trace_id == "trace-tool-001"


class UnexpectedExceptionTool(EchoTool):
    async def _execute(
        self,
        tool_input: EchoInput,
        context: ToolContext,
    ) -> EchoOutput | Mapping[str, object]:
        self.calls += 1
        raise RuntimeError("private implementation detail")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unexpected_exception_is_logged_but_result_stays_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="agent-service.tool"):
        result = await UnexpectedExceptionTool().execute(
            {"text": "ORDER-003"},
            tool_context(),
        )

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNKNOWN_TOOL_ERROR
    assert result.error.message == "tool execution failed unexpectedly"
    assert "private implementation detail" not in result.error.message
    assert result.error.trace_id == "trace-tool-001"
    record = caplog.records[-1]
    assert record.message == "tool_execution_failed"
    assert record.tool_name == "echo_order"  # type: ignore[attr-defined]
    assert record.run_id == "run-tool-001"  # type: ignore[attr-defined]
    assert record.error_code == "UNKNOWN_TOOL_ERROR"  # type: ignore[attr-defined]
    assert record.trace_id == "trace-tool-001"  # type: ignore[attr-defined]
    assert record.exc_info is not None


class SlowTool(EchoTool):
    async def _execute(
        self,
        tool_input: EchoInput,
        context: ToolContext,
    ) -> EchoOutput | Mapping[str, object]:
        self.calls += 1
        await asyncio.sleep(0.02)
        return EchoOutput(echoed=tool_input.text)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_base_tool_enforces_total_timeout_without_retrying() -> None:
    tool = SlowTool(timeout=0.001, max_retries=3)

    result = await tool.execute({"text": "ORDER-003"}, tool_context())

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_TIMEOUT
    assert result.error.retryable is True
    assert result.error.trace_id == "trace-tool-001"
    assert tool.calls == 1


class MetadataTool(BaseTool[EchoInput, EchoOutput]):
    async def _execute(
        self,
        tool_input: EchoInput,
        context: ToolContext,
    ) -> EchoOutput | Mapping[str, object]:
        return EchoOutput(echoed=tool_input.text)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"name": "invalid name"}, "name"),
        ({"description": ""}, "description"),
        ({"timeout": 0}, "timeout"),
        ({"max_retries": -1}, "max_retries"),
        ({"required_permissions": frozenset({"invalid permission"})}, "permission"),
    ],
)
def test_base_tool_rejects_invalid_metadata(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    arguments: dict[str, object] = {
        "name": "echo_order",
        "description": "返回经过校验的测试文本",
        "input_model": EchoInput,
        "output_model": EchoOutput,
        "risk_level": ToolRiskLevel.LOW,
        "required_permissions": frozenset({"ORDER_READ"}),
        "timeout": 1.0,
        "max_retries": 0,
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=expected_message):
        MetadataTool(**arguments)  # type: ignore[arg-type]


@pytest.mark.unit
def test_registry_registers_gets_and_lists_tools_by_stable_name() -> None:
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)

    assert registry.get("echo_order") is tool
    assert registry.names == ("echo_order",)
    assert len(registry) == 1
    assert "echo_order" in registry


@pytest.mark.unit
def test_registry_rejects_duplicate_names_and_reports_unknown_names() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(DuplicateToolRegistrationError, match="echo_order"):
        registry.register(EchoTool())

    with pytest.raises(ToolNotRegisteredError, match="missing_tool"):
        registry.get("missing_tool")
