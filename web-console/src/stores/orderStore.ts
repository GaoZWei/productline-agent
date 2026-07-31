import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { fetchOrder, fetchOrderOverview } from "../api/businessApi";
import { BusinessApiError } from "../api/businessClient";
import type { Order, OrderOverview } from "../types/business";

export const DEMO_ORDER_IDS = [
  "ORDER-001",
  "ORDER-002",
  "ORDER-003",
  "ORDER-004",
  "ORDER-005",
] as const;

export type DemoOrderId = (typeof DEMO_ORDER_IDS)[number];

export const ORDER_SCENES: Record<DemoOrderId, string> = {
  "ORDER-001": "正常生产",
  "ORDER-002": "生产阻塞",
  "ORDER-003": "质检问题阻塞",
  "ORDER-004": "等待复核",
  "ORDER-005": "满足交付",
};

export const useOrderStore = defineStore("orders", () => {
  const orders = ref<Order[]>([]);
  const selectedOrderId = ref<DemoOrderId>("ORDER-003");
  const overview = ref<OrderOverview>();
  const listLoading = ref(false);
  const detailLoading = ref(false);
  const error = ref<BusinessApiError>();
  const traceId = ref<string>();
  const initialized = ref(false);
  let detailRequestSequence = 0;

  const selectedOrder = computed(() =>
    orders.value.find((order) => order.orderId === selectedOrderId.value),
  );

  async function initialize() {
    if (initialized.value) return;
    listLoading.value = true;
    error.value = undefined;
    try {
      const results = await Promise.all(DEMO_ORDER_IDS.map((orderId) => fetchOrder(orderId)));
      orders.value = results.map((result) => result.data);
      initialized.value = true;
      await selectOrder("ORDER-003");
    } catch (reason) {
      error.value = toBusinessError(reason);
    } finally {
      listLoading.value = false;
    }
  }

  async function selectOrder(orderId: DemoOrderId) {
    selectedOrderId.value = orderId;
    const requestSequence = ++detailRequestSequence;
    detailLoading.value = true;
    error.value = undefined;
    try {
      const result = await fetchOrderOverview(orderId);
      if (requestSequence !== detailRequestSequence) return;
      overview.value = result.data;
      traceId.value = result.traceId;
    } catch (reason) {
      if (requestSequence !== detailRequestSequence) return;
      overview.value = undefined;
      error.value = toBusinessError(reason);
    } finally {
      if (requestSequence === detailRequestSequence) {
        detailLoading.value = false;
      }
    }
  }

  async function retry() {
    if (!initialized.value) {
      await initialize();
      return;
    }
    await selectOrder(selectedOrderId.value);
  }

  return {
    orders,
    selectedOrderId,
    selectedOrder,
    overview,
    listLoading,
    detailLoading,
    error,
    traceId,
    initialize,
    selectOrder,
    retry,
  };
});

function toBusinessError(reason: unknown) {
  if (reason instanceof BusinessApiError) return reason;
  return new BusinessApiError({
    code: "UNKNOWN_CLIENT_ERROR",
    message: "加载订单数据时发生未知错误",
  });
}
