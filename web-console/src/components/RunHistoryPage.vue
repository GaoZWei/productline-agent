<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { AgentApiError } from "../api/agentClient";
import {
  requestRunDetail,
  requestRunHistory,
  requestRunSteps,
} from "../api/runHistoryClient";
import type { KnowledgeCitation } from "../types/agent";
import type {
  ApprovalFieldChange,
  RunDetailResponse,
  RunStatus,
  RunSummary,
  StepStatus,
  StepSummary,
  StepType,
} from "../types/runHistory";
import KnowledgeCitationCard from "./KnowledgeCitationCard.vue";

const pageSize = 10;
const runs = ref<RunSummary[]>([]);
const page = ref(1);
const total = ref(0);
const listLoading = ref(false);
const listError = ref<AgentApiError | null>(null);
const selectedRunId = ref<string | null>(null);
const detail = ref<RunDetailResponse | null>(null);
const steps = ref<StepSummary[]>([]);
const detailLoading = ref(false);
const detailError = ref<AgentApiError | null>(null);
let detailRequestSequence = 0;

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const selectedRun = computed(
  () => runs.value.find((run) => run.run_id === selectedRunId.value) ?? detail.value?.run ?? null,
);
const citations = computed(() => {
  const unique = new Map<string, KnowledgeCitation>();
  // 前端引用整理，将所有引用的规范（包括原始草稿和最终草稿）都添加到引用列表中（）
  for (const approval of detail.value?.approvals ?? []) {
    for (const citation of approval.effective_draft.specification_references) {
      const key = `${citation.document_id}:${citation.document_version}:${citation.chunk_id}`;
      unique.set(key, citation);
    }
  }
  return [...unique.values()];
});

const runStatusLabels: Record<RunStatus, string> = {
  PENDING: "等待执行",
  RUNNING: "执行中",
  SUCCEEDED: "已成功",
  FAILED: "执行失败",
  WAITING_APPROVAL: "等待确认",
  CANCELLED: "已取消",
};

const stepStatusLabels: Record<StepStatus, string> = {
  PENDING: "等待执行",
  RUNNING: "执行中",
  SUCCEEDED: "已完成",
  FAILED: "失败",
};

const stepTypeLabels: Record<StepType, string> = {
  CONTEXT: "上下文",
  ROUTER: "路由",
  WORKFLOW: "工作流",
  AGENT: "Agent决策",
  TOOL: "业务工具",
  RAG: "规范检索",
  LLM: "模型调用",
  APPROVAL: "人工确认",
  WRITEBACK: "业务写回",
};

onMounted(() => loadRuns());

async function loadRuns(targetPage = page.value) {
  listLoading.value = true;
  listError.value = null;
  try {
    const response = await requestRunHistory(targetPage, pageSize);
    runs.value = response.items;
    page.value = response.page;
    total.value = response.total;
    const nextSelection = response.items.some((run) => run.run_id === selectedRunId.value)
      ? selectedRunId.value
      : response.items[0]?.run_id ?? null;
    if (nextSelection) await selectRun(nextSelection);
    else clearDetail();
  } catch (reason) {
    listError.value = asAgentError(reason);
  } finally {
    listLoading.value = false;
  }
}

async function selectRun(runId: string) {
  if (detailLoading.value && selectedRunId.value === runId) return;
  selectedRunId.value = runId;
  detail.value = null;
  steps.value = [];
  detailError.value = null;
  detailLoading.value = true;
  const requestSequence = ++detailRequestSequence;
  try {
    // 并行请求Run详情和Step列表
    const [runDetail, runSteps] = await Promise.all([
      requestRunDetail(runId),
      requestRunSteps(runId),
    ]);
    if (requestSequence !== detailRequestSequence) return;
    detail.value = runDetail;
    steps.value = runSteps.items;
  } catch (reason) {
    if (requestSequence !== detailRequestSequence) return;
    detailError.value = asAgentError(reason);
  } finally {
    if (requestSequence === detailRequestSequence) detailLoading.value = false;
  }
}

function clearDetail() {
  detailRequestSequence += 1;
  selectedRunId.value = null;
  detail.value = null;
  steps.value = [];
  detailError.value = null;
  detailLoading.value = false;
}

