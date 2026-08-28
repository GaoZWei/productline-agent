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
// 规范引用：它表示一条可以追溯的规范依据
export interface KnowledgeCitation {
  document_id: string; // 哪份规范引用
  document_name: string;
  document_version: string; // 哪个版本的规范引用
  section: string[]; // 哪个章节引用
  chunk_id: string; //哪些原始分块
  chunk_ids: string[];
  content: string; // 原文内容
  relevance_score: number | null; // 检索相关性分数
}
// 复核结论 三个结果：通过、拒绝、需要返工
export type ReviewConclusion = "APPROVED" | "REJECTED" | "REWORK_REQUIRED";
// 返工建议 当前只实现了坐标系返工
export type ReworkType = "COORDINATE_SYSTEM_FIX";

export interface ReworkSuggestion {
  required: boolean;
  type: ReworkType | null;
}
// 用户最终准备确认的完整复核单
export interface ReviewDraft {
  task_id: string; // 复核哪个任务
  issue_id: string; // 复核哪个质检问题
  conclusion: ReviewConclusion; // 复核结论
  problem_summary: string; // agent根据事实整理的问题摘要
  review_comment: string; // 复核意见
  specification_references: KnowledgeCitation[]; // 规范依据
  suggested_rework: ReworkSuggestion; // 是否需要创建返工任务
}

export type ApprovalStatus =
  | "DRAFT"
  | "WAITING_CONFIRMATION"
  | "CONFIRMED"
  | "EXECUTING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED"
  | "STALE";

export type ApprovalOperationType = "SUBMIT_REVIEW" | "CREATE_REWORK";
// 一张完整的“待确认单”
export interface ReviewApproval {
  approval_id: string; // 确认单身份
  run_id: string | null; // 由哪个agent run 生成
  status: ApprovalStatus; // 当前能不能确认
  operation_type: ApprovalOperationType;
  target_id: string; // 将影响哪个业务对象
  target_version: number; // 生成草稿时看到的业务版本
  draft: ReviewDraft; // 用户实际审查的内容
}
// 确认事件数据
export interface ReviewApprovalDecision {
  approval_id: string;
  draft: ReviewDraft;
}

export interface WriteReviewResult {
  approval_id: string;
  task_id: string;
  issue_id: string;
  review_id: string;
  status: ReviewConclusion;
  review_comment: string;
  task_version: number;
  java_trace_id: string;
}

export interface CreateReworkTaskResult {
  approval_id: string;
  task_id: string;
  source_issue_id: string;
  rework_task_id: string;
  rework_type: ReworkType;
  status: "PENDING";
  reason: string;
  task_version: number;
  java_trace_id: string;
}

export interface ApprovalConfirmationResponse {
  approval_id: string;
  status: "SUCCEEDED";
  trace_id: string;
  result: WriteReviewResult | CreateReworkTaskResult;
}

export interface ApprovalConfirmationErrorResponse {
  approval_id: string | null;
  status: ApprovalStatus | null;
  trace_id: string;
  code: string;
  message: string;
  retryable: boolean;
}

export interface OperationBeforeSummary {
  task_id: string;
  issue_id: string;
  task_version: number;
  conclusion: ReviewConclusion;
  problem_summary: string;
  review_comment: string;
  rework_required: boolean;
  rework_type: ReworkType | null;
  specification_sources: string[];
}

export interface OperationFieldChange {
  field_path: string;
  before: string | boolean | string[] | null;
  after: string | boolean | string[] | null;
}

export interface OperationFailureSummary {
  code: string;
  status_code: number;
  retryable: boolean;
}

export interface ReviewOperationResultSummary {
  operation_type: "SUBMIT_REVIEW";
  task_id: string;
  issue_id: string;
  review_id: string;
  status: ReviewConclusion;
  review_comment: string;
  task_version: number;
}

export interface ReworkOperationResultSummary {
  operation_type: "CREATE_REWORK";
  task_id: string;
  source_issue_id: string;
  rework_task_id: string;
  rework_type: ReworkType;
  status: "PENDING";
  reason: string;
  task_version: number;
}

export interface OperationAfterSummary {
  outcome: "SUCCEEDED" | "FAILED" | "STALE";
  result: ReviewOperationResultSummary | ReworkOperationResultSummary | null;
  failure: OperationFailureSummary | null;
}

export interface OperationLogDetail {
  operation_log_id: string;
  approval_id: string;
  operation_type: ApprovalOperationType;
  target_id: string;
  target_version: number;
  confirmed_by_user_id: string;
  before_summary: OperationBeforeSummary;
  after_summary: OperationAfterSummary;
  user_modification_diff: OperationFieldChange[];
  java_trace_id: string | null;
  created_at: string;
}
