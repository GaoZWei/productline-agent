import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import type { KnowledgeCitation } from "../types/agent";
import KnowledgeCitationCard from "./KnowledgeCitationCard.vue";

let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;

afterEach(() => {
  application?.unmount();
  host?.remove();
  application = undefined;
  host = undefined;
});

describe("Knowledge citation card", () => {
  it("展示引用身份、相关性并可展开和收起原文", async () => {
    mountCard({
      document_id: "DOC-QUALITY-001",
      document_name: "坐标系统一与返工规范",
      document_version: "2.1",
      section: ["质量复核", "坐标系问题"],
      chunk_id: "CHUNK-001",
      chunk_ids: ["CHUNK-001", "CHUNK-002"],
      content: "发现坐标系不一致时必须返工。处理完成后重新提交复核。",
      relevance_score: 0.93,
    });

    expect(host?.textContent).toContain("坐标系统一与返工规范");
    expect(host?.textContent).toContain("版本 2.1");
    expect(host?.textContent).toContain("质量复核 / 坐标系问题");
    expect(host?.textContent).toContain("相关性 93%");
    expect(host?.textContent).toContain("CHUNK-001 · CHUNK-002");
    expect(host?.textContent).not.toContain("发现坐标系不一致时必须返工");

    click('[data-testid="toggle-citation-content"]');
    await nextTick();
    expect(host?.textContent).toContain("发现坐标系不一致时必须返工");
    expect(host?.textContent).toContain("收起引用原文");

    click('[data-testid="toggle-citation-content"]');
    await nextTick();
    expect(host?.textContent).not.toContain("发现坐标系不一致时必须返工");
    expect(host?.textContent).toContain("查看引用原文");
  });

  it("重排降级时不伪造相关性分数", () => {
    mountCard({
      document_id: "DOC-QUALITY-001",
      document_name: "坐标系统一与返工规范",
      document_version: "2.1",
      section: ["质量复核"],
      chunk_id: "CHUNK-001",
      chunk_ids: ["CHUNK-001"],
      content: "引用正文",
      relevance_score: null,
    });

    expect(host?.textContent).toContain("相关性未评分");
    expect(host?.textContent).not.toContain("相关性 0%");
  });
});

function mountCard(citation: KnowledgeCitation) {
  host = document.createElement("div");
  document.body.append(host);
  application = createApp(KnowledgeCitationCard, { citation });
  application.mount(host);
}

function click(selector: string) {
  const element = host?.querySelector<HTMLButtonElement>(selector);
  expect(element).toBeTruthy();
  element?.click();
}
