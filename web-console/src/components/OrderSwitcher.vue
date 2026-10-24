<script setup lang="ts">
import { ElSkeleton } from "element-plus";
import { computed, ref } from "vue";
import type { Order } from "../types/business";
import { ORDER_SCENARIOS, SCENARIO_CATEGORIES } from "../demoScenarios";

const props = defineProps<{
  orders: Order[];
  selectedOrderId: string;
  loading: boolean;
}>();

const emit = defineEmits<{
  select: [orderId: string];
}>();
const search = ref("");
const category = ref("");
const visibleOrders = computed(() => props.orders.filter((order) => {
  const scene = ORDER_SCENARIOS[order.orderId];
  const query = search.value.trim().toLowerCase();
  return (!category.value || scene?.category === category.value)
    && (!query || order.orderId.toLowerCase().includes(query) || scene?.name.toLowerCase().includes(query));
}));
const boundary = computed(() => ORDER_SCENARIOS[props.selectedOrderId]?.boundary);
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

    <div class="order-filters">
      <input v-model="search" aria-label="搜索订单号或场景名称" placeholder="订单号 / 场景名称" type="search" />
      <select v-model="category" aria-label="场景分类">
        <option value="">全部场景</option>
        <option v-for="item in SCENARIO_CATEGORIES" :key="item" :value="item">{{ item }}</option>
      </select>
      <small>显示 {{ visibleOrders.length }} / {{ orders.length }} 单</small>
    </div>
    <nav v-if="!loading || orders.length > 0" class="order-list" aria-label="订单列表">
      <button
        v-for="order in visibleOrders"
        :key="order.orderId"
        type="button"
        class="order-button"
        :class="{ active: order.orderId === selectedOrderId }"
        :data-order-id="order.orderId"
        :aria-current="order.orderId === selectedOrderId ? 'page' : undefined"
        @click="emit('select', order.orderId)"
      >
        <span class="order-index">{{ order.orderId.slice(-2) }}</span>
        <span class="order-label">
          <strong>{{ order.orderId }}</strong>
          <small>{{ ORDER_SCENARIOS[order.orderId]?.name ?? "业务订单" }}</small>
        </span>
        <span class="order-arrow" aria-hidden="true">→</span>
      </button>
      <p v-if="visibleOrders.length === 0" class="empty-copy">没有匹配的订单。</p>
    </nav>
    <p v-if="boundary" class="scenario-boundary" role="note"><strong>能力边界</strong>：{{ boundary }}</p>

    <div class="rail-note">
      <span class="live-dot" aria-hidden="true"></span>
      <span>数据源：business-service</span>
    </div>
  </aside>
</template>
