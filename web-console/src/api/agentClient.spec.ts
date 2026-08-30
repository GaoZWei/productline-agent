import MockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";

import {
  AgentApiError,
  agentHttpClient,
  requestApprovalConfirmation,
  requestApprovalOperationLog,
  requestOrderDiagnosis,
} from "./agentClient";

const mock = new MockAdapter(agentHttpClient);

afterEach(() => mock.reset());

describe("agent API client", () => {
  it("提交订单与问题并校验完整诊断响应", async () => {
    mock.onPost("/api/agent/order-diagnosis").reply(200, goldenResponse());

    await expect(
      requestOrderDiagnosis({
        order_id: "ORDER-003",
        user_message: "这个订单为什么还没有交付？",
        page_context: orderPageContext(),
      }, "stream-client-003"),
    ).resolves.toMatchObject({
      run_id: "run-order-003",
      session_id: "session-order-003",
      trace_id: "trace-order-003",
      diagnosis: {
        order_id: "ORDER-003",
        blocking_stage: "QUALITY_REVIEW",
      },
    });

    expect(mock.history.post[0]?.headers?.["X-User-Id"]).toBe("reviewer-001");
    expect(mock.history.post[0]?.headers?.["X-User-Role"]).toBe("REVIEWER");
    expect(mock.history.post[0]?.headers?.["X-Event-Stream-Id"]).toBe("stream-client-003");
    expect(JSON.parse(mock.history.post[0]?.data ?? "{}")).toMatchObject({
      order_id: "ORDER-003",
      page_context: {
        current_page: "order-detail",
        order_id: "ORDER-003",
        product_type: "DOM",
        user_role: "REVIEWER",
      },
    });
  });

  it("把服务端稳定错误转换为包含 Run 和失败步骤的客户端错误", async () => {
    mock.onPost("/api/agent/order-diagnosis").reply(502, {
      run_id: "run-failed",
      trace_id: "trace-failed",
      code: "UPSTREAM_TIMEOUT",
      message: "business service timed out",
      retryable: true,
      error_step: "get_quality_issues",
    });

    const error = await requestOrderDiagnosis({
      order_id: "ORDER-003",
      user_message: "why",
      page_context: orderPageContext(),
    }).catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(AgentApiError);
    expect(error).toMatchObject({
      code: "UPSTREAM_TIMEOUT",
      runId: "run-failed",
      traceId: "trace-failed",
      retryable: true,
      errorStep: "get_quality_issues",
      status: 502,
    });
  });

  it("拒绝缺少字段级证据的伪成功响应", async () => {
    const response = goldenResponse();
    response.diagnosis.evidence = [];
    mock.onPost("/api/agent/order-diagnosis").reply(200, response);

    await expect(
      requestOrderDiagnosis({
        order_id: "ORDER-003",
        user_message: "why",
        page_context: orderPageContext(),
      }),
    ).rejects.toMatchObject({
      code: "RESPONSE_VALIDATION_ERROR",
      traceId: "trace-order-003",
    });
  });

  it("把请求超时标记为可重试错误", async () => {
    mock.onPost("/api/agent/order-diagnosis").timeout();

    await expect(
      requestOrderDiagnosis({
        order_id: "ORDER-003",
        user_message: "why",
        page_context: orderPageContext(),
      }),
    ).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
      retryable: true,
    });
  });

  it("提交最终复核草稿并校验Java写入结果", async () => {
    mock.onPost("/api/agent/approvals/approval-confirm-003/confirm").reply(200, {
      approval_id: "approval-confirm-003",
      status: "SUCCEEDED",
      trace_id: "trace-confirm-003",
      result: {
        approval_id: "approval-confirm-003",
        task_id: "TASK-003",
        issue_id: "ISSUE-001",
        review_id: "REVIEW-WRITE-003",
        status: "REWORK_REQUIRED",
        review_comment: "完成坐标系统处理后重新提交复核",
        task_version: 8,
        java_trace_id: "trace-java-write",
      },
    });

    await expect(
      requestApprovalConfirmation({
        approval_id: "approval-confirm-003",
        draft: reviewDraft(),
      }),
    ).resolves.toMatchObject({
      status: "SUCCEEDED",
      result: { review_id: "REVIEW-WRITE-003", task_version: 8 },
    });
    expect(JSON.parse(mock.history.post[0]?.data ?? "{}")).toEqual({ draft: reviewDraft() });
  });

  it("把Approval过期错误转换为可展示的客户端错误", async () => {
    mock.onPost("/api/agent/approvals/approval-confirm-003/confirm").reply(410, {
      approval_id: "approval-confirm-003",
      status: "EXPIRED",
      trace_id: "trace-confirm-expired",
      code: "APPROVAL_EXPIRED",
      message: "approval confirmation window has expired",
      retryable: false,
    });

    await expect(
      requestApprovalConfirmation({
        approval_id: "approval-confirm-003",
        draft: reviewDraft(),
      }),
    ).rejects.toMatchObject({
      code: "APPROVAL_EXPIRED",
      traceId: "trace-confirm-expired",
      status: 410,
    });
  });

  it("读取并校验Approval操作日志详情", async () => {
    mock.onGet("/api/agent/approvals/approval-confirm-003/operation-log").reply(
      200,
      operationLogDetail(),
    );

    await expect(requestApprovalOperationLog("approval-confirm-003")).resolves.toMatchObject({
      approval_id: "approval-confirm-003",
      after_summary: { outcome: "SUCCEEDED" },
      java_trace_id: "trace-java-write",
    });
  });

  it("拒绝成功结果与失败摘要同时存在的操作日志", async () => {
    const detail = operationLogDetail();
    detail.after_summary.failure = {
      code: "UPSTREAM_UNAVAILABLE",
      status_code: 502,
      retryable: true,
    };
    mock.onGet("/api/agent/approvals/approval-confirm-003/operation-log").reply(200, detail);

    await expect(requestApprovalOperationLog("approval-confirm-003")).rejects.toMatchObject({
      code: "RESPONSE_VALIDATION_ERROR",
    });
  });
});

