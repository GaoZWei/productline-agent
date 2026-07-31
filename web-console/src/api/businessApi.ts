import { requestBusinessData } from "./businessClient";
import type { ApiResult, Order, OrderOverview } from "../types/business";

export function fetchOrder(orderId: string): Promise<ApiResult<Order>> {
  return requestBusinessData(`/api/orders/${encodeURIComponent(orderId)}`);
}

export function fetchOrderOverview(orderId: string): Promise<ApiResult<OrderOverview>> {
  return requestBusinessData(`/api/orders/${encodeURIComponent(orderId)}/overview`);
}
