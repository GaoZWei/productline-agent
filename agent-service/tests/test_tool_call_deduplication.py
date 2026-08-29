from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.errors import ToolErrorCode
from app.schemas.business import BusinessIdentity
from app.tools import BaseTool, ToolContext, ToolRiskLevel, build_tool_call_fingerprint


class DedupInput(BaseModel):
    """重复调用测试使用的严格输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    order_id: str = Field(pattern=r"^ORDER-[0-9]{3}$")
    options: dict[str, int] = Field(default_factory=dict)


class DedupOutput(BaseModel):
    """记录测试 Tool 实际执行次数。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invocation: int


class DedupTool(BaseTool[DedupInput, DedupOutput]):
    """通过调用计数证明重复请求是否到达具体 Tool。"""

    def __init__(self, *, name: str = "dedup_order") -> None:
        super().__init__(
            name=name,
            description="验证单次 Run 的 Tool 重复调用门禁",
            input_model=DedupInput,
            output_model=DedupOutput,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=frozenset({"ORDER_READ"}),
            timeout=1.0,
            max_retries=0,
        )
        self.calls = 0

    async def _execute(
        self,
        tool_input: DedupInput,
        context: ToolContext,
    ) -> DedupOutput | Mapping[str, object]:
        self.calls += 1
        await asyncio.sleep(0)
        return DedupOutput(invocation=self.calls)


def tool_context(*, run_id: str = "run-dedup-001") -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="dedup-user-001", role="REVIEWER"),
        permissions=frozenset({"ORDER_READ"}),
        trace_id="trace-dedup-001",
        run_id=run_id,
    )


@pytest.mark.unit
def test_fingerprint_is_stable_for_equivalent_arguments_and_hides_raw_input() -> None:
    first = DedupInput(
        order_id="ORDER-003",
        options={"limit": 10, "offset": 0},
    )
    second = DedupInput(
        order_id="ORDER-003",
        options={"offset": 0, "limit": 10},
    )

    first_fingerprint = build_tool_call_fingerprint("dedup_order", first)
    second_fingerprint = build_tool_call_fingerprint("dedup_order", second)

    assert first_fingerprint == second_fingerprint
    assert re.fullmatch(r"[0-9a-f]{64}", first_fingerprint)
    assert "ORDER-003" not in first_fingerprint


@pytest.mark.unit
def test_fingerprint_changes_with_tool_name_or_validated_arguments() -> None:
    tool_input = DedupInput(order_id="ORDER-003")

    original = build_tool_call_fingerprint("dedup_order", tool_input)

    assert build_tool_call_fingerprint("other_order", tool_input) != original
    assert (
        build_tool_call_fingerprint(
            "dedup_order",
            DedupInput(order_id="ORDER-004"),
        )
        != original
    )


@pytest.mark.unit
def test_tool_context_owns_a_private_run_scoped_ledger() -> None:
    context = tool_context()

    assert context.tool_call_ledger.run_id == "run-dedup-001"
    assert context.tool_call_ledger.recorded_call_count == 0
    assert "tool_call_ledger" not in context.model_dump()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_tool_and_arguments_are_blocked_within_one_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tool = DedupTool()
    context = tool_context()

    first = await tool.execute({"order_id": "ORDER-003"}, context)
    with caplog.at_level(logging.WARNING, logger="agent-service.tool"):
        duplicate = await tool.execute({"order_id": "ORDER-003"}, context)

    assert first.success is True
    assert duplicate.success is False
    assert duplicate.error is not None
    assert duplicate.error.code is ToolErrorCode.DUPLICATE_CALL
    assert duplicate.error.retryable is False
    assert duplicate.error.trace_id == "trace-dedup-001"
    assert tool.calls == 1
    assert context.tool_call_ledger.recorded_call_count == 1
    duplicate_record = next(
        record for record in caplog.records if record.message == "duplicate_tool_call_blocked"
    )
    assert duplicate_record.tool_name == "dedup_order"  # type: ignore[attr-defined]
    assert duplicate_record.run_id == "run-dedup-001"  # type: ignore[attr-defined]
    assert duplicate_record.error_code == "DUPLICATE_CALL"  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_different_arguments_are_allowed_within_one_run() -> None:
    tool = DedupTool()
    context = tool_context()

    first = await tool.execute({"order_id": "ORDER-003"}, context)
    second = await tool.execute({"order_id": "ORDER-004"}, context)

    assert first.success is True
    assert second.success is True
    assert tool.calls == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_call_is_allowed_in_different_runs() -> None:
    tool = DedupTool()

    first = await tool.execute(
        {"order_id": "ORDER-003"},
        tool_context(run_id="run-dedup-001"),
    )
    second = await tool.execute(
        {"order_id": "ORDER-003"},
        tool_context(run_id="run-dedup-002"),
    )

    assert first.success is True
    assert second.success is True
    assert tool.calls == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_refresh_explicitly_allows_the_same_call_again() -> None:
    tool = DedupTool()
    context = tool_context()

    first = await tool.execute({"order_id": "ORDER-003"}, context)
    refreshed = await tool.execute(
        {"order_id": "ORDER-003"},
        context,
        force_refresh=True,
    )
    blocked_again = await tool.execute({"order_id": "ORDER-003"}, context)

    assert first.success is True
    assert refreshed.success is True
    assert blocked_again.success is False
    assert blocked_again.error is not None
    assert blocked_again.error.code is ToolErrorCode.DUPLICATE_CALL
    assert tool.calls == 2
    assert context.tool_call_ledger.recorded_call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_identical_calls_reserve_only_one_execution() -> None:
    tool = DedupTool()
    context = tool_context()

    results = await asyncio.gather(
        tool.execute({"order_id": "ORDER-003"}, context),
        tool.execute({"order_id": "ORDER-003"}, context),
    )

    assert sum(result.success for result in results) == 1
    errors = [result.error for result in results if result.error is not None]
    assert len(errors) == 1
    assert errors[0].code is ToolErrorCode.DUPLICATE_CALL
    assert tool.calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_refresh_requires_a_real_boolean() -> None:
    tool = DedupTool()

    with pytest.raises(ValueError, match="force_refresh"):
        await tool.execute(
            {"order_id": "ORDER-003"},
            tool_context(),
            force_refresh="true",  # type: ignore[arg-type]
        )
