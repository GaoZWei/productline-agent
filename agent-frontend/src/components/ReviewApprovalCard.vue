<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type {
  ApprovalStatus,
  ReviewApproval,
  ReviewApprovalDecision,
  ReviewConclusion,
  ReviewDraft,
} from "../types/agent";
import KnowledgeCitationCard from "./KnowledgeCitationCard.vue";

const props = withDefaults(
  defineProps<{
    approval: ReviewApproval; // 后端返回的待确认单
    submitting?: boolean; // 是否正在提交确认
  }>(),
  { submitting: false },
);

const emit = defineEmits<{
  confirm: [decision: ReviewApprovalDecision];
  cancel: [approvalId: string];
}>();

const conclusionOptions: ReadonlyArray<{
  value: ReviewConclusion;
  label: string;
}> = [
  { value: "APPROVED", label: "复核通过" },
  { value: "REJECTED", label: "复核拒绝" },
  { value: "REWORK_REQUIRED", label: "需要返工" },
];

const statusLabels: Record<ApprovalStatus, string> = {
  DRAFT: "草稿",
  WAITING_CONFIRMATION: "待人工确认",
  CONFIRMED: "已确认",
  EXECUTING: "执行中",
  SUCCEEDED: "已完成",
  FAILED: "执行失败",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
  STALE: "目标已变化",
};

// 用户正在编辑的草稿副本
const localDraft = ref<ReviewDraft>(cloneDraft(props.approval.draft));
// 是否打开二次确认弹窗
const confirmationOpen = ref(false);
// 用户是否已经触发操作
const pendingAction = ref<"confirm" | "cancel" | null>(null);

const isWaitingConfirmation = computed(
  () => props.approval.status === "WAITING_CONFIRMATION",
);
// 如果确认单已经不是待确认状态，或者正在提交确认，或者用户已经触发操作，禁用所有操作
const controlsDisabled = computed(
  () =>
    !isWaitingConfirmation.value || props.submitting || pendingAction.value !== null,
);
const normalizedComment = computed(() => localDraft.value.review_comment.trim());
const commentError = computed(() => {
  if (normalizedComment.value.length === 0) return "复核意见不能为空";
  if (normalizedComment.value.length > 1000) return "复核意见不能超过 1000 个字符";
  return "";
});

const confirmDisabled = computed(
  () => controlsDisabled.value || commentError.value.length > 0,
);
const statusLabel = computed(() => statusLabels[props.approval.status]);
const submitLabel = computed(() => {
  if (props.submitting || pendingAction.value === "confirm") return "正在提交确认…";
  return "确认复核结论";
});
const cancelLabel = computed(() =>
  pendingAction.value === "cancel" ? "正在取消…" : "取消草稿",
);
// Approval变化时要重置本地草稿
watch(
  () => [props.approval.approval_id, props.approval.status] as const,
  () => resetFromApproval(),
);

watch(
  () => props.submitting,
  (submitting, previous) => {
    // 父级请求失败并结束提交态后允许用户重试；成功时父级应更新状态或卸载卡片。
    if (previous && !submitting && isWaitingConfirmation.value) {
      pendingAction.value = null;
    }
  },
);

function cloneDraft(draft: ReviewDraft): ReviewDraft {
  return {
    ...draft,
    specification_references: draft.specification_references.map((citation) => ({
      ...citation,
      section: [...citation.section],
      chunk_ids: [...citation.chunk_ids],
    })),
    suggested_rework: { ...draft.suggested_rework },
  };
}

function resetFromApproval() {
  localDraft.value = cloneDraft(props.approval.draft);
  confirmationOpen.value = false;
  pendingAction.value = null;
}

function updateConclusion(event: Event) {
  const conclusion = (event.target as HTMLSelectElement).value as ReviewConclusion;
  localDraft.value.conclusion = conclusion;
  localDraft.value.suggested_rework =
    conclusion === "REWORK_REQUIRED"
      ? { required: true, type: "COORDINATE_SYSTEM_FIX" }
      : { required: false, type: null };
}

function openConfirmation() {
  if (confirmDisabled.value || confirmationOpen.value) return;
  confirmationOpen.value = true;
}

function closeConfirmation() {
  if (pendingAction.value !== null) return;
  confirmationOpen.value = false;
}

