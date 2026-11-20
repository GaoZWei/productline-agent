import axios from "axios";
import { AGENT_USER_ID, AGENT_USER_ROLE, agentHttpClient } from "./agentClient";
import { isReworkInspection, isReworkProcessing, isReworkReview } from "./reworkClient";
import type { ReworkDetail, ReworkInspection, ReworkProcessing, ReworkReview } from "../types/rework";
import type { ReworkInspectionItem } from "../types/reworkApproval";

export type PageReworkAction =
  | "START_REWORK" | "BLOCK_REWORK" | "FAIL_REWORK" | "RESUME_REWORK" | "REGISTER_REWORK_RESULT"
  | "REGISTER_REWORK_INSPECTION" | "SUBMIT_REWORK_REVIEW" | "CREATE_NEXT_REWORK";

export type PageReworkCommand = {
  task_id: string;
  rework_task_id: string;
} & (
  | { operation: "START_REWORK" }
  | { operation: "BLOCK_REWORK" | "FAIL_REWORK" | "RESUME_REWORK" | "CREATE_NEXT_REWORK"; reason: string }
  | { operation: "REGISTER_REWORK_INSPECTION"; items: ReworkInspectionItem[] }
  | { operation: "SUBMIT_REWORK_REVIEW"; status: ReworkReview["status"]; review_comment: string }
  | {
    operation: "REGISTER_REWORK_RESULT";
    artifact: { artifactId: string; artifactVersion: string };
    processing_comment: string;
    evidence_references: string[];
  }
);

export function isPageReworkAction(action: string): action is PageReworkAction {
  return ["START_REWORK", "BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK",
    "REGISTER_REWORK_RESULT", "REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW", "CREATE_NEXT_REWORK"].includes(action);
}

export interface ReworkApprovalReference {
  runId: string;
  approvalId: string;
  nextRound: boolean;
}

export interface ReworkPageTarget {
  order_id: string;
  task_id: string;
  rework_task_id: string;
}

export interface ReworkActionPreview extends ReworkApprovalReference {
  expiresAt: string;
  taskVersion: number;
  roundNumber: number;
  issueId: string;
  reworkStatusAfter: string;
  issueStatusAfter: string;
  deliveryEffect: "NONE" | "RECHECK_ONLY";
  boundMaterials?: { processing: ReworkProcessing; inspection: ReworkInspection | null };
  previousReview?: ReworkReview;
}

export class ReworkActionError extends Error {
  constructor(readonly code: string, readonly traceId?: string) {
    super(code);
  }
}

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const token = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9._:-]{1,128}$/u.test(value);
const invalid = () => new ReworkActionError("RESPONSE_VALIDATION_ERROR");
const path = "/api/agent/rework-actions";

async function post(url: string, body?: unknown): Promise<unknown> {
  try {
    const response = await agentHttpClient.post<unknown>(url, body, { timeout: 60_000 });
    return response.data;
  } catch (error) {
    const response = axios.isAxiosError<unknown>(error) ? error.response : undefined;
    const data = response?.data;
    if (object(data) && object(data.detail) && token(data.detail.code)) {
      throw new ReworkActionError(data.detail.code, token(data.detail.trace_id) ? data.detail.trace_id : undefined);
    }
    throw new ReworkActionError(response?.status === 422 ? "PARAM_VALIDATION_ERROR" : "REQUEST_FAILED");
  }
}

function referencesMatch(value: unknown, expected: readonly string[]): boolean {
  return Array.isArray(value) && value.length === expected.length
    && value.every((item, index) => item === expected[index]);
}

function requestMatches(
  request: Record<string, unknown>, target: Record<string, unknown>, command: PageReworkCommand,
): boolean {
  if (command.operation === "START_REWORK") return Object.keys(request).length === 1;
  if (command.operation === "REGISTER_REWORK_INSPECTION") {
    const items = request.items;
    return Object.keys(request).length === 3
      && request.processingRevision === target.processing_revision
      && Array.isArray(items) && items.length === command.items.length
      && command.items.every((expected, index) => {
        const item: unknown = items[index];
        return object(item) && Object.keys(item).length === 4
          && item.checkItem === expected.checkItem && item.result === expected.result
          && item.comment === expected.comment
          && referencesMatch(item.evidenceReferences, expected.evidenceReferences);
      });
  }
  if (command.operation === "SUBMIT_REWORK_REVIEW") {
    return Object.keys(request).length === 5
      && request.processingRevision === target.processing_revision
      && request.inspectionId === target.inspection_id
      && request.status === command.status && request.reviewComment === command.review_comment;
  }
  if (command.operation !== "REGISTER_REWORK_RESULT") {
    return Object.keys(request).length === 2 && request.reason === command.reason;
  }
  return Object.keys(request).length === 4 && object(request.artifact)
    && request.artifact.artifactId === command.artifact.artifactId
    && request.artifact.artifactVersion === command.artifact.artifactVersion
    && request.processingComment === command.processing_comment
    && referencesMatch(request.evidenceReferences, command.evidence_references);
}

