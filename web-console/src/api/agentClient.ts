import axios, { AxiosError } from "axios";

import type {
  AgentCapabilitiesResponse,
  AgentMessageRequest,
  AgentMessageResponse,
  ApprovalConfirmationErrorResponse,
  ApprovalConfirmationResponse,
  ApprovalCancellationResponse,
  ApprovalAgentResult,
  ApprovalStatus,
  BlockingStage,
  OrderDiagnosisErrorResponse,
  OrderDiagnosisRequest,
  OrderDiagnosisResponse,
  OperationLogDetail,
  ReviewApprovalDecision,
  ReworkApprovalCreationResponse,
} from "../types/agent";

export const AGENT_API_BASE_URL = import.meta.env.VITE_AGENT_API_BASE_URL ?? "/agent-api";
export const AGENT_USER_ID = import.meta.env.VITE_AGENT_USER_ID ?? "reviewer-001";
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

const AGENT_RESULT_KINDS = [
  "ORDER_STATUS",
  "DIAGNOSIS",
  "SPECIFICATION_ANSWER",
  "CLARIFICATION",
  "APPROVAL",
] as const;

const AGENT_INTENTS = [
  "ORDER_QUERY",
  "TASK_TRACKING",
  "ORDER_DIAGNOSIS",
  "SPEC_QA",
  "REVIEW_GENERATION",
  "UNKNOWN",
] as const;

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

export async function requestAgentCapabilities(): Promise<AgentCapabilitiesResponse> {
  try {
    const response = await agentHttpClient.get<unknown>("/api/agent/capabilities");
    if (!isAgentCapabilitiesResponse(response.data)) {
      throw responseValidationError(response.status, traceIdFrom(response.data));
    }
    return response.data;
  } catch (reason) {
    throw normalizeAgentError(reason);
  }
}
// 发送统一消息
export async function requestAgentMessage(
  request: AgentMessageRequest,
  eventStreamId?: string,
): Promise<AgentMessageResponse> {
  try {
    const response = await agentHttpClient.post<unknown>("/api/agent/messages", request, {
      headers: eventStreamId ? { "X-Event-Stream-Id": eventStreamId } : undefined,
    });
    if (!isAgentMessageResponse(response.data)) {
      throw responseValidationError(response.status, traceIdFrom(response.data));
    }
    return response.data;
  } catch (reason) {
    throw normalizeAgentError(reason);
  }
}

