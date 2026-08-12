import MockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";

import { AgentApiError, agentHttpClient, requestOrderDiagnosis } from "./agentClient";

const mock = new MockAdapter(agentHttpClient);

afterEach(() => mock.reset());

describe("agent API client", () => {
  it("提交订单与问题并校验完整诊断响应", async () => {
    mock.onPost("/api/agent/order-diagnosis").reply(200, goldenResponse());

    await expect(
      requestOrderDiagnosis({
        order_id: "ORDER-003",
        user_message: "这个订单为什么还没有交付？",
      }),
    ).resolves.toMatchObject({
      run_id: "run-order-003",
      trace_id: "trace-order-003",
      diagnosis: {
        order_id: "ORDER-003",
        blocking_stage: "QUALITY_REVIEW",
      },
    });

    expect(mock.history.post[0]?.headers?.["X-User-Id"]).toBe("reviewer-001");
    expect(mock.history.post[0]?.headers?.["X-User-Role"]).toBe("REVIEWER");
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
      requestOrderDiagnosis({ order_id: "ORDER-003", user_message: "why" }),
    ).rejects.toMatchObject({
      code: "RESPONSE_VALIDATION_ERROR",
      traceId: "trace-order-003",
    });
  });

  it("把请求超时标记为可重试错误", async () => {
    mock.onPost("/api/agent/order-diagnosis").timeout();

    await expect(
      requestOrderDiagnosis({ order_id: "ORDER-003", user_message: "why" }),
    ).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
      retryable: true,
    });
  });
});

function goldenResponse() {
  return {
    run_id: "run-order-003",
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
