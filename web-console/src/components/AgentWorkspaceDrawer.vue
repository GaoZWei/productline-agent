<script setup lang="ts">
import { ElAlert, ElButton } from "element-plus";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import {
  cancelReviewApproval,
  confirmReviewApproval,
  createReworkApproval,
  diagnoseOrder,
  getAgentCapabilities,
  sendAgentMessage,
} from "../api/agentApi";
import { AGENT_USER_ROLE, AgentApiError } from "../api/agentClient";
import {
  createRunEventStreamId,
  openRunEventStream,
  RunEventClientError,
  type RunEventConnection,
} from "../api/runEventClient";
import { createOrderDetailPageContext } from "../context/pageContext";
import type {
  AgentCapabilitiesResponse,
  AgentMessageResponse,
  ApprovalAgentResult,
  ClarificationChoice,
  ReviewApprovalDecision,
} from "../types/agent";
import type { Order } from "../types/business";
import type { RunEvent, RunEventConnectionStatus } from "../types/runEvents";
import AgentResultView from "./AgentResultView.vue";
import AgentRunTimeline from "./AgentRunTimeline.vue";

const DEFAULT_MESSAGE = "这个订单为什么还没有交付？";

const props = defineProps<{ order?: Order }>();
const visible = ref(false);
const userMessage = ref(DEFAULT_MESSAGE);
const loading = ref(false);
const actionLoading = ref(false);
const result = ref<AgentMessageResponse>();
const error = ref<AgentApiError>();
const actionMessage = ref("");
const capabilities = ref<AgentCapabilitiesResponse>();
const capabilityError = ref<AgentApiError>();
const sessionId = ref<string>();
const messageInput = ref<HTMLTextAreaElement>();
const runEvents = ref<RunEvent[]>([]);
const connectionStatus = ref<RunEventConnectionStatus | "idle">("idle");
const connectionWarning = ref<RunEventClientError>();
const lastRequest = ref<{ message: string; clarification?: ClarificationChoice }>();
let eventConnection: RunEventConnection | undefined;
let requestSequence = 0;

const currentOrderId = computed(() => props.order?.orderId);
const busy = computed(() => loading.value || actionLoading.value);
const canSubmit = computed(
  () => Boolean(currentOrderId.value && userMessage.value.trim()) && !busy.value,
);

watch(currentOrderId, resetConversation);
onBeforeUnmount(() => eventConnection?.close());

async function openDrawer() {
  visible.value = true;
  if (!capabilities.value) void loadCapabilities();
  await nextTick();
  messageInput.value?.focus();
}

function closeDrawer() {
  visible.value = false;
}
// 切换订单时，重置会话状态
function resetConversation() {
  requestSequence += 1;
  eventConnection?.close();
  eventConnection = undefined;
  loading.value = false;
  actionLoading.value = false;
  result.value = undefined;
  error.value = undefined;
  actionMessage.value = "";
  sessionId.value = undefined;
  lastRequest.value = undefined;
  resetTimeline();
}

function resetTimeline() {
  runEvents.value = [];
  connectionStatus.value = "idle";
  connectionWarning.value = undefined;
}

async function loadCapabilities() {
  try {
    capabilities.value = await getAgentCapabilities();
    capabilityError.value = undefined;
  } catch (reason) {
    capabilityError.value = toAgentError(reason, "读取Agent能力失败");
  }
}
// 用户发送消息到Agent执行
async function submitAgent(
  clarification?: ClarificationChoice,
  messageOverride?: string,
) {
  // 先快照当前订单，避免异步执行过程中直接依赖不断变化的 props.order
  const order = props.order;
  const message = (messageOverride ?? userMessage.value).trim();
  if (!order || !message || busy.value) return;
  // 清理上一轮状态
  loading.value = true;
  error.value = undefined;
  result.value = undefined;
  actionMessage.value = "";
  // 保存重试数据
  lastRequest.value = clarification ? { message, clarification } : { message };
  let sequence: number | undefined;
  try {
    // 先建立SSE，再发送消息
    const streamId = await connectEventStream(order.orderId);
    sequence = requestSequence;
    const response = await sendAgentMessage(
      {
        message,
        session_id: sessionId.value,
        page_context: createOrderDetailPageContext(order, AGENT_USER_ROLE),
        clarification,
      },
      streamId,
    );
    if (sequence !== requestSequence || currentOrderId.value !== order.orderId) return;
    // 响应成功后保存 sessionId 和 result
    sessionId.value = response.session_id;
    result.value = response;
  } catch (reason) {
    if (
      currentOrderId.value !== order.orderId ||
      (reason instanceof AgentApiError && reason.code === "REQUEST_SUPERSEDED") ||
      (sequence !== undefined && sequence !== requestSequence)
    ) return;
    error.value = toAgentError(reason, "执行Agent请求时发生未知错误");
    if (!(reason instanceof RunEventClientError) && sequence === requestSequence) {
      eventConnection?.close();
    }
  } finally {
    if (sequence === undefined || sequence === requestSequence) loading.value = false;
  }
}

