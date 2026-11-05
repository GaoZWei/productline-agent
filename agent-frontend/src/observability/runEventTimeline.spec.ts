import { describe, expect, it } from "vitest";

import type { JsonObject, RunEvent, RunEventType } from "../types/runEvents";
import { buildRunTimeline } from "./runEventTimeline";

describe("run event timeline", () => {
  it("把Tool和RAG开始完成事件配对并计算耗时", () => {
    const timeline = buildRunTimeline([
      event("1", "run_started", "2026-08-29T03:00:00.000Z"),
      event("2", "tool_started", "2026-08-29T03:00:01.000Z", {
        stepId: "step-quality",
        data: { step_name: "load_quality", status: "RUNNING" },
      }),
      event("3", "tool_completed", "2026-08-29T03:00:02.250Z", {
        stepId: "step-quality",
        data: { step_name: "load_quality", status: "SUCCEEDED" },
      }),
      event("4", "retrieval_started", "2026-08-29T03:00:03.000Z"),
      event("5", "retrieval_completed", "2026-08-29T03:00:03.480Z", {
        data: { retrieved_count: 10, selected_count: 3, rerank_degraded: false },
      }),
      event("6", "run_completed", "2026-08-29T03:00:04.000Z"),
    ]);

    expect(timeline.map((item) => item.kind)).toEqual(["run", "tool", "rag"]);
    expect(timeline[0]).toMatchObject({ status: "succeeded", durationMs: 4000 });
    expect(timeline[1]).toMatchObject({
      label: "查询质检问题",
      status: "succeeded",
      durationMs: 1250,
    });
    expect(timeline[2]).toMatchObject({
      label: "检索现行规范",
      status: "succeeded",
      durationMs: 480,
    });
    expect(timeline[2]?.detail).toContain("召回 10 条，保留 3 条");
  });

  it("显示人工确认、写回状态并把失败定位到正在运行的步骤", () => {
    const timeline = buildRunTimeline([
      event("1", "run_started", "2026-08-29T03:00:00.000Z"),
      event("2", "approval_required", "2026-08-29T03:00:01.000Z", {
        data: {
          approval_id: "approval-web-001",
          status: "WAITING_CONFIRMATION",
          target_id: "TASK-003",
        },
      }),
      event("3", "writeback_started", "2026-08-29T03:00:02.000Z", {
        data: {
          approval_id: "approval-web-001",
          tool_name: "write_review_result",
          target_id: "TASK-003",
        },
      }),
      event("4", "run_failed", "2026-08-29T03:00:02.300Z", {
        data: {
          approval_id: "approval-web-001",
          error_code: "BUSINESS_CONFLICT",
          error_step: "write_review_result",
          retryable: false,
        },
      }),
    ]);

    expect(timeline.find((item) => item.kind === "approval")).toMatchObject({
      label: "等待人工确认",
      status: "succeeded",
      durationMs: 1000,
    });
    expect(timeline.find((item) => item.kind === "writeback")).toMatchObject({
      label: "写回复核结果",
      status: "failed",
      durationMs: 300,
      errorCode: "BUSINESS_CONFLICT",
    });
    expect(timeline.find((item) => item.kind === "run")).toMatchObject({
      status: "failed",
      durationMs: 2300,
    });
  });

  it("按sequence_number去重和排序重连回放事件", () => {
    const completed = event("2", "run_completed", "2026-08-29T03:00:01.000Z");
    const timeline = buildRunTimeline([
      completed,
      event("1", "run_started", "2026-08-29T03:00:00.000Z"),
      completed,
    ]);

    expect(timeline).toHaveLength(1);
    expect(timeline[0]).toMatchObject({ status: "succeeded", durationMs: 1000 });
  });

  it("即使失败发生在Run建立前也显示安全失败步骤", () => {
    const timeline = buildRunTimeline([
      event("1", "run_failed", "2026-08-29T03:00:00.000Z", {
        data: { error_code: "CONTEXT_VALIDATION_ERROR", retryable: false },
      }),
    ]);

    expect(timeline).toEqual([
      expect.objectContaining({
        kind: "run",
        label: "执行订单诊断",
        status: "failed",
        durationMs: 0,
        errorCode: "CONTEXT_VALIDATION_ERROR",
      }),
    ]);
  });
});

function event(
  eventId: string,
  eventType: RunEventType,
  occurredAt: string,
  options: { stepId?: string; data?: JsonObject } = {},
): RunEvent {
  return {
    event_id: eventId,
    event_type: eventType,
    stream_id: "stream-timeline-001",
    run_id: "run-timeline-001",
    sequence_number: Number(eventId),
    occurred_at: occurredAt,
    trace_id: "trace-timeline-001",
    step_id: options.stepId ?? null,
    data: options.data ?? {},
  };
}
