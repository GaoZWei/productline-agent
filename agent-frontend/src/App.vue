<script setup lang="ts">
import { ElAlert, ElButton, ElLoading, ElSkeleton } from "element-plus";
import { onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import AgentWorkspaceDrawer from "./components/AgentWorkspaceDrawer.vue";
import DeliveryStatusPanel from "./components/DeliveryStatusPanel.vue";
import OrderSummary from "./components/OrderSummary.vue";
import OrderSwitcher from "./components/OrderSwitcher.vue";
import QualityIssuesPanel from "./components/QualityIssuesPanel.vue";
import RunHistoryPage from "./components/RunHistoryPage.vue";
import TaskList from "./components/TaskList.vue";
import ReworkDetailPanel from "./components/ReworkDetailPanel.vue";
import { useOrderStore } from "./stores/orderStore";

const store = useOrderStore();
const currentView = ref<"business" | "history">("business");
const selectedRework = ref<{ orderId: string; taskId: string; reworkId: string }>();
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
// 切单意图一发生就隔离旧详情，不等旧overview被新响应替换。
watch([selectedOrderId, currentView], () => { selectedRework.value = undefined; }, { flush: "sync" });
watch(overview, () => { selectedRework.value = undefined; });
function openRework(taskId: string, reworkId: string) {
  if (detailLoading.value || !overview.value || overview.value.order.orderId !== selectedOrderId.value) return;
  const task = overview.value.tasks.find(item => item.task.taskId === taskId && item.task.orderId === selectedOrderId.value);
  if (!task?.reworkTasks.some(item => item.taskId === taskId && item.reworkTaskId === reworkId)) return;
  selectedRework.value = { orderId: selectedOrderId.value, taskId, reworkId };
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="遥感产线协同中心首页">
        <span class="brand-mark">PL</span>
        <span><strong>产线协同中心</strong><small>遥感数据生产业务</small></span>
      </a>
      <div class="topbar-status">
        <nav class="topbar-navigation" aria-label="主导航">
          <button
            type="button"
            :class="{ active: currentView === 'business' }"
            data-testid="business-view-nav"
            @click="currentView = 'business'"
          >
            业务全景
          </button>
          <button
            type="button"
            :class="{ active: currentView === 'history' }"
            data-testid="run-history-nav"
            @click="currentView = 'history'"
          >
            运行历史
          </button>
        </nav>
        <span class="environment">M7 · Agent生产闭环</span>
        <span class="service-health"><i></i>Java 事实源 · Agent 在线</span>
      </div>
    </header>

    <div v-if="currentView === 'business'" class="workspace">
      <OrderSwitcher
        :orders="orders"
        :selected-order-id="selectedOrderId"
        :loading="listLoading"
        @select="store.selectOrder"
      />

      <main class="content-area">
        <div class="page-intro">
          <div>
            <span class="eyebrow">业务事实</span>
            <h2>订单业务全景</h2>
          </div>
          <div class="page-actions">
            <div v-if="traceId" class="trace-chip" title="用于关联 Java 服务日志">
              TRACE · {{ traceId }}
            </div>
            <AgentWorkspaceDrawer :order="overview?.order" :switch-order="store.switchOrderForAgent" />
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
              <TaskList :tasks="overview.tasks" @open-rework="openRework" />
              <div class="side-stack">
                <QualityIssuesPanel :tasks="overview.tasks" />
                <DeliveryStatusPanel :records="overview.deliveryRecords" />
              </div>
            </div>
            <ReworkDetailPanel v-if="selectedRework" :order-id="selectedRework.orderId" :task-id="selectedRework.taskId" :rework-id="selectedRework.reworkId" @close="selectedRework = undefined" />
          </div>
        </template>

        <footer class="page-footer">
          <span>事实数据均由 Java business-service 提供</span>
          <span>Agent写操作必须经过人工确认与Java重新校验</span>
        </footer>
      </main>
    </div>
    <RunHistoryPage v-else />
  </div>
</template>
