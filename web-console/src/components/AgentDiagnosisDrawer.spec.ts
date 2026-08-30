import { createApp, nextTick, type App } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { diagnoseOrder } from "../api/agentApi";
import { AgentApiError } from "../api/agentClient";
import {
  createRunEventStreamId,
  openRunEventStream,
  type OpenRunEventStreamOptions,
} from "../api/runEventClient";
import type { OrderDiagnosisResponse } from "../types/agent";
import type { RunEvent } from "../types/runEvents";
import AgentDiagnosisDrawer from "./AgentDiagnosisDrawer.vue";

vi.mock("../api/agentApi", () => ({ diagnoseOrder: vi.fn() }));
vi.mock("../api/runEventClient", () => ({
  createRunEventStreamId: vi.fn(),
  openRunEventStream: vi.fn(),
  RunEventClientError: class RunEventClientError extends Error {},
}));

const mockedDiagnoseOrder = vi.mocked(diagnoseOrder);
const mockedCreateStreamId = vi.mocked(createRunEventStreamId);
const mockedOpenStream = vi.mocked(openRunEventStream);
let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;

beforeEach(() => {
  mockedCreateStreamId.mockReturnValue("stream-drawer-003");
  mockedOpenStream.mockImplementation((options) => {
    options.onStateChange?.({ status: "connecting", reconnectAttempt: 0 });
    options.onStateChange?.({ status: "open", reconnectAttempt: 0 });
    return {
      streamId: options.streamId,
      ready: Promise.resolve(),
      close: vi.fn(),
    };
  });
});

afterEach(() => {
  application?.unmount();
  host?.remove();
  host = undefined;
  application = undefined;
  vi.resetAllMocks();
});

describe("Agent diagnosis drawer", () => {
  it("显示当前订单、加载状态和完整诊断结果", async () => {
    let resolveDiagnosis!: (value: OrderDiagnosisResponse) => void;
    mockedDiagnoseOrder.mockReturnValue(
      new Promise((resolve) => {
        resolveDiagnosis = resolve;
      }),
    );
    mountDrawer();

    click('[data-testid="open-agent-drawer"]');
    await nextTick();
    expect(host?.textContent).toContain("ORDER-003");
    expect(host?.textContent).toContain("QUALITY_CHECKING");

    click('[data-testid="submit-diagnosis"]');
    await settleUi();
    expect(mockedDiagnoseOrder).toHaveBeenCalledWith(
      "ORDER-003",
      "这个订单为什么还没有交付？",
      {
        current_system: "production-system",
        current_page: "order-detail",
        order_id: "ORDER-003",
        task_id: null,
        issue_id: null,
        batch_id: null,
        product_type: "DOM",
        satellite_type: null,
        user_role: "REVIEWER",
      },
      undefined,
      "stream-drawer-003",
    );
    expect(host?.textContent).toContain("正在核对订单事实");

    resolveDiagnosis(goldenDiagnosis());
    await settleUi();

    expect(host?.textContent).toContain("QUALITY_REVIEW");
    expect(host?.textContent).toContain("未关闭的坐标系质量问题");
    expect(host?.textContent).toContain("4 条");
    expect(host?.textContent).toContain("reviews[0].status");
    expect(host?.textContent).toContain("PENDING");
    expect(host?.textContent).toContain("RESUBMIT_REVIEW");
    expect(host?.textContent).toContain("仅建议，未执行");
    expect(host?.textContent).toContain("trace-order-003");

    click('[data-testid="submit-diagnosis"]');
    await settleUi();
    expect(mockedDiagnoseOrder).toHaveBeenLastCalledWith(
      "ORDER-003",
      "这个订单为什么还没有交付？",
      expect.objectContaining({ order_id: "ORDER-003" }),
      "session-order-003",
      "stream-drawer-003",
    );
  });

  it("显示可定位、可重试的结构化错误", async () => {
    mockedDiagnoseOrder.mockRejectedValue(
      new AgentApiError({
        code: "UPSTREAM_TIMEOUT",
        message: "business service timed out",
        runId: "run-failed",
        traceId: "trace-failed",
        retryable: true,
        errorStep: "get_quality_issues",
        status: 504,
      }),
    );
    mountDrawer();

    click('[data-testid="open-agent-drawer"]');
    await nextTick();
    click('[data-testid="submit-diagnosis"]');
    await settleUi();

    expect(host?.textContent).toContain("UPSTREAM_TIMEOUT");
    expect(host?.textContent).toContain("business service timed out");
    expect(host?.textContent).toContain("Run ID：run-failed");
    expect(host?.textContent).toContain("失败步骤：get_quality_issues");
    expect(host?.textContent).toContain("Trace ID：trace-failed");
    expect(host?.textContent).toContain("重新诊断");
  });

  it("实时显示Tool步骤、失败状态和耗时", async () => {
    let streamOptions: OpenRunEventStreamOptions | undefined;
    let resolveDiagnosis!: (value: OrderDiagnosisResponse) => void;
    mockedOpenStream.mockImplementation((options) => {
      streamOptions = options;
      options.onStateChange?.({ status: "open", reconnectAttempt: 0 });
      return { streamId: options.streamId, ready: Promise.resolve(), close: vi.fn() };
    });
    mockedDiagnoseOrder.mockReturnValue(
      new Promise((resolve) => {
        resolveDiagnosis = resolve;
      }),
    );
    mountDrawer();

    click('[data-testid="open-agent-drawer"]');
    await nextTick();
    click('[data-testid="submit-diagnosis"]');
    await settleUi();
    streamOptions?.onEvent(runEvent("1", "run_started", "2026-08-29T03:00:00.000Z"));
    streamOptions?.onEvent(
      runEvent("2", "tool_started", "2026-08-29T03:00:01.000Z", {
        stepId: "step-quality",
        data: { step_name: "load_quality", status: "RUNNING" },
      }),
    );
    streamOptions?.onEvent(
      runEvent("3", "tool_completed", "2026-08-29T03:00:01.220Z", {
        stepId: "step-quality",
        data: {
          step_name: "load_quality",
          status: "FAILED",
          error_code: "RESOURCE_NOT_FOUND",
        },
      }),
    );
    await nextTick();

    expect(host?.textContent).toContain("实时执行步骤");
    expect(host?.textContent).toContain("查询质检问题");
    expect(host?.textContent).toContain("220 ms");
    expect(host?.textContent).toContain("RESOURCE_NOT_FOUND");
    expect(host?.querySelector('[data-status="failed"]')).toBeTruthy();

    resolveDiagnosis(goldenDiagnosis());
    await settleUi();
  });
});

