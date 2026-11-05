<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { buildRunTimeline, type RunTimelineStatus } from "../observability/runEventTimeline";
import type { RunEvent, RunEventConnectionStatus } from "../types/runEvents";

const props = defineProps<{
  events: RunEvent[];
  connectionStatus: RunEventConnectionStatus | "idle";
}>();

const now = ref(Date.now());
let timer: ReturnType<typeof globalThis.setInterval> | undefined;
const timeline = computed(() => buildRunTimeline(props.events));
const connectionLabel = computed(() => {
  const labels: Record<typeof props.connectionStatus, string> = {
    idle: "等待连接",
    connecting: "正在连接",
    open: "实时更新",
    reconnecting: "正在重连",
    closed: "执行结束",
    failed: "连接中断",
  };
  return labels[props.connectionStatus];
});
const statusLabels: Record<RunTimelineStatus, string> = {
  running: "进行中",
  succeeded: "已完成",
  failed: "失败",
  waiting: "等待确认",
  degraded: "已降级",
  info: "已选择",
};

onMounted(() => {
  timer = globalThis.setInterval(() => {
    now.value = Date.now();
  }, 250);
});
onBeforeUnmount(() => {
  if (timer !== undefined) globalThis.clearInterval(timer);
});

function formatDuration(startedAt: string, completedAt: string | null) {
  const end = completedAt ? Date.parse(completedAt) : now.value;
  const elapsed = Math.max(0, end - Date.parse(startedAt));
  if (elapsed < 1_000) return `${elapsed} ms`;
  return `${(elapsed / 1_000).toFixed(elapsed < 10_000 ? 1 : 0)} s`;
}
</script>

<template>
  <section class="agent-run-timeline" aria-live="polite" data-testid="run-timeline">
    <header>
      <div>
        <span>LIVE RUN</span>
        <h3>实时执行步骤</h3>
      </div>
      <small :data-connection-status="connectionStatus">{{ connectionLabel }}</small>
    </header>

    <ol v-if="timeline.length" class="run-timeline-list">
      <li
        v-for="item in timeline"
        :key="item.key"
        class="run-timeline-item"
        :data-kind="item.kind"
        :data-status="item.status"
      >
        <span class="run-timeline-marker" aria-hidden="true"></span>
        <div class="run-timeline-content">
          <div class="run-timeline-heading">
            <strong>{{ item.label }}</strong>
            <span>{{ statusLabels[item.status] }}</span>
          </div>
          <p v-if="item.detail">{{ item.detail }}</p>
          <div class="run-timeline-meta">
            <time :datetime="item.startedAt">
              {{ formatDuration(item.startedAt, item.completedAt) }}
            </time>
            <code v-if="item.errorCode">{{ item.errorCode }}</code>
          </div>
        </div>
      </li>
    </ol>
    <p v-else class="run-timeline-empty">正在建立安全事件连接…</p>
  </section>
</template>
