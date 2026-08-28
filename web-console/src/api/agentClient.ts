import axios, { AxiosError } from "axios";

import type {
  ApprovalConfirmationErrorResponse,
  ApprovalConfirmationResponse,
  ApprovalStatus,
  BlockingStage,
  OrderDiagnosisErrorResponse,
  OrderDiagnosisRequest,
  OrderDiagnosisResponse,
  OperationLogDetail,
  ReviewApprovalDecision,
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
  readonly approvalStatus: ApprovalStatus | null;
  readonly status?: number;

  constructor(options: {
    message: string;
    code: string;
    runId?: string | null;
    traceId?: string;
    retryable?: boolean;
    errorStep?: string | null;
    approvalStatus?: ApprovalStatus | null;
    status?: number;
  }) {
    super(options.message);
    this.name = "AgentApiError";
    this.code = options.code;
    this.runId = options.runId ?? null;
    this.traceId = options.traceId;
    this.retryable = options.retryable ?? false;
    this.errorStep = options.errorStep ?? null;
    this.approvalStatus = options.approvalStatus ?? null;
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

export async function requestApprovalConfirmation(
  decision: ReviewApprovalDecision,
): Promise<ApprovalConfirmationResponse> {
  try {
    const approvalId = encodeURIComponent(decision.approval_id);
    const response = await agentHttpClient.post<unknown>(
      `/api/agent/approvals/${approvalId}/confirm`,
      { draft: decision.draft },
    );
    if (!isApprovalConfirmationResponse(response.data)) {
      throw responseValidationError(response.status, traceIdFrom(response.data));
    }
    return response.data;
  } catch (reason) {
    throw normalizeAgentError(reason);
  }
}

export async function requestApprovalOperationLog(
  approvalId: string,
): Promise<OperationLogDetail> {
  try {
    const encodedApprovalId = encodeURIComponent(approvalId);
    const response = await agentHttpClient.get<unknown>(
      `/api/agent/approvals/${encodedApprovalId}/operation-log`,
    );
    if (!isOperationLogDetail(response.data)) {
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
  if (isApprovalConfirmationErrorResponse(payload)) {
    return new AgentApiError({
      code: payload.code,
      message: payload.message,
      traceId: payload.trace_id,
      retryable: payload.retryable,
      approvalStatus: payload.status,
      status,
    });
  }
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

function isApprovalConfirmationResponse(value: unknown): value is ApprovalConfirmationResponse {
  return (
    isRecord(value) &&
    isNonEmptyString(value.approval_id) &&
    value.status === "SUCCEEDED" &&
    isNonEmptyString(value.trace_id) &&
    isApprovalWriteResult(value.result)
  );
}

function isApprovalWriteResult(value: unknown) {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.approval_id) ||
    !isNonEmptyString(value.task_id) ||
    !Number.isInteger(value.task_version) ||
    Number(value.task_version) < 0 ||
    !isNonEmptyString(value.java_trace_id)
  ) {
    return false;
  }
  if (isNonEmptyString(value.review_id)) {
    return (
      isNonEmptyString(value.issue_id) &&
      ["APPROVED", "REJECTED", "REWORK_REQUIRED"].includes(String(value.status)) &&
      isNonEmptyString(value.review_comment)
    );
  }
  return (
    isNonEmptyString(value.rework_task_id) &&
    isNonEmptyString(value.source_issue_id) &&
    value.rework_type === "COORDINATE_SYSTEM_FIX" &&
    value.status === "PENDING" &&
    isNonEmptyString(value.reason)
  );
}

function isApprovalConfirmationErrorResponse(
  value: unknown,
): value is ApprovalConfirmationErrorResponse {
  return (
    isRecord(value) &&
    (value.approval_id === null || isNonEmptyString(value.approval_id)) &&
    (value.status === null || isApprovalStatus(value.status)) &&
    isNonEmptyString(value.trace_id) &&
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.message) &&
    typeof value.retryable === "boolean"
  );
}

function isOperationLogDetail(value: unknown): value is OperationLogDetail {
  return (
    isRecord(value) &&
    isNonEmptyString(value.operation_log_id) &&
    isNonEmptyString(value.approval_id) &&
    ["SUBMIT_REVIEW", "CREATE_REWORK"].includes(String(value.operation_type)) &&
    isNonEmptyString(value.target_id) &&
    Number.isInteger(value.target_version) &&
    Number(value.target_version) >= 0 &&
    isNonEmptyString(value.confirmed_by_user_id) &&
    isOperationBeforeSummary(value.before_summary) &&
    isOperationAfterSummary(value.after_summary) &&
    Array.isArray(value.user_modification_diff) &&
    value.user_modification_diff.every(isOperationFieldChange) &&
    (value.java_trace_id === null || isNonEmptyString(value.java_trace_id)) &&
    isNonEmptyString(value.created_at)
  );
}

function isOperationBeforeSummary(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.task_id) &&
    isNonEmptyString(value.issue_id) &&
    Number.isInteger(value.task_version) &&
    ["APPROVED", "REJECTED", "REWORK_REQUIRED"].includes(String(value.conclusion)) &&
    isNonEmptyString(value.problem_summary) &&
    isNonEmptyString(value.review_comment) &&
    typeof value.rework_required === "boolean" &&
    (value.rework_type === null || value.rework_type === "COORDINATE_SYSTEM_FIX") &&
    Array.isArray(value.specification_sources) &&
    value.specification_sources.every(isNonEmptyString)
  );
}

function isOperationAfterSummary(value: unknown) {
  if (!isRecord(value) || !["SUCCEEDED", "FAILED", "STALE"].includes(String(value.outcome))) {
    return false;
  }
  if (value.outcome === "SUCCEEDED") {
    return isOperationResultSummary(value.result) && value.failure === null;
  }
  return value.result === null && isOperationFailureSummary(value.failure);
}

function isOperationResultSummary(value: unknown) {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.task_id) ||
    !Number.isInteger(value.task_version) ||
    Number(value.task_version) < 0
  ) {
    return false;
  }
  if (value.operation_type === "SUBMIT_REVIEW") {
    return (
      isNonEmptyString(value.issue_id) &&
      isNonEmptyString(value.review_id) &&
      ["APPROVED", "REJECTED", "REWORK_REQUIRED"].includes(String(value.status)) &&
      isNonEmptyString(value.review_comment)
    );
  }
  return (
    value.operation_type === "CREATE_REWORK" &&
    isNonEmptyString(value.source_issue_id) &&
    isNonEmptyString(value.rework_task_id) &&
    value.rework_type === "COORDINATE_SYSTEM_FIX" &&
    value.status === "PENDING" &&
    isNonEmptyString(value.reason)
  );
}

function isOperationFailureSummary(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.code) &&
    Number.isInteger(value.status_code) &&
    Number(value.status_code) >= 400 &&
    Number(value.status_code) <= 599 &&
    typeof value.retryable === "boolean"
  );
}

function isOperationFieldChange(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.field_path) &&
    isOperationDiffValue(value.before) &&
    isOperationDiffValue(value.after)
  );
}

function isOperationDiffValue(value: unknown) {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (Array.isArray(value) && value.every(isNonEmptyString))
  );
}

function isApprovalStatus(value: unknown): value is ApprovalStatus {
  return (
    typeof value === "string" &&
    [
      "DRAFT",
      "WAITING_CONFIRMATION",
      "CONFIRMED",
      "EXECUTING",
      "SUCCEEDED",
      "FAILED",
      "CANCELLED",
      "EXPIRED",
      "STALE",
    ].includes(value)
  );
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
