import type { ReworkTask } from "./business";

export const reworkActionLabels = {
  START_REWORK: "开始返工",
  BLOCK_REWORK: "登记阻塞",
  FAIL_REWORK: "登记失败",
  RESUME_REWORK: "恢复处理",
  REGISTER_REWORK_RESULT: "登记成果",
  REGISTER_REWORK_INSPECTION: "登记人工检查",
  SUBMIT_REWORK_REVIEW: "再次复核",
  CREATE_NEXT_REWORK: "创建下一轮返工",
} as const;

export type ReworkAction = keyof typeof reworkActionLabels;
export type InspectionResult = "PASSED" | "FAILED";
export interface ReworkProcessing {
  processingRevision: number;
  artifact: { artifactId: string; artifactVersion: string };
  processingComment: string;
  evidenceReferences: string[];
  registeredBy: string;
  registeredAt: string;
}
export interface ReworkInspection {
  inspectionId: string;
  inspectionSequence: number;
  roundNumber: number;
  processingRevision: number;
  inspectorId: string;
  inspectedAt: string;
  result: InspectionResult;
  items: {
    checkItem: string;
    result: InspectionResult;
    comment: string;
    evidenceReferences: string[];
  }[];
}
export interface ReworkReview {
  reviewId: string;
  reviewSequence: number;
  roundNumber: number;
  processingRevision: number;
  inspectionId: string;
  status: "APPROVED" | "REJECTED" | "REWORK_REQUIRED";
  reviewComment: string;
  reviewedBy: string;
  reviewedAt: string;
}
export interface ReworkDetail {
  reworkTask: ReworkTask;
  issueStatus: "OPEN" | "PROCESSING" | "RESOLVED" | "CLOSED" | null;
  roundNumber: number | null;
  previousReworkTaskId: string | null;
  allowedActions: ReworkAction[];
  taskVersion: number;
  processing: ReworkProcessing | null;
  inspection: ReworkInspection | null;
  review: ReworkReview | null;
}
export interface ReworkHistoryRecords {
  results: ReworkProcessing;
  inspections: ReworkInspection;
  reviews: ReworkReview;
}
export type ReworkHistoryKind = keyof ReworkHistoryRecords;
export interface ReworkHistoryPage<K extends ReworkHistoryKind> {
  taskId: string;
  reworkTaskId: string;
  records: ReworkHistoryRecords[K][];
  nextCursor: string | null;
}

export function reworkRecordSequence(kind: ReworkHistoryKind, record: ReworkHistoryRecords[ReworkHistoryKind]): number {
  if (kind === "results") return (record as ReworkProcessing).processingRevision;
  if (kind === "inspections") return (record as ReworkInspection).inspectionSequence;
  return (record as ReworkReview).reviewSequence;
}
