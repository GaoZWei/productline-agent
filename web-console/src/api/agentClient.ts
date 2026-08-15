import axios, { AxiosError } from "axios";

import type {
  BlockingStage,
  OrderDiagnosisErrorResponse,
  OrderDiagnosisRequest,
  OrderDiagnosisResponse,
} from "../types/agent";

const AGENT_API_BASE_URL = import.meta.env.VITE_AGENT_API_BASE_URL ?? "/agent-api";
const AGENT_USER_ID = import.meta.env.VITE_AGENT_USER_ID ?? "reviewer-001";
export const AGENT_USER_ROLE = import.meta.env.VITE_AGENT_USER_ROLE ?? "REVIEWER";

const BLOCKING_STAGES = new Set<BlockingStage>([
  "PRODUCTION",
  "PRODUCTION_BLOCKED",
  "QUALITY_REVIEW",
  "REVIEW",
  "DELIVERY",
  "NONE",
  "INSUFFICIENT_INFORMATION",
]);

export class AgentApiError extends Error {
  readonly code: string;
  readonly runId: string | null;
  readonly traceId?: string;
  readonly retryable: boolean;
  readonly errorStep: string | null;
  readonly status?: number;

  constructor(options: {
    message: string;
    code: string;
    runId?: string | null;
    traceId?: string;
    retryable?: boolean;
    errorStep?: string | null;
    status?: number;
  }) {
    super(options.message);
    this.name = "AgentApiError";
    this.code = options.code;
    this.runId = options.runId ?? null;
    this.traceId = options.traceId;
    this.retryable = options.retryable ?? false;
    this.errorStep = options.errorStep ?? null;
    this.status = options.status;
  }
}

export const agentHttpClient = axios.create({
  baseURL: AGENT_API_BASE_URL,
  timeout: 20_000,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
    "X-User-Id": AGENT_USER_ID,
    "X-User-Role": AGENT_USER_ROLE,
  },
});

export async function requestOrderDiagnosis(
  request: OrderDiagnosisRequest,
): Promise<OrderDiagnosisResponse> {
  try {
    const response = await agentHttpClient.post<unknown>("/api/agent/order-diagnosis", request);
    if (!isOrderDiagnosisResponse(response.data)) {
      throw responseValidationError(response.status, traceIdFrom(response.data));
    }
    return response.data;
  } catch (reason) {
    throw normalizeAgentError(reason);
  }
}

function normalizeAgentError(reason: unknown): AgentApiError {
  if (reason instanceof AgentApiError) return reason;
  if (!axios.isAxiosError(reason)) {
    return new AgentApiError({
      code: "UNKNOWN_CLIENT_ERROR",
      message: "执行订单诊断时发生未知错误",
    });
  }
  return errorFromAxios(reason);
}

function errorFromAxios(error: AxiosError): AgentApiError {
  const status = error.response?.status;
  const payload = error.response?.data;
  if (isOrderDiagnosisErrorResponse(payload)) {
    return new AgentApiError({
      code: payload.code,
      message: payload.message,
      runId: payload.run_id,
      traceId: payload.trace_id,
      retryable: payload.retryable,
      errorStep: payload.error_step,
      status,
    });
  }
  if (status === 422) {
    return new AgentApiError({
      code: "REQUEST_VALIDATION_ERROR",
      message: "诊断请求参数无效",
      traceId: traceIdFrom(payload),
      status,
    });
  }
  if (error.code === AxiosError.ETIMEDOUT || error.code === "ECONNABORTED") {
    return new AgentApiError({
      code: "REQUEST_TIMEOUT",
      message: "诊断服务响应超时，请稍后重试",
      retryable: true,
      status,
    });
  }
  if (error.response) {
    return responseValidationError(status, traceIdFrom(payload));
  }
  return new AgentApiError({
    code: "NETWORK_ERROR",
    message: "无法连接诊断服务，请检查服务状态",
    retryable: true,
  });
}

function responseValidationError(status?: number, traceId?: string) {
  return new AgentApiError({
    code: "RESPONSE_VALIDATION_ERROR",
    message: "诊断服务返回了无法识别的响应结构",
    traceId,
    status,
  });
}

function isOrderDiagnosisResponse(value: unknown): value is OrderDiagnosisResponse {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.run_id) ||
    !isNonEmptyString(value.session_id) ||
    !isNonEmptyString(value.trace_id)
  ) {
    return false;
  }
  const diagnosis = value.diagnosis;
  return (
    isRecord(diagnosis) &&
    isNonEmptyString(diagnosis.order_id) &&
    isBlockingStage(diagnosis.blocking_stage) &&
    isNonEmptyString(diagnosis.summary) &&
    Array.isArray(diagnosis.root_causes) &&
    diagnosis.root_causes.every(isRootCause) &&
    Array.isArray(diagnosis.evidence) &&
    diagnosis.evidence.length > 0 &&
    diagnosis.evidence.every(isEvidence) &&
    Array.isArray(diagnosis.suggestions) &&
    diagnosis.suggestions.length > 0 &&
    diagnosis.suggestions.every(isSuggestion) &&
    typeof diagnosis.confidence === "number" &&
    diagnosis.confidence >= 0 &&
    diagnosis.confidence <= 1
  );
}

function isOrderDiagnosisErrorResponse(value: unknown): value is OrderDiagnosisErrorResponse {
  return (
    isRecord(value) &&
    (value.run_id === null || isNonEmptyString(value.run_id)) &&
    isNonEmptyString(value.trace_id) &&
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.message) &&
    typeof value.retryable === "boolean" &&
    (value.error_step === null || isNonEmptyString(value.error_step))
  );
}

function isRootCause(value: unknown) {
  return isRecord(value) && isNonEmptyString(value.code) && isNonEmptyString(value.description);
}

function isEvidence(value: unknown) {
  return (
    isRecord(value) &&
    value.source_type === "TOOL" &&
    isNonEmptyString(value.tool_name) &&
    isNonEmptyString(value.field_path) &&
    isScalar(value.value) &&
    isNonEmptyString(value.description)
  );
}

function isSuggestion(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.action_type) &&
    isNonEmptyString(value.description)
  );
}

function isBlockingStage(value: unknown): value is BlockingStage {
  return typeof value === "string" && BLOCKING_STAGES.has(value as BlockingStage);
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function traceIdFrom(value: unknown): string | undefined {
  if (!isRecord(value)) return undefined;
  return isNonEmptyString(value.trace_id) ? value.trace_id : undefined;
}
