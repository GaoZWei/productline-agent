import { createApp, h, nextTick, ref, type App, type Ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelReviewApproval,
  confirmReviewApproval,
  createReworkApproval,
  diagnoseOrder,
  getAgentCapabilities,
  sendAgentMessage,
} from "../api/agentApi";
import { AgentApiError } from "../api/agentClient";
import { BusinessApiError } from "../api/businessClient";
import { createRunEventStreamId, openRunEventStream } from "../api/runEventClient";
import type { AgentMessageResponse, ApprovalAgentResult } from "../types/agent";
import type { Order } from "../types/business";
import AgentWorkspaceDrawer from "./AgentWorkspaceDrawer.vue";

vi.mock("../api/agentApi", () => ({
  cancelReviewApproval: vi.fn(),
  confirmReviewApproval: vi.fn(),
  createReworkApproval: vi.fn(),
  diagnoseOrder: vi.fn(),
  getAgentCapabilities: vi.fn(),
  sendAgentMessage: vi.fn(),
}));
vi.mock("../api/runEventClient", () => ({
  createRunEventStreamId: vi.fn(),
  openRunEventStream: vi.fn(),
  RunEventClientError: class RunEventClientError extends Error {},
}));

const mockedSend = vi.mocked(sendAgentMessage);
const mockedCapabilities = vi.mocked(getAgentCapabilities);
const mockedConfirm = vi.mocked(confirmReviewApproval);
const mockedCancel = vi.mocked(cancelReviewApproval);
const mockedRework = vi.mocked(createReworkApproval);
const mockedFixedDiagnosis = vi.mocked(diagnoseOrder);
const mockedStreamId = vi.mocked(createRunEventStreamId);
const mockedOpenStream = vi.mocked(openRunEventStream);
let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;
let selectedOrder: Ref<Order> | undefined;
let streamSequence = 0;

beforeEach(() => {
  streamSequence = 0;
  mockedStreamId.mockImplementation(() => `stream-${++streamSequence}`);
  mockedOpenStream.mockImplementation((options) => {
    options.onStateChange?.({ status: "open", reconnectAttempt: 0 });
    return { streamId: options.streamId, ready: Promise.resolve(), close: vi.fn() };
  });
  mockedCapabilities.mockResolvedValue({
    message_api_enabled: true,
    result_kinds: [
      "ORDER_STATUS",
      "DIAGNOSIS",
      "SPECIFICATION_ANSWER",
      "CLARIFICATION",
      "APPROVAL",
    ],
    model: { configured: true, provider: "openai_compatible", model_name: "agent-model" },
    knowledge_index: {
      ready: false,
      status: "NOT_INDEXED",
      expected_document_count: 16,
      document_count: 0,
      chunk_count: 0,
      expected_index: indexIdentity(),
      stored_index: null,
    },
  });
});

afterEach(() => {
  application?.unmount();
  host?.remove();
  host = undefined;
  application = undefined;
  selectedOrder = undefined;
  vi.resetAllMocks();
});

