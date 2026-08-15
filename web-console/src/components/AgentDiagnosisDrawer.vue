<script setup lang="ts">
import { ElAlert, ElButton, ElTag } from "element-plus";
import { computed, nextTick, ref, watch } from "vue";

import { diagnoseOrder } from "../api/agentApi";
import { AGENT_USER_ROLE, AgentApiError } from "../api/agentClient";
import { createOrderDetailPageContext } from "../context/pageContext";
import type { BlockingStage, OrderDiagnosisResponse } from "../types/agent";
import type { Order } from "../types/business";

const DEFAULT_MESSAGE = "这个订单为什么还没有交付？";
const STAGE_LABELS: Record<BlockingStage, string> = {
  PRODUCTION: "正常生产中",
  PRODUCTION_BLOCKED: "生产阻塞",
  QUALITY_REVIEW: "质量复核",
  REVIEW: "复核处理",
  DELIVERY: "成果交付",
  NONE: "未发现阻塞",
  INSUFFICIENT_INFORMATION: "信息不足",
};

const props = defineProps<{ order?: Order }>();
const visible = ref(false);
const userMessage = ref(DEFAULT_MESSAGE);
const loading = ref(false);
const result = ref<OrderDiagnosisResponse>();
const error = ref<AgentApiError>();
const sessionId = ref<string>();
const messageInput = ref<HTMLTextAreaElement>();
let requestSequence = 0;

const currentOrderId = computed(() => props.order?.orderId);
const canSubmit = computed(
  () => Boolean(currentOrderId.value && userMessage.value.trim()) && !loading.value,
);

watch(currentOrderId, () => {
  requestSequence += 1;
  loading.value = false;
  result.value = undefined;
  error.value = undefined;
  sessionId.value = undefined;
});

async function openDrawer() {
  visible.value = true;
  await nextTick();
  messageInput.value?.focus();
}

function closeDrawer() {
  visible.value = false;
}