function confirmDecision() {
  // 再次检查状态，确保确认单状态没有改变
  if (confirmDisabled.value || !confirmationOpen.value) return;
  // 立即加本地锁，防止并发提交
  pendingAction.value = "confirm";
  confirmationOpen.value = false;
  // 复制最终草稿，避免修改原始数据
  const draft = cloneDraft(localDraft.value);
  // 清理意见首尾空格
  draft.review_comment = normalizedComment.value;
  // 发事件
  emit("confirm", { approval_id: props.approval.approval_id, draft });
}

function cancelApproval() {
  if (controlsDisabled.value) return;
  pendingAction.value = "cancel";
  confirmationOpen.value = false;
  emit("cancel", props.approval.approval_id);
}
</script>

<template>
  <article
    class="review-approval-card"
    :aria-busy="submitting || pendingAction !== null"
  >
    <header class="approval-card-header">
      <div>
        <span class="approval-eyebrow">人工复核确认</span>
        <h3>复核草稿</h3>
      </div>
      <!-- 确认单状态 -->
      <span class="approval-status" :data-status="approval.status">{{ statusLabel }}</span>
    </header>
    <!-- 影响对象和版本 -->
    <section class="approval-target" aria-label="影响对象">
      <span>影响对象</span>
      <strong>{{ approval.target_id }}</strong>
      <small>{{ localDraft.issue_id }} · 版本 {{ approval.target_version }}</small>
    </section>
    <!-- 问题摘要 -->
    <section class="approval-section">
      <h4>问题摘要</h4>
      <p class="approval-problem-summary">{{ localDraft.problem_summary }}</p>
    </section>
    <!-- 可编辑结论 -->
    <section class="approval-section approval-form">
      <label for="review-conclusion">复核结论</label>
      <select
        id="review-conclusion"
        data-testid="review-conclusion"
        :value="localDraft.conclusion"
        :disabled="controlsDisabled"
        @change="updateConclusion"
      >
        <option
          v-for="option in conclusionOptions"
          :key="option.value"
          :value="option.value"
        >
          {{ option.label }}
        </option>
      </select>
      <!-- 可编辑复核意见 -->
      <div class="approval-label-row">
        <label for="review-comment">复核意见</label>
        <span>{{ localDraft.review_comment.length }}/1000</span>
      </div>
      <textarea
        id="review-comment"
        v-model="localDraft.review_comment"
        data-testid="review-comment"
        rows="4"
        :disabled="controlsDisabled"
        aria-describedby="review-comment-help review-comment-error"
      />
      <small id="review-comment-help">可在最终确认前修改，提交时会去除首尾空格。</small>
      <p
        v-if="commentError"
        id="review-comment-error"
        class="approval-field-error"
        aria-live="polite"
      >
        {{ commentError }}
      </p>
    </section>
    <!-- 规范引用 -->
    <section class="approval-section">
      <div class="approval-section-heading">
        <h4>规范引用</h4>
        <span>{{ localDraft.specification_references.length }} 条</span>
      </div>
      <div v-if="localDraft.specification_references.length" class="approval-citations">
        <KnowledgeCitationCard
          v-for="citation in localDraft.specification_references"
          :key="`${citation.document_id}:${citation.document_version}:${citation.chunk_id}`"
          :citation="citation"
        />
      </div>
      <p v-else class="approval-empty-reference">当前草稿没有规范引用，请谨慎确认。</p>
    </section>

    <footer class="approval-actions">
      <p>此处只提交人工决定；业务写入仍须经过后续安全执行链。</p>
      <div>
        <button
          type="button"
          class="approval-button approval-button-secondary"
          data-testid="cancel-review-approval"
          :disabled="controlsDisabled"
          @click="cancelApproval"
        >
          {{ cancelLabel }}
        </button>
        <button
          type="button"
          class="approval-button approval-button-primary"
          data-testid="open-review-confirmation"
          :disabled="confirmDisabled"
          @click="openConfirmation"
        >
          {{ submitLabel }}
        </button>
      </div>
    </footer>

    <div v-if="confirmationOpen" class="approval-dialog-backdrop">
      <section
        class="approval-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="review-confirmation-title"
        aria-describedby="review-confirmation-description"
      >
        <span class="approval-dialog-mark" aria-hidden="true">!</span>
        <h3 id="review-confirmation-title">确认提交复核结论？</h3>
        <p id="review-confirmation-description">
          将提交“{{
            conclusionOptions.find((option) => option.value === localDraft.conclusion)?.label
          }}”及当前复核意见。后续执行前仍会重新校验权限、状态和目标版本。
        </p>
        <div class="approval-dialog-actions">
          <button
            type="button"
            class="approval-button approval-button-secondary"
            @click="closeConfirmation"
          >
            返回修改
          </button>
          <button
            type="button"
            class="approval-button approval-button-primary"
            data-testid="confirm-review-decision"
            :disabled="confirmDisabled"
            @click="confirmDecision"
          >
            确认提交
          </button>
        </div>
      </section>
    </div>
  </article>
