import { createPinia } from "pinia";
import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppComponent from "./App.vue";
import { fetchOrders, fetchOrderOverview } from "./api/businessApi";
import { fetchReworkDetail, fetchReworkHistory } from "./api/reworkClient";
import { useOrderStore } from "./stores/orderStore";
import { orderFixtures, overviewFixture } from "./test/fixtures";
import { detailFixture } from "./test/reworkFixtures";
import type { ApiResult, OrderOverview } from "./types/business";

vi.mock("./api/businessApi", () => ({ fetchOrders: vi.fn(), fetchOrderOverview: vi.fn() }));
vi.mock("./api/reworkClient", () => ({ fetchReworkDetail: vi.fn(), fetchReworkHistory: vi.fn() }));
let app: App | undefined;
let host: HTMLDivElement;
afterEach(() => { app?.unmount(); host?.remove(); vi.resetAllMocks(); });
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick(); }
async function mount() {
  vi.mocked(fetchOrders).mockResolvedValue({ data: { orders: orderFixtures }, traceId: "list" });
  const overview = overviewFixture("ORDER-003");
  const detail = detailFixture();
  overview.tasks[0]!.task.taskId = "TASK-030-A";
  overview.tasks[0]!.reworkTasks = [detail.reworkTask, { ...detail.reworkTask, reworkTaskId: "REWORK-A1" }];
  vi.mocked(fetchOrderOverview).mockResolvedValue({ data: overview, traceId: "overview" });
  vi.mocked(fetchReworkDetail).mockImplementation(async (_task, rework) => {
    const value = detailFixture(); value.reworkTask.reworkTaskId = rework;
    if (rework === "REWORK-A1") Object.assign(value, { roundNumber: 1, previousReworkTaskId: null, processing: null, inspection: null, review: null });
    return { data: value, traceId: "detail" };
  });
  vi.mocked(fetchReworkHistory).mockImplementation(async (_task, rework) => ({ data: { taskId: "TASK-030-A", records: [], nextCursor: null, reworkTaskId: rework }, traceId: "history" }));
  host = document.createElement("div"); document.body.append(host);
  const pinia = createPinia(); app = createApp(AppComponent).use(pinia); app.mount(host);
  await settle(); return useOrderStore(pinia);
}
describe("订单返工入口", () => {
  it("从任务下打开指定返工，两轮分别使用Java详情，不按编号猜轮次", async () => {
    await mount();
    expect(fetchReworkDetail).not.toHaveBeenCalled();
    host.querySelector<HTMLButtonElement>('[data-rework-id="REWORK-Z9"]')!.click(); await settle();
    expect(fetchReworkDetail).toHaveBeenLastCalledWith("TASK-030-A", "REWORK-Z9");
    expect(host.querySelector('[data-testid="rework-detail-panel"]')?.textContent).toContain("第 2 轮");
    host.querySelector<HTMLButtonElement>('[data-rework-id="REWORK-A1"]')!.click(); await settle();
    expect(host.querySelector('[data-testid="rework-detail-panel"]')?.textContent).toContain("第 1 轮");
    [...host.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "关闭详情")!.click(); await settle();
    expect(host.querySelector('[data-testid="rework-detail-panel"]')).toBeNull();
    expect(host.textContent).toContain("COMPLETED");
  });
  it("切单意图立即关闭详情，旧overview和迟到响应不能重新打开", async () => {
    const store = await mount();
    let resolveDetail!: (value: Awaited<ReturnType<typeof fetchReworkDetail>>) => void;
    vi.mocked(fetchReworkDetail).mockImplementation(() => new Promise(resolve => { resolveDetail = resolve; }));
    host.querySelector<HTMLButtonElement>('[data-rework-id="REWORK-Z9"]')!.click(); await settle();
    let resolveOrder!: (value: ApiResult<OrderOverview>) => void;
    vi.mocked(fetchOrderOverview).mockImplementation(() => new Promise(resolve => { resolveOrder = resolve; }));
    const switchOrder = store.selectOrder("ORDER-005"); await nextTick();
    expect(host.querySelector('[data-testid="rework-detail-panel"]')).toBeNull();
    host.querySelector<HTMLButtonElement>('[data-rework-id="REWORK-A1"]')!.click();
    expect(fetchReworkDetail).toHaveBeenCalledTimes(1);
    resolveDetail({ data: detailFixture(), traceId: "late" }); await settle();
    expect(fetchReworkHistory).not.toHaveBeenCalled();
    resolveOrder({ data: overviewFixture("ORDER-005"), traceId: "new" }); await switchOrder; await settle();
    expect(host.querySelector('[data-testid="rework-detail-panel"]')).toBeNull();
    expect(host.querySelector("[data-current-order]")?.textContent).toContain("ORDER-005");
  });
});
