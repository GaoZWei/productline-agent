import axios, { AxiosError } from "axios";

import type { ReviewDraft } from "../types/agent";
import type {
  ApprovalFieldChange,
  ApprovalHistory,
  RunDetailResponse,
  RunListResponse,
  RunSummary,
  StepListResponse,
  StepSummary,
} from "../types/runHistory";
import { AgentApiError, agentHttpClient } from "./agentClient";

export async function requestRunHistory(
  page = 1,
  pageSize = 20,
): Promise<RunListResponse> {
  return request(
    `/api/agent/runs?page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(pageSize)}`,
    isRunListResponse,
  );
}

export async function requestRunDetail(runId: string): Promise<RunDetailResponse> {
  return request(`/api/agent/runs/${encodeURIComponent(runId)}`, isRunDetailResponse);
}

export async function requestRunSteps(runId: string): Promise<StepListResponse> {
  return request(`/api/agent/runs/${encodeURIComponent(runId)}/steps`, isStepListResponse);
}

async function request<T>(path: string, validate: (value: unknown) => value is T): Promise<T> {
  try {
    const response = await agentHttpClient.get<unknown>(path);
    if (!validate(response.data)) throw responseValidationError(response.status, response.data);
    return response.data;
  } catch (reason) {
    throw normalizeHistoryError(reason);
  }
}

function normalizeHistoryError(reason: unknown): AgentApiError {
  if (reason instanceof AgentApiError) return reason;
  if (!axios.isAxiosError(reason)) {
    return new AgentApiError({ code: "UNKNOWN_CLIENT_ERROR", message: "读取运行历史时发生未知错误" });
  }
  const payload = reason.response?.data;
  if (isHistoryError(payload)) {
    return new AgentApiError({
      code: payload.code,
      message: payload.message,
      traceId: payload.trace_id,
      status: reason.response?.status,
    });
  }
  if (reason.code === AxiosError.ETIMEDOUT || reason.code === "ECONNABORTED") {
    return new AgentApiError({
      code: "REQUEST_TIMEOUT",
      message: "运行历史服务响应超时，请稍后重试",
      retryable: true,
    });
  }
  if (!reason.response) {
    return new AgentApiError({
      code: "NETWORK_ERROR",
      message: "无法连接运行历史服务，请检查服务状态",
      retryable: true,
    });
  }
  return responseValidationError(reason.response.status, payload);
}

function responseValidationError(status: number, value: unknown) {
  return new AgentApiError({
    code: "RESPONSE_VALIDATION_ERROR",
    message: "运行历史服务返回了无法识别的响应结构",
    traceId: isRecord(value) && isString(value.trace_id) ? value.trace_id : undefined,
    status,
  });
}

function isRunListResponse(value: unknown): value is RunListResponse {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(isRunSummary) &&
    isPositiveInteger(value.page) &&
    isPositiveInteger(value.page_size) &&
    isNonnegativeInteger(value.total)
  );
}

function isRunDetailResponse(value: unknown): value is RunDetailResponse {
  return (
    isRecord(value) &&
    isRunSummary(value.run) &&
    isNonnegativeInteger(value.input_token_count) &&
    isNonnegativeInteger(value.output_token_count) &&
    (value.result === null || isDiagnosisResult(value.result)) &&
    Array.isArray(value.approvals) &&
    value.approvals.every(isApprovalHistory)
  );
}

function isStepListResponse(value: unknown): value is StepListResponse {
  return (
    isRecord(value) &&
    isString(value.run_id) &&
    Array.isArray(value.items) &&
    value.items.every(isStepSummary)
  );
}

function isRunSummary(value: unknown): value is RunSummary {
  return (
    isRecord(value) &&
    isString(value.run_id) &&
    isString(value.session_id) &&
    ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "WAITING_APPROVAL", "CANCELLED"].includes(
      String(value.status),
    ) &&
    isNullableString(value.order_id) &&
    isNullableString(value.task_id) &&
    isNonnegativeInteger(value.tool_call_count) &&
    isNonnegativeInteger(value.total_token_count) &&
    isNullableNonnegativeInteger(value.duration_ms) &&
    isNullableString(value.termination_reason) &&
    isNullableString(value.error_code) &&
    isNullableString(value.error_step) &&
    isString(value.created_at) &&
    isNullableString(value.started_at) &&
    isNullableString(value.finished_at)
  );
}

