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
  const selectedOrderId = ref<string>("ORDER-003");
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

  async function selectOrder(orderId: string) {
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

  async function switchOrderForAgent(orderId: string): Promise<Order> {
    // 成功读取并校验目标后才提交切换，加载失败时保留原页面。
    const sequence = ++detailRequestSequence;
    detailLoading.value = true;
    try {
      const result = await fetchOrderOverview(orderId);
      if (sequence !== detailRequestSequence) {
        throw new BusinessApiError({ code: "REQUEST_SUPERSEDED", message: "订单切换已被替代" });
      }
      if (result.data.order.orderId !== orderId) {
        throw new BusinessApiError({ code: "RESPONSE_VALIDATION_ERROR", message: "返回的订单与目标不一致" });
      }
      // 演示侧栏固定五单，非目录目标也由Java响应决定能否读取。
      selectedOrderId.value = orderId;
      overview.value = result.data;
      traceId.value = result.traceId;
      error.value = undefined;
      return result.data.order;
    } finally {
      if (sequence === detailRequestSequence) detailLoading.value = false;
    }
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
    switchOrderForAgent,
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
