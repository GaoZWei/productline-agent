<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { fetchReworkDetail } from "../api/reworkClient";
import { BusinessApiError } from "../api/businessClient";
import { reworkActionLabels, type ReworkDetail } from "../types/rework";
import ReworkActionForm from "./ReworkActionForm.vue";
import ReworkHistory from "./ReworkHistory.vue";
import ReworkRecord from "./ReworkRecord.vue";

const props = defineProps<{ orderId: string; taskId: string; reworkId: string }>();
const emit = defineEmits<{ close: []; written: [orderId: string]; openNext: [taskId: string, reworkId: string] }>();
const detail = ref<ReworkDetail>();
const traceId = ref<string>();
const loading = ref(false);
const error = ref<BusinessApiError>();
const actionBusy = ref(false);
const operationId = ref<string>();
const nextReworkId = ref<string | null>(null);
let generation = 0;
watch(() => [props.orderId, props.taskId, props.reworkId], () => {
  operationId.value = undefined;
  nextReworkId.value = null;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { generation++; });

async function load() {
  const current = ++generation;
  const { taskId, reworkId } = props;
  detail.value = undefined;
  actionBusy.value = false;
  traceId.value = undefined;
  error.value = undefined;
  loading.value = true;
  try {
    const response = await fetchReworkDetail(taskId, reworkId);
    if (current !== generation) return;
    detail.value = response.data;
    traceId.value = response.traceId;
  } catch (reason) {
    if (current !== generation) return;
    error.value = reason instanceof BusinessApiError ? reason : new BusinessApiError({ code: "UNKNOWN_CLIENT_ERROR", message: "读取返工详情失败" });
  } finally {
    if (current === generation) loading.value = false;
  }
}

function written(id: string, nextId: string | null) {
  operationId.value = id;
  nextReworkId.value = nextId;
  emit("written", props.orderId);
  void load();
}
</script>

<template>
  <section class="panel rework-detail-panel" aria-label="返工详情" :aria-busy="loading" data-testid="rework-detail-panel">
    <header class="panel-heading">
      <div><span class="eyebrow">返工详情</span><h2>{{ reworkId }}</h2><p>{{ orderId }} · {{ taskId }}</p></div>
      <div class="rework-detail-actions">
        <button type="button" :disabled="loading || actionBusy" @click="load">刷新详情</button>
        <button type="button" @click="emit('close')">关闭详情</button>
      </div>
    </header>
    <p v-if="operationId" role="status">操作已登记，回执 {{ operationId }}。</p>
    <button v-if="nextReworkId" type="button" @click="emit('openNext', taskId, nextReworkId)">
      查看下一轮 {{ nextReworkId }}
    </button>
    <p v-if="loading" role="status">正在读取 Java 返工事实…</p>
    <div v-if="error" role="alert"><p>{{ error.code }} · {{ error.message }}</p><small v-if="error.traceId">Trace：{{ error.traceId }}</small></div>
    <template v-if="detail">
      <dl class="rework-facts">
        <div><dt>返工状态</dt><dd>{{ detail.reworkTask.status }}</dd></div>
        <div><dt>任务版本</dt><dd>{{ detail.taskVersion }}</dd></div>
        <div><dt>来源问题</dt><dd>{{ detail.reworkTask.sourceIssueId ?? '无来源问题' }} · {{ detail.issueStatus ?? '无问题状态' }}</dd></div>
        <div><dt>返工轮次</dt><dd>{{ detail.roundNumber === null ? '存量记录，未登记轮次' : `第 ${detail.roundNumber} 轮` }}</dd></div>
        <div><dt>前一轮返工</dt><dd>{{ detail.previousReworkTaskId ?? '无' }}</dd></div>
      </dl>
      <p class="original-text">返工原因：{{ detail.reworkTask.reason }}</p>
      <p v-if="detail.roundNumber === null" class="rework-boundary">存量记录缺少轮次和处理证据，不能据状态补造检查或复核结论。</p>
      <p class="rework-boundary">返工进度单独管理。处理说明不等于检查通过，本轮完成不等于最终验收；再次复核通过后仍须检查其他交付阻塞。</p>
      <section aria-label="Java允许动作">
        <h3>当前快照允许动作</h3>
        <ul v-if="detail.allowedActions.length" class="rework-allowed-actions"><li v-for="action in detail.allowedActions" :key="action">{{ reworkActionLabels[action] }}</li></ul>
        <p v-else>Java 未返回当前可用动作。</p>
        <ReworkActionForm :key="`${orderId}/${taskId}/${reworkId}`" :order-id="orderId" :detail="detail"
          @busy="actionBusy = $event" @written="written" @refresh="load" />
      </section>
      <section aria-label="Java当前材料">
        <h3>Java 当前材料</h3>
        <ReworkRecord v-if="detail.processing" kind="results" :record="detail.processing" />
        <p v-else>尚无当前成果登记。</p>
        <ReworkRecord v-if="detail.inspection" kind="inspections" :record="detail.inspection" />
        <p v-else>尚无绑定当前成果的检查记录。</p>
        <ReworkRecord v-if="detail.review" kind="reviews" :record="detail.review" />
        <p v-else>尚无绑定当前成果和检查的复核记录。</p>
      </section>
      <p class="muted-copy">详情与各历史页分别读取，不是跨请求原子快照；当前材料只取详情，不从历史推断。刷新详情会重新读取全部首屏。</p>
      <div class="rework-histories">
        <ReworkHistory v-for="kind in (['results', 'inspections', 'reviews'] as const)" :key="kind" :task-id="taskId" :rework-id="reworkId" :round-number="detail.roundNumber" :kind="kind" />
      </div>
      <small v-if="traceId">详情 Trace：{{ traceId }}</small>
    </template>
  </section>
</template>
