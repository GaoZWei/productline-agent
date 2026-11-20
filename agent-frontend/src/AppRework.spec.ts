import { createPinia } from "pinia";
import { createApp, nextTick, type App, type PropType } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppComponent from "./App.vue";
import { fetchOrders, fetchOrderOverview } from "./api/businessApi";
import { BusinessApiError } from "./api/businessClient";
import { confirmReworkAction, previewReworkAction } from "./api/reworkActionClient";
import { fetchReworkDetail, fetchReworkHistory } from "./api/reworkClient";
import type AgentWorkspaceDrawer from "./components/AgentWorkspaceDrawer.vue";
import { useOrderStore } from "./stores/orderStore";
import { orderFixtures, overviewFixture } from "./test/fixtures";
import { detailFixture } from "./test/reworkFixtures";
import type { ApiResult, OrderOverview } from "./types/business";

vi.mock("./api/businessApi", () => ({ fetchOrders: vi.fn(), fetchOrderOverview: vi.fn() }));
vi.mock("./api/reworkActionClient", async importOriginal => ({
  ...await importOriginal<typeof import("./api/reworkActionClient")>(),
  confirmReworkAction: vi.fn(),
  previewReworkAction: vi.fn(),
}));
vi.mock("./api/reworkClient", () => ({ fetchReworkDetail: vi.fn(), fetchReworkHistory: vi.fn() }));
type OpenGuidedRework = NonNullable<InstanceType<typeof AgentWorkspaceDrawer>["$props"]["openRework"]>;
let openGuidedRework: OpenGuidedRework;
vi.mock("./components/AgentWorkspaceDrawer.vue", async () => {
  const { defineComponent } = await import("vue");
  return { default: defineComponent({
    props: { openRework: { type: Function as PropType<OpenGuidedRework>, required: true } },
    setup(props) {
      openGuidedRework = props.openRework;
      return () => null;
    },
  }) };
});
let app: App | undefined;
let host: HTMLDivElement;
afterEach(() => { app?.unmount(); host?.remove(); vi.resetAllMocks(); });
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick(); }
function buttonWithText(text: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.trim() === text);
  expect(button).toBeDefined();
  return button!;
}
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

  it("Agent定位到总览尚未包含的新返工时先重读订单再打开", async () => {
    await mount();
    const target = { task_id: "TASK-030-A", rework_task_id: "REWORK-NEW" };
    const refreshed = overviewFixture("ORDER-003");
    refreshed.tasks[0]!.task.taskId = target.task_id;
    refreshed.tasks[0]!.reworkTasks = [{ ...detailFixture().reworkTask, reworkTaskId: target.rework_task_id }];
    vi.mocked(fetchOrderOverview).mockResolvedValueOnce({ data: refreshed, traceId: "refreshed" });

    await expect(openGuidedRework("ORDER-003", target, null)).resolves.toBe(true);
    await settle();
    expect(fetchOrderOverview).toHaveBeenCalledTimes(2);
    expect(fetchOrderOverview).toHaveBeenLastCalledWith("ORDER-003");
    expect(fetchReworkDetail).toHaveBeenCalledTimes(1);
    expect(fetchReworkDetail).toHaveBeenCalledWith(target.task_id, target.rework_task_id);
    expect(host.querySelector('[data-testid="rework-detail-panel"]')?.textContent).toContain("REWORK-NEW");
  });

  it("Agent刷新总览后目标仍缺失时不打开返工详情", async () => {
    await mount();
    const target = { task_id: "TASK-030-A", rework_task_id: "REWORK-UNKNOWN" };

    await expect(openGuidedRework("ORDER-003", target, null)).rejects.toMatchObject({ code: "RESOURCE_NOT_FOUND" });
    expect(fetchOrderOverview).toHaveBeenCalledTimes(2);
    expect(fetchReworkDetail).not.toHaveBeenCalled();
  });

  it("Agent重读总览期间切单时丢弃原订单的打开请求", async () => {
    const store = await mount();
    let resolveOriginal!: (value: ApiResult<OrderOverview>) => void;
    vi.mocked(fetchOrderOverview).mockImplementationOnce(() => new Promise(resolve => { resolveOriginal = resolve; }));
    const target = { task_id: "TASK-030-A", rework_task_id: "REWORK-NEW" };
    const opening = openGuidedRework("ORDER-003", target, null);
    vi.mocked(fetchOrderOverview).mockResolvedValueOnce({ data: overviewFixture("ORDER-005"), traceId: "changed" });
    await store.selectOrder("ORDER-005");
    resolveOriginal({ data: overviewFixture("ORDER-003"), traceId: "late" });

    await expect(opening).resolves.toBe(false);
    await settle();
    expect(fetchReworkDetail).not.toHaveBeenCalled();
    expect(host.querySelector('[data-testid="rework-detail-panel"]')).toBeNull();
    expect(store.selectedOrderId).toBe("ORDER-005");
  });

  it("下一轮写入成功后总览刷新失败时保留回执，重试成功后可打开下一轮", async () => {
    await mount();
    const priorDetail = detailFixture();
    vi.mocked(previewReworkAction).mockResolvedValue({
      runId: "run-next", approvalId: "approval-next", nextRound: true,
      expiresAt: "2026-11-20T11:00:00Z", taskVersion: priorDetail.taskVersion, roundNumber: 2,
      issueId: "ISSUE-030-A", reworkStatusAfter: "PENDING", issueStatusAfter: "OPEN",
      deliveryEffect: "NONE", previousReview: priorDetail.review!,
    });
    vi.mocked(confirmReworkAction).mockResolvedValue({
      outcome: "SUCCEEDED", operationId: "OP-NEXT", nextReworkId: "REWORK-NEXT",
    });
    const unavailable = new BusinessApiError({
      code: "NETWORK_ERROR", message: "暂时无法读取订单总览", retryable: true,
    });
    vi.mocked(fetchOrderOverview).mockRejectedValueOnce(unavailable).mockRejectedValueOnce(unavailable);

    host.querySelector<HTMLButtonElement>('[data-rework-id="REWORK-Z9"]')!.click();
    await settle();
    buttonWithText("创建下一轮返工").click();
    await settle();
    const reason = host.querySelector<HTMLTextAreaElement>(".rework-action-form textarea")!;
    reason.value = "补查产品范围";
    reason.dispatchEvent(new Event("input", { bubbles: true }));
    buttonWithText("预览操作").click();
    await settle();
    buttonWithText("确认并执行").click();
    await settle();

    expect(host.textContent).toContain("操作已登记，回执 OP-NEXT");
    expect(host.textContent).toContain("订单总览刷新失败，仍显示上次读取的内容");
    expect(buttonWithText("查看下一轮 REWORK-NEXT").disabled).toBe(true);
    buttonWithText("重新加载").click();
    await settle();
    expect(host.textContent).toContain("操作已登记，回执 OP-NEXT");

    const refreshed = overviewFixture("ORDER-003");
    refreshed.tasks[0]!.task.taskId = "TASK-030-A";
    refreshed.tasks[0]!.reworkTasks = [priorDetail.reworkTask, {
      ...priorDetail.reworkTask, reworkTaskId: "REWORK-NEXT", status: "PENDING",
    }];
    vi.mocked(fetchOrderOverview).mockResolvedValueOnce({ data: refreshed, traceId: "refreshed" });
    buttonWithText("重新加载").click();
    await settle();
    expect(buttonWithText("查看下一轮 REWORK-NEXT").disabled).toBe(false);
    buttonWithText("查看下一轮 REWORK-NEXT").click();
    await settle();
    expect(fetchReworkDetail).toHaveBeenLastCalledWith("TASK-030-A", "REWORK-NEXT");
    expect(confirmReworkAction).toHaveBeenCalledTimes(1);
  });
});
