<script setup lang="ts">
import { ElTag } from "element-plus";
import type { DeliveryRecord } from "../types/business";

defineProps<{ records: DeliveryRecord[] }>();

function isReady(status: string) {
  return status === "READY" || status === "DELIVERED";
}
</script>

<template>
  <section class="panel delivery-panel">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">成果交付</span>
        <h2>成果交付</h2>
      </div>
    </div>

    <div v-if="records.length === 0" class="empty-copy">当前订单没有交付记录。</div>
    <article v-for="record in records" v-else :key="record.deliveryId" class="delivery-card">
      <span class="delivery-icon" :class="{ ready: isReady(record.status) }">
        {{ isReady(record.status) ? "✓" : "!" }}
      </span>
      <div>
        <small>{{ record.deliveryId }}</small>
        <strong>{{ isReady(record.status) ? "已满足交付条件" : "交付尚未就绪" }}</strong>
      </div>
      <el-tag :type="isReady(record.status) ? 'success' : 'danger'" effect="dark">
        {{ record.status }}
      </el-tag>
    </article>
  </section>
</template>
