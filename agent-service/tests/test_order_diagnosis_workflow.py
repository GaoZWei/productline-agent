"""M2.5 固定订单诊断 Workflow 节点、状态合并和失败中断测试。"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode
from app.models import AgentStepType
from app.schemas.business import BusinessIdentity
from app.settings import Settings
from app.tools import ToolContext, create_read_tool_registry
from app.workflows import OrderDiagnosisWorkflow, WorkflowStepRecorder


def _success(data: object, trace_id: str = "trace-workflow-003") -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": True,
            "code": "SUCCESS",
            "message": "ok",
            "data": data,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


def _not_found(trace_id: str = "trace-workflow-003") -> httpx.Response:
    return httpx.Response(
        404,
        headers={"X-Trace-Id": trace_id},
        json={
            "success": False,
            "code": "RESOURCE_NOT_FOUND",
            "message": "quality issues were not found",
            "data": None,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


def _settings() -> Settings:
    return Settings(
        environment="test",
        business_service_url=AnyHttpUrl("http://business.test"),
    )


def _context(*, run_id: str = "run-workflow-003") -> ToolContext:
    return ToolContext(
        identity=BusinessIdentity(user_id="workflow-user", role="REVIEWER"),
        permissions=frozenset(
            {
                "ORDER_READ",
                "TASK_READ",
                "QUALITY_ISSUE_READ",
                "REVIEW_READ",
                "DELIVERY_READ",
            }
        ),
        trace_id="trace-workflow-003",
        run_id=run_id,
    )


@dataclass(slots=True)
class RecordedStep:
    step_id: str
    run_id: str
    sequence_number: int
    step_type: AgentStepType
    step_name: str
    input_summary: str | None
    status: str = "RUNNING"
    output_summary: str | None = None
    error_code: str | None = None


@dataclass(slots=True)
class MemoryStepRecorder(WorkflowStepRecorder):
    steps: list[RecordedStep] = field(default_factory=list)

    async def start_step(
        self,
        *,
        step_id: str,
        run_id: str,
        sequence_number: int,
        step_type: AgentStepType,
        step_name: str,
        input_summary: str | None,
    ) -> None:
        self.steps.append(
            RecordedStep(
                step_id=step_id,
                run_id=run_id,
                sequence_number=sequence_number,
                step_type=step_type,
                step_name=step_name,
                input_summary=input_summary,
            )
        )

    async def mark_succeeded(
        self,
        step_id: str,
        *,
        output_summary: str | None,
    ) -> None:
        step = self._find(step_id)
        step.status = "SUCCEEDED"
        step.output_summary = output_summary

    async def mark_failed(
        self,
        step_id: str,
        *,
        error_code: str,
        output_summary: str | None,
    ) -> None:
        step = self._find(step_id)
        step.status = "FAILED"
        step.error_code = error_code
        step.output_summary = output_summary

    def _find(self, step_id: str) -> RecordedStep:
        return next(step for step in self.steps if step.step_id == step_id)


def _golden_handler(calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        responses: dict[str, object] = {
            "/api/orders/ORDER-003": {
                "orderId": "ORDER-003",
                "productType": "DOM",
                "status": "QUALITY_CHECKING",
            },
            "/api/orders/ORDER-003/tasks": {
                "orderId": "ORDER-003",
                "tasks": [
                    {
                        "taskId": "TASK-003",
                        "orderId": "ORDER-003",
                        "status": "COMPLETED",
                        "version": 0,
                    }
                ],
            },
            "/api/tasks/TASK-003": {
                "taskId": "TASK-003",
                "orderId": "ORDER-003",
                "status": "COMPLETED",
                "version": 0,
            },
            "/api/tasks/TASK-003/progress": {
                "taskId": "TASK-003",
                "steps": [
                    {
                        "stepId": "STEP-003-01",
                        "taskId": "TASK-003",
                        "stepName": "DOM production",
                        "sequenceNumber": 1,
                        "status": "COMPLETED",
                    }
                ],
            },
            "/api/tasks/TASK-003/quality-issues": {
                "taskId": "TASK-003",
                "issues": [
                    {
                        "issueId": "ISSUE-001",
                        "taskId": "TASK-003",
                        "issueType": "COORDINATE_SYSTEM",
                        "status": "OPEN",
                        "description": "coordinate system mismatch",
                    }
                ],
            },
            "/api/tasks/TASK-003/review": {
                "taskId": "TASK-003",
                "reviews": [
                    {
                        "reviewId": "REVIEW-003",
                        "issueId": "ISSUE-001",
                        "status": "PENDING",
                        "reviewComment": None,
                    }
                ],
            },
            "/api/orders/ORDER-003/delivery-status": {
                "orderId": "ORDER-003",
                "records": [
                    {
                        "deliveryId": "DELIVERY-003",
                        "orderId": "ORDER-003",
                        "status": "BLOCKED",
                    }
                ],
            },
        }
        return _success(responses[request.url.path])

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fixed_workflow_loads_order_003_in_declared_order_and_merges_state() -> None:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_golden_handler(calls))
    recorder = MemoryStepRecorder()
    workflow = OrderDiagnosisWorkflow(
        tool_registry=create_read_tool_registry(client),
        tool_context=_context(),
        step_recorder=recorder,
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert calls == [
        "/api/orders/ORDER-003",
        "/api/orders/ORDER-003/tasks",
        "/api/tasks/TASK-003/progress",
        "/api/tasks/TASK-003/quality-issues",
        "/api/tasks/TASK-003/review",
        "/api/orders/ORDER-003/delivery-status",
    ]
    assert state["run_id"] == "run-workflow-003"
    assert state["order"] is not None
    assert state["order"].order_id == "ORDER-003"
    assert [task.task_id for task in state["tasks"]] == ["TASK-003"]
    assert list(state["progress"]) == ["TASK-003"]
    assert state["quality_issues"]["TASK-003"][0].issue_id == "ISSUE-001"
    assert state["reviews"]["TASK-003"] is not None
    assert state["delivery"] is not None
    assert state["delivery"].records[0].status == "BLOCKED"
    assert state["diagnosis"] is None
    assert state["errors"] == []
    assert [step.sequence_number for step in recorder.steps] == list(range(1, 8))
    assert [step.step_name for step in recorder.steps] == [
        "load_context",
        "load_order",
        "load_tasks",
        "load_progress",
        "load_quality",
        "load_review",
        "load_delivery",
    ]
    assert all(step.status == "SUCCEEDED" for step in recorder.steps)


@pytest.mark.asyncio
async def test_multi_task_nodes_merge_results_by_stable_task_id() -> None:
    calls: list[str] = []
    golden_transport = _golden_handler(calls)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/orders/ORDER-003/tasks":
            calls.append(request.url.path)
            return _success(
                {
                    "orderId": "ORDER-003",
                    "tasks": [
                        {
                            "taskId": "TASK-004",
                            "orderId": "ORDER-003",
                            "status": "COMPLETED",
                            "version": 1,
                        },
                        {
                            "taskId": "TASK-003",
                            "orderId": "ORDER-003",
                            "status": "COMPLETED",
                            "version": 0,
                        },
                    ],
                }
            )
        if request.url.path == "/api/tasks/TASK-004/progress":
            calls.append(request.url.path)
            return _success({"taskId": "TASK-004", "steps": []})
        if request.url.path == "/api/tasks/TASK-004/quality-issues":
            calls.append(request.url.path)
            return _success({"taskId": "TASK-004", "issues": []})
        if request.url.path == "/api/tasks/TASK-004/review":
            calls.append(request.url.path)
            return _success({"taskId": "TASK-004", "reviews": []})
        return golden_transport.handle_request(request)

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    recorder = MemoryStepRecorder()
    workflow = OrderDiagnosisWorkflow(
        tool_registry=create_read_tool_registry(client),
        tool_context=_context(run_id="run-workflow-multi-task"),
        step_recorder=recorder,
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert [task.task_id for task in state["tasks"]] == ["TASK-003", "TASK-004"]
    assert list(state["progress"]) == ["TASK-003", "TASK-004"]
    assert list(state["quality_issues"]) == ["TASK-003", "TASK-004"]
    assert list(state["reviews"]) == ["TASK-003", "TASK-004"]
    assert calls.index("/api/tasks/TASK-003/progress") < calls.index(
        "/api/tasks/TASK-004/progress"
    )
    assert calls.index("/api/tasks/TASK-003/quality-issues") < calls.index(
        "/api/tasks/TASK-004/quality-issues"
    )
    assert calls.index("/api/tasks/TASK-003/review") < calls.index(
        "/api/tasks/TASK-004/review"
    )
    assert [step.sequence_number for step in recorder.steps] == list(range(1, 11))
    assert all(step.status == "SUCCEEDED" for step in recorder.steps)


@pytest.mark.asyncio
async def test_tool_failure_is_added_to_state_and_interrupts_later_nodes() -> None:
    calls: list[str] = []
    golden_transport = _golden_handler(calls)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tasks/TASK-003/quality-issues":
            calls.append(request.url.path)
            return _not_found()
        return golden_transport.handle_request(request)

    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(handler))
    recorder = MemoryStepRecorder()
    workflow = OrderDiagnosisWorkflow(
        tool_registry=create_read_tool_registry(client),
        tool_context=_context(),
        step_recorder=recorder,
    )

    try:
        state = await workflow.ainvoke("ORDER-003")
    finally:
        await client.aclose()

    assert calls[-1] == "/api/tasks/TASK-003/quality-issues"
    assert "/api/tasks/TASK-003/review" not in calls
    assert "/api/orders/ORDER-003/delivery-status" not in calls
    assert state["progress"]["TASK-003"].task_id == "TASK-003"
    assert state["quality_issues"] == {}
    assert state["reviews"] == {}
    assert state["delivery"] is None
    assert len(state["errors"]) == 1
    error = state["errors"][0]
    assert error.step_name == "load_quality"
    assert error.code is ToolErrorCode.RESOURCE_NOT_FOUND
    assert error.retryable is False
    assert error.trace_id == "trace-workflow-003"
    assert recorder.steps[-1].status == "FAILED"
    assert recorder.steps[-1].error_code == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_invalid_order_context_stops_before_any_business_tool_call() -> None:
    calls: list[str] = []
    client = BusinessHttpClient(_settings(), transport=_golden_handler(calls))
    recorder = MemoryStepRecorder()
    workflow = OrderDiagnosisWorkflow(
        tool_registry=create_read_tool_registry(client),
        tool_context=_context(),
        step_recorder=recorder,
    )

    try:
        state = await workflow.ainvoke("invalid-order")
    finally:
        await client.aclose()

    assert calls == []
    assert state["order"] is None
    assert len(state["errors"]) == 1
    assert state["errors"][0].step_name == "load_context"
    assert state["errors"][0].code is ToolErrorCode.PARAM_VALIDATION_ERROR
    assert recorder.steps[0].status == "FAILED"


@pytest.mark.asyncio
async def test_compiled_graph_contains_only_m25_loader_nodes() -> None:
    client = BusinessHttpClient(_settings(), transport=httpx.MockTransport(lambda _: _success({})))
    workflow = OrderDiagnosisWorkflow(
        tool_registry=create_read_tool_registry(client),
        tool_context=_context(),
        step_recorder=MemoryStepRecorder(),
    )

    try:
        graph = workflow.graph.get_graph()
    finally:
        await client.aclose()

    assert set(graph.nodes) == {
        "__start__",
        "load_context",
        "load_order",
        "load_tasks",
        "load_progress",
        "load_quality",
        "load_review",
        "load_delivery",
        "__end__",
    }
