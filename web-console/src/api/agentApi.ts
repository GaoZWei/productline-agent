import { requestOrderDiagnosis } from "./agentClient";
import type { OrderDiagnosisResponse } from "../types/agent";

export function diagnoseOrder(
  orderId: string,
  userMessage: string,
): Promise<OrderDiagnosisResponse> {
  return requestOrderDiagnosis({
    order_id: orderId,
    user_message: userMessage,
  });
}
