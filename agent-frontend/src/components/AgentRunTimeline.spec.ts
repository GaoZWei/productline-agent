import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import type { JsonObject, RunEvent } from "../types/runEvents";
import AgentRunTimeline from "./AgentRunTimeline.vue";

let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;

afterEach(() => {
  application?.unmount();
  host?.remove();
  application = undefined;
  host = undefined;
});

describe("Agent run timeline", () => {
  it("展示运行、Tool、RAG、确认、失败和耗时", async () => {
    mountTimeline([
      event("1", "run_started", "2026-08-29T03:00:00.000Z"),
      event("2", "tool_started", "2026-08-29T03:00:01.000Z", "step-quality", {
        step_name: "load_quality",
        status: "RUNNING",
      }),
      event("3", "tool_completed", "2026-08-29T03:00:01.125Z", "step-quality", {
        step_name: "load_quality",
        status: "SUCCEEDED",
      }),
      event("4", "retrieval_started", "2026-08-29T03:00:02.000Z"),
      event("5", "retrieval_completed", "2026-08-29T03:00:02.240Z", null, {
        retrieved_count: 5,
        selected_count: 2,
        rerank_degraded: true,
      }),
      event("6", "approval_required", "2026-08-29T03:00:03.000Z", null, {
        approval_id: "approval-timeline-001",
        status: "WAITING_CONFIRMATION",
        target_id: "TASK-003",
      }),
      event("7", "run_failed", "2026-08-29T03:00:04.000Z", null, {
        error_code: "BUSINESS_CONFLICT",
        retryable: false,
      }),
    ]);
    await nextTick();

    expect(host?.textContent).toContain("实时执行步骤");
    expect(host?.textContent).toContain("查询质检问题");
    expect(host?.textContent).toContain("125 ms");
    expect(host?.textContent).toContain("检索现行规范");
    expect(host?.textContent).toContain("重排已降级");
    expect(host?.textContent).toContain("等待人工确认");
    expect(host?.textContent).toContain("BUSINESS_CONFLICT");
    expect(host?.querySelector('[data-status="failed"]')).toBeTruthy();
  });
});

function mountTimeline(events: RunEvent[]) {
  host = document.createElement("div");
  document.body.append(host);
  application = createApp(AgentRunTimeline, { events, connectionStatus: "closed" });
  application.mount(host);
}

function event(
  eventId: string,
  eventType: RunEvent["event_type"],
  occurredAt: string,
  stepId: string | null = null,
  data: JsonObject = {},
): RunEvent {
  return {
    event_id: eventId,
    event_type: eventType,
    stream_id: "stream-component-001",
    run_id: "run-component-001",
    sequence_number: Number(eventId),
    occurred_at: occurredAt,
    trace_id: "trace-component-001",
    step_id: stepId,
    data,
  };
}
