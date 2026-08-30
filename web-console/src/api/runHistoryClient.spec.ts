import AxiosMockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";

import { agentHttpClient } from "./agentClient";
import { requestRunDetail, requestRunHistory, requestRunSteps } from "./runHistoryClient";

const mock = new AxiosMockAdapter(agentHttpClient);

afterEach(() => mock.reset());

describe("run history client", () => {
  it("校验并返回Run列表、详情和Step时间线", async () => {
    mock.onGet("/api/agent/runs?page=1&page_size=10").reply(200, {
      items: [runSummary()],
      page: 1,
      page_size: 10,
      total: 1,
    });
    mock.onGet("/api/agent/runs/run-history-003").reply(200, {
      run: runSummary(),
      input_token_count: 12,
      output_token_count: 4,
      result: null,
      approvals: [],
    });
    mock.onGet("/api/agent/runs/run-history-003/steps").reply(200, {
      run_id: "run-history-003",
      items: [stepSummary()],
    });

    await expect(requestRunHistory(1, 10)).resolves.toMatchObject({ total: 1 });
    await expect(requestRunDetail("run-history-003")).resolves.toMatchObject({
      input_token_count: 12,
    });
    await expect(requestRunSteps("run-history-003")).resolves.toMatchObject({
      items: [expect.objectContaining({ step_type: "TOOL" })],
    });
  });

  it("拒绝无法识别的响应，并保留后端安全错误", async () => {
    mock.onGet("/api/agent/runs?page=1&page_size=10").reply(200, {
      items: [{ run_id: "incomplete" }],
      page: 1,
      page_size: 10,
      total: 1,
    });
    mock.onGet("/api/agent/runs/run-foreign").reply(404, {
      trace_id: "trace-run-history",
      code: "RUN_NOT_FOUND",
      message: "run was not found",
    });

    await expect(requestRunHistory(1, 10)).rejects.toMatchObject({
      code: "RESPONSE_VALIDATION_ERROR",
    });
    await expect(requestRunDetail("run-foreign")).rejects.toMatchObject({
      code: "RUN_NOT_FOUND",
      traceId: "trace-run-history",
      status: 404,
    });
  });
});

function runSummary() {
  return {
    run_id: "run-history-003",
    session_id: "session-history-003",
    status: "SUCCEEDED",
    order_id: "ORDER-003",
    task_id: "TASK-003",
    tool_call_count: 6,
    total_token_count: 16,
    duration_ms: 320,
    termination_reason: "COMPLETED",
    error_code: null,
    error_step: null,
    created_at: "2026-08-30T02:00:00Z",
    started_at: "2026-08-30T02:00:00Z",
    finished_at: "2026-08-30T02:00:00.320Z",
  };
}

function stepSummary() {
  return {
    step_id: "step-history-003",
    sequence_number: 1,
    step_type: "TOOL",
    step_name: "get_order",
    status: "SUCCEEDED",
    input_summary: "order_id=ORDER-003",
    output_summary: "status=IN_PROGRESS",
    error_code: null,
    duration_ms: 12,
    created_at: "2026-08-30T02:00:00Z",
    started_at: "2026-08-30T02:00:00Z",
    finished_at: "2026-08-30T02:00:00.012Z",
  };
}
