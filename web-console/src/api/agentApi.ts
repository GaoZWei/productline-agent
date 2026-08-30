import {
  requestApprovalConfirmation,
  requestApprovalOperationLog,
  requestOrderDiagnosis,
} from "./agentClient";
import type {
  ApprovalConfirmationResponse,
  OrderDiagnosisResponse,
  OperationLogDetail,
  PageContext,
  ReviewApprovalDecision,
} from "../types/agent";

export function diagnoseOrder(
  orderId: string,
  userMessage: string,
  pageContext: PageContext,
  sessionId?: string,
  eventStreamId?: string,
): Promise<OrderDiagnosisResponse> {
  return requestOrderDiagnosis(
    {
      session_id: sessionId,
      order_id: orderId,
      user_message: userMessage,
      page_context: pageContext,
    },
    eventStreamId,
  );
}

export function confirmReviewApproval(
  decision: ReviewApprovalDecision,
): Promise<ApprovalConfirmationResponse> {
  return requestApprovalConfirmation(decision);
}

export function getApprovalOperationLog(approvalId: string): Promise<OperationLogDetail> {
  return requestApprovalOperationLog(approvalId);
}
