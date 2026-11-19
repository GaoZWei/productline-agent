<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { fetchReworkHistory } from "../api/reworkClient";
import { BusinessApiError } from "../api/businessClient";
import { reworkRecordSequence, type ReworkHistoryKind, type ReworkHistoryRecords } from "../types/rework";
import ReworkRecord from "./ReworkRecord.vue";

const props = defineProps<{ taskId: string; reworkId: string; roundNumber: number | null; kind: ReworkHistoryKind }>();
const titles = { results: "成果修订历史", inspections: "人工检查历史", reviews: "再次复核历史" };
const records = ref<ReworkHistoryRecords[ReworkHistoryKind][]>([]);
const nextCursor = ref<string | null>(null);
const loading = ref(false);
const loaded = ref(false);
const error = ref<BusinessApiError>();
const traceId = ref<string>();
let generation = 0;
let consumedCursors = new Set<string>();

watch(() => [props.taskId, props.reworkId, props.kind, props.roundNumber], () => {
  generation++;
  records.value = [];
  nextCursor.value = null;
  loaded.value = false;
  loading.value = false;
  error.value = undefined;
  traceId.value = undefined;
  consumedCursors = new Set();
  void load();
}, { immediate: true });
onBeforeUnmount(() => { generation++; });

async function load() {
  if (loading.value || (loaded.value && nextCursor.value === null)) return;
  const current = generation;
  const { taskId, reworkId, kind, roundNumber } = props;
  const cursor = nextCursor.value;
  loading.value = true;
  error.value = undefined;
  try {
    const response = await fetchReworkHistory(taskId, reworkId, kind, cursor);
    if (current !== generation) return;
    const page = response.data;
    const previous = records.value.at(-1);
    // 历史只按Java序号拼页，不按时间重排，也不从历史挑选当前有效结论。
    if ((roundNumber === null && page.records.length > 0)
      || page.records.some(record => "roundNumber" in record && record.roundNumber !== roundNumber)
      || (previous && page.records[0] && reworkRecordSequence(kind, page.records[0]) <= reworkRecordSequence(kind, previous))
      || (page.nextCursor !== null && (page.nextCursor === cursor || consumedCursors.has(page.nextCursor)))) {
      throw new BusinessApiError({ code: "RESPONSE_VALIDATION_ERROR", message: "返工历史轮次、顺序或游标不一致，请刷新详情", traceId: response.traceId });
    }
    records.value = [...records.value, ...page.records];
    if (cursor !== null) consumedCursors.add(cursor);
    nextCursor.value = page.nextCursor;
    traceId.value = response.traceId;
    loaded.value = true;
  } catch (reason) {
    if (current !== generation) return;
    error.value = reason instanceof BusinessApiError ? reason : new BusinessApiError({ code: "UNKNOWN_CLIENT_ERROR", message: "读取返工历史失败" });
  } finally {
    if (current === generation) loading.value = false;
  }
}
</script>

<template>
  <section class="rework-history" :aria-label="titles[kind]" :data-history-kind="kind" :aria-busy="loading">
    <h3>{{ titles[kind] }}</h3>
    <p class="muted-copy">按本返工 Java 序号升序，已加载 {{ records.length }} 条。历史不代表当前有效复核。</p>
    <ol class="rework-record-list">
      <li v-for="record in records" :key="reworkRecordSequence(kind, record)"><ReworkRecord :kind="kind" :record="record" /></li>
    </ol>
    <p v-if="loaded && !records.length">暂无已登记记录{{ roundNumber === null ? '，存量记录缺少处理证据' : '' }}。</p>
    <p v-if="loading" role="status">正在读取历史…</p>
    <div v-if="error" role="alert">
      <p>{{ error.code }} · {{ error.message }}</p>
      <small v-if="error.traceId">Trace：{{ error.traceId }}</small>
      <button type="button" :disabled="loading" @click="load">重试本页</button>
    </div>
    <button v-else-if="loaded && nextCursor !== null" type="button" :disabled="loading" @click="load">加载更多</button>
    <small v-if="traceId">Trace：{{ traceId }}</small>
  </section>
</template>
