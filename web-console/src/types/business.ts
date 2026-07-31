export interface ApiEnvelope<T> {
  success: boolean;
  code: string;
  message: string;
  data: T;
  trace_id: string;
  retryable: boolean;
}

export interface ApiResult<T> {
  data: T;
  traceId: string;
}

export interface Order {
  orderId: string;
  productType: string;
  status: string;
}

export interface ProductionTask {
  taskId: string;
  orderId: string;
  status: string;
  version: number;
}

export interface ProductionStep {
  stepId: string;
  taskId: string;
  stepName: string;
  sequenceNumber: number;
  status: string;
}

export interface QualityIssue {
  issueId: string;
  taskId: string;
  issueType: string;
  status: string;
  description: string;
}

export interface ReviewRecord {
  reviewId: string;
  issueId: string;
  status: string;
  reviewComment: string | null;
}

export interface DeliveryRecord {
  deliveryId: string;
  orderId: string;
  status: string;
}

export interface QualityIssueOverview {
  issue: QualityIssue;
  reviews: ReviewRecord[];
}

export interface TaskOverview {
  task: ProductionTask;
  steps: ProductionStep[];
  qualityIssues: QualityIssueOverview[];
}

export interface OrderOverview {
  order: Order;
  tasks: TaskOverview[];
  deliveryRecords: DeliveryRecord[];
}
