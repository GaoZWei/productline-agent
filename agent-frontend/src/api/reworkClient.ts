import { AGENT_USER_ID, AGENT_USER_ROLE } from "./agentClient";
import { businessHttpClient, BusinessApiError } from "./businessClient";
import type { ApiEnvelope, ApiResult } from "../types/business";
import {
  reworkActionLabels, reworkRecordSequence,
  type ReworkDetail, type ReworkHistoryKind, type ReworkHistoryPage,
  type ReworkProcessing, type ReworkInspection, type ReworkReview,
} from "../types/rework";

type JsonObject = Record<string, unknown>;
const object = (v: unknown): v is JsonObject => typeof v === "object" && v !== null && !Array.isArray(v);
// 使用Java空白语义校验而不改写原文，NBSP等合法材料不能被JS trim误判为空。
const text = (v: unknown): v is string => typeof v === "string" && !v.includes("\0")
  && /[^\t\n\v\f\r\x1c-\x1f \u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000]/u.test(v);
const id = (v: unknown): v is string => typeof v === "string" && v.length <= 64
  && !/[\r\n]/.test(v) && /^[A-Z]+-[A-Z0-9][A-Z0-9-]*$/.test(v);
const sequence = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) > 0;
const instant = (v: unknown): v is string => text(v) && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
const references = (v: unknown): v is string[] => Array.isArray(v) && v.length >= 1 && v.length <= 20 && v.every(text);
const result = (v: unknown) => v === "PASSED" || v === "FAILED";
const cursorValid = (v: unknown): v is string => text(v) && !/[\r\n]/.test(v);
function fields(v: unknown, keys: string): v is JsonObject {
  return object(v) && Object.keys(v).length === keys.split(" ").length && keys.split(" ").every(k => Object.hasOwn(v, k));
}
function processing(v: unknown): v is ReworkProcessing {
  return fields(v, "processingRevision artifact processingComment evidenceReferences registeredBy registeredAt") && sequence(v.processingRevision)
    && fields(v.artifact, "artifactId artifactVersion") && text(v.artifact.artifactId) && text(v.artifact.artifactVersion)
    && text(v.processingComment) && references(v.evidenceReferences) && text(v.registeredBy) && instant(v.registeredAt);
}
function inspection(v: unknown): v is ReworkInspection {
  return fields(v, "inspectionId inspectionSequence roundNumber processingRevision inspectorId inspectedAt result items")
    && id(v.inspectionId) && sequence(v.inspectionSequence) && sequence(v.roundNumber) && sequence(v.processingRevision)
    && text(v.inspectorId) && instant(v.inspectedAt) && result(v.result) && Array.isArray(v.items) && v.items.length >= 1 && v.items.length <= 50
    && v.items.every(item => fields(item, "checkItem result comment evidenceReferences") && text(item.checkItem) && result(item.result) && text(item.comment) && references(item.evidenceReferences))
    && v.result === (v.items.every(item => item.result === "PASSED") ? "PASSED" : "FAILED");
}
function review(v: unknown): v is ReworkReview {
  return fields(v, "reviewId reviewSequence roundNumber processingRevision inspectionId status reviewComment reviewedBy reviewedAt")
    && id(v.reviewId) && sequence(v.reviewSequence) && sequence(v.roundNumber) && sequence(v.processingRevision) && id(v.inspectionId)
    && ["APPROVED", "REJECTED", "REWORK_REQUIRED"].includes(v.status as string)
    && text(v.reviewComment) && text(v.reviewedBy) && instant(v.reviewedAt);
}
export { processing as isReworkProcessing, inspection as isReworkInspection, review as isReworkReview };
function detail(v: unknown): v is ReworkDetail {
  if (!fields(v, "reworkTask issueStatus roundNumber previousReworkTaskId allowedActions taskVersion processing inspection review")
    || !fields(v.reworkTask, "reworkTaskId taskId sourceIssueId status reason")
    || !id(v.reworkTask.reworkTaskId) || !id(v.reworkTask.taskId)
    || !(v.reworkTask.sourceIssueId === null || id(v.reworkTask.sourceIssueId))
    || !["PENDING", "RUNNING", "BLOCKED", "FAILED", "COMPLETED"].includes(v.reworkTask.status as string) || !text(v.reworkTask.reason)
    || !(v.issueStatus === null || ["OPEN", "PROCESSING", "RESOLVED", "CLOSED"].includes(v.issueStatus as string))
    || (v.reworkTask.sourceIssueId === null) !== (v.issueStatus === null)
    || !(v.roundNumber === null || sequence(v.roundNumber)) || !(v.previousReworkTaskId === null || id(v.previousReworkTaskId))
    || !Number.isSafeInteger(v.taskVersion) || (v.taskVersion as number) < 0
    || !Array.isArray(v.allowedActions) || !v.allowedActions.every(a => typeof a === "string" && Object.hasOwn(reworkActionLabels, a))
    || new Set(v.allowedActions).size !== v.allowedActions.length
    || !(v.processing === null || processing(v.processing)) || !(v.inspection === null || inspection(v.inspection)) || !(v.review === null || review(v.review))) return false;
  if (v.roundNumber === null) {
    if (v.previousReworkTaskId !== null || v.processing !== null || v.inspection !== null || v.review !== null || v.allowedActions.length) return false;
  } else if (v.reworkTask.sourceIssueId === null || (v.roundNumber === 1) !== (v.previousReworkTaskId === null)) return false;
  if (v.inspection !== null && (!processing(v.processing) || v.inspection.roundNumber !== v.roundNumber || v.inspection.processingRevision !== v.processing.processingRevision)) return false;
  if (v.review !== null && (!inspection(v.inspection) || v.inspection.result !== "PASSED" || v.review.roundNumber !== v.roundNumber || v.review.processingRevision !== v.inspection.processingRevision || v.review.inspectionId !== v.inspection.inspectionId)) return false;
  return true;
}
function invalid(traceId?: string): BusinessApiError {
  return new BusinessApiError({ code: "RESPONSE_VALIDATION_ERROR", message: "返工响应结构或资源绑定不一致，请刷新后重试", traceId });
}
function resourcePath(taskId: string, reworkId: string): string {
  if (!id(taskId) || !taskId.startsWith("TASK-") || !id(reworkId)) {
    throw new BusinessApiError({ code: "PARAM_VALIDATION_ERROR", message: "返工资源编号无效" });
  }
  return `/api/tasks/${encodeURIComponent(taskId)}/reworks/${encodeURIComponent(reworkId)}`;
}
async function read(path: string, params?: Record<string, string | number>): Promise<ApiResult<unknown>> {
  // 这里只查询Java；身份沿用演示上下文，是否允许读取由Java裁决。
  const response = await businessHttpClient.get<ApiEnvelope<unknown>>(path, {
    params, headers: { "X-User-Id": AGENT_USER_ID, "X-User-Role": AGENT_USER_ROLE },
  });
  return { data: response.data.data, traceId: response.data.trace_id };
}
export async function fetchReworkDetail(taskId: string, reworkId: string): Promise<ApiResult<ReworkDetail>> {
  const value = await read(resourcePath(taskId, reworkId));
  if (!detail(value.data) || value.data.reworkTask.taskId !== taskId || value.data.reworkTask.reworkTaskId !== reworkId) throw invalid(value.traceId);
  return { ...value, data: value.data };
}
export async function fetchReworkHistory<K extends ReworkHistoryKind>(taskId: string, reworkId: string, kind: K, cursor: string | null = null): Promise<ApiResult<ReworkHistoryPage<K>>> {
  const path = resourcePath(taskId, reworkId);
  if (!["results", "inspections", "reviews"].includes(kind) || !(cursor === null || cursorValid(cursor))) {
    throw new BusinessApiError({ code: "PARAM_VALIDATION_ERROR", message: "返工历史分页参数无效" });
  }
  const value = await read(`${path}/${kind}`, { limit: 20, ...(cursor === null ? {} : { cursor }) });
  const v = value.data;
  const validRecord = { results: processing, inspections: inspection, reviews: review }[kind];
  if (!fields(v, "taskId reworkTaskId records nextCursor") || v.taskId !== taskId || v.reworkTaskId !== reworkId
    || !Array.isArray(v.records) || v.records.length > 20 || !v.records.every(validRecord)
    || !(v.nextCursor === null || cursorValid(v.nextCursor)) || (v.nextCursor !== null && v.records.length === 0)) throw invalid(value.traceId);
  const page = v as unknown as ReworkHistoryPage<K>;
  if (page.records.some((record, index) => index > 0 && reworkRecordSequence(kind, record) <= reworkRecordSequence(kind, page.records[index - 1]!))) throw invalid(value.traceId);
  return { ...value, data: page };
}
