import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentMessageResponse, AgentMessageResult } from "../types/agent";
import AgentResultView from "./AgentResultView.vue";

let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;

afterEach(() => {
  application?.unmount();
  host?.remove();
  application = undefined;
  host = undefined;
});

describe("Agent result view", () => {
  it.each([
    [statusResult(), ["确定性状态", "BLOCKED", "Java Tool"]],
    [diagnosisResult(), ["QUALITY_REVIEW", "未关闭问题", "仅建议，未执行"]],
    [specificationResult(), ["规范回答", "质量复核规范", "版本 1.0"]],
    [clarificationResult(), ["需要确认", "请选择订单", "ORDER-004"]],
    [approvalResult(), ["人工复核确认", "TASK-003", "存在坐标系问题"]],
  ] as const)("按kind渲染统一结果", async (result, expectedTexts) => {
    mountResult(result);
    await nextTick();

    for (const text of expectedTexts) expect(host?.textContent).toContain(text);
  });

  it("只提交服务端提供的澄清候选和来源Run", async () => {
    const onClarify = vi.fn();
    mountResult(clarificationResult(), { onClarify });
    await nextTick();

    const buttons = host?.querySelectorAll<HTMLButtonElement>(".clarification-options button");
    buttons?.[1]?.click();
    await nextTick();

    expect(onClarify).toHaveBeenCalledWith(
      {
        source_run_id: "run-result-003",
        selection: { field: "order_id", value: "ORDER-004" },
      },
      "选择 ORDER-004",
    );
  });
});

function mountResult(
  result: AgentMessageResult,
  handlers: { onClarify?: (...args: unknown[]) => void } = {},
) {
  host = document.createElement("div");
  document.body.append(host);
  application = createApp(AgentResultView, {
    response: response(result),
    onClarify: handlers.onClarify,
  });
  application.mount(host);
}

function response(result: AgentMessageResult): AgentMessageResponse {
  return {
    run_id: "run-result-003",
    session_id: "session-result-003",
    trace_id: "trace-result-003",
    result,
  };
}

function statusResult(): AgentMessageResult {
  return {
    kind: "ORDER_STATUS",
    subject: "ORDER",
    order_id: "ORDER-003",
    task_id: null,
    status: "BLOCKED",
    summary: "订单处于阻塞状态。",
  };
}

function diagnosisResult(): AgentMessageResult {
  return {
    kind: "DIAGNOSIS",
    diagnosis: {
      order_id: "ORDER-003",
      blocking_stage: "QUALITY_REVIEW",
      summary: "阻塞在质量复核。",
      root_causes: [{ code: "OPEN_ISSUE", description: "存在未关闭问题" }],
      evidence: [{
        source_type: "TOOL",
        tool_name: "get_quality_issues",
        field_path: "issues[0].status",
        value: "OPEN",
        description: "问题未关闭",
      }],
      suggestions: [{ action_type: "RESUBMIT_REVIEW", description: "重新复核" }],
      confidence: 1,
    },
  };
}

function specificationResult(): AgentMessageResult {
  return {
    kind: "SPECIFICATION_ANSWER",
    specification_answer: {
      status: "ANSWERED",
      question: "如何处理",
      rewritten_query: "坐标系问题如何处理",
      answer: "处理后重新复核。",
      citations: [citation()],
      rerank_degraded: false,
    },
  };
}

function clarificationResult(): AgentMessageResult {
  return {
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
  };
}

function approvalResult(): AgentMessageResult {
  return {
    kind: "APPROVAL",
    approval_id: "approval-003",
    run_id: "run-result-003",
    source_run_id: "run-diagnosis-003",
    status: "WAITING_CONFIRMATION",
    operation_type: "SUBMIT_REVIEW",
    target_id: "TASK-003",
    target_version: 7,
    draft: {
      task_id: "TASK-003",
      issue_id: "ISSUE-001",
      conclusion: "REWORK_REQUIRED",
      problem_summary: "存在坐标系问题",
      review_comment: "完成处理后重新提交复核",
      specification_references: [citation()],
      suggested_rework: { required: true, type: "COORDINATE_SYSTEM_FIX" },
    },
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