function mountDrawer() {
  host = document.createElement("div");
  document.body.append(host);
  application = createApp(AgentDiagnosisDrawer, {
    order: {
      orderId: "ORDER-003",
      productType: "DOM",
      status: "QUALITY_CHECKING",
    },
  });
  application.mount(host);
}

function click(selector: string) {
  const element = host?.querySelector<HTMLButtonElement>(selector);
  expect(element).toBeTruthy();
  element?.click();
}

async function settleUi() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}

function goldenDiagnosis(): OrderDiagnosisResponse {
  return {
    run_id: "run-order-003",
    session_id: "session-order-003",
    trace_id: "trace-order-003",
    diagnosis: {
      order_id: "ORDER-003",
      blocking_stage: "QUALITY_REVIEW",
      summary: "订单阻塞在质量复核环节。",
      root_causes: [
        {
          code: "OPEN_COORDINATE_SYSTEM_ISSUE",
          description: "关联任务存在未关闭的坐标系质量问题",
        },
        { code: "REVIEW_PENDING", description: "质检复核尚未完成" },
      ],
      evidence: [
        evidence("get_related_tasks", "tasks[0].status", "COMPLETED", "生产已完成"),
        evidence("get_quality_issues", "issues[0].status", "OPEN", "问题仍未关闭"),
        evidence("get_review_result", "reviews[0].status", "PENDING", "复核仍在等待"),
        evidence("get_delivery_status", "records[0].status", "BLOCKED", "交付被阻塞"),
      ],
      suggestions: [
        {
          action_type: "CREATE_COORDINATE_SYSTEM_REWORK",
          description: "创建坐标系处理返工任务",
        },
        { action_type: "RESUBMIT_REVIEW", description: "处理后重新提交复核" },
      ],
      confidence: 1,
    },
  };
}

function evidence(toolName: string, fieldPath: string, value: string, description: string) {
  return {
    source_type: "TOOL" as const,
    tool_name: toolName,
    field_path: fieldPath,
    value,
    description,
  };
}

function runEvent(
  eventId: string,
  eventType: RunEvent["event_type"],
  occurredAt: string,
  options: { stepId?: string; data?: RunEvent["data"] } = {},
): RunEvent {
  return {
    event_id: eventId,
    event_type: eventType,
    stream_id: "stream-drawer-003",
    run_id: "run-drawer-003",
    sequence_number: Number(eventId),
    occurred_at: occurredAt,
    trace_id: "trace-drawer-003",
    step_id: options.stepId ?? null,
    data: options.data ?? {},
  };
}
