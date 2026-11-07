import type { ManagedKnowledgeIndexCapabilities } from "../types/managedKnowledgeIndex";

const DESCRIPTIONS = {
  NOT_INDEXED: ["NO_PUBLISHED_DOCUMENTS", "无已发布资料"],
  INCOMPLETE: ["PUBLISHED_INDEX_INCOMPLETE", "已发布索引不完整"],
  INDEX_MISMATCH: ["INDEX_IDENTITY_MISMATCH", "已发布索引与当前配置不匹配"],
  READY: ["PUBLISHED_INDEX_READY", "已发布索引可用"],
} as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCounter(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isIdentity(value: unknown): value is ManagedKnowledgeIndexCapabilities["expected_index"] {
  return isRecord(value)
    && ["provider", "model", "index_version", "chunking_version"].every(
      (key) => typeof value[key] === "string" && String(value[key]).trim().length > 0)
    && typeof value.dimension === "number" && Number.isSafeInteger(value.dimension) && value.dimension > 0;
}

function sameIdentity(left: ManagedKnowledgeIndexCapabilities["expected_index"], right: unknown): boolean {
  return isIdentity(right) && left.provider === right.provider && left.model === right.model
    && left.dimension === right.dimension && left.index_version === right.index_version
    && left.chunking_version === right.chunking_version;
}

export function isManagedKnowledgeIndexCapabilities(value: unknown): value is ManagedKnowledgeIndexCapabilities {
  if (!isRecord(value) || value.source !== "MANAGED"
    || (value.configured_source_mode !== "LEGACY" && value.configured_source_mode !== "MANAGED")
    || !isCounter(value.release_revision) || typeof value.status !== "string"
    || !Object.hasOwn(DESCRIPTIONS, value.status) || typeof value.ready !== "boolean"
    || !isCounter(value.expected_document_count) || !isCounter(value.document_count)
    || !isCounter(value.chunk_count) || value.document_count > value.expected_document_count
    || !isIdentity(value.expected_index)
    || (value.stored_index !== null && !isIdentity(value.stored_index))) return false;
  const status = value.status as keyof typeof DESCRIPTIONS;
  const [reason, message] = DESCRIPTIONS[status];
  if (value.ready !== (status === "READY") || value.reason !== reason || value.message !== message) return false;
  if (status === "NOT_INDEXED") {
    return value.expected_document_count === 0 && value.document_count === 0
      && value.chunk_count === 0 && value.stored_index === null;
  }
  if (value.expected_document_count === 0) return false;
  if (status === "INCOMPLETE") return true;
  return value.document_count === value.expected_document_count && value.chunk_count > 0
    && (sameIdentity(value.expected_index, value.stored_index) === (status === "READY"));
}