async function submitFixedDiagnosis() {
  const order = props.order;
  const message = userMessage.value.trim();
  if (!order || !message || busy.value) return;
  loading.value = true;
  error.value = undefined;
  result.value = undefined;
  actionMessage.value = "";
  let sequence: number | undefined;
  try {
    const streamId = await connectEventStream(order.orderId);
    sequence = requestSequence;
    const response = await diagnoseOrder(
      order.orderId,
      message,
      createOrderDetailPageContext(order, AGENT_USER_ROLE),
      sessionId.value,
      streamId,
    );
    if (sequence !== requestSequence || currentOrderId.value !== order.orderId) return;
    sessionId.value = response.session_id;
    result.value = { ...response, result: { kind: "DIAGNOSIS", diagnosis: response.diagnosis } };
  } catch (reason) {
    if (
      currentOrderId.value !== order.orderId ||
      (reason instanceof AgentApiError && reason.code === "REQUEST_SUPERSEDED") ||
      (sequence !== undefined && sequence !== requestSequence)
    ) return;
    error.value = toAgentError(reason, "执行固定诊断时发生未知错误");
    if (!(reason instanceof RunEventClientError) && sequence === requestSequence) {
      eventConnection?.close();
    }
  } finally {
    if (sequence === undefined || sequence === requestSequence) loading.value = false;
  }
}

async function retryLastRequest() {
  const previous = lastRequest.value;
  if (previous) await submitAgent(previous.clarification, previous.message);
  else await submitAgent();
}

async function submitClarification(choice: ClarificationChoice, message: string) {
  await submitAgent(choice, message);
}

async function confirmApproval(decision: ReviewApprovalDecision) {
  const order = props.order;
  if (!order || actionLoading.value) return;
  actionLoading.value = true;
  error.value = undefined;
  actionMessage.value = "";
  let sequence: number | undefined;
  try {
    // 确认时同样先建立新SSE连接
    const streamId = await connectEventStream(order.orderId);
    sequence = requestSequence;
    const response = await confirmReviewApproval(decision, streamId);
    if (sequence !== requestSequence || currentOrderId.value !== order.orderId) return;
    updateApprovalStatus("SUCCEEDED");
    actionMessage.value = "review_id" in response.result
      ? `复核已写入 · ${response.result.review_id} · 任务版本 ${response.result.task_version}`
      : `返工任务已创建 · ${response.result.rework_task_id} · 任务版本 ${response.result.task_version}`;
  } catch (reason) {
    if (
      currentOrderId.value !== order.orderId ||
      (reason instanceof AgentApiError && reason.code === "REQUEST_SUPERSEDED") ||
      (sequence !== undefined && sequence !== requestSequence)
    ) return;
    error.value = toAgentError(reason, "确认Approval时发生未知错误");
    const status = error.value.approvalStatus;
    if (status) updateApprovalStatus(status);
  } finally {
    if (sequence === undefined || sequence === requestSequence) actionLoading.value = false;
  }
}

async function cancelApproval(approvalId: string) {
  if (actionLoading.value) return;
  const orderId = currentOrderId.value;
  const sequence = requestSequence;
  actionLoading.value = true;
  error.value = undefined;
  try {
    await cancelReviewApproval(approvalId);
    if (sequence !== requestSequence || currentOrderId.value !== orderId) return;
    updateApprovalStatus("CANCELLED");
    actionMessage.value = "确认单已取消，未执行Java写入";
  } catch (reason) {
    if (sequence !== requestSequence || currentOrderId.value !== orderId) return;
    error.value = toAgentError(reason, "取消Approval时发生未知错误");
  } finally {
    if (sequence === requestSequence) actionLoading.value = false;
  }
}

async function requestRework(approvalId: string) {
  if (actionLoading.value || !sessionId.value) return;
  const orderId = currentOrderId.value;
  const sequence = requestSequence;
  actionLoading.value = true;
  error.value = undefined;
  try {
    const response = await createReworkApproval(approvalId);
    if (sequence !== requestSequence || currentOrderId.value !== orderId) return;
    result.value = {
      run_id: response.run_id,
      session_id: sessionId.value,
      trace_id: response.trace_id,
      result: response.result,
    };
    actionMessage.value = "返工确认单已创建，请再次核对并确认";
    resetTimeline();
  } catch (reason) {
    if (sequence !== requestSequence || currentOrderId.value !== orderId) return;
    error.value = toAgentError(reason, "创建返工确认单时发生未知错误");
  } finally {
    if (sequence === requestSequence) actionLoading.value = false;
  }
}

