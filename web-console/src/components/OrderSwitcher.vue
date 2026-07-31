<script setup lang="ts">
import { ElSkeleton } from "element-plus";
import type { Order } from "../types/business";
import { ORDER_SCENES, type DemoOrderId } from "../stores/orderStore";

defineProps<{
  orders: Order[];
  selectedOrderId: DemoOrderId;
  loading: boolean;
}>();

const emit = defineEmits<{
  select: [orderId: DemoOrderId];
}>();

function isDemoOrderId(orderId: string): orderId is DemoOrderId {
  return orderId in ORDER_SCENES;
}
</script>

<template>
  <aside class="order-rail" aria-label="固定演示订单">
    <div class="rail-heading">
      <span class="eyebrow">固定演示订单</span>
      <h2>业务场景</h2>
      <p>选择固定订单，查看 Java 事实层返回的完整业务快照。</p>
    </div>

    <div v-if="loading && orders.length === 0" class="rail-loading">
      <el-skeleton :rows="5" animated />
    </div>

    <nav v-else class="order-list">
      <button
        v-for="order in orders"
        :key="order.orderId"
        type="button"
        class="order-button"
        :class="{ active: order.orderId === selectedOrderId }"
        :data-order-id="order.orderId"
        :aria-current="order.orderId === selectedOrderId ? 'page' : undefined"
        @click="isDemoOrderId(order.orderId) && emit('select', order.orderId)"
      >
        <span class="order-index">{{ order.orderId.slice(-2) }}</span>
        <span class="order-label">
          <strong>{{ order.orderId }}</strong>
          <small>{{ isDemoOrderId(order.orderId) ? ORDER_SCENES[order.orderId] : "业务订单" }}</small>
        </span>
        <span class="order-arrow" aria-hidden="true">→</span>
      </button>
    </nav>

    <div class="rail-note">
      <span class="live-dot" aria-hidden="true"></span>
      <span>数据源：business-service</span>
    </div>
  </aside>
</template>
