<script setup lang="ts">
import { computed } from "vue";
import type { ReworkHistoryKind, ReworkHistoryRecords, ReworkProcessing, ReworkInspection, ReworkReview } from "../types/rework";

const props = defineProps<{ kind: ReworkHistoryKind; record: ReworkHistoryRecords[ReworkHistoryKind] }>();
const processing = computed(() => props.kind === "results" ? props.record as ReworkProcessing : null);
const inspection = computed(() => props.kind === "inspections" ? props.record as ReworkInspection : null);
const review = computed(() => props.kind === "reviews" ? props.record as ReworkReview : null);
</script>

<template>
  <article class="rework-record">
    <template v-if="processing">
      <strong>处理修订 {{ processing.processingRevision }}</strong>
      <p>成果：{{ processing.artifact.artifactId }} · 版本 {{ processing.artifact.artifactVersion }}</p>
      <p class="original-text">{{ processing.processingComment }}</p>
      <p>登记：{{ processing.registeredBy }} · {{ processing.registeredAt }}</p>
      <ul aria-label="处理证据"><li v-for="(reference, index) in processing.evidenceReferences" :key="index">{{ reference }}</li></ul>
    </template>
    <template v-else-if="inspection">
      <strong>检查 {{ inspection.inspectionSequence }} · {{ inspection.result }}</strong>
      <p>{{ inspection.inspectionId }} · 第 {{ inspection.roundNumber }} 轮 · 处理修订 {{ inspection.processingRevision }}</p>
      <p>检查：{{ inspection.inspectorId }} · {{ inspection.inspectedAt }}</p>
      <section v-for="(item, index) in inspection.items" :key="index" class="rework-check-item">
        <strong>{{ item.checkItem }} · {{ item.result }}</strong>
        <p class="original-text">{{ item.comment }}</p>
        <ul aria-label="检查证据"><li v-for="(reference, referenceIndex) in item.evidenceReferences" :key="referenceIndex">{{ reference }}</li></ul>
      </section>
    </template>
    <template v-else-if="review">
      <strong>复核 {{ review.reviewSequence }} · {{ review.status }}</strong>
      <p>{{ review.reviewId }} · 第 {{ review.roundNumber }} 轮 · 处理修订 {{ review.processingRevision }} · 检查 {{ review.inspectionId }}</p>
      <p class="original-text">{{ review.reviewComment }}</p>
      <p>复核：{{ review.reviewedBy }} · {{ review.reviewedAt }}</p>
    </template>
  </article>
</template>
