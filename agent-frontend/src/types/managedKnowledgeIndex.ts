import type { KnowledgeIndexCapabilities, KnowledgeIndexIdentity } from "./agent";

export interface ManagedKnowledgeIndexIdentity extends KnowledgeIndexIdentity {
  chunking_version: string;
}

export interface ManagedKnowledgeIndexCapabilities extends KnowledgeIndexCapabilities {
  source: "MANAGED";
  configured_source_mode: "LEGACY" | "MANAGED";
  release_revision: number;
  expected_index: ManagedKnowledgeIndexIdentity;
  stored_index: ManagedKnowledgeIndexIdentity | null;
  reason:
    | "NO_PUBLISHED_DOCUMENTS"
    | "PUBLISHED_INDEX_INCOMPLETE"
    | "INDEX_IDENTITY_MISMATCH"
    | "PUBLISHED_INDEX_READY";
  message: "无已发布资料" | "已发布索引不完整" | "已发布索引与当前配置不匹配" | "已发布索引可用";
}
