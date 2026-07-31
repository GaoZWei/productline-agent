<script setup lang="ts">
import { ElTag } from "element-plus";
import { computed } from "vue";
import type { TaskOverview } from "../types/business";

const props = defineProps<{ tasks: TaskOverview[] }>();

const issues = computed(() =>
  props.tasks.flatMap((task) =>
    task.qualityIssues.map((overview) => ({
      taskId: task.task.taskId,
      ...overview,
    })),
  ),
);
</script>

<template>
  <section class="panel quality-panel">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">QUALITY CONTROL</span>
        <h2>质检与复核</h2>
      </div>
      <span class="count-badge" :class="{ alert: issues.length > 0 }">
        {{ issues.length }} 个问题
      </span>
    </div>

    <div v-if="issues.length === 0" class="clear-state">
      <span class="clear-icon">✓</span>
      <div><strong>未发现质检问题</strong><small>当前业务快照中没有关联问题。</small></div>
    </div>

    <article v-for="item in issues" v-else :key="item.issue.issueId" class="issue-card">
      <div class="issue-title-row">
        <div>
          <span class="issue-id">{{ item.issue.issueId }}</span>
          <h3>{{ item.issue.issueType }}</h3>
        </div>
        <el-tag :type="item.issue.status === 'OPEN' ? 'danger' : 'warning'" effect="dark">
          {{ item.issue.status }}
        </el-tag>
      </div>
      <p>{{ item.issue.description }}</p>
      <div class="issue-meta">关联任务 {{ item.taskId }}</div>

      <div class="review-list">
        <div v-for="review in item.reviews" :key="review.reviewId" class="review-row">
          <span>
            <small>复核记录</small>
            <strong>{{ review.reviewId }}</strong>
          </span>
          <span class="review-comment">{{ review.reviewComment || "暂无复核意见" }}</span>
          <el-tag :type="review.status === 'PENDING' ? 'warning' : 'success'" effect="plain">
            {{ review.status }}
          </el-tag>
        </div>
      </div>
    </article>
  </section>
</template>