describe("Agent workspace drawer", () => {
  it("跨页确认先加载目标，阻止重复点击，再用原问题和新会话发送", async () => {
    mockedSend.mockResolvedValueOnce(switchResponse()).mockResolvedValueOnce(statusResponse("session-new", "run-new"));
    let finishLoad: (() => void) | undefined;
    const switchOrder = vi.fn(() => new Promise<Order>((resolve) => {
      finishLoad = () => {
        const order = { orderId: "ORDER-003", productType: "DOM", status: "QUALITY_CHECKING" };
        selectedOrder!.value = order;
        resolve(order);
      };
    }));
    mountDrawer(switchOrder, "ORDER-001");
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    input('[data-testid="agent-message-input"]', "诊断 ORDER-003 为什么没有交付");
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    expect(host?.textContent).toContain("当前页面是 ORDER-001");
    click('[data-testid="confirm-order-switch"]');
    click('[data-testid="confirm-order-switch"]');
    expect(switchOrder).toHaveBeenCalledTimes(1);
    expect(mockedSend).toHaveBeenCalledTimes(1);
    finishLoad?.();
    await settleUi();
    expect(mockedSend).toHaveBeenCalledTimes(2);
    expect(mockedSend).toHaveBeenLastCalledWith(expect.objectContaining({
      message: "诊断 ORDER-003 为什么没有交付", session_id: undefined,
      page_context: expect.objectContaining({ order_id: "ORDER-003" }),
    }), "stream-2");
    expect(host?.textContent).toContain("确定性状态");
    expect(host?.querySelector('[data-testid="order-switch-prompt"]')).toBeNull();
    const oldStream = mockedOpenStream.mock.calls[0]?.[0];
    oldStream?.onError?.({ code: "OLD_STREAM", message: "旧订单迟到错误" } as never);
    await settleUi();
    expect(host?.textContent).not.toContain("旧订单迟到错误");
  });

  it("取消切换时保持当前页面且不发送目标诊断", async () => {
    mockedSend.mockResolvedValueOnce(switchResponse());
    const switchOrder = vi.fn();
    mountDrawer(switchOrder, "ORDER-001");
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    click('[data-testid="cancel-order-switch"]');
    await settleUi();
    expect(selectedOrder?.value.orderId).toBe("ORDER-001");
    expect(switchOrder).not.toHaveBeenCalled();
    expect(mockedSend).toHaveBeenCalledTimes(1);
    expect(host?.textContent).toContain("已取消切换");
  });

  it.each([[403, "PERMISSION_DENIED"], [404, "RESOURCE_NOT_FOUND"]])(
    "目标加载失败%s保留原页并停止诊断", async (status, code) => {
      mockedSend.mockResolvedValueOnce(switchResponse());
      const switchOrder = vi.fn().mockRejectedValue(new BusinessApiError({ code, message: "目标订单不可读取", status }));
      mountDrawer(switchOrder, "ORDER-001");
      click('[data-testid="open-agent-drawer"]');
      await settleUi();
      click('[data-testid="submit-agent-message"]');
      await settleUi();
      click('[data-testid="confirm-order-switch"]');
      await settleUi();
      expect(host?.textContent).toContain(code);
      expect(selectedOrder?.value.orderId).toBe("ORDER-001");
      expect(mockedSend).toHaveBeenCalledTimes(1);
    },
  );

  it("加载目标期间手动切页后不继续原请求", async () => {
    mockedSend.mockResolvedValueOnce(switchResponse());
    let finishLoad: ((order: Order) => void) | undefined;
    mountDrawer(() => new Promise((resolve) => { finishLoad = resolve; }), "ORDER-001");
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    click('[data-testid="confirm-order-switch"]');
    selectedOrder!.value = { orderId: "ORDER-005", productType: "DOM", status: "READY_FOR_DELIVERY" };
    await settleUi();
    finishLoad?.({ orderId: "ORDER-003", productType: "DOM", status: "QUALITY_CHECKING" });
    await settleUi();
    expect(mockedSend).toHaveBeenCalledTimes(1);
    expect(host?.textContent).not.toContain("确定性状态");
  });
  it("使用新事件流发送统一消息并在同一订单复用Session", async () => {
    mockedSend
      .mockResolvedValueOnce(statusResponse("session-003", "run-status"))
      .mockResolvedValueOnce(specificationResponse("session-003", "run-specification"));
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();

    expect(host?.textContent).toContain("模型 agent-model");
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    expect(mockedSend).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ session_id: undefined }),
      "stream-1",
    );
    expect(host?.textContent).toContain("确定性状态");
    expect(host?.textContent).toContain("BLOCKED");

    input('[data-testid="agent-message-input"]', "坐标系问题如何处理");
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    expect(mockedSend).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ session_id: "session-003", message: "坐标系问题如何处理" }),
      "stream-2",
    );
    expect(host?.textContent).toContain("规范回答");
    expect(host?.textContent).toContain("质量复核规范");
  });

  it("把受控澄清选项连同来源Run提交到同一Session", async () => {
    mockedSend
      .mockResolvedValueOnce(clarificationResponse())
      .mockResolvedValueOnce(statusResponse("session-003", "run-after-clarification"));
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    clickText("ORDER-004");
    await settleUi();

    expect(mockedSend).toHaveBeenLastCalledWith(
      expect.objectContaining({
        message: "选择 ORDER-004",
        session_id: "session-003",
        clarification: {
          source_run_id: "run-clarification",
          selection: { field: "order_id", value: "ORDER-004" },
        },
      }),
      "stream-2",
    );
  });

  it("接通Review确认、显式返工授权和第二次确认", async () => {
    mockedSend.mockResolvedValue(approvalResponse());
    mockedConfirm
      .mockResolvedValueOnce({
        approval_id: "approval-review",
        status: "SUCCEEDED",
        trace_id: "trace-confirm-review",
        result: {
          approval_id: "approval-review",
          task_id: "TASK-003",
          issue_id: "ISSUE-001",
          review_id: "REVIEW-003",
          status: "REWORK_REQUIRED",
          review_comment: "完成处理后重新复核",
          task_version: 8,
          java_trace_id: "trace-java-review",
        },
      })
      .mockResolvedValueOnce({
        approval_id: "approval-rework",
        status: "SUCCEEDED",
        trace_id: "trace-confirm-rework",
        result: {
          approval_id: "approval-rework",
          task_id: "TASK-003",
          source_issue_id: "ISSUE-001",
          rework_task_id: "REWORK-003",
          rework_type: "COORDINATE_SYSTEM_FIX",
          status: "PENDING",
          reason: "完成处理后重新复核",
          task_version: 9,
          java_trace_id: "trace-java-rework",
        },
      });
    mockedRework.mockResolvedValue({
      run_id: "run-rework",
      trace_id: "trace-rework",
      result: { ...approval(), approval_id: "approval-rework", run_id: "run-rework", source_run_id: "run-review", operation_type: "CREATE_REWORK", target_version: 8 },
    });
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();

    click('[data-testid="open-review-confirmation"]');
    await nextTick();
    click('[data-testid="confirm-review-decision"]');
    await settleUi();
    expect(mockedConfirm).toHaveBeenNthCalledWith(1, expect.objectContaining({ approval_id: "approval-review" }), "stream-2");
    expect(host?.textContent).toContain("复核已写入");

    click('[data-testid="create-rework-approval"]');
    await settleUi();
    expect(mockedRework).toHaveBeenCalledWith("approval-review");
    expect(host?.textContent).toContain("返工确认单已创建");

    click('[data-testid="open-review-confirmation"]');
    await nextTick();
    click('[data-testid="confirm-review-decision"]');
    await settleUi();
    expect(mockedConfirm).toHaveBeenNthCalledWith(2, expect.objectContaining({ approval_id: "approval-rework" }), "stream-3");
    expect(host?.textContent).toContain("返工任务已创建 · REWORK-003");
  });

  it("保留显式固定诊断入口", async () => {
    mockedFixedDiagnosis.mockResolvedValue({
      run_id: "run-fixed",
      session_id: "session-fixed",
      trace_id: "trace-fixed",
      diagnosis: diagnosis(),
    });
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-fixed-diagnosis"]');
    await settleUi();

    expect(mockedFixedDiagnosis).toHaveBeenCalledWith(
      "ORDER-003",
      "这个订单为什么还没有交付？",
      expect.objectContaining({ order_id: "ORDER-003" }),
      undefined,
      "stream-1",
    );
    expect(host?.textContent).toContain("QUALITY_REVIEW");
  });

  it("取消待确认单并明确显示没有执行写入", async () => {
    mockedSend.mockResolvedValue(approvalResponse());
    mockedCancel.mockResolvedValue({
      approval_id: "approval-review",
      run_id: "run-review",
      status: "CANCELLED",
      run_status: "CANCELLED",
      trace_id: "trace-cancel",
    });
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();
    click('[data-testid="cancel-review-approval"]');
    await settleUi();

    expect(mockedCancel).toHaveBeenCalledWith("approval-review");
    expect(host?.textContent).toContain("已取消");
    expect(host?.textContent).toContain("未执行Java写入");
  });

  it("模型故障保持失败语义并用新事件流重试同一轮", async () => {
    mockedSend
      .mockRejectedValueOnce(
        new AgentApiError({
          code: "MODEL_UNAVAILABLE",
          message: "model service is unavailable",
          traceId: "trace-model-error",
          retryable: true,
          status: 503,
        }),
      )
      .mockResolvedValueOnce(statusResponse("session-after-retry", "run-after-retry"));
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();

    expect(host?.textContent).toContain("MODEL_UNAVAILABLE");
    expect(host?.textContent).toContain("trace-model-error");
    expect(host?.textContent).not.toContain("确定性状态");

    clickText("重试本轮");
    await settleUi();
    expect(mockedSend).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        message: "这个订单为什么还没有交付？",
        session_id: undefined,
      }),
      "stream-2",
    );
    expect(host?.textContent).toContain("确定性状态");
  });

  it("切换订单后丢弃上一订单的迟到响应", async () => {
    let finishOldRequest: ((response: AgentMessageResponse) => void) | undefined;
    mockedSend.mockImplementationOnce(
      () => new Promise((resolve) => { finishOldRequest = resolve; }),
    );
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();

    expect(mockedSend).toHaveBeenCalledTimes(1);
    const order = selectedOrder;
    if (!order) throw new Error("order test wrapper was not initialized");
    order.value = {
      orderId: "ORDER-004",
      productType: "DSM",
      status: "PRODUCING",
    };
    await settleUi();
    finishOldRequest?.(statusResponse("session-old", "run-old"));
    await settleUi();

    expect(host?.textContent).toContain("ORDER-004");
    expect(host?.textContent).not.toContain("session-old");
    expect(host?.textContent).not.toContain("确定性状态");
  });

  it("等待结果超时提示先查运行历史且不显示重试本轮", async () => {
    mockedSend.mockRejectedValue(new AgentApiError({
      code: "REQUEST_TIMEOUT",
      message: "等待Agent结果超时，后台可能仍在执行，请先到运行历史查看，避免重复提交。",
      retryable: false,
    }));
    mountDrawer();
    click('[data-testid="open-agent-drawer"]');
    await settleUi();
    click('[data-testid="submit-agent-message"]');
    await settleUi();

    expect(host?.textContent).toContain("后台可能仍在执行");
    expect(host?.textContent).toContain("运行历史");
    expect(host?.textContent).not.toContain("重试本轮");
    expect(host?.textContent).not.toContain("确定性状态");
    expect(mockedSend).toHaveBeenCalledTimes(1);
  });
});