async function submitDiagnosis() {
  const order = props.order;
  const orderId = order?.orderId;
  const message = userMessage.value.trim();
  if (!order || !orderId || !message || loading.value) return;

  const sequence = ++requestSequence;
  loading.value = true;
  result.value = undefined;
  error.value = undefined;
  try {
    // 创建订单详情页上下文
    const pageContext = createOrderDetailPageContext(order, AGENT_USER_ROLE);
    // 请求诊断订单
    const response = await diagnoseOrder(orderId, message, pageContext, sessionId.value);
    if (sequence === requestSequence && currentOrderId.value === orderId) {
      sessionId.value = response.session_id;
      result.value = response;
    }
  } catch (reason) {
    if (sequence === requestSequence && currentOrderId.value === orderId) {
      error.value = toAgentError(reason);
    }
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function toAgentError(reason: unknown) {
  if (reason instanceof AgentApiError) return reason;
  return new AgentApiError({
    code: "UNKNOWN_CLIENT_ERROR",
    message: "执行订单诊断时发生未知错误",
  });
}

function formatEvidenceValue(value: string | number | boolean | null) {
  if (value === null) return "null";
  return typeof value === "string" ? value : JSON.stringify(value);
}
</script>

<template>
  <el-button
    class="agent-trigger"
    type="primary"
    :disabled="!order"
    data-testid="open-agent-drawer"
    @click="openDrawer"
  >
    <span class="agent-trigger-mark">AI</span>
    诊断当前订单
  </el-button>

  <div v-if="visible" class="agent-drawer-layer" @keydown.esc="closeDrawer">
    <button class="agent-drawer-backdrop" aria-label="关闭诊断侧边栏" @click="closeDrawer"></button>
    <aside
      class="agent-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="agent-drawer-title"
      data-testid="agent-drawer"
    >
      <header class="agent-drawer-header">
        <div>
          <span class="agent-kicker">DETERMINISTIC AGENT</span>
          <h2 id="agent-drawer-title">订单诊断助手</h2>
          <p>基于 Java Tool 事实运行固定诊断流程</p>
        </div>
        <button class="agent-close" aria-label="关闭诊断侧边栏" @click="closeDrawer">×</button>
      </header>

      <div class="agent-drawer-body">
        <section v-if="order" class="agent-order-context" aria-label="当前订单上下文">
          <span>当前订单</span>
          <strong>{{ order.orderId }}</strong>
          <dl>
            <div><dt>产品类型</dt><dd>{{ order.productType }}</dd></div>
            <div><dt>业务状态</dt><dd>{{ order.status }}</dd></div>
          </dl>
        </section>

        <section class="agent-prompt-panel">
          <label for="agent-user-message">你想了解什么？</label>
          <textarea
            id="agent-user-message"
            ref="messageInput"
            v-model="userMessage"
            maxlength="2000"
            rows="3"
            :disabled="loading"
            data-testid="agent-message-input"
          ></textarea>
          <div class="agent-prompt-actions">
            <small>{{ userMessage.length }} / 2000</small>
            <el-button
              type="primary"
              :loading="loading"
              :disabled="!canSubmit"
              data-testid="submit-diagnosis"
              @click="submitDiagnosis"
            >
              开始诊断
            </el-button>
          </div>
        </section>

        <div v-if="loading" class="agent-loading" role="status" aria-live="polite">
          <span class="agent-loading-spinner"></span>
          <div>
            <strong>正在核对订单事实</strong>
            <p>依次读取生产、质检、复核与交付状态…</p>
          </div>
        </div>

        <el-alert
          v-if="error"
          class="agent-error"
          :title="`${error.code} · ${error.message}`"
          type="error"
          :closable="false"
          show-icon
        >
          <template #default>
            <div class="agent-error-detail">
              <span v-if="error.runId">Run ID：{{ error.runId }}</span>
              <span v-if="error.errorStep">失败步骤：{{ error.errorStep }}</span>
              <span v-if="error.traceId">Trace ID：{{ error.traceId }}</span>
              <el-button v-if="error.retryable" size="small" @click="submitDiagnosis">
                重新诊断
              </el-button>
            </div>
          </template>
        </el-alert>

        <template v-if="result">
          <section class="diagnosis-stage-card">
            <div class="diagnosis-stage-heading">
              <span>阻塞环节</span>
              <el-tag effect="dark">{{ STAGE_LABELS[result.diagnosis.blocking_stage] }}</el-tag>
            </div>
            <strong>{{ result.diagnosis.blocking_stage }}</strong>
            <p>{{ result.diagnosis.summary }}</p>
            <small>规则置信度 {{ Math.round(result.diagnosis.confidence * 100) }}%</small>
          </section>

          <section class="diagnosis-section">
            <div class="diagnosis-section-title">
              <span>01</span><h3>根因</h3><small>{{ result.diagnosis.root_causes.length }} 项</small>
            </div>
            <ol class="diagnosis-list root-cause-list">
              <li v-for="cause in result.diagnosis.root_causes" :key="cause.code">
                <code>{{ cause.code }}</code>
                <p>{{ cause.description }}</p>
              </li>
            </ol>
          </section>

          <section class="diagnosis-section">
            <div class="diagnosis-section-title">
              <span>02</span><h3>字段级证据</h3><small>{{ result.diagnosis.evidence.length }} 条</small>
            </div>
            <ul class="diagnosis-list evidence-list">
              <li
                v-for="(item, index) in result.diagnosis.evidence"
                :key="`${item.tool_name}-${item.field_path}-${index}`"
              >
                <div class="evidence-source">
                  <code>{{ item.tool_name }}</code>
                  <span>TOOL</span>
                </div>
                <p>{{ item.description }}</p>
                <div class="evidence-field">
                  <code>{{ item.field_path }}</code>
                  <strong>{{ formatEvidenceValue(item.value) }}</strong>
                </div>
              </li>
            </ul>
          </section>

          <section class="diagnosis-section">
            <div class="diagnosis-section-title">
              <span>03</span><h3>处理建议</h3><small>仅建议，未执行</small>
            </div>
            <ol class="diagnosis-list suggestion-list">
              <li v-for="item in result.diagnosis.suggestions" :key="item.action_type">
                <code>{{ item.action_type }}</code>
                <p>{{ item.description }}</p>
              </li>
            </ol>
          </section>

          <footer class="diagnosis-trace">
            <span>Run · {{ result.run_id }}</span>
            <span>Trace · {{ result.trace_id }}</span>
          </footer>
        </template>
      </div>
    </aside>
  </div>
</template>
