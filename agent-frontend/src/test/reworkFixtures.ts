import type { ReworkDetail, ReworkProcessing, ReworkInspection, ReworkReview } from "../types/rework";

export const reworkPath = "/api/tasks/TASK-030-A/reworks/REWORK-Z9";
export function processingFixture(revision = 1): ReworkProcessing {
  return { processingRevision: revision, artifact: { artifactId: "成果原件", artifactVersion: "001.0" },
    processingComment: "  人工修正坐标系\n保留原始说明  ", evidenceReferences: ["javascript:证据只作文本", "evidence://人工检查/001"],
    registeredBy: "operator-001", registeredAt: "2026-11-19T01:00:00.123456789Z" };
}
export function inspectionFixture(sequence = 1, revision = 1): ReworkInspection {
  return { inspectionId: `INSPECT-${sequence}`, inspectionSequence: sequence, roundNumber: 2, processingRevision: revision,
    inspectorId: "checker-001", inspectedAt: "2026-11-19T02:00:00Z", result: "PASSED",
    items: [{ checkItem: "坐标系统一", result: "PASSED", comment: "人工核对通过", evidenceReferences: ["evidence://检查原件"] }] };
}
export function reviewFixture(sequence = 1): ReworkReview {
  return { reviewId: `REVIEW-${sequence}`, reviewSequence: sequence, roundNumber: 2, processingRevision: 1,
    inspectionId: "INSPECT-1", status: "REWORK_REQUIRED", reviewComment: "需要再次处理", reviewedBy: "reviewer-001", reviewedAt: "2026-11-19T03:00:00Z" };
}
export function detailFixture(): ReworkDetail {
  return { reworkTask: { taskId: "TASK-030-A", reworkTaskId: "REWORK-Z9", sourceIssueId: "ISSUE-030-A", status: "COMPLETED", reason: "人工返工验证" },
    issueStatus: "OPEN", taskVersion: 12, roundNumber: 2, previousReworkTaskId: "REWORK-A1", allowedActions: ["CREATE_NEXT_REWORK"],
    processing: processingFixture(), inspection: inspectionFixture(), review: reviewFixture() };
}
export function envelope(data: unknown, trace = "trace-t831") {
  return { success: true, code: "SUCCESS", message: "success", data, trace_id: trace, retryable: false };
}
export function historyPage(records: unknown[] = [], nextCursor: string | null = null) {
  return { taskId: "TASK-030-A", reworkTaskId: "REWORK-Z9", records, nextCursor };
}
