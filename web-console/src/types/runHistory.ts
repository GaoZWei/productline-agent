import type {
  ApprovalOperationType,
  ApprovalStatus,
  DiagnosisResult,
  ReviewDraft,
} from "./agent";

export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "WAITING_APPROVAL"
  | "CANCELLED";

export type StepType =
  | "CONTEXT"
  | "ROUTER"
  | "WORKFLOW"
  | "AGENT"
  | "TOOL"
  | "RAG"
  | "LLM"
  | "APPROVAL"
  | "WRITEBACK";

export type StepStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";

export interface RunSummary {
  run_id: string;
  session_id: string;
  status: RunStatus;
  order_id: string | null;
  task_id: string | null;
  tool_call_count: number;
  total_token_count: number;
  duration_ms: number | null;
  termination_reason: string | null;
  error_code: string | null;
  error_step: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunListResponse {
  items: RunSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface ApprovalFieldChange {
  field_path: string;
  before: string | boolean | string[] | null;
  after: string | boolean | string[] | null;
}

export interface ApprovalHistory {
  approval_id: string;
  status: ApprovalStatus;
  operation_type: ApprovalOperationType;
  target_id: string;
  target_version: number;
  original_draft: ReviewDraft;
  effective_draft: ReviewDraft;
  user_modification_diff: ApprovalFieldChange[];
  confirmed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunDetailResponse {
  run: RunSummary;
  input_token_count: number;
  output_token_count: number;
  result: DiagnosisResult | null;
  approvals: ApprovalHistory[];
}

export interface StepSummary {
  step_id: string;
  sequence_number: number;
  step_type: StepType;
  step_name: string;
  status: StepStatus;
  input_summary: string | null;
  output_summary: string | null;
  error_code: string | null;
  duration_ms: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface StepListResponse {
  run_id: string;
  items: StepSummary[];
}
