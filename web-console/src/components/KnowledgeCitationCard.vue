<script setup lang="ts">
import { computed, ref } from "vue";

import type { KnowledgeCitation } from "../types/agent";

const props = defineProps<{ citation: KnowledgeCitation }>();
const expanded = ref(false);
const sectionLabel = computed(() => props.citation.section.join(" / "));
const chunkLabel = computed(() => props.citation.chunk_ids.join(" · "));
const relevanceLabel = computed(() =>
  props.citation.relevance_score === null
    ? "相关性未评分"
    : `相关性 ${Math.round(props.citation.relevance_score * 100)}%`,
);
</script>

<template>
  <article class="knowledge-citation-card" :data-chunk-id="citation.chunk_id">
    <header>
      <div>
        <strong>{{ citation.document_name }}</strong>
        <span>版本 {{ citation.document_version }}</span>
      </div>
      <span class="citation-score">{{ relevanceLabel }}</span>
    </header>
    <p class="citation-section">{{ sectionLabel }}</p>
    <code>{{ chunkLabel }}</code>
    <p v-if="expanded" class="citation-content">{{ citation.content }}</p>
    <button
      type="button"
      class="citation-toggle"
      data-testid="toggle-citation-content"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? "收起引用原文" : "查看引用原文" }}
    </button>
  </article>
</template>
