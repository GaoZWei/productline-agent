import { describe, expect, it, vi } from "vitest";

import type { RunEvent, RunEventType } from "../types/runEvents";
import { openRunEventStream, RunEventClientError } from "./runEventClient";

describe("run event SSE client", () => {
  it("解析分块事件并携带Last-Event-ID自动重连", async () => {
    const events: RunEvent[] = [];
    const states: string[] = [];
    const startedFrame = eventFrame(event("1", "run_started", "2026-08-29T03:00:00Z"));
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        eventResponse([
          ": connected stream-web-001\nretry: 0\n\n",
          startedFrame.slice(0, 37),
          startedFrame.slice(37),
        ]),
      )
      .mockResolvedValueOnce(
        eventResponse([
          ": connected stream-web-001\n\n",
          startedFrame,
          eventFrame(event("2", "run_completed", "2026-08-29T03:00:01Z")),
        ]),
      );

    const connection = openRunEventStream({
      streamId: "stream-web-001",
      fetchImpl: fetchMock,
      reconnectDelayMs: 0,
      maxReconnectAttempts: 2,
      onEvent: (item) => events.push(item),
      onStateChange: (state) => states.push(state.status),
    });

    await connection.ready;
    await vi.waitFor(() => expect(events.map((item) => item.event_id)).toEqual(["1", "2"]));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("Last-Event-ID")).toBe("1");
    expect(states).toContain("reconnecting");
    expect(states.at(-1)).toBe("closed");
    connection.close();
  });

  it("拒绝无法识别的事件结构且不把原始响应交给页面", async () => {
    const onEvent = vi.fn();
    const onError = vi.fn();
    const connection = openRunEventStream({
      streamId: "stream-web-invalid",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        eventResponse([
          ": connected stream-web-invalid\n\n",
          "id: 1\nevent: tool_started\ndata: {\"unexpected\":true}\n\n",
        ]),
      ),
      maxReconnectAttempts: 0,
      onEvent,
      onError,
    });

    await connection.ready;
    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());

    expect(onEvent).not.toHaveBeenCalled();
    expect(onError.mock.calls[0]?.[0]).toMatchObject({
      code: "RESPONSE_VALIDATION_ERROR",
      retryable: false,
    });
  });

  it("把连接建立前的结构化HTTP错误转换为可重试客户端错误", async () => {
    const connection = openRunEventStream({
      streamId: "stream-web-not-ready",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            stream_id: "stream-web-not-ready",
            trace_id: "trace-sse-error",
            code: "EVENT_STREAM_CAPACITY_REACHED",
            message: "event stream capacity was reached",
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      ),
      maxReconnectAttempts: 0,
      onEvent: vi.fn(),
    });

    const error = await connection.ready.catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(RunEventClientError);
    expect(error).toMatchObject({
      code: "EVENT_STREAM_CAPACITY_REACHED",
      traceId: "trace-sse-error",
      retryable: true,
      status: 503,
    });
  });
});

function event(
  eventId: string,
  eventType: RunEventType,
  occurredAt: string,
): RunEvent {
  return {
    event_id: eventId,
    event_type: eventType,
    stream_id: "stream-web-001",
    run_id: "run-web-001",
    sequence_number: Number(eventId),
    occurred_at: occurredAt,
    trace_id: "trace-web-001",
    step_id: null,
    data: eventType === "run_completed" ? { status: "SUCCEEDED" } : {},
  };
}

function eventFrame(value: RunEvent) {
  return `id: ${value.event_id}\nevent: ${value.event_type}\ndata: ${JSON.stringify(value)}\n\n`;
}

function eventResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}
