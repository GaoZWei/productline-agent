"""M7.8统一EvalRunner的注册、顺序执行和失败隔离测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from pydantic import BaseModel, ConfigDict

from app.evaluation.runner import (
    EvalRunner,
    EvalRunnerConfigurationError,
    EvalSuiteExecutionError,
    EvalSuiteResultError,
    EvaluationSuite,
)


class _Report(BaseModel):
    """代表现有Router或RAG等套件返回的最小结构化报告。"""

    model_config = ConfigDict(frozen=True)

    value: int


def _executor(
    name: str,
    value: int,
    calls: list[str],
) -> Callable[[], Awaitable[BaseModel]]:
    async def execute() -> BaseModel:
        calls.append(name)
        return _Report(value=value)

    return execute


@pytest.mark.asyncio
async def test_runs_all_suites_sequentially_in_registration_order() -> None:
    calls: list[str] = []
    runner = EvalRunner(
        (
            EvaluationSuite("router", _executor("router", 1, calls)),
            EvaluationSuite("rag", _executor("rag", 2, calls)),
            EvaluationSuite("diagnosis", _executor("diagnosis", 3, calls)),
        )
    )

    reports = await runner.run()

    assert runner.suite_names == ("router", "rag", "diagnosis")
    assert calls == ["router", "rag", "diagnosis"]
    assert tuple(reports) == ("router", "rag", "diagnosis")
    assert reports["router"] == _Report(value=1)
    with pytest.raises(TypeError):
        reports["another"] = _Report(value=4)  # type: ignore[index]


@pytest.mark.asyncio
async def test_runs_selected_suites_in_explicit_order() -> None:
    calls: list[str] = []
    runner = EvalRunner(
        (
            EvaluationSuite("router", _executor("router", 1, calls)),
            EvaluationSuite("rag", _executor("rag", 2, calls)),
            EvaluationSuite("approval", _executor("approval", 3, calls)),
        )
    )

    reports = await runner.run(("approval", "router"))

    assert calls == ["approval", "router"]
    assert tuple(reports) == ("approval", "router")


@pytest.mark.parametrize("name", ["", "Router", "rag-eval", "1router", "a" * 65])
def test_rejects_invalid_suite_names(name: str) -> None:
    async def execute() -> BaseModel:
        return _Report(value=1)

    with pytest.raises(EvalRunnerConfigurationError):
        EvaluationSuite(name, execute)


def test_rejects_empty_or_duplicate_registration() -> None:
    calls: list[str] = []
    suite = EvaluationSuite("router", _executor("router", 1, calls))

    with pytest.raises(EvalRunnerConfigurationError, match="at least one"):
        EvalRunner(())
    with pytest.raises(EvalRunnerConfigurationError, match="unique"):
        EvalRunner((suite, suite))


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [(), ("router", "router"), ("missing",)])
async def test_rejects_invalid_selection_before_starting_any_suite(
    selection: tuple[str, ...],
) -> None:
    calls: list[str] = []
    runner = EvalRunner((EvaluationSuite("router", _executor("router", 1, calls)),))

    with pytest.raises(EvalRunnerConfigurationError):
        await runner.run(selection)

    assert calls == []


@pytest.mark.asyncio
async def test_identifies_failed_suite_without_exposing_original_error() -> None:
    calls: list[str] = []

    async def fail() -> BaseModel:
        calls.append("rag")
        raise RuntimeError("sensitive provider response")

    runner = EvalRunner(
        (
            EvaluationSuite("router", _executor("router", 1, calls)),
            EvaluationSuite("rag", fail),
            EvaluationSuite("approval", _executor("approval", 3, calls)),
        )
    )

    with pytest.raises(EvalSuiteExecutionError) as captured:
        await runner.run()

    assert captured.value.suite_name == "rag"
    assert str(captured.value) == "evaluation suite failed: rag"
    assert "sensitive" not in str(captured.value)
    assert calls == ["router", "rag"]


@pytest.mark.asyncio
async def test_rejects_non_pydantic_report_and_preserves_cancellation() -> None:
    async def invalid_report() -> BaseModel:
        return {"value": 1}  # type: ignore[return-value]

    invalid_runner = EvalRunner((EvaluationSuite("tools", invalid_report),))
    with pytest.raises(EvalSuiteResultError, match="tools"):
        await invalid_runner.run()

    async def cancel() -> BaseModel:
        raise asyncio.CancelledError

    cancelled_runner = EvalRunner((EvaluationSuite("router", cancel),))
    with pytest.raises(asyncio.CancelledError):
        await cancelled_runner.run()
