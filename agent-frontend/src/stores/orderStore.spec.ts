import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchOrders, fetchOrderOverview } from "../api/businessApi";
import { BusinessApiError } from "../api/businessClient";
import { orderFixtures, overviewFixture } from "../test/fixtures";
import { useOrderStore } from "./orderStore";

vi.mock("../api/businessApi", () => ({
  fetchOrders: vi.fn(),
  fetchOrderOverview: vi.fn(),
}));

const mockedFetchOrder = vi.mocked(fetchOrders);
const mockedFetchOverview = vi.mocked(fetchOrderOverview);

beforeEach(() => {
  setActivePinia(createPinia());
  vi.resetAllMocks();
});

describe("order store", () => {
  it("列表请求失败可重试，恢复后一次加载30单", async () => {
    const store = useOrderStore();
    mockedFetchOrder.mockRejectedValueOnce(new BusinessApiError({ code: "UPSTREAM_UNAVAILABLE", message: "暂不可用" }));
    await store.initialize();
    expect(store.error?.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(store.orders).toEqual([]);
    mockedFetchOrder.mockResolvedValueOnce({ data: { orders: orderFixtures }, traceId: "trace-list" });
    mockedFetchOverview.mockResolvedValueOnce(resultFor("ORDER-003"));
    await store.retry();
    expect(store.orders).toHaveLength(30);
    expect(store.error).toBeUndefined();
    expect(store.overview?.order.orderId).toBe("ORDER-003");
  });
  it("Agent目标加载失败保留原订单与业务快照", async () => {
    const store = useOrderStore();
    mockedFetchOverview.mockResolvedValueOnce(resultFor("ORDER-001"));
    await store.selectOrder("ORDER-001");
    mockedFetchOverview.mockRejectedValueOnce(new BusinessApiError({ code: "PERMISSION_DENIED", message: "无权限" }));
    await expect(store.switchOrderForAgent("ORDER-003")).rejects.toMatchObject({ code: "PERMISSION_DENIED" });
    expect(store.selectedOrderId).toBe("ORDER-001");
    expect(store.overview?.order.orderId).toBe("ORDER-001");
  });

  it("Agent切换丢弃被手动切页替代的迟到结果", async () => {
    let finish: ((value: ReturnType<typeof resultFor>) => void) | undefined;
    const store = useOrderStore();
    mockedFetchOverview.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = store.switchOrderForAgent("ORDER-003");
    const rejected = expect(pending).rejects.toMatchObject({ code: "REQUEST_SUPERSEDED" });
    mockedFetchOverview.mockResolvedValueOnce(resultFor("ORDER-005"));
    await store.selectOrder("ORDER-005");
    finish?.(resultFor("ORDER-003"));
    await rejected;
    expect(store.overview?.order.orderId).toBe("ORDER-005");
  });
  it("初始化时加载Java 订单列表并默认展示黄金场景 ORDER-003", async () => {
    mockedFetchOrder.mockResolvedValue({ data: { orders: orderFixtures }, traceId: "trace-list" });
    mockedFetchOverview.mockResolvedValue({
      data: overviewFixture(),
      traceId: "trace-overview-003",
    });

    const store = useOrderStore();
    await store.initialize();

    expect(store.orders.map((order) => order.orderId)).toEqual(orderFixtures.map((order) => order.orderId));
    expect(mockedFetchOrder).toHaveBeenCalledTimes(1);
    expect(store.orders).toHaveLength(30);
    expect(store.selectedOrderId).toBe("ORDER-003");
    expect(store.overview?.tasks[0]?.qualityIssues[0]?.issue.issueId).toBe("ISSUE-001");
  });

  it("快速切换时只接受最后一次请求的结果", async () => {
    const resolvers = new Map<string, (value: ReturnType<typeof resultFor>) => void>();
    mockedFetchOverview.mockImplementation(
      (orderId) =>
        new Promise((resolve) => {
          resolvers.set(orderId, resolve);
        }),
    );

    const store = useOrderStore();
    const first = store.selectOrder("ORDER-004");
    const second = store.selectOrder("ORDER-005");
    resolvers.get("ORDER-005")?.(resultFor("ORDER-005"));
    await second;
    resolvers.get("ORDER-004")?.(resultFor("ORDER-004"));
    await first;

    expect(store.selectedOrderId).toBe("ORDER-005");
    expect(store.overview?.order.orderId).toBe("ORDER-005");
  });
});

function resultFor(orderId: string) {
  return { data: overviewFixture(orderId), traceId: `trace-${orderId}` };
}
