import {
  requestAgentCapabilities,
  requestAgentMessage,
  requestApprovalConfirmation,
  requestApprovalCancellation,
  requestApprovalOperationLog,
  requestReworkApproval,
  requestOrderDiagnosis,
} from "./agentClient";
import type {
  AgentCapabilitiesResponse,
  AgentMessageRequest,
  AgentMessageResponse,
  ApprovalConfirmationResponse,
  ApprovalCancellationResponse,
  OrderDiagnosisResponse,
  OperationLogDetail,
  PageContext,
  ReviewApprovalDecision,
  ReworkApprovalCreationResponse,
} from "../types/agent";

export function getAgentCapabilities(): Promise<AgentCapabilitiesResponse> {
  return requestAgentCapabilities();
}

export function sendAgentMessage(
  message: AgentMessageRequest,
  eventStreamId?: string,
): Promise<AgentMessageResponse> {
  return requestAgentMessage(message, eventStreamId);
}

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
  eventStreamId?: string,
): Promise<ApprovalConfirmationResponse> {
  return requestApprovalConfirmation(decision, eventStreamId);
}

export function cancelReviewApproval(
  approvalId: string,
): Promise<ApprovalCancellationResponse> {
  return requestApprovalCancellation(approvalId);
}

export function createReworkApproval(
  sourceApprovalId: string,
): Promise<ReworkApprovalCreationResponse> {
  return requestReworkApproval(sourceApprovalId);
}

export function getApprovalOperationLog(approvalId: string): Promise<OperationLogDetail> {
  return requestApprovalOperationLog(approvalId);
}