export async function previewReworkAction(
  orderId: string, detail: ReworkDetail, command: PageReworkCommand,
): Promise<ReworkActionPreview> {
  const value = await post(`${path}/preview`, { order_id: orderId, command });
  if (!object(value) || !token(value.run_id) || !token(value.approval_id) || value.order_id !== orderId
    || typeof value.expires_at !== "string" || !Number.isFinite(Date.parse(value.expires_at))
    || !object(value.review) || !object(value.review.draft) || !object(value.review.expected_effects)) {
    throw invalid();
  }
  const { draft, expected_effects: effects } = value.review;
  const { target, request } = draft;
  const expectedDelivery = command.operation === "SUBMIT_REWORK_REVIEW" && command.status === "APPROVED"
    ? "RECHECK_ONLY" : "NONE";
  if (!object(target) || !object(request) || draft.operation !== command.operation
    || target.task_id !== command.task_id || target.rework_task_id !== command.rework_task_id
    || request.expectedVersion !== target.task_version || !Number.isSafeInteger(target.task_version)
    || !Number.isSafeInteger(target.round_number) || typeof target.source_issue_id !== "string"
    || !requestMatches(request, target, command)
    || value.review.effect_semantics !== "EXPECTED_IF_JAVA_ACCEPTS"
    || effects.production_status_after !== "COMPLETED" || effects.delivery_effect !== expectedDelivery
    || !["PENDING", "RUNNING", "BLOCKED", "FAILED", "COMPLETED"].includes(effects.rework_status_after as string)
    || !["OPEN", "PROCESSING", "RESOLVED", "CLOSED"].includes(effects.issue_status_after as string)) {
    throw invalid();
  }
  const preview: ReworkActionPreview = {
    runId: value.run_id, approvalId: value.approval_id, expiresAt: value.expires_at,
    nextRound: command.operation === "CREATE_NEXT_REWORK",
    taskVersion: target.task_version as number, roundNumber: target.round_number as number,
    issueId: target.source_issue_id, reworkStatusAfter: effects.rework_status_after as string,
    issueStatusAfter: effects.issue_status_after as string, deliveryEffect: expectedDelivery,
  };
  if (preview.nextRound) {
    const previous = value.previous_review;
    if (!isReworkReview(previous) || previous.reviewId !== target.review_id
      || previous.inspectionId !== target.inspection_id
      || previous.roundNumber !== target.round_number
      || previous.processingRevision !== target.processing_revision
      || previous.status === "APPROVED"
      || effects.rework_status_after !== "PENDING" || effects.issue_status_after !== "OPEN") throw invalid();
    preview.previousReview = previous;
  }
  if (command.operation === "REGISTER_REWORK_INSPECTION" || command.operation === "SUBMIT_REWORK_REVIEW") {
    const bound = value.bound_materials;
    if (!object(bound) || !isReworkProcessing(bound.processing) || !object(target.artifact)
      || bound.processing.processingRevision !== target.processing_revision
      || bound.processing.artifact.artifactId !== target.artifact.artifactId
      || bound.processing.artifact.artifactVersion !== target.artifact.artifactVersion) throw invalid();
    if (command.operation === "SUBMIT_REWORK_REVIEW") {
      if (!isReworkInspection(bound.inspection) || bound.inspection.result !== "PASSED"
        || bound.inspection.inspectionId !== target.inspection_id
        || bound.inspection.roundNumber !== target.round_number
        || bound.inspection.processingRevision !== target.processing_revision) throw invalid();
      preview.boundMaterials = { processing: bound.processing, inspection: bound.inspection };
    } else {
      if (bound.inspection !== null) throw invalid();
      preview.boundMaterials = { processing: bound.processing, inspection: null };
    }
  }
  if (preview.taskVersion !== detail.taskVersion || preview.roundNumber !== detail.roundNumber
    || preview.issueId !== detail.reworkTask.sourceIssueId
    || target.previous_rework_task_id !== detail.previousReworkTaskId
    || target.processing_revision !== (detail.processing?.processingRevision ?? null)
    || (detail.processing
      ? !object(target.artifact) || target.artifact.artifactId !== detail.processing.artifact.artifactId
        || target.artifact.artifactVersion !== detail.processing.artifact.artifactVersion
      : target.artifact !== null)
    || target.inspection_id !== (detail.inspection?.inspectionId ?? null)
    || target.review_id !== (detail.review?.reviewId ?? null)) {
    // 草稿是新读事实，页面应刷新并让用户重新核对，不能直接沿用旧材料。
    await cancelReworkAction(preview).catch(() => undefined);
    throw new ReworkActionError("APPROVAL_STALE");
  }
  return preview;
}