function asAgentError(reason: unknown) {
  return reason instanceof AgentApiError
    ? reason
    : new AgentApiError({ code: "UNKNOWN_CLIENT_ERROR", message: "读取运行历史失败" });
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function formatDuration(value: number | null) {
  if (value === null) return "—";
  if (value < 1_000) return `${value} ms`;
  return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

function formatDiffValue(value: ApprovalFieldChange["before"]) {
  if (value === null) return "未设置";
  if (Array.isArray(value)) return value.join("、") || "空列表";
  if (typeof value === "boolean") return value ? "是" : "否";
  return value;
}
</script>

<template>
  <main class="run-history-page" data-testid="run-history-page">
    <header class="run-history-heading">
      <div>
        <span class="eyebrow">AGENT OBSERVABILITY</span>
        <h1>运行历史</h1>
        <p>查看自己的诊断执行、步骤摘要、规范引用与人工确认记录。</p>
      </div>
      <button type="button" class="history-refresh" :disabled="listLoading" @click="loadRuns(page)">
        {{ listLoading ? "正在刷新…" : "刷新记录" }}
      </button>
    </header>

    <div v-if="listError" class="history-error" role="alert">
      <strong>{{ listError.code }} · {{ listError.message }}</strong>
      <span v-if="listError.traceId">Trace ID：{{ listError.traceId }}</span>
      <button type="button" @click="loadRuns(page)">重新加载</button>
    </div>

    <div class="run-history-layout">
      <section class="run-list-panel" aria-label="Run列表">
        <header>
          <div><strong>执行记录</strong><span>{{ total }} 条</span></div>
          <small>仅显示当前用户</small>
        </header>

        <div v-if="listLoading && !runs.length" class="history-loading">正在读取执行记录…</div>
        <div v-else-if="!runs.length" class="history-empty">还没有可查看的运行记录。</div>
        <ol v-else class="history-run-list">
          <li v-for="run in runs" :key="run.run_id">
            <button
              type="button"
              :class="{ active: run.run_id === selectedRunId }"
              :data-run-id="run.run_id"
              @click="selectRun(run.run_id)"
            >
              <span class="run-list-marker" :data-status="run.status"></span>
              <span class="run-list-main">
                <span><strong>{{ run.order_id ?? "未关联订单" }}</strong><small>{{ formatDate(run.created_at) }}</small></span>
                <code>{{ run.run_id }}</code>
                <span class="run-list-meta">
                  <em :data-status="run.status">{{ runStatusLabels[run.status] }}</em>
                  <small>{{ run.tool_call_count }} Tool · {{ formatDuration(run.duration_ms) }}</small>
                </span>
              </span>
            </button>
          </li>
        </ol>

        <footer class="history-pagination">
          <button type="button" :disabled="page <= 1 || listLoading" @click="loadRuns(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button type="button" :disabled="page >= totalPages || listLoading" @click="loadRuns(page + 1)">下一页</button>
        </footer>
      </section>

      <section class="run-detail-panel" aria-label="Run详情">
        <div v-if="detailLoading" class="history-loading history-detail-loading">正在读取Run详情和执行步骤…</div>
        <div v-else-if="detailError" class="history-error history-detail-error" role="alert">
          <strong>{{ detailError.code }} · {{ detailError.message }}</strong>
          <span v-if="detailError.traceId">Trace ID：{{ detailError.traceId }}</span>
          <button v-if="selectedRunId" type="button" @click="selectRun(selectedRunId)">重试详情</button>
        </div>
        <div v-else-if="!selectedRun" class="history-empty history-detail-empty">选择一条Run查看详情。</div>

        <template v-else-if="detail">
          <header class="run-detail-heading">
            <div>
              <span class="eyebrow">{{ detail.run.order_id ?? "AGENT RUN" }}</span>
              <h2>{{ detail.run.run_id }}</h2>
              <p>Session {{ detail.run.session_id }} · {{ formatDate(detail.run.created_at) }}</p>
            </div>
            <span class="run-detail-status" :data-status="detail.run.status">{{ runStatusLabels[detail.run.status] }}</span>
          </header>

          <dl class="run-metrics">
            <div><dt>执行耗时</dt><dd>{{ formatDuration(detail.run.duration_ms) }}</dd></div>
            <div><dt>Tool调用</dt><dd>{{ detail.run.tool_call_count }}</dd></div>
            <div><dt>输入Token</dt><dd>{{ detail.input_token_count }}</dd></div>
            <div><dt>输出Token</dt><dd>{{ detail.output_token_count }}</dd></div>
          </dl>
          <!-- 错误详情 -->
          <section v-if="detail.run.error_code" class="run-error-detail" data-testid="run-error-detail">
            <span>执行错误</span>
            <strong>{{ detail.run.error_code }}</strong>
            <p>失败步骤：{{ detail.run.error_step ?? "未记录" }}</p>
            <small>终止原因：{{ detail.run.termination_reason ?? "未记录" }}</small>
          </section>
          <!-- 诊断结果 -->
          <section v-if="detail.result" class="history-section diagnosis-history-result">
            <header><h3>诊断结果</h3><span>置信度 {{ Math.round(detail.result.confidence * 100) }}%</span></header>
            <p>{{ detail.result.summary }}</p>
            <ul>
              <li v-for="cause in detail.result.root_causes" :key="cause.code">
                <code>{{ cause.code }}</code>{{ cause.description }}
              </li>
            </ul>
          </section>
          <!-- Step时间线 -->
          <section class="history-section step-history-section" data-testid="step-history">
            <header><h3>执行时间线</h3><span>{{ steps.length }} 个步骤</span></header>
            <p v-if="!steps.length" class="history-section-empty">该Run没有持久化步骤。</p>
            <ol v-else class="step-history-list">
              <li v-for="step in steps" :key="step.step_id" :data-status="step.status" :data-step-type="step.step_type">
                <span class="step-history-index">{{ step.sequence_number }}</span>
                <div>
                  <header>
                    <span>{{ stepTypeLabels[step.step_type] }}</span>
                    <strong>{{ step.step_name }}</strong>
                    <em :data-status="step.status">{{ stepStatusLabels[step.status] }}</em>
                  </header>
                  <div v-if="step.input_summary || step.output_summary" class="step-summary-grid">
                    <p v-if="step.input_summary"><small>输入摘要</small><code>{{ step.input_summary }}</code></p>
                    <p v-if="step.output_summary"><small>输出摘要</small><code>{{ step.output_summary }}</code></p>
                  </div>
                  <p v-if="step.model_name" class="llm-step-metrics">
                    <small>模型 {{ step.model_name }}</small>
                    <span>输入 {{ step.input_token_count ?? 0 }} Token</span>
                    <span>输出 {{ step.output_token_count ?? 0 }} Token</span>
                    <span>重试 {{ step.retry_count ?? 0 }} 次</span>
                  </p>
                  <footer>
                    <span>{{ formatDuration(step.duration_ms) }}</span>
                    <code v-if="step.error_code">{{ step.error_code }}</code>
                  </footer>
                </div>
              </li>
            </ol>
          </section>
          <!-- 规范引用 -->
          <section class="history-section" data-testid="rag-citations">
            <header><h3>规范引用</h3><span>{{ citations.length }} 条</span></header>
            <p v-if="!citations.length" class="history-section-empty">该Run没有形成可展示的规范引用。</p>
            <div v-else class="history-citations">
              <KnowledgeCitationCard
                v-for="citation in citations"
                :key="`${citation.document_id}:${citation.document_version}:${citation.chunk_id}`"
                :citation="citation"
              />
            </div>
          </section>
          <!-- Approval确认历史 -->
          <section class="history-section" data-testid="approval-history">
            <header><h3>人工确认记录</h3><span>{{ detail.approvals.length }} 条</span></header>
            <p v-if="!detail.approvals.length" class="history-section-empty">该Run没有产生人工确认记录。</p>
            <article v-for="approval in detail.approvals" v-else :key="approval.approval_id" class="approval-history-card">
              <header>
                <div><strong>{{ approval.approval_id }}</strong><small>{{ approval.target_id }} · 版本 {{ approval.target_version }}</small></div>
                <span :data-status="approval.status">{{ approval.status }}</span>
              </header>
              <p class="approval-history-comment">{{ approval.effective_draft.review_comment }}</p>
              <div v-if="approval.user_modification_diff.length" class="approval-diff-list">
                <strong>用户修改 {{ approval.user_modification_diff.length }} 项</strong>
                <dl v-for="change in approval.user_modification_diff" :key="change.field_path">
                  <dt>{{ change.field_path }}</dt>
                  <dd><del>{{ formatDiffValue(change.before) }}</del><span>→</span><ins>{{ formatDiffValue(change.after) }}</ins></dd>
                </dl>
              </div>
              <p v-else class="approval-no-diff">用户未修改模型原稿。</p>
            </article>
          </section>
        </template>
      </section>
    </div>
  </main>
</template>
