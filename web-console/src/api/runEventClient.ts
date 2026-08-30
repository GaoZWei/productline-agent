import {
  AGENT_API_BASE_URL,
  AGENT_USER_ID,
  AGENT_USER_ROLE,
} from "./agentClient";
import type {
  JsonObject,
  JsonValue,
  RunEvent,
  RunEventConnectionState,
  RunEventStreamErrorResponse,
  RunEventType,
} from "../types/runEvents";

const RUN_EVENT_TYPES = new Set<RunEventType>([
  "run_started",
  "context_loaded",
  "intent_detected",
  "clarification_required",
  "agent_action_selected",
  "tool_started",
  "tool_completed",
  "retrieval_started",
  "retrieval_completed",
  "diagnosis_generated",
  "approval_required",
  "writeback_started",
  "writeback_completed",
  "run_completed",
  "run_failed",
]);
const TERMINAL_EVENT_TYPES = new Set<RunEventType>([
  "run_completed",
  "run_failed",
  "writeback_completed",
]);
const EVENT_FIELDS = new Set([
  "event_id",
  "event_type",
  "stream_id",
  "run_id",
  "sequence_number",
  "occurred_at",
  "trace_id",
  "step_id",
  "data",
]);

export class RunEventClientError extends Error {
  readonly code: string;
  readonly traceId?: string;
  readonly retryable: boolean;
  readonly status?: number;

  constructor(options: {
    code: string;
    message: string;
    traceId?: string;
    retryable?: boolean;
    status?: number;
  }) {
    super(options.message);
    this.name = "RunEventClientError";
    this.code = options.code;
    this.traceId = options.traceId;
    this.retryable = options.retryable ?? false;
    this.status = options.status;
  }
}

export interface RunEventConnection {
  readonly streamId: string;
  readonly ready: Promise<void>;
  close(): void;
}

