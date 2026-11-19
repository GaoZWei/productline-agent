import MockAdapter from "axios-mock-adapter";
import { createApp, h, nextTick, reactive, type App } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import ReworkDetailPanel from "./ReworkDetailPanel.vue";
import { businessHttpClient } from "../api/businessClient";
import { detailFixture, envelope, historyPage, inspectionFixture, processingFixture, reviewFixture, reworkPath } from "../test/reworkFixtures";

const mock = new MockAdapter(businessHttpClient);
let app: App | undefined;
let host: HTMLDivElement;
afterEach(() => { app?.unmount(); app = undefined; host?.remove(); mock.reset(); });
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick(); }
function setup(detail = detailFixture()) {
  mock.onGet(reworkPath).reply(200, envelope(detail));
  for (const kind of ["results", "inspections", "reviews"]) mock.onGet(`${reworkPath}/${kind}`).reply(200, envelope(historyPage()));
}
async function mount() {
  const props = reactive({ orderId: "ORDER-030", taskId: "TASK-030-A", reworkId: "REWORK-Z9" });
  host = document.createElement("div"); document.body.append(host);
  // 由父级响应式props驱动，覆盖切换与迟到响应，不修改子组件内部状态。
  app = createApp({ render: () => h(ReworkDetailPanel, props) }); app.mount(host);
  await settle(); return props;
}
function button(label: string, root: ParentNode = host) {
  const item = [...root.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === label);
  expect(item).toBeTruthy(); return item!;
}

describe("返工详情与历史", () => {
  it("展示第二轮真实绑定及Java允许动作，材料安全原样展示", async () => {
    setup(); await mount();
    expect(host.textContent).toContain("第 2 轮");
    expect(host.textContent).toContain("REWORK-A1");
    expect(host.textContent).toContain("需要再次处理");
    expect(host.textContent).toContain("001.0");
    expect(host.textContent).toContain("javascript:证据只作文本");
    expect(host.querySelector("a")).toBeNull();
    expect(host.querySelector('[aria-label="Java允许动作"]')?.textContent).toContain("创建下一轮返工");
    expect(host.querySelector('[aria-label="Java允许动作"]')?.textContent).not.toContain("开始返工");
    expect(host.textContent).toContain("本轮完成不等于最终验收");
    expect(mock.history.post).toHaveLength(0);
  });
  it("按序号加载多页，错误后重试原游标，不从历史通过重算当前结论", async () => {
    setup();
    let calls = 0;
    mock.onGet(`${reworkPath}/results`).reply(() => {
      calls++;
      if (calls === 1) return [200, envelope(historyPage([processingFixture(1)], "next/+=="))];
      if (calls === 2) return [503, { ...envelope(null), success: false, code: "UPSTREAM_ERROR", message: "busy" }];
      return [200, envelope(historyPage([processingFixture(2)]))];
    });
    mock.onGet(`${reworkPath}/reviews`).reply(200, envelope(historyPage([{ ...reviewFixture(), status: "APPROVED" }])));
    await mount();
    const section = host.querySelector('[data-history-kind="results"]')!;
    button("加载更多", section).click(); button("加载更多", section).click(); await settle();
    expect(section.textContent).toContain("UPSTREAM_ERROR");
    expect(section.querySelectorAll(".rework-record")).toHaveLength(1);
    button("重试本页", section).click(); await settle();
    expect(section.querySelectorAll(".rework-record")).toHaveLength(2);
    expect(mock.history.get.filter(r => r.url?.endsWith("/results")).map(r => r.params.cursor)).toEqual([undefined, "next/+==", "next/+=="]);
    expect(host.querySelector('[aria-label="Java当前材料"]')?.textContent).toContain("REWORK_REQUIRED");
  });
  it.each(["overlap", "cycle", "wrongRound"])("历史异常%s不拼入坏记录", async change => {
    setup();
    const kind = change === "wrongRound" ? "inspections" : "results";
    const first = kind === "results" ? processingFixture(1) : inspectionFixture(1);
    const second = kind === "results" ? processingFixture(change === "overlap" ? 1 : 2) : { ...inspectionFixture(2), roundNumber: 1 };
    mock.onGet(`${reworkPath}/${kind}`).reply(config => [200, envelope(config.params.cursor === undefined
      ? historyPage([first], "next") : historyPage([second], change === "cycle" ? "next" : null))]);
    await mount();
    const section = host.querySelector(`[data-history-kind="${kind}"]`)!;
    button("加载更多", section).click(); await settle();
    expect(section.textContent).toContain("RESPONSE_VALIDATION_ERROR");
    expect(section.querySelectorAll(".rework-record")).toHaveLength(1);
  });
  it("存量记录明确缺证据，空历史不生成通过或第一轮", async () => {
    const value = detailFixture();
    Object.assign(value, { roundNumber: null, previousReworkTaskId: null, processing: null, inspection: null, review: null, allowedActions: [] });
    setup(value); await mount();
    expect(host.textContent).toContain("存量记录，未登记轮次");
    expect(host.textContent).toContain("存量记录缺少处理证据");
    expect(host.textContent).not.toContain("第 1 轮");
    expect(host.textContent).not.toContain("APPROVED");
  });
  it("切换返工和卸载隔离迟到详情及历史", async () => {
    setup(); let resolveOld!: (value: [number, unknown]) => void;
    mock.onGet(`${reworkPath}/results`).reply(() => new Promise(resolve => { resolveOld = resolve; }));
    const props = await mount();
    const next = detailFixture(); next.reworkTask.reworkTaskId = "REWORK-A1";
    Object.assign(next, { roundNumber: 1, previousReworkTaskId: null, processing: null, inspection: null, review: null, allowedActions: ["START_REWORK"] });
    const path = reworkPath.replace("REWORK-Z9", "REWORK-A1");
    mock.onGet(path).reply(200, envelope(next));
    for (const kind of ["results", "inspections", "reviews"]) mock.onGet(`${path}/${kind}`).reply(200, envelope({ ...historyPage(), reworkTaskId: "REWORK-A1" }));
    props.reworkId = "REWORK-A1"; await settle();
    resolveOld([200, envelope(historyPage([processingFixture(9)]))]); await settle();
    expect(host.textContent).toContain("第 1 轮");
    expect(host.textContent).not.toContain("处理修订 9");
    let resolveDetail!: (value: [number, unknown]) => void;
    mock.onGet(reworkPath).reply(() => new Promise(resolve => { resolveDetail = resolve; }));
    props.reworkId = "REWORK-Z9"; await settle();
    app?.unmount(); app = undefined;
    resolveDetail([200, envelope(detailFixture())]); await settle();
    expect(host.textContent).toBe("");
  });
  it("详情失败不展示旧材料，刷新后重新读取历史首屏", async () => {
    setup(); await mount();
    let reads = 0;
    mock.onGet(reworkPath).reply(() => ++reads === 1
      ? [403, { ...envelope(null, "denied-trace"), success: false, code: "PERMISSION_DENIED", message: "denied" }]
      : [200, envelope(detailFixture())]);
    button("刷新详情").click(); await settle();
    expect(host.textContent).toContain("PERMISSION_DENIED");
    expect(host.textContent).toContain("denied-trace");
    expect(host.querySelector('[aria-label="Java当前材料"]')).toBeNull();
    button("刷新详情").click(); await settle();
    expect(host.querySelectorAll(".rework-history")).toHaveLength(3);
    expect(mock.history.get.filter(r => r.url?.endsWith("/results"))).toHaveLength(2);
  });
});