export async function requestOrderDiagnosis(
  request: OrderDiagnosisRequest,
  eventStreamId?: string,
): Promise<OrderDiagnosisResponse> {
  try {
    const response = await agentHttpClient.post<unknown>("/api/agent/order-diagnosis", request, {
      headers: eventStreamId ? { "X-Event-Stream-Id": eventStreamId } : undefined,
    });
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
  eventStreamId?: string,
): Promise<ApprovalConfirmationResponse> {
  try {
    const approvalId = encodeURIComponent(decision.approval_id);
    const response = await agentHttpClient.post<unknown>(
      `/api/agent/approvals/${approvalId}/confirm`,
      { draft: decision.draft },
      { headers: eventStreamId ? { "X-Event-Stream-Id": eventStreamId } : undefined },
    );
    if (!isApprovalConfirmationResponse(response.data)) {
      throw responseValidationError(response.status, traceIdFrom(response.data));
    }
    return response.data;
  } catch (reason) {
    throw normalizeAgentError(reason);
  }
}

export async function requestApprovalCancellation(
  approvalId: string,
): Promise<ApprovalCancellationResponse> {
  try {
    const encodedApprovalId = encodeURIComponent(approvalId);
    const response = await agentHttpClient.post<unknown>(
      `/api/agent/approvals/${encodedApprovalId}/cancel`,
    );
    if (!isApprovalCancellationResponse(response.data)) {
      throw responseValidationError(response.status, traceIdFrom(response.data));
    }
    return response.data;
  } catch (reason) {
    throw normalizeAgentError(reason);
  }
}

export async function requestReworkApproval(
  sourceApprovalId: string,
): Promise<ReworkApprovalCreationResponse> {
  try {
    const encodedApprovalId = encodeURIComponent(sourceApprovalId);
    const response = await agentHttpClient.post<unknown>(
      `/api/agent/approvals/${encodedApprovalId}/rework`,
    );
    if (!isReworkApprovalCreationResponse(response.data)) {
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

function isAgentCapabilitiesResponse(value: unknown): value is AgentCapabilitiesResponse {
  if (
    !isRecord(value) ||
    value.message_api_enabled !== true ||
    !Array.isArray(value.result_kinds) ||
    !isRecord(value.model) ||
    typeof value.model.configured !== "boolean" ||
    !isRecord(value.knowledge_index)
  ) {
    return false;
  }
  const resultKinds = value.result_kinds;
  if (
    resultKinds.length !== AGENT_RESULT_KINDS.length ||
    !AGENT_RESULT_KINDS.every((kind) => resultKinds.includes(kind))
  ) {
    return false;
  }
  const modelValid = value.model.configured
    ? value.model.provider === "openai_compatible" && isNonEmptyString(value.model.model_name)
    : value.model.provider === null && value.model.model_name === null;
  const knowledge = value.knowledge_index;
  const statusValid = ["NOT_INDEXED", "INCOMPLETE", "INDEX_MISMATCH", "READY"].includes(
    String(knowledge.status),
  );
  return (
    modelValid &&
    statusValid &&
    typeof knowledge.ready === "boolean" &&
    knowledge.ready === (knowledge.status === "READY") &&
    Number.isInteger(knowledge.expected_document_count) &&
    Number(knowledge.expected_document_count) > 0 &&
    Number.isInteger(knowledge.document_count) &&
    Number(knowledge.document_count) >= 0 &&
    Number.isInteger(knowledge.chunk_count) &&
    Number(knowledge.chunk_count) >= 0 &&
    isKnowledgeIndexIdentity(knowledge.expected_index) &&
    (knowledge.stored_index === null || isKnowledgeIndexIdentity(knowledge.stored_index))
  );
}

function isKnowledgeIndexIdentity(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.provider) &&
    isNonEmptyString(value.model) &&
    Number.isInteger(value.dimension) &&
    Number(value.dimension) > 0 &&
    isNonEmptyString(value.index_version)
  );
}

function isAgentMessageResponse(value: unknown): value is AgentMessageResponse {
  return (
    isRecord(value) &&
    isNonEmptyString(value.run_id) &&
    isNonEmptyString(value.session_id) &&
    isNonEmptyString(value.trace_id) &&
    isAgentMessageResult(value.result)
  );
}
// 根据 kind 做第二层校验
function isAgentMessageResult(value: unknown) {
  if (!isRecord(value) || !AGENT_RESULT_KINDS.includes(value.kind as never)) return false;
  if (value.kind === "ORDER_STATUS") {
    return (
      ["ORDER", "TASK"].includes(String(value.subject)) &&
      isNonEmptyString(value.order_id) &&
      (value.task_id === null || isNonEmptyString(value.task_id)) &&
      (value.subject === "ORDER" ? value.task_id === null : isNonEmptyString(value.task_id)) &&
      isNonEmptyString(value.status) &&
      isNonEmptyString(value.summary)
    );
  }
  if (value.kind === "DIAGNOSIS") return isDiagnosisResult(value.diagnosis);
  if (value.kind === "SPECIFICATION_ANSWER") { // ANSWERED规范回答必须至少携带一个 Citation
    return isSpecificationQaResult(value.specification_answer);
  }
  if (value.kind === "CLARIFICATION") return isClarificationResult(value);
  return isApprovalAgentResult(value);
}

function isSpecificationQaResult(value: unknown) {
  if (
    !isRecord(value) ||
    !["ANSWERED", "INSUFFICIENT_CONTEXT", "RERANK_UNAVAILABLE", "GENERATION_FAILED"].includes(
      String(value.status),
    ) ||
    !isNonEmptyString(value.question) ||
    !isNonEmptyString(value.rewritten_query) ||
    !isNonEmptyString(value.answer) ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isKnowledgeCitation) ||
    typeof value.rerank_degraded !== "boolean"
  ) {
    return false;
  }
  return value.status === "ANSWERED"
    ? value.citations.length > 0 && !value.rerank_degraded
    : value.citations.length === 0 &&
        value.rerank_degraded === (value.status === "RERANK_UNAVAILABLE");
}

function isClarificationResult(value: Record<string, unknown>) {
  if (
    !AGENT_INTENTS.includes(value.intent as never) ||
    typeof value.confidence !== "number" ||
    value.confidence < 0 ||
    value.confidence > 1 ||
    !isRecord(value.clarification)
  ) {
    return false;
  }
  const clarification = value.clarification;
  if (
    ![
      "UNKNOWN_INTENT",
      "ENTITY_CONFLICT",
      "MISSING_PARAMETER",
      "LOW_CONFIDENCE",
      "CONFIRM_INTENT",
      "MODEL_REQUEST",
    ].includes(String(clarification.reason)) ||
    !isNonEmptyString(clarification.question) ||
    !Array.isArray(clarification.options) ||
    !clarification.options.every(isClarificationOption)
  ) {
    return false;
  }
  const hasField = isRoutingEntityField(clarification.field);
  if (clarification.reason === "ENTITY_CONFLICT") {
    return hasField && clarification.options.length >= 2;
  }
  if (clarification.reason === "MISSING_PARAMETER") {
    return hasField && clarification.options.length === 0;
  }
  return clarification.field === null && clarification.options.length === 0;
}

function isClarificationOption(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.value) &&
    ["USER_MESSAGE", "CONFIRMED_SESSION", "PAGE_CONTEXT", "SESSION_CANDIDATE"].includes(
      String(value.source),
    )
  );
}