function operationLogDetail() {
  return {
    operation_log_id: "operation-log-003",
    approval_id: "approval-confirm-003",
    operation_type: "SUBMIT_REVIEW",
    target_id: "TASK-003",
    target_version: 7,
    confirmed_by_user_id: "reviewer-001",
    before_summary: {
      task_id: "TASK-003",
      issue_id: "ISSUE-001",
      task_version: 7,
      conclusion: "REWORK_REQUIRED",
      problem_summary: "存在未关闭的坐标系质量问题",
      review_comment: "完成坐标系统处理后重新提交复核",
      rework_required: true,
      rework_type: "COORDINATE_SYSTEM_FIX",
      specification_sources: [],
    },
    after_summary: {
      outcome: "SUCCEEDED",
      result: {
        operation_type: "SUBMIT_REVIEW",
        task_id: "TASK-003",
        issue_id: "ISSUE-001",
        review_id: "REVIEW-WRITE-003",
        status: "REWORK_REQUIRED",
        review_comment: "完成坐标系统处理后重新提交复核",
        task_version: 8,
      },
      failure: null as null | {
        code: string;
        status_code: number;
        retryable: boolean;
      },
    },
    user_modification_diff: [],
    java_trace_id: "trace-java-write",
    created_at: "2026-08-27T13:00:00Z",
  };
}

function reviewDraft() {
  return {
    task_id: "TASK-003",
    issue_id: "ISSUE-001",
    conclusion: "REWORK_REQUIRED" as const,
    problem_summary: "存在未关闭的坐标系质量问题",
    review_comment: "完成坐标系统处理后重新提交复核",
    specification_references: [],
    suggested_rework: {
      required: true,
      type: "COORDINATE_SYSTEM_FIX" as const,
    },
  };
}

function orderPageContext() {
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

function goldenResponse() {
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
      ],
      evidence: [
        {
          source_type: "TOOL",
          tool_name: "get_quality_issues",
          field_path: "issues[0].status",
          value: "OPEN",
          description: "ISSUE-001问题状态为OPEN",
        },
      ],
      suggestions: [
        {
          action_type: "CREATE_COORDINATE_SYSTEM_REWORK",
          description: "创建坐标系处理返工任务",
        },
      ],
      confidence: 1,
    },
  };
}