function isStepSummary(value: unknown): value is StepSummary {
  return (
    isRecord(value) &&
    isString(value.step_id) &&
    isPositiveInteger(value.sequence_number) &&
    ["CONTEXT", "ROUTER", "WORKFLOW", "AGENT", "TOOL", "RAG", "LLM", "APPROVAL", "WRITEBACK"].includes(
      String(value.step_type),
    ) &&
    isString(value.step_name) &&
    ["PENDING", "RUNNING", "SUCCEEDED", "FAILED"].includes(String(value.status)) &&
    isNullableString(value.input_summary) &&
    isNullableString(value.output_summary) &&
    isNullableString(value.error_code) &&
    isNullableNonnegativeInteger(value.duration_ms) &&
    isNullableString(value.model_name) &&
    isNullableNonnegativeInteger(value.input_token_count) &&
    isNullableNonnegativeInteger(value.output_token_count) &&
    isNullableNonnegativeInteger(value.total_token_count) &&
    isNullableNonnegativeInteger(value.retry_count) &&
    isString(value.created_at) &&
    isNullableString(value.started_at) &&
    isNullableString(value.finished_at)
  );
}

function isApprovalHistory(value: unknown): value is ApprovalHistory {
  return (
    isRecord(value) &&
    isString(value.approval_id) &&
    ["DRAFT", "WAITING_CONFIRMATION", "CONFIRMED", "EXECUTING", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED", "STALE"].includes(
      String(value.status),
    ) &&
    ["SUBMIT_REVIEW", "CREATE_REWORK"].includes(String(value.operation_type)) &&
    isString(value.target_id) &&
    isNonnegativeInteger(value.target_version) &&
    isReviewDraft(value.original_draft) &&
    isReviewDraft(value.effective_draft) &&
    Array.isArray(value.user_modification_diff) &&
    value.user_modification_diff.every(isApprovalFieldChange) &&
    isNullableString(value.confirmed_at) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isReviewDraft(value: unknown): value is ReviewDraft {
  return (
    isRecord(value) &&
    isString(value.task_id) &&
    isString(value.issue_id) &&
    ["APPROVED", "REJECTED", "REWORK_REQUIRED"].includes(String(value.conclusion)) &&
    isString(value.problem_summary) &&
    isString(value.review_comment) &&
    Array.isArray(value.specification_references) &&
    value.specification_references.every(
      (citation) =>
        isRecord(citation) &&
        isString(citation.document_id) &&
        isString(citation.document_name) &&
        isString(citation.document_version) &&
        Array.isArray(citation.section) &&
        citation.section.every(isString) &&
        isString(citation.chunk_id) &&
        Array.isArray(citation.chunk_ids) &&
        citation.chunk_ids.every(isString) &&
        isString(citation.content) &&
        (citation.relevance_score === null || typeof citation.relevance_score === "number"),
    ) &&
    isRecord(value.suggested_rework) &&
    typeof value.suggested_rework.required === "boolean" &&
    (value.suggested_rework.type === null || value.suggested_rework.type === "COORDINATE_SYSTEM_FIX")
  );
}

function isDiagnosisResult(value: unknown) {
  return (
    isRecord(value) &&
    isString(value.order_id) &&
    [
      "PRODUCTION",
      "PRODUCTION_BLOCKED",
      "QUALITY_REVIEW",
      "REVIEW",
      "DELIVERY",
      "NONE",
      "INSUFFICIENT_INFORMATION",
    ].includes(String(value.blocking_stage)) &&
    isString(value.summary) &&
    Array.isArray(value.root_causes) &&
    value.root_causes.every(
      (cause) => isRecord(cause) && isString(cause.code) && isString(cause.description),
    ) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(
      (evidence) =>
        isRecord(evidence) &&
        evidence.source_type === "TOOL" &&
        isString(evidence.tool_name) &&
        isString(evidence.field_path) &&
        isScalar(evidence.value) &&
        isString(evidence.description),
    ) &&
    Array.isArray(value.suggestions) &&
    value.suggestions.every(
      (suggestion) =>
        isRecord(suggestion) &&
        isString(suggestion.action_type) &&
        isString(suggestion.description),
    ) &&
    typeof value.confidence === "number" &&
    value.confidence >= 0 &&
    value.confidence <= 1
  );
}

function isScalar(value: unknown) {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function isApprovalFieldChange(value: unknown): value is ApprovalFieldChange {
  return (
    isRecord(value) &&
    isString(value.field_path) &&
    isDiffValue(value.before) &&
    isDiffValue(value.after)
  );
}

function isDiffValue(value: unknown) {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (Array.isArray(value) && value.every(isString))
  );
}

function isHistoryError(value: unknown): value is { trace_id: string; code: string; message: string } {
  return isRecord(value) && isString(value.trace_id) && isString(value.code) && isString(value.message);
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isNullableNonnegativeInteger(value: unknown): value is number | null {
  return value === null || isNonnegativeInteger(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