function updateApprovalStatus(status: ApprovalAgentResult["status"]) {
  const current = result.value;
  if (!current || current.result.kind !== "APPROVAL") return;
  result.value = { ...current, result: { ...current.result, status } };
}
// 建立SSE 连接，用于接收Agent执行结果
async function connectEventStream(orderId: string): Promise<string> {
  const sequence = ++requestSequence;
  eventConnection?.close();
  resetTimeline();
  connectionStatus.value = "connecting";
  const streamId = createRunEventStreamId();
  const connection = openRunEventStream({
    streamId,
    onEvent: (event) => {
      if (sequence === requestSequence && currentOrderId.value === orderId) {
        runEvents.value = [...runEvents.value, event];
      }
    },
    onStateChange: (state) => {
      if (sequence === requestSequence && currentOrderId.value === orderId) {
        connectionStatus.value = state.status;
      }
    },
    onError: (streamError) => {
      if (sequence === requestSequence && currentOrderId.value === orderId) {
        connectionWarning.value = streamError;
      }
    },
  });
  eventConnection = connection;
  await connection.ready;
  if (sequence !== requestSequence || currentOrderId.value !== orderId) {
    connection.close();
    throw new AgentApiError({ code: "REQUEST_SUPERSEDED", message: "请求已被新的页面上下文替代" });
  }
  return streamId;
}

function toAgentError(reason: unknown, fallback: string) {
  if (reason instanceof AgentApiError) return reason;
  if (reason instanceof RunEventClientError) {
    return new AgentApiError({
      code: reason.code,
      message: reason.message,
      traceId: reason.traceId,
      retryable: reason.retryable,
      status: reason.status,
    });
  }
  return new AgentApiError({ code: "UNKNOWN_CLIENT_ERROR", message: fallback });
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
    打开Agent助手
  </el-button>

  <div v-if="visible" class="agent-drawer-layer" @keydown.esc="closeDrawer">
    <button class="agent-drawer-backdrop" aria-label="关闭Agent侧边栏" @click="closeDrawer"></button>
    <aside
      class="agent-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="agent-drawer-title"
      data-testid="agent-drawer"
    >
      <header class="agent-drawer-header">
        <div>
          <span class="agent-kicker">PRODUCTION AGENT</span>
          <h2 id="agent-drawer-title">产线Agent助手</h2>
          <p>状态、诊断、规范问答与人工复核统一入口</p>
        </div>
        <button class="agent-close" aria-label="关闭Agent侧边栏" @click="closeDrawer">×</button>
      </header>

      <div class="agent-drawer-body">
        <section v-if="order" class="agent-order-context" aria-label="当前订单上下文">
          <span>当前订单</span><strong>{{ order.orderId }}</strong>
          <dl>
            <div><dt>产品类型</dt><dd>{{ order.productType }}</dd></div>
            <div><dt>业务状态</dt><dd>{{ order.status }}</dd></div>
          </dl>
        </section>

        <section v-if="capabilities" class="agent-capabilities" aria-label="Agent运行能力">
          <span :data-ready="capabilities.model.configured">
            模型 {{ capabilities.model.configured ? capabilities.model.model_name : "未配置" }}
          </span>
          <span :data-ready="capabilities.knowledge_index.ready">
            知识库 {{ capabilities.knowledge_index.status }}
          </span>
          <small v-if="sessionId">Session · {{ sessionId }}</small>
        </section>
        <el-alert
          v-else-if="capabilityError"
          class="agent-stream-warning"
          title="暂时无法读取Agent能力"
          type="warning"
          :closable="false"
        />

        <section class="agent-prompt-panel">
          <label for="agent-user-message">向Agent提问</label>
          <textarea
            id="agent-user-message"
            ref="messageInput"
            v-model="userMessage"
            maxlength="2000"
            rows="3"
            :disabled="busy"
            data-testid="agent-message-input"
          ></textarea>
          <div class="agent-prompt-actions">
            <button
              type="button"
              class="fixed-diagnosis-action"
              :disabled="!canSubmit"
              data-testid="submit-fixed-diagnosis"
              @click="submitFixedDiagnosis"
            >
              固定诊断
            </button>
            <el-button
              type="primary"
              :loading="loading"
              :disabled="!canSubmit"
              data-testid="submit-agent-message"
              @click="submitAgent()"
            >
              发送给Agent
            </el-button>
          </div>
        </section>

        <AgentRunTimeline
          v-if="runEvents.length || connectionStatus !== 'idle'"
          :events="runEvents"
          :connection-status="connectionStatus"
        />

        <div v-if="loading && runEvents.length === 0" class="agent-loading" role="status">
          <span class="agent-loading-spinner"></span>
          <div><strong>Agent正在处理</strong><p>正在路由请求并核对事实与规范…</p></div>
        </div>

        <el-alert
          v-if="connectionWarning && !error"
          class="agent-stream-warning"
          title="实时步骤连接已中断，请求仍可能继续执行"
          type="warning"
          :closable="false"
          show-icon
        />

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
              <el-button v-if="error.retryable" size="small" @click="retryLastRequest">
                重试本轮
              </el-button>
            </div>
          </template>
        </el-alert>

        <AgentResultView
          v-if="result"
          :response="result"
          :submitting="actionLoading || loading"
          :action-message="actionMessage"
          @clarify="submitClarification"
          @confirm="confirmApproval"
          @cancel="cancelApproval"
          @rework="requestRework"
        />
      </div>
    </aside>
  </div>
</template>
