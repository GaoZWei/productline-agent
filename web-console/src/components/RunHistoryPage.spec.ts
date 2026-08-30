import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  requestRunDetail,
  requestRunHistory,
  requestRunSteps,
} from "../api/runHistoryClient";
import type { RunDetailResponse, RunSummary, StepSummary } from "../types/runHistory";
import RunHistoryPage from "./RunHistoryPage.vue";

vi.mock("../api/runHistoryClient", () => ({
  requestRunHistory: vi.fn(),
  requestRunDetail: vi.fn(),
  requestRunSteps: vi.fn(),
}));

const mockedHistory = vi.mocked(requestRunHistory);
const mockedDetail = vi.mocked(requestRunDetail);
const mockedSteps = vi.mocked(requestRunSteps);
let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;

afterEach(() => {
  application?.unmount();
  host?.remove();
  application = undefined;
  host = undefined;
  vi.resetAllMocks();
});

describe("Run history page", () => {
  it("展示Run详情、Step摘要、规范引用和Approval修改记录", async () => {
    mockedHistory.mockResolvedValue({ items: [runSummary()], page: 1, page_size: 10, total: 1 });
    mockedDetail.mockResolvedValue(runDetail());
    mockedSteps.mockResolvedValue({ run_id: "run-history-003", items: [toolStep()] });

    mountPage();
    await settleUi();

    expect(host?.textContent).toContain("ORDER-003");
    expect(host?.textContent).toContain("run-history-003");
    expect(host?.textContent).toContain("get_quality_issues");
    expect(host?.textContent).toContain("task_id=TASK-003");
    expect(host?.textContent).toContain("issue_count=1");
    expect(host?.textContent).toContain("坐标系统处理规范");
    expect(host?.textContent).toContain("用户修改 1 项");
    expect(host?.textContent).toContain("用户确认先完成返工");
    expect(mockedDetail).toHaveBeenCalledWith("run-history-003");
    expect(mockedSteps).toHaveBeenCalledWith("run-history-003");
  });

  it("突出展示失败Run的错误码、失败步骤和终止原因", async () => {
    const failed = runSummary({
      status: "FAILED",
      error_code: "UPSTREAM_UNAVAILABLE",
      error_step: "load_quality",
      termination_reason: "EXECUTION_ERROR",
    });
    mockedHistory.mockResolvedValue({ items: [failed], page: 1, page_size: 10, total: 1 });
    mockedDetail.mockResolvedValue({
      run: failed,
      input_token_count: 0,
      output_token_count: 0,
      result: null,
      approvals: [],
    });
    mockedSteps.mockResolvedValue({ run_id: failed.run_id, items: [] });

    mountPage();
    await settleUi();

    expect(host?.querySelector('[data-testid="run-error-detail"]')).toBeTruthy();
    expect(host?.textContent).toContain("UPSTREAM_UNAVAILABLE");
    expect(host?.textContent).toContain("load_quality");
    expect(host?.textContent).toContain("EXECUTION_ERROR");
  });
});

function mountPage() {
  host = document.createElement("div");
  document.body.append(host);
  application = createApp(RunHistoryPage);
  application.mount(host);
}

async function settleUi() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "run-history-003",
    session_id: "session-history-003",
    status: "SUCCEEDED",
    order_id: "ORDER-003",
    task_id: "TASK-003",
    tool_call_count: 6,
    total_token_count: 0,
    duration_ms: 320,
    termination_reason: "COMPLETED",
    error_code: null,
    error_step: null,
    created_at: "2026-08-30T02:00:00Z",
    started_at: "2026-08-30T02:00:00Z",
    finished_at: "2026-08-30T02:00:00.320Z",
    ...overrides,
  };
}

function toolStep(): StepSummary {
  return {
    step_id: "step-history-tool",
    sequence_number: 1,
    step_type: "TOOL",
    step_name: "get_quality_issues",
    status: "SUCCEEDED",
    input_summary: "task_id=TASK-003",
    output_summary: "issue_count=1",
    error_code: null,
    duration_ms: 12,
    created_at: "2026-08-30T02:00:00Z",
    started_at: "2026-08-30T02:00:00Z",
    finished_at: "2026-08-30T02:00:00.012Z",
  };
}

function runDetail(): RunDetailResponse {
  const originalDraft = {
    task_id: "TASK-003",
    issue_id: "ISSUE-001",
    conclusion: "REWORK_REQUIRED" as const,
    problem_summary: "存在未关闭的坐标系质量问题",
    review_comment: "Agent原始意见",
    specification_references: [
      {
        document_id: "SPEC-COORD-001",
        document_name: "坐标系统处理规范",
        document_version: "2.0",
        section: ["质量复核", "坐标系统"],
        chunk_id: "CHUNK-COORD-001",
        chunk_ids: ["CHUNK-COORD-001"],
        content: "坐标系统问题关闭后方可重新提交复核。",
        relevance_score: 0.98,
      },
    ],
    suggested_rework: { required: true, type: "COORDINATE_SYSTEM_FIX" as const },
  };
  return {
    run: runSummary(),
    input_token_count: 0,
    output_token_count: 0,
    result: null,
    approvals: [
      {
        approval_id: "approval-history-003",
        status: "SUCCEEDED",
        operation_type: "SUBMIT_REVIEW",
        target_id: "TASK-003",
        target_version: 7,
        original_draft: originalDraft,
        effective_draft: { ...originalDraft, review_comment: "用户确认先完成返工" },
        user_modification_diff: [
          { field_path: "review_comment", before: "Agent原始意见", after: "用户确认先完成返工" },
        ],
        confirmed_at: "2026-08-30T02:01:00Z",
        created_at: "2026-08-30T02:00:00Z",
        updated_at: "2026-08-30T02:01:00Z",
      },
    ],
  };
}
