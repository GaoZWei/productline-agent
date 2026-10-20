// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { agentHttpClient, requestAgentCapabilities, requestAgentMessage } from "./agentClient";

const originalAdapter = agentHttpClient.defaults.adapter;
const originalBaseUrl = agentHttpClient.defaults.baseURL;
const originalEnvironment = agentHttpClient.defaults.env;

beforeEach(() => {
  vi.useFakeTimers();
  agentHttpClient.defaults.adapter = "fetch";
  agentHttpClient.defaults.baseURL = "https://agent.example.test";
});

afterEach(() => {
  agentHttpClient.defaults.adapter = originalAdapter;
  agentHttpClient.defaults.baseURL = originalBaseUrl;
  agentHttpClient.defaults.env = originalEnvironment;
  vi.useRealTimers();
});

function delayResponse(delayMs: number) {
  const fetch = vi.fn<typeof globalThis.fetch>((input, init) => {
    const signal = input instanceof Request ? input.signal : init?.signal;
    return new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(new Response(JSON.stringify({
        run_id: "run-slow-specification",
        session_id: "session-slow-specification",
        trace_id: "trace-slow-specification",
        result: {
          kind: "SPECIFICATION_ANSWER",
          specification_answer: {
            status: "INSUFFICIENT_CONTEXT",
            question: "演示规范有什么要求？",
            rewritten_query: "演示规范有什么要求?",
            answer: "未检索到足够相关的规范。",
            citations: [],
            rerank_degraded: false,
          },
        },
      }), { headers: { "Content-Type": "application/json" } })), delayMs);
      signal?.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(signal.reason);
      }, { once: true });
    });
  });
  agentHttpClient.defaults.env = { ...originalEnvironment, fetch };
  return fetch;
}

describe("统一消息真实Axios计时器", () => {
  it("35秒响应超过旧20秒限制后仍正常返回且只发送一次", async () => {
    const fetch = delayResponse(35_000);
    const promise = requestAgentMessage({ message: "演示规范有什么要求？" });
    const result = expect(promise).resolves.toMatchObject({ run_id: "run-slow-specification" });

    await vi.advanceTimersByTimeAsync(35_000);
    await result;
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("达到5分钟预算后提示执行结果未知且不自动重发", async () => {
    const fetch = delayResponse(301_000);
    const result = expect(requestAgentMessage({ message: "演示规范有什么要求？" }))
      .rejects.toMatchObject({
        code: "REQUEST_TIMEOUT",
        retryable: false,
        message: expect.stringContaining("后台可能仍在执行"),
      });

    await vi.advanceTimersByTimeAsync(300_000);
    await result;
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("普通能力查询仍在20秒超时", async () => {
    const fetch = delayResponse(35_000);
    const result = expect(requestAgentCapabilities()).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
      retryable: true,
    });

    await vi.advanceTimersByTimeAsync(20_000);
    await result;
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