</template>

<style scoped>
.review-approval-card {
  position: relative;
  display: grid;
  gap: 20px;
  width: min(100%, 680px);
  padding: 24px;
  overflow: hidden;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow);
}

.approval-card-header,
.approval-section-heading,
.approval-label-row,
.approval-actions > div,
.approval-dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.approval-card-header h3,
.approval-section h4,
.approval-dialog h3 {
  margin: 0;
}

.approval-eyebrow {
  display: block;
  margin-bottom: 5px;
  color: var(--blue);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.approval-status {
  padding: 6px 10px;
  color: #b54708;
  background: var(--warning-soft);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.approval-status:not([data-status="WAITING_CONFIRMATION"]) {
  color: var(--muted);
  background: #f2f4f7;
}

.approval-target {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 13px 15px;
  background: var(--blue-soft);
  border: 1px solid #d1e0ff;
  border-radius: 10px;
}

.approval-target span,
.approval-target small,
.approval-section-heading span,
.approval-label-row span,
.approval-form small,
.approval-actions p {
  color: var(--muted);
  font-size: 12px;
}

.approval-target strong {
  color: var(--blue-dark);
}

.approval-section {
  display: grid;
  gap: 10px;
}

.approval-problem-summary,
.approval-empty-reference {
  margin: 0;
  line-height: 1.7;
}

.approval-problem-summary {
  padding: 13px 15px;
  background: var(--danger-soft);
  border-left: 3px solid var(--danger);
  border-radius: 4px 9px 9px 4px;
}

.approval-form label {
  font-size: 13px;
  font-weight: 650;
}

.approval-form select,
.approval-form textarea {
  width: 100%;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  font: inherit;
}

.approval-form select {
  height: 40px;
  padding: 0 11px;
}

.approval-form textarea {
  padding: 11px 12px;
  line-height: 1.6;
  resize: vertical;
}

.approval-form select:focus,
.approval-form textarea:focus {
  border-color: var(--blue);
  outline: 3px solid rgb(47 107 255 / 12%);
}

.approval-form select:disabled,
.approval-form textarea:disabled {
  color: var(--muted);
  background: #f9fafb;
  cursor: not-allowed;
}

.approval-field-error {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
}

.approval-citations {
  display: grid;
  gap: 10px;
}

.approval-empty-reference {
  padding: 12px;
  color: #b54708;
  background: var(--warning-soft);
  border-radius: 8px;
}

.approval-actions {
  display: grid;
  gap: 13px;
  padding-top: 17px;
  border-top: 1px solid var(--line);
}

.approval-actions p {
  margin: 0;
  line-height: 1.5;
}

.approval-button {
  min-height: 38px;
  padding: 0 15px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-weight: 650;
  cursor: pointer;
}

.approval-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.approval-button-primary {
  color: #fff;
  background: var(--blue);
}

.approval-button-secondary {
  color: #344054;
  background: var(--paper);
  border-color: #d0d5dd;
}

.approval-dialog-backdrop {
  position: absolute;
  z-index: 3;
  inset: 0;
  display: grid;
  padding: 20px;
  background: rgb(23 36 59 / 48%);
  place-items: center;
}

.approval-dialog {
  width: min(100%, 420px);
  padding: 24px;
  background: var(--paper);
  border-radius: 12px;
  box-shadow: 0 18px 42px rgb(16 24 40 / 22%);
  text-align: center;
}

.approval-dialog-mark {
  display: grid;
  width: 42px;
  height: 42px;
  margin: 0 auto 13px;
  color: #b54708;
  background: var(--warning-soft);
  border-radius: 50%;
  font-size: 23px;
  font-weight: 700;
  place-items: center;
}

.approval-dialog p {
  margin: 11px 0 20px;
  color: var(--muted);
  line-height: 1.65;
}

.approval-dialog-actions {
  justify-content: flex-end;
}

@media (max-width: 600px) {
  .review-approval-card {
    padding: 18px;
  }

  .approval-target {
    grid-template-columns: 1fr auto;
  }

  .approval-target span {
    grid-column: 1 / -1;
  }

  .approval-actions > div,
  .approval-dialog-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}
</style>
