<script setup lang="ts">
import type { TaskOverview } from "../types/business";

defineProps<{ tasks: TaskOverview[] }>();

function statusClass(status: string) {
  if (status === "COMPLETED") return "status-success";
  if (status === "FAILED" || status === "BLOCKED") return "status-danger";
  return "status-pending";
}
</script>

<template>
  <section class="panel task-panel">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">PRODUCTION</span>
        <h2>生产任务</h2>
      </div>
      <span class="count-badge">{{ tasks.length }} 个任务</span>
    </div>

    <div v-if="tasks.length === 0" class="empty-copy">当前订单没有生产任务。</div>
    <article v-for="item in tasks" v-else :key="item.task.taskId" class="task-card">
      <div class="task-title-row">
        <div>
          <span class="task-id">{{ item.task.taskId }}</span>
          <span class="version">v{{ item.task.version }}</span>
        </div>
        <span class="status-pill" :class="statusClass(item.task.status)">
          {{ item.task.status }}
        </span>
      </div>

      <ol class="step-list">
        <li v-for="step in item.steps" :key="step.stepId">
          <span class="step-marker" :class="statusClass(step.status)">
            {{ step.sequenceNumber }}
          </span>
          <span>
            <strong>{{ step.stepName }}</strong>
            <small>{{ step.stepId }}</small>
          </span>
          <span class="step-status">{{ step.status }}</span>
        </li>
      </ol>
    </article>
  </section>
</template>
