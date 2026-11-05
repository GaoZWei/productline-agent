<script setup lang="ts">
import { ElTag } from "element-plus";
import type { Order } from "../types/business";

defineProps<{ order: Order }>();

function tagType(status: string) {
  if (status.includes("READY") || status === "COMPLETED") return "success";
  if (status.includes("BLOCK")) return "danger";
  if (status.includes("PRODUCTION")) return "warning";
  return "info";
}
</script>

<template>
  <section class="summary-card" data-current-order>
    <div>
      <span class="eyebrow">订单概览</span>
      <h1>{{ order.orderId }}</h1>
      <p>遥感数据生产订单业务快照</p>
    </div>
    <dl class="summary-metrics">
      <div>
        <dt>产品类型</dt>
        <dd>{{ order.productType }}</dd>
      </div>
      <div>
        <dt>订单状态</dt>
        <dd><el-tag :type="tagType(order.status)" effect="dark">{{ order.status }}</el-tag></dd>
      </div>
    </dl>
  </section>
</template>
