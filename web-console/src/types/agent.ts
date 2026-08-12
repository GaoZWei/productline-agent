export type BlockingStage =
  | "PRODUCTION"
  | "PRODUCTION_BLOCKED"
  | "QUALITY_REVIEW"
  | "REVIEW"
  | "DELIVERY"
  | "NONE"
  | "INSUFFICIENT_INFORMATION";

export interface RootCause {
  code: string;
  description: string;
}

export interface DiagnosisEvidence {
  source_type: "TOOL";
  tool_name: string;
  field_path: string;
  value: string | number | boolean | null;
  description: string;
}

export interface DiagnosisSuggestion {
  action_type: string;
  description: string;
}

export interface DiagnosisResult {
  order_id: string;
  blocking_stage: BlockingStage;
  summary: string;
  root_causes: RootCause[];
  evidence: DiagnosisEvidence[];
  suggestions: DiagnosisSuggestion[];
  confidence: number;
}

export interface OrderDiagnosisRequest {
  order_id: string;
  user_message: string;
}

export interface OrderDiagnosisResponse {
  run_id: string;
  trace_id: string;
  diagnosis: DiagnosisResult;
}

export interface OrderDiagnosisErrorResponse {
  run_id: string | null;
  trace_id: string;
  code: string;
  message: string;
  retryable: boolean;
  error_step: string | null;
}
