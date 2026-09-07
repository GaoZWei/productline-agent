import MockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";

import type { AgentMessageResult } from "../types/agent";
import {
  AgentApiError,
  agentHttpClient,
  requestAgentCapabilities,
  requestAgentMessage,
} from "./agentClient";

const mock = new MockAdapter(agentHttpClient);

afterEach(() => mock.reset());

describe("unified agent client", () => {
  it("校验模型、知识索引和五类结果能力", async () => {
    mock.onGet("/api/agent/capabilities").reply(200, capabilities());

    await expect(requestAgentCapabilities()).resolves.toMatchObject({
      message_api_enabled: true,
      model: { configured: true, model_name: "agent-model" },
      knowledge_index: { ready: true, status: "READY" },
    });
  });

  it.each([
    ["ORDER_STATUS", orderStatus()],
    ["DIAGNOSIS", diagnosis()],
    ["SPECIFICATION_ANSWER", specification()],
    ["CLARIFICATION", clarification()],
    ["APPROVAL", approval()],
  ] as const)("校验%s统一结果并携带同一会话和事件流", async (_kind, result) => {
    mock.onPost("/api/agent/messages").reply(200, response(result));

    await expect(
      requestAgentMessage(
        { message: "继续处理", session_id: "session-003", page_context: pageContext() },
        "stream-003",
      ),
    ).resolves.toMatchObject({ result: { kind: _kind } });
    expect(mock.history.post[0]?.headers?.["X-Event-Stream-Id"]).toBe("stream-003");
    expect(JSON.parse(mock.history.post[0]?.data ?? "{}")).toMatchObject({
      message: "继续处理",
      session_id: "session-003",
    });
  });

  it("拒绝没有引用却伪装ANSWERED的规范结果", async () => {
    const invalid = specification();
    invalid.specification_answer.citations = [];
    mock.onPost("/api/agent/messages").reply(200, response(invalid));

    const error = await requestAgentMessage({ message: "规范是什么" }).catch(
      (reason: unknown) => reason,
    );
    expect(error).toBeInstanceOf(AgentApiError);
    expect(error).toMatchObject({ code: "RESPONSE_VALIDATION_ERROR" });
  });
});

function response(result: AgentMessageResult) {
  return {
    run_id: "run-003",
    session_id: "session-003",
    trace_id: "trace-003",
    result,
  };
}

function capabilities() {
  const index = {
    provider: "openai_compatible",
    model: "text-embedding-3-small",
    dimension: 1536,
    index_version: "text-embedding-3-small-1536-v1",
  };
  return {
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
      ready: true,
      status: "READY",
      expected_document_count: 16,
      document_count: 16,
      chunk_count: 80,
      expected_index: index,
      stored_index: index,
    },
  };
}

function orderStatus(): AgentMessageResult {
  return {
    kind: "ORDER_STATUS",
    subject: "ORDER",
    order_id: "ORDER-003",
    task_id: null,
    status: "BLOCKED",
    summary: "订单当前处于阻塞状态。",
  };
}

function diagnosis(): AgentMessageResult {
  return {
    kind: "DIAGNOSIS",
    diagnosis: {
      order_id: "ORDER-003",
      blocking_stage: "QUALITY_REVIEW",
      summary: "订单阻塞在质量复核。",
      root_causes: [{ code: "OPEN_ISSUE", description: "存在未关闭问题" }],
      evidence: [{
        source_type: "TOOL",
        tool_name: "get_quality_issues",
        field_path: "issues[0].status",
        value: "OPEN",
        description: "问题仍未关闭",
      }],
      suggestions: [{ action_type: "RESUBMIT_REVIEW", description: "处理后重新复核" }],
      confidence: 1,
    },
  };
}

function specification(): Extract<AgentMessageResult, { kind: "SPECIFICATION_ANSWER" }> {
  return {
    kind: "SPECIFICATION_ANSWER",
    specification_answer: {
      status: "ANSWERED",
      question: "坐标系问题如何处理",
      rewritten_query: "坐标系统偏差处理规范",
      answer: "应创建坐标系返工任务并重新提交复核。",
      citations: [citation()],
      rerank_degraded: false,
    },
  };
}

function clarification(): AgentMessageResult {
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

function approval(): AgentMessageResult {
  return {
    kind: "APPROVAL",
    approval_id: "approval-003",
    run_id: "run-003",
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
    content: "坐标系问题处理后应重新提交复核。",
    relevance_score: 0.98,
  };
}

function pageContext() {
  return {
    current_system: "production-system" as const,
    current_page: "order-detail" as const,
    order_id: "ORDER-003",
    task_id: null,
    issue_id: null,
    batch_id: null,
    product_type: "DOM",
    satellite_type: null,
    user_role: "REVIEWER",
  };
}
