export type BlockingStage =
  | "PRODUCTION"
  | "PRODUCTION_BLOCKED"
  | "QUALITY_REVIEW"
  | "REVIEW"
  | "DELIVERY"
  | "NONE"
  | "INSUFFICIENT_INFORMATION";

// 定义了三个页面类型，分别是订单详情、任务详情和质量问题
export type PageType = "order-detail" | "task-detail" | "quality-issue";
// 核心字段
export interface PageContext {
  current_system: "production-system";
  current_page: PageType;
  order_id: string;
  task_id: string | null;
  issue_id: string | null;
  batch_id: string | null;
  product_type: string | null;
  satellite_type: string | null;
  user_role: string;
}

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
  session_id?: string | null;
  order_id?: string;
  user_message: string;
  page_context?: PageContext;
}

export interface OrderDiagnosisResponse {
  run_id: string;
  session_id: string;
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

export interface KnowledgeCitation {
  document_id: string;
  document_name: string;
  document_version: string;
  section: string[];
  chunk_id: string;
  chunk_ids: string[];
  content: string;
  relevance_score: number | null;
}