export interface OpenRunEventStreamOptions {
  streamId: string;
  onEvent: (event: RunEvent) => void;
  onStateChange?: (state: RunEventConnectionState) => void;
  onError?: (error: RunEventClientError) => void;
  fetchImpl?: typeof fetch;
  maxReconnectAttempts?: number;
  reconnectDelayMs?: number;
  connectionTimeoutMs?: number;
}
// 生成streamId
export function createRunEventStreamId(): string {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi) {
    throw new RunEventClientError({
      code: "SSE_CRYPTO_UNAVAILABLE",
      message: "当前浏览器无法生成安全事件流标识",
    });
  }
  if (typeof cryptoApi.randomUUID === "function") {
    return `stream-${cryptoApi.randomUUID()}`;
  }
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  return `stream-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
}
// 自动重连必须避免重复和漏事件
export function openRunEventStream(options: OpenRunEventStreamOptions): RunEventConnection {
  const fetchImpl = options.fetchImpl ?? fetch;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 3;
  const connectionTimeoutMs = options.connectionTimeoutMs ?? 5_000;
  let reconnectDelayMs = options.reconnectDelayMs ?? 3_000;
  let reconnectAttempt = 0;
  let currentController: AbortController | undefined;
  let closed = false;
  let terminal = false;
  let readySettled = false;
  let lastEventId: string | undefined;
  let resolveReady!: () => void;
  let rejectReady!: (reason: RunEventClientError) => void;
  const ready = new Promise<void>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });

  const emitState = (status: RunEventConnectionState["status"]) => {
    options.onStateChange?.({ status, reconnectAttempt });
  };
  const settleReady = (error?: RunEventClientError) => {
    if (readySettled) return;
    readySettled = true;
    if (error) rejectReady(error);
    else resolveReady();
  };

  const run = async () => {
     // 自动重连流程
    while (!closed && !terminal) {
      emitState(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      try {
        await connectOnce();
        if (closed || terminal) break;
        throw new RunEventClientError({
          code: "SSE_CONNECTION_CLOSED",
          message: "实时步骤连接已中断",
          retryable: true,
        });
      } catch (reason) {
        if (closed) return;
        const error = normalizeRunEventError(reason);
        if (!error.retryable || reconnectAttempt >= maxReconnectAttempts) {
          emitState("failed");
          settleReady(error);
          options.onError?.(error);
          return;
        }
        reconnectAttempt += 1;
        emitState("reconnecting");
        await wait(reconnectDelayMs);
      }
    }
    if (terminal && !closed) {
      closed = true;
      emitState("closed");
    }
  };

  const connectOnce = async () => {
    const controller = new AbortController();
    currentController = controller;
    let timedOut = false;
    let connected = false;
    const timeout = globalThis.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, connectionTimeoutMs);
    try {
      const headers = new Headers({
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
        "X-User-Id": AGENT_USER_ID,
        "X-User-Role": AGENT_USER_ROLE,
      });
      // 每收到一条合法事件，前端保存event_id
      if (lastEventId) headers.set("Last-Event-ID", lastEventId);
      const response = await fetchImpl(
        `${AGENT_API_BASE_URL}/api/agent/events/${encodeURIComponent(options.streamId)}`,
        { method: "GET", headers, signal: controller.signal },
      );
      if (!response.ok) throw await errorFromResponse(response);
      if (!response.headers.get("content-type")?.startsWith("text/event-stream")) {
        throw responseValidationError("SSE响应类型不正确");
      }
      if (!response.body) throw responseValidationError("SSE响应缺少可读数据流");
      // 收到connected确认
      const parser = createSseParser({
        streamId: options.streamId,
        onConnected: () => {
          if (connected) return;
          connected = true;
          globalThis.clearTimeout(timeout);
          settleReady();
          emitState("open");
        },
        onRetry: (delayMs) => {
          if (options.reconnectDelayMs === undefined) reconnectDelayMs = delayMs;
        },
        onEvent: (event) => {
          const previousId = lastEventId ? Number(lastEventId) : 0;
          const currentId = Number(event.event_id);
          if (currentId <= previousId) return;
          if (previousId > 0 && currentId !== previousId + 1) {
            throw responseValidationError("SSE事件序号不连续");
          }
          lastEventId = event.event_id;
          options.onEvent(event);
          if (TERMINAL_EVENT_TYPES.has(event.event_type)) terminal = true;
        },
      });
      // 手动读取数据流
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
     
      while (!closed && !terminal) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.push(decoder.decode(value, { stream: true }));
      }
      parser.push(decoder.decode());
      if (!connected && !terminal) {
        throw responseValidationError("SSE连接未返回connected确认");
      }
    } catch (reason) {
      if (timedOut) {
        throw new RunEventClientError({
          code: "SSE_CONNECTION_TIMEOUT",
          message: "实时步骤连接超时",
          retryable: true,
        });
      }
      throw reason;
    } finally {
      globalThis.clearTimeout(timeout);
      if (currentController === controller) currentController = undefined;
    }
  };

  void run();
  return {
    streamId: options.streamId,
    ready,
    close() {
      if (closed) return;
      closed = true;
      currentController?.abort();
      emitState("closed");
      if (!readySettled) {
        settleReady(
          new RunEventClientError({
            code: "SSE_CONNECTION_CLOSED",
            message: "实时步骤连接已关闭",
          }),
        );
      }
    },
  };
}
// 网络分块解析
function createSseParser(callbacks: {
  streamId: string;
  onConnected: () => void;
  onRetry: (delayMs: number) => void;
  onEvent: (event: RunEvent) => void;
}) {
  let buffer = "";
  return {
    push(chunk: string) {
      buffer += chunk;
      while (true) {
        const boundary = buffer.match(/\r?\n\r?\n/);
        if (!boundary || boundary.index === undefined) return;
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        parseSseBlock(block, callbacks);
      }
    },
  };
}

function parseSseBlock(
  block: string,
  callbacks: {
    streamId: string;
    onConnected: () => void;
    onRetry: (delayMs: number) => void;
    onEvent: (event: RunEvent) => void;
  },
) {
  let eventId = "";
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) {
      if (line.slice(1).trimStart().startsWith("connected")) callbacks.onConnected();
      continue;
    }
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const value = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "id") eventId = value;
    else if (field === "event") eventName = value;
    else if (field === "data") dataLines.push(value);
    else if (field === "retry" && /^\d+$/.test(value)) callbacks.onRetry(Number(value));
  }
  if (dataLines.length === 0) return;
  let raw: unknown;
  try {
    raw = JSON.parse(dataLines.join("\n"));
  } catch {
    throw responseValidationError("SSE事件不是有效JSON");
  }
  const event = parseRunEvent(raw, callbacks.streamId);
  if (eventId && event.event_id !== eventId) {
    throw responseValidationError("SSE事件ID与数据体不一致");
  }
  if (eventName !== event.event_type) {
    throw responseValidationError("SSE事件类型与数据体不一致");
  }
  callbacks.onEvent(event);
}

function parseRunEvent(value: unknown, expectedStreamId: string): RunEvent {
  if (
    !isRecord(value) ||
    Object.keys(value).some((key) => !EVENT_FIELDS.has(key)) ||
    !isPositiveIntegerText(value.event_id) ||
    !RUN_EVENT_TYPES.has(value.event_type as RunEventType) ||
    value.stream_id !== expectedStreamId ||
    !(value.run_id === null || isNonEmptyString(value.run_id)) ||
    !Number.isSafeInteger(value.sequence_number) ||
    Number(value.sequence_number) < 1 ||
    Number(value.event_id) !== value.sequence_number ||
    !isAwareDateTime(value.occurred_at) ||
    !isNonEmptyString(value.trace_id) ||
    !(value.step_id === null || isNonEmptyString(value.step_id)) ||
    !isJsonObject(value.data)
  ) {
    throw responseValidationError("诊断服务返回了无法识别的SSE事件");
  }
  return value as unknown as RunEvent;
}

async function errorFromResponse(response: Response): Promise<RunEventClientError> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    return responseValidationError("SSE连接返回了无法识别的错误", response.status);
  }
  if (!isRunEventStreamError(value)) {
    return responseValidationError("SSE连接返回了无法识别的错误", response.status);
  }
  return new RunEventClientError({
    code: value.code,
    message: value.message,
    traceId: value.trace_id,
    retryable: response.status >= 500,
    status: response.status,
  });
}

function normalizeRunEventError(reason: unknown): RunEventClientError {
  if (reason instanceof RunEventClientError) return reason;
  if (reason instanceof DOMException && reason.name === "AbortError") {
    return new RunEventClientError({
      code: "SSE_CONNECTION_ABORTED",
      message: "实时步骤连接已中断",
      retryable: true,
    });
  }
  return new RunEventClientError({
    code: "SSE_NETWORK_ERROR",
    message: "无法连接实时步骤服务",
    retryable: true,
  });
}

function responseValidationError(message: string, status?: number) {
  return new RunEventClientError({
    code: "RESPONSE_VALIDATION_ERROR",
    message,
    retryable: false,
    status,
  });
}

function isRunEventStreamError(value: unknown): value is RunEventStreamErrorResponse {
  return (
    isRecord(value) &&
    isNonEmptyString(value.stream_id) &&
    isNonEmptyString(value.trace_id) &&
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.message)
  );
}

function isJsonObject(value: unknown): value is JsonObject {
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isJsonValue(value: unknown): value is JsonValue {
  return (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "string" ||
    (typeof value === "number" && Number.isFinite(value)) ||
    (Array.isArray(value) && value.every(isJsonValue)) ||
    isJsonObject(value)
  );
}

function isAwareDateTime(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function isPositiveIntegerText(value: unknown): value is string {
  return typeof value === "string" && /^[1-9]\d*$/.test(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function wait(delayMs: number) {
  await new Promise<void>((resolve) => globalThis.setTimeout(resolve, delayMs));
}