function isRoutingEntityField(value: unknown) {
  return [
    "order_id",
    "task_id",
    "issue_id",
    "batch_id",
    "product_type",
    "satellite_type",
  ].includes(String(value));
}

function isApprovalCancellationResponse(value: unknown): value is ApprovalCancellationResponse {
  return (
    isRecord(value) &&
    isNonEmptyString(value.approval_id) &&
    isNonEmptyString(value.run_id) &&
    value.status === "CANCELLED" &&
    value.run_status === "CANCELLED" &&
    isNonEmptyString(value.trace_id)
  );
}

function isReworkApprovalCreationResponse(
  value: unknown,
): value is ReworkApprovalCreationResponse {
  return (
    isRecord(value) &&
    isNonEmptyString(value.run_id) &&
    isNonEmptyString(value.trace_id) &&
    isApprovalAgentResult(value.result) &&
    value.run_id === value.result.run_id &&
    value.result.operation_type === "CREATE_REWORK"
  );
}

function isApprovalAgentResult(value: unknown): value is ApprovalAgentResult {
  return (
    isRecord(value) &&
    value.kind === "APPROVAL" &&
    isNonEmptyString(value.approval_id) &&
    isNonEmptyString(value.run_id) &&
    isNonEmptyString(value.source_run_id) &&
    isApprovalStatus(value.status) &&
    ["SUBMIT_REVIEW", "CREATE_REWORK"].includes(String(value.operation_type)) &&
    isNonEmptyString(value.target_id) &&
    Number.isInteger(value.target_version) &&
    Number(value.target_version) >= 0 &&
    isReviewDraft(value.draft)
  );
}

function isReviewDraft(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.task_id) &&
    isNonEmptyString(value.issue_id) &&
    ["APPROVED", "REJECTED", "REWORK_REQUIRED"].includes(String(value.conclusion)) &&
    isNonEmptyString(value.problem_summary) &&
    isNonEmptyString(value.review_comment) &&
    Array.isArray(value.specification_references) &&
    value.specification_references.every(isKnowledgeCitation) &&
    isRecord(value.suggested_rework) &&
    typeof value.suggested_rework.required === "boolean" &&
    (value.suggested_rework.type === null ||
      value.suggested_rework.type === "COORDINATE_SYSTEM_FIX")
  );
}

function isKnowledgeCitation(value: unknown) {
  return (
    isRecord(value) &&
    isNonEmptyString(value.document_id) &&
    isNonEmptyString(value.document_name) &&
    isNonEmptyString(value.document_version) &&
    Array.isArray(value.section) &&
    value.section.every(isNonEmptyString) &&
    isNonEmptyString(value.chunk_id) &&
    Array.isArray(value.chunk_ids) &&
    value.chunk_ids.every(isNonEmptyString) &&
    isNonEmptyString(value.content) &&
    (value.relevance_score === null || typeof value.relevance_score === "number")
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
  return isDiagnosisResult(value.diagnosis);
}

function isDiagnosisResult(diagnosis: unknown) {
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
