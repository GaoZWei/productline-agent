<script setup lang="ts">
import { computed } from "vue";

import type {
  AgentMessageResponse,
  ClarificationChoice,
  ReviewApprovalDecision,
} from "../types/agent";
import KnowledgeCitationCard from "./KnowledgeCitationCard.vue";
import ReviewApprovalCard from "./ReviewApprovalCard.vue";

const props = withDefaults(
  defineProps<{
    response: AgentMessageResponse;
    submitting?: boolean;
    actionMessage?: string;
  }>(),
  { submitting: false, actionMessage: "" },
);

const emit = defineEmits<{
  clarify: [choice: ClarificationChoice, message: string];
  confirm: [decision: ReviewApprovalDecision];
  cancel: [approvalId: string];
  rework: [approvalId: string];
}>();
// 从Agent响应中提取出五类结果类型：ORDER_STATUS, DIAGNOSIS, SPECIFICATION_ANSWER, CLARIFICATION, APPROVAL
const orderStatus = computed(() =>
  props.response.result.kind === "ORDER_STATUS" ? props.response.result : undefined,
);
const diagnosis = computed(() =>
  props.response.result.kind === "DIAGNOSIS" ? props.response.result.diagnosis : undefined,
);
const specification = computed(() =>
  props.response.result.kind === "SPECIFICATION_ANSWER"
    ? props.response.result.specification_answer
    : undefined,
);
const clarification = computed(() =>
  props.response.result.kind === "CLARIFICATION" ? props.response.result : undefined,
);
const approval = computed(() =>
  props.response.result.kind === "APPROVAL" ? props.response.result : undefined,
);

function chooseOption(value: string) {
  const result = clarification.value;
  const field = result?.clarification.field;
  if (!result || !field) return;
  emit(
    "clarify",
    { source_run_id: props.response.run_id, selection: { field, value } },
    `选择 ${value}`,
  );
}

function confirmIntent() {
  if (!clarification.value) return;
  emit(
    "clarify",
    { source_run_id: props.response.run_id, confirm_intent: true },
    "确认这个意图",
  );
}

function formatEvidenceValue(value: string | number | boolean | null) {
  if (value === null) return "null";
  return typeof value === "string" ? value : JSON.stringify(value);
}
</script>

<template>
  <div class="agent-result-view" :data-result-kind="response.result.kind">
    <section v-if="orderStatus" class="agent-result-card order-status-result">
      <header><span>确定性状态</span><strong>{{ orderStatus.status }}</strong></header>
      <h3>{{ orderStatus.subject === "ORDER" ? orderStatus.order_id : orderStatus.task_id }}</h3>
      <p>{{ orderStatus.summary }}</p>
      <small>业务事实来自 Java Tool</small>
    </section>

    <template v-if="diagnosis">
      <section class="diagnosis-stage-card">
        <div class="diagnosis-stage-heading">
          <span>阻塞环节</span><strong>{{ diagnosis.blocking_stage }}</strong>
        </div>
        <p>{{ diagnosis.summary }}</p>
        <small>诊断置信度 {{ Math.round(diagnosis.confidence * 100) }}%</small>
      </section>
      <section class="diagnosis-section">
        <div class="diagnosis-section-title">
          <span>01</span><h3>根因</h3><small>{{ diagnosis.root_causes.length }} 项</small>
        </div>
        <ol class="diagnosis-list root-cause-list">
          <li v-for="cause in diagnosis.root_causes" :key="cause.code">
            <code>{{ cause.code }}</code><p>{{ cause.description }}</p>
          </li>
        </ol>
      </section>
      <section class="diagnosis-section">
        <div class="diagnosis-section-title">
          <span>02</span><h3>Java字段级证据</h3><small>{{ diagnosis.evidence.length }} 条</small>
        </div>
        <ul class="diagnosis-list evidence-list">
          <li
            v-for="(item, index) in diagnosis.evidence"
            :key="`${item.tool_name}-${item.field_path}-${index}`"
          >
            <div class="evidence-source"><code>{{ item.tool_name }}</code><span>TOOL</span></div>
            <p>{{ item.description }}</p>
            <div class="evidence-field">
              <code>{{ item.field_path }}</code><strong>{{ formatEvidenceValue(item.value) }}</strong>
            </div>
          </li>
        </ul>
      </section>
      <section class="diagnosis-section">
        <div class="diagnosis-section-title">
          <span>03</span><h3>处理建议</h3><small>仅建议，未执行</small>
        </div>
        <ol class="diagnosis-list suggestion-list">
          <li v-for="item in diagnosis.suggestions" :key="item.action_type">
            <code>{{ item.action_type }}</code><p>{{ item.description }}</p>
          </li>
        </ol>
      </section>
    </template>

    <section v-if="specification" class="agent-result-card specification-result">
      <header>
        <span>规范回答</span>
        <strong>{{ specification.status }}</strong>
      </header>
      <p class="specification-answer">{{ specification.answer }}</p>
      <p v-if="specification.rewritten_query !== specification.question" class="result-meta">
        检索问题：{{ specification.rewritten_query }}
      </p>
      <div v-if="specification.citations.length" class="approval-citations">
        <KnowledgeCitationCard
          v-for="citation in specification.citations"
          :key="`${citation.document_id}:${citation.document_version}:${citation.chunk_id}`"
          :citation="citation"
        />
      </div>
      <small v-else>未形成可引用的规范结论</small>
    </section>

    <section v-if="clarification" class="agent-result-card clarification-result">
      <header><span>需要确认</span><strong>{{ clarification.clarification.reason }}</strong></header>
      <h3>{{ clarification.clarification.question }}</h3>
      <div v-if="clarification.clarification.options.length" class="clarification-options">
        <button
          v-for="option in clarification.clarification.options"
          :key="`${option.source}:${option.value}`"
          type="button"
          :disabled="submitting"
          @click="chooseOption(option.value)"
        >
          <strong>{{ option.value }}</strong><small>{{ option.source }}</small>
        </button>
      </div>
      <button
        v-else-if="clarification.clarification.reason === 'CONFIRM_INTENT'"
        type="button"
        class="agent-result-primary-action"
        :disabled="submitting"
        data-testid="confirm-agent-intent"
        @click="confirmIntent"
      >
        确认并继续
      </button>
      <small v-else>请在输入框中补充明确的订单号、任务号或问题。</small>
    </section>

    <template v-if="approval">
      <ReviewApprovalCard
        :approval="approval"
        :submitting="submitting"
        @confirm="emit('confirm', $event)"
        @cancel="emit('cancel', $event)"
      />
      <button
        v-if="
          approval.operation_type === 'SUBMIT_REVIEW' &&
          approval.status === 'SUCCEEDED' &&
          approval.draft.suggested_rework.required
        "
        type="button"
        class="agent-result-primary-action"
        :disabled="submitting"
        data-testid="create-rework-approval"
        @click="emit('rework', approval.approval_id)"
      >
        创建独立返工确认单
      </button>
    </template>

    <p v-if="actionMessage" class="agent-action-message" role="status">{{ actionMessage }}</p>
    <footer class="diagnosis-trace">
      <span>Run · {{ response.run_id }}</span>
      <span>Trace · {{ response.trace_id }}</span>
    </footer>
  </div>
</template>
