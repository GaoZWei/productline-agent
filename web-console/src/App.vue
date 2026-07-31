<script setup lang="ts">
import { ElAlert, ElButton, ElLoading, ElSkeleton } from "element-plus";
import { onMounted } from "vue";
import { storeToRefs } from "pinia";

import DeliveryStatusPanel from "./components/DeliveryStatusPanel.vue";
import OrderSummary from "./components/OrderSummary.vue";
import OrderSwitcher from "./components/OrderSwitcher.vue";
import QualityIssuesPanel from "./components/QualityIssuesPanel.vue";
import TaskList from "./components/TaskList.vue";
import { useOrderStore } from "./stores/orderStore";

const store = useOrderStore();
const vLoading = ElLoading.directive;
const {
  orders,
  selectedOrderId,
  overview,
  listLoading,
  detailLoading,
  error,
  traceId,
} = storeToRefs(store);

onMounted(() => store.initialize());
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="遥感产线协同中心首页">
        <span class="brand-mark">PL</span>
        <span><strong>产线协同中心</strong><small>REMOTE SENSING OPERATIONS</small></span>
      </a>
      <div class="topbar-status">
        <span class="environment">M0 · BUSINESS VIEW</span>
        <span class="service-health"><i></i>业务服务</span>
      </div>
    </header>

    <div class="workspace">
      <OrderSwitcher
        :orders="orders"
        :selected-order-id="selectedOrderId"
        :loading="listLoading"
        @select="store.selectOrder"
      />

      <main class="content-area">
        <div class="page-intro">
          <div>
            <span class="eyebrow">BUSINESS FACTS</span>
            <h2>订单业务全景</h2>
          </div>
          <div v-if="traceId" class="trace-chip" title="用于关联 Java 服务日志">
            TRACE · {{ traceId }}
          </div>
        </div>

        <el-alert
          v-if="error"
          class="error-alert"
          :title="`${error.code} · ${error.message}`"
          type="error"
          :closable="false"
          show-icon
        >
          <template #default>
            <span v-if="error.traceId">Trace ID：{{ error.traceId }}</span>
            <el-button size="small" @click="store.retry">重新加载</el-button>
          </template>
        </el-alert>

        <div v-if="(listLoading || detailLoading) && !overview" class="loading-grid">
          <el-skeleton :rows="9" animated />
        </div>

        <template v-if="overview">
          <div v-loading="detailLoading" element-loading-text="正在读取最新业务快照">
            <OrderSummary :order="overview.order" />
            <div class="dashboard-grid">
              <TaskList :tasks="overview.tasks" />
              <div class="side-stack">
                <QualityIssuesPanel :tasks="overview.tasks" />
                <DeliveryStatusPanel :records="overview.deliveryRecords" />
              </div>
            </div>
          </div>
        </template>

        <footer class="page-footer">
          <span>事实数据均由 Java business-service 提供</span>
          <span>本页面不调用模型，不生成业务结论</span>
        </footer>
      </main>
    </div>
  </div>
</template>