function approvalPath(reference: ReworkApprovalReference): string {
  return `${path}/${encodeURIComponent(reference.runId)}/${encodeURIComponent(reference.approvalId)}`;
}

const businessId = (value: unknown): value is string =>
  typeof value === "string" && value.length <= 64 && !/[\r\n]/u.test(value)
    && /^[A-Z]+-[A-Z0-9][A-Z0-9-]*$/u.test(value);

function decodeExecution(value: unknown, reference: ReworkApprovalReference) {
  if (!object(value) || value.approval_id !== reference.approvalId) throw invalid();
  const nextId = value.next_rework_task_id ?? null;
  if (nextId !== null && !businessId(nextId)) throw invalid();
  if (value.outcome === "SUCCEEDED" && businessId(value.operation_id)
    && reference.nextRound === (nextId !== null)) {
    return { outcome: "SUCCEEDED", operationId: value.operation_id, nextReworkId: nextId } as const;
  }
  if ((value.outcome === "IN_PROGRESS" || value.outcome === "UNKNOWN")
    && value.operation_id === null && nextId === null) {
    return { outcome: value.outcome, code: token(value.error_code) ? value.error_code : null } as const;
  }
  throw invalid();
}

export async function confirmReworkAction(reference: ReworkApprovalReference) {
  return decodeExecution(await post(`${approvalPath(reference)}/confirm`, { decision: "CONFIRM" }), reference);
}

export async function reconcileReworkAction(reference: ReworkApprovalReference, target: ReworkPageTarget) {
  const value = await post(`${approvalPath(reference)}/reconcile`, target);
  if (object(value) && value.approval_id === reference.approvalId && value.operation_id === null
    && (value.outcome === "WAITING_CONFIRMATION" || value.outcome === "NOT_SUBMITTED")) {
    return { outcome: value.outcome } as const;
  }
  const result = decodeExecution(value, reference);
  if (result.outcome === "SUCCEEDED" && result.nextReworkId === target.rework_task_id) throw invalid();
  return result;
}

export async function cancelReworkAction(reference: ReworkApprovalReference): Promise<void> {
  const value = await post(`${approvalPath(reference)}/cancel`);
  if (!object(value) || value.approval_id !== reference.approvalId || value.status !== "CANCELLED") {
    throw invalid();
  }
}

function recoveryKey(target: ReworkPageTarget) {
  return `rework-confirmation:${JSON.stringify([AGENT_USER_ID, AGENT_USER_ROLE, target.order_id, target.task_id, target.rework_task_id])}`;
}

export function readReworkRecovery(target: ReworkPageTarget): ReworkApprovalReference | undefined {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(recoveryKey(target)) ?? "null");
    if (object(value) && token(value.runId) && token(value.approvalId) && typeof value.nextRound === "boolean") {
      return { runId: value.runId, approvalId: value.approvalId, nextRound: value.nextRound };
    }
  } catch {
    // 浏览器禁用或清理存储时，只保留当前表单中的原审批。
  }
}

export function storeReworkRecovery(target: ReworkPageTarget, reference?: ReworkApprovalReference) {
  try {
    if (reference) {
      const { runId, approvalId, nextRound } = reference;
      sessionStorage.setItem(recoveryKey(target), JSON.stringify({ runId, approvalId, nextRound }));
    } else {
      sessionStorage.removeItem(recoveryKey(target));
    }
  } catch {
    // 浏览器存储不是执行授权，原审批仍由服务端保存。
  }
}