function mountDrawer(switchOrder?: (orderId: string) => Promise<Order>, orderId = "ORDER-003") {
  host = document.createElement("div");
  document.body.append(host);
  selectedOrder = ref({
    orderId,
    productType: "DOM",
    status: "QUALITY_CHECKING",
  });
  application = createApp({
    setup: () => () => h(AgentWorkspaceDrawer, { order: selectedOrder?.value, switchOrder }),
  });
  application.mount(host);
}

function switchResponse(): AgentMessageResponse {
  return {
    run_id: "run-switch", session_id: "session-old", trace_id: "trace-switch",
    result: { kind: "CLARIFICATION", intent: "ORDER_DIAGNOSIS", confidence: 0.95,
      clarification: { reason: "PAGE_ORDER_MISMATCH", question: "确认切换后继续？", field: "order_id",
        options: [{ value: "ORDER-001", source: "PAGE_CONTEXT" }, { value: "ORDER-003", source: "USER_MESSAGE" }],
      },
    },
  };
}

function click(selector: string) {
  const element = host?.querySelector<HTMLButtonElement>(selector);
  expect(element).toBeTruthy();
  element?.click();
}

function clickText(text: string) {
  const element = [...(host?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find(
    (candidate) => candidate.textContent?.includes(text),
  );
  expect(element).toBeTruthy();
  element?.click();
}

function input(selector: string, value: string) {
  const element = host?.querySelector<HTMLTextAreaElement>(selector);
  expect(element).toBeTruthy();
  if (!element) return;
  element.value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

async function settleUi() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}

function statusResponse(sessionId: string, runId: string): AgentMessageResponse {
  return {
    run_id: runId,
    session_id: sessionId,
    trace_id: `trace-${runId}`,
    result: {
      kind: "ORDER_STATUS",
      subject: "ORDER",
      order_id: "ORDER-003",
      task_id: null,
      status: "BLOCKED",
      summary: "订单处于阻塞状态。",
    },
  };
}

function specificationResponse(sessionId: string, runId: string): AgentMessageResponse {
  return {
    run_id: runId,
    session_id: sessionId,
    trace_id: `trace-${runId}`,
    result: {
      kind: "SPECIFICATION_ANSWER",
      specification_answer: {
        status: "ANSWERED",
        question: "如何处理",
        rewritten_query: "坐标系问题如何处理",
        answer: "处理后重新复核。",
        citations: [citation()],
        rerank_degraded: false,
      },
    },
  };
}

function clarificationResponse(): AgentMessageResponse {
  return {
    run_id: "run-clarification",
    session_id: "session-003",
    trace_id: "trace-clarification",
    result: {
      kind: "CLARIFICATION",
      intent: "ORDER_QUERY",
      confidence: 0.9,
      clarification: {
        reason: "ENTITY_CONFLICT",
        question: "请选择订单",
        field: "order_id",
        options: [
          { value: "ORDER-003", source: "USER_MESSAGE" },
          { value: "ORDER-004", source: "PAGE_CONTEXT" },
        ],
      },
    },
  };
}

function approvalResponse(): AgentMessageResponse {
  return {
    run_id: "run-review",
    session_id: "session-003",
    trace_id: "trace-review",
    result: approval(),
  };
}

function approval(): ApprovalAgentResult {
  return {
    kind: "APPROVAL",
    approval_id: "approval-review",
    run_id: "run-review",
    source_run_id: "run-diagnosis",
    status: "WAITING_CONFIRMATION",
    operation_type: "SUBMIT_REVIEW",
    target_id: "TASK-003",
    target_version: 7,
    draft: {
      task_id: "TASK-003",
      issue_id: "ISSUE-001",
      conclusion: "REWORK_REQUIRED",
      problem_summary: "存在坐标系问题",
      review_comment: "完成处理后重新复核",
      specification_references: [citation()],
      suggested_rework: { required: true, type: "COORDINATE_SYSTEM_FIX" },
    },
  };
}

function diagnosis() {
  return {
    order_id: "ORDER-003",
    blocking_stage: "QUALITY_REVIEW" as const,
    summary: "阻塞在质量复核。",
    root_causes: [{ code: "OPEN_ISSUE", description: "存在未关闭问题" }],
    evidence: [{
      source_type: "TOOL" as const,
      tool_name: "get_quality_issues",
      field_path: "issues[0].status",
      value: "OPEN",
      description: "问题未关闭",
    }],
    suggestions: [{ action_type: "RESUBMIT_REVIEW", description: "重新复核" }],
    confidence: 1,
  };
}

function citation() {
  return {
    document_id: "quality-review-spec",
    document_name: "质量复核规范",
    document_version: "1.0",
    section: ["坐标系问题"],
    chunk_id: "chunk-003",
    chunk_ids: ["chunk-003"],
    content: "处理后重新提交复核。",
    relevance_score: 0.98,
  };
}

function indexIdentity() {
  return {
    provider: "openai_compatible",
    model: "text-embedding-3-small",
    dimension: 1536,
    index_version: "text-embedding-3-small-1536-v1",
  };
}
