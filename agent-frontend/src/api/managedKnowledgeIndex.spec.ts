import MockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";

import { agentHttpClient, requestAgentCapabilities } from "./agentClient";
import { isManagedKnowledgeIndexCapabilities } from "./managedKnowledgeIndex";

const mock = new MockAdapter(agentHttpClient);
afterEach(() => mock.reset());

function empty() {
  return {
    source: "MANAGED", configured_source_mode: "LEGACY", release_revision: 3,
    ready: false, status: "NOT_INDEXED", reason: "NO_PUBLISHED_DOCUMENTS", message: "无已发布资料",
    expected_document_count: 0, document_count: 0, chunk_count: 0,
    expected_index: { provider: "test", model: "embedding", dimension: 1536, index_version: "v1", chunking_version: "heading-v1" },
    stored_index: null,
  };
}

describe("managed knowledge readiness contract", () => {
  it("接受带MANAGED标识的零发布，既有能力Client也可校验", async () => {
    const managed = empty();
    expect(isManagedKnowledgeIndexCapabilities(managed)).toBe(true);
    mock.onGet("/api/agent/capabilities").reply(200, {
      message_api_enabled: true,
      result_kinds: ["ORDER_STATUS", "DIAGNOSIS", "SPECIFICATION_ANSWER", "CLARIFICATION", "APPROVAL"],
      model: { configured: false, provider: null, model_name: null }, knowledge_index: managed,
    });
    await expect(requestAgentCapabilities()).resolves.toMatchObject({ knowledge_index: { expected_document_count: 0, message: "无已发布资料" } });
    const legacy = { ...managed, source: "LEGACY" };
    mock.onGet("/api/agent/capabilities").reply(200, {
      message_api_enabled: true,
      result_kinds: ["ORDER_STATUS", "DIAGNOSIS", "SPECIFICATION_ANSWER", "CLARIFICATION", "APPROVAL"],
      model: { configured: false, provider: null, model_name: null }, knowledge_index: legacy,
    });
    await expect(requestAgentCapabilities()).rejects.toMatchObject({ code: "RESPONSE_VALIDATION_ERROR" });
  });

  it("接受动态数量的READY、INCOMPLETE及完整或混合身份不匹配", () => {
    const base = empty();
    const ready = { ...base, expected_document_count: 1, document_count: 1, chunk_count: 2,
      ready: true, status: "READY", reason: "PUBLISHED_INDEX_READY", message: "已发布索引可用", stored_index: base.expected_index };
    expect(isManagedKnowledgeIndexCapabilities(ready)).toBe(true);
    expect(isManagedKnowledgeIndexCapabilities({ ...ready, ready: false, status: "INCOMPLETE", reason: "PUBLISHED_INDEX_INCOMPLETE", message: "已发布索引不完整" })).toBe(true);
    expect(isManagedKnowledgeIndexCapabilities({ ...ready, ready: false, status: "INDEX_MISMATCH", reason: "INDEX_IDENTITY_MISMATCH", message: "已发布索引与当前配置不匹配", stored_index: null })).toBe(true);
  });

  it.each([
    { ready: true }, { expected_document_count: -1 }, { expected_document_count: 1 },
    { document_count: 1 }, { chunk_count: 1 }, { release_revision: true },
    { release_revision: Number.MAX_SAFE_INTEGER + 1 }, { configured_source_mode: ["LEGACY"] },
    { reason: "PUBLISHED_INDEX_READY" }, { source: "OTHER" }, { expected_index: null },
  ])("拒绝不一致或丢失身份的零发布状态 %j", (updates) => {
    expect(isManagedKnowledgeIndexCapabilities({ ...empty(), ...updates })).toBe(false);
  });
});
