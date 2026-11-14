// T826仅提供未来确认卡片的独立类型契约，当前无HTTP入口、运行时解码或写操作。
// 资源格式、安全整数、Java UTF-16长度和材料绑定仍由服务端严格校验。

export const REWORK_APPROVAL_TOOLS = {
  CREATE_LIFECYCLE_REWORK: "create_lifecycle_rework",
  START_REWORK: "start_rework",
  BLOCK_REWORK: "block_rework",
  FAIL_REWORK: "fail_rework",
  RESUME_REWORK: "resume_rework",
  REGISTER_REWORK_RESULT: "register_rework_result",
  REGISTER_REWORK_INSPECTION: "register_rework_inspection",
  SUBMIT_REWORK_REVIEW: "submit_rework_review",
  CREATE_NEXT_REWORK: "create_next_rework",
} as const;

export type ReworkApprovalOperation = keyof typeof REWORK_APPROVAL_TOOLS;
export interface ReworkArtifactIdentity {
  readonly artifactId: string;
  readonly artifactVersion: string;
}

interface TargetBase {
  readonly task_id: string;
  readonly task_version: number;
  readonly source_issue_id: string;
}

export interface UncreatedReworkTarget extends TargetBase {
  readonly rework_task_id: null;
  readonly round_number: null;
  readonly previous_rework_task_id: null;
  readonly processing_revision: null;
  readonly artifact: null;
  readonly inspection_id: null;
  readonly review_id: null;
}

interface ManagedRound extends TargetBase {
  readonly rework_task_id: string;
  readonly round_number: number;
  readonly previous_rework_task_id: string | null;
}

export type ManagedReworkTarget = ManagedRound & (
  | { readonly processing_revision: null; readonly artifact: null; readonly inspection_id: null; readonly review_id: null }
  | { readonly processing_revision: number; readonly artifact: ReworkArtifactIdentity; readonly inspection_id: null; readonly review_id: null }
  | { readonly processing_revision: number; readonly artifact: ReworkArtifactIdentity; readonly inspection_id: string; readonly review_id: string | null }
);

export type CurrentMaterialTarget = Extract<ManagedReworkTarget, { readonly processing_revision: number }>;
export type CurrentInspectionTarget = Extract<ManagedReworkTarget, { readonly inspection_id: string }>;
export type PreviousReviewedTarget = CurrentInspectionTarget & { readonly review_id: string };

interface VersionRequest { readonly expectedVersion: number }
interface ReasonRequest extends VersionRequest { readonly reason: string }
export interface ReworkInspectionItem {
  readonly checkItem: string;
  readonly result: "PASSED" | "FAILED";
  readonly comment: string;
  readonly evidenceReferences: readonly string[];
}
interface ResultRequest extends VersionRequest {
  readonly artifact: ReworkArtifactIdentity;
  readonly processingComment: string;
  readonly evidenceReferences: readonly string[];
}
interface InspectionRequest extends VersionRequest {
  readonly processingRevision: number;
  readonly items: readonly ReworkInspectionItem[];
}
interface ReviewRequest extends VersionRequest {
  readonly processingRevision: number;
  readonly inspectionId: string;
  readonly status: "APPROVED" | "REJECTED" | "REWORK_REQUIRED";
  readonly reviewComment: string;
}

interface Draft<O extends ReworkApprovalOperation, T, R> {
  readonly operation: O;
  readonly target: T;
  readonly request: R;
}

export type ReworkApprovalDraft =
  | Draft<"CREATE_LIFECYCLE_REWORK", UncreatedReworkTarget, ReasonRequest & { readonly sourceIssueId: string }>
  | Draft<"START_REWORK", ManagedReworkTarget, VersionRequest>
  | Draft<"BLOCK_REWORK", ManagedReworkTarget, ReasonRequest>
  | Draft<"FAIL_REWORK", ManagedReworkTarget, ReasonRequest>
  | Draft<"RESUME_REWORK", ManagedReworkTarget, ReasonRequest>
  | Draft<"REGISTER_REWORK_RESULT", ManagedReworkTarget, ResultRequest>
  | Draft<"REGISTER_REWORK_INSPECTION", CurrentMaterialTarget, InspectionRequest>
  | Draft<"SUBMIT_REWORK_REVIEW", CurrentInspectionTarget, ReviewRequest>
  | Draft<"CREATE_NEXT_REWORK", PreviousReviewedTarget, ReasonRequest>;

export interface ReworkExpectedEffects {
  readonly production_status_after: "COMPLETED";
  readonly rework_status_after: "PENDING" | "RUNNING" | "BLOCKED" | "FAILED" | "COMPLETED";
  readonly issue_status_after: "OPEN" | "PROCESSING" | "RESOLVED" | "CLOSED";
  readonly delivery_effect: "NONE" | "RECHECK_ONLY";
}

export type ReworkDraftReview = {
  [O in ReworkApprovalOperation]: {
    readonly draft: Extract<ReworkApprovalDraft, { readonly operation: O }>;
    readonly pending_tool: (typeof REWORK_APPROVAL_TOOLS)[O];
    readonly required_permission: O extends "SUBMIT_REWORK_REVIEW" ? "REVIEW_WRITE" : "REWORK_WRITE";
    readonly effect_semantics: "EXPECTED_IF_JAVA_ACCEPTS";
    readonly expected_effects: ReworkExpectedEffects;
  }
}[ReworkApprovalOperation];
