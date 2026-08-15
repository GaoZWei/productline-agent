import { requestOrderDiagnosis } from "./agentClient";
import type { OrderDiagnosisResponse, PageContext } from "../types/agent";

export function diagnoseOrder(
  orderId: string,
  userMessage: string,
  pageContext: PageContext,
  sessionId?: string,
): Promise<OrderDiagnosisResponse> {
  return requestOrderDiagnosis({
    session_id: sessionId,
    order_id: orderId,
    user_message: userMessage,
    page_context: pageContext,
  });
}
