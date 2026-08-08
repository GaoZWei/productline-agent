from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest
from pydantic import BaseModel, ConfigDict

from app.errors import ToolErrorCode, ToolException
from app.schemas.business import BusinessIdentity
from app.tools import BaseTool, RetryPolicy, ToolContext, ToolRiskLevel


class RetryInput(BaseModel):
    """重试测试使用的严格输入。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    value: str


class RetryOutput(BaseModel):
    """重试测试使用的严格输出。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    value: str


def tool_context() -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="retry-user-001", role="REVIEWER"),
        permissions=frozenset({"ORDER_READ"}),
        trace_id="trace-retry-001",
        run_id="run-retry-001",
    )


def tool_exception(
    code: ToolErrorCode = ToolErrorCode.TOOL_TIMEOUT,
    *,
    retryable: bool = True,
) -> ToolException:
    return ToolException(
        code=code,
        message=f"simulated {code.value}",
        retryable=retryable,
        trace_id="trace-retry-001",
    )


class SequencedRetryTool(BaseTool[RetryInput, RetryOutput]):
    """按照测试给定结果序列返回或抛出异常。"""

    def __init__(
        self,
        outcomes: list[RetryOutput | ToolException],
        *,
        retry_policy: RetryPolicy,
        timeout: float = 1.0,
    ) -> None:
        super().__init__(
            name="retry_test",
            description="验证只读 Tool 的重试边界",
            input_model=RetryInput,
            output_model=RetryOutput,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=frozenset({"ORDER_READ"}),
            timeout=timeout,
            max_retries=retry_policy.max_retries,
            retry_policy=retry_policy,
        )
        self._outcomes = outcomes
        self.calls = 0

    async def _execute(
        self,
        tool_input: RetryInput,
        context: ToolContext,
    ) -> RetryOutput | Mapping[str, object]:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, ToolException):
            raise outcome
        return outcome


@pytest.mark.unit
def test_retry_policy_calculates_capped_exponential_backoff() -> None:
    policy = RetryPolicy(
        max_retries=4,
        initial_backoff_seconds=0.01,
        backoff_multiplier=2.0,
        max_backoff_seconds=0.05,
    )

    assert [policy.backoff_seconds(number) for number in range(1, 5)] == [
        0.01,
        0.02,
        0.04,
        0.05,
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exception", "retries_completed", "expected"),
    [
        (tool_exception(ToolErrorCode.TOOL_TIMEOUT), 0, True),
        (tool_exception(ToolErrorCode.UPSTREAM_UNAVAILABLE), 0, True),
        (tool_exception(ToolErrorCode.UPSTREAM_UNAVAILABLE, retryable=False), 0, False),
        (tool_exception(ToolErrorCode.RESOURCE_NOT_FOUND), 0, False),
        (tool_exception(ToolErrorCode.RESPONSE_VALIDATION_ERROR), 0, False),
        (tool_exception(ToolErrorCode.TOOL_TIMEOUT), 1, False),
    ],
    ids=[
        "timeout",
        "upstream-unavailable",
        "retryable-false",
        "not-found",
        "response-validation",
        "retry-limit",
    ],
)
def test_retry_policy_requires_safe_code_retryable_flag_and_remaining_budget(
    exception: ToolException,
    retries_completed: int,
    expected: bool,
) -> None:
    policy = RetryPolicy(max_retries=1)

    assert policy.should_retry(exception, retries_completed=retries_completed) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "arguments",
    [
        {"max_retries": -1},
        {"max_retries": True},
        {"max_retries": 1, "initial_backoff_seconds": 0},
        {"max_retries": 1, "backoff_multiplier": 0.5},
        {
            "max_retries": 1,
            "initial_backoff_seconds": 0.2,
            "max_backoff_seconds": 0.1,
        },
    ],
    ids=[
        "negative-retries",
        "boolean-retries",
        "zero-backoff",
        "invalid-multiplier",
        "max-below-initial",
    ],
)
def test_retry_policy_rejects_invalid_configuration(arguments: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**arguments)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_base_tool_retries_transient_failure_then_returns_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = RetryPolicy(max_retries=1, initial_backoff_seconds=0.001)
    tool = SequencedRetryTool(
        [tool_exception(), RetryOutput(value="recovered")],
        retry_policy=policy,
    )

    with caplog.at_level(logging.WARNING, logger="agent-service.tool"):
        result = await tool.execute({"value": "ORDER-003"}, tool_context())

    assert result.success is True
    assert result.data == RetryOutput(value="recovered")
    assert tool.calls == 2
    retry_record = next(
        record for record in caplog.records if record.message == "tool_retry_scheduled"
    )
    assert retry_record.retry_number == 1  # type: ignore[attr-defined]
    assert retry_record.retry_delay_ms == 1.0  # type: ignore[attr-defined]
    assert retry_record.error_code == "TOOL_TIMEOUT"  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_base_tool_stops_after_maximum_retries_and_preserves_last_error() -> None:
    policy = RetryPolicy(max_retries=2, initial_backoff_seconds=0.001)
    tool = SequencedRetryTool(
        [tool_exception(ToolErrorCode.UPSTREAM_UNAVAILABLE)],
        retry_policy=policy,
    )

    result = await tool.execute({"value": "ORDER-003"}, tool_context())

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.error.retryable is True
    assert tool.calls == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_total_tool_timeout_includes_retry_backoff() -> None:
    policy = RetryPolicy(max_retries=1, initial_backoff_seconds=0.02)
    tool = SequencedRetryTool(
        [tool_exception()],
        retry_policy=policy,
        timeout=0.001,
    )

    result = await tool.execute({"value": "ORDER-003"}, tool_context())

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_TIMEOUT
    assert result.error.message == "tool execution timed out"
    assert tool.calls == 1


@pytest.mark.unit
def test_base_tool_rejects_retry_policy_and_metadata_mismatch() -> None:
    policy = RetryPolicy(max_retries=1)

    with pytest.raises(ValueError, match="max_retries"):
        BaseTool.__init__(
            SequencedRetryTool.__new__(SequencedRetryTool),
            name="retry_test",
            description="验证不一致重试元数据",
            input_model=RetryInput,
            output_model=RetryOutput,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=frozenset({"ORDER_READ"}),
            timeout=1.0,
            max_retries=2,
            retry_policy=policy,
        )
