import { createPinia } from "pinia";
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchOrder, fetchOrderOverview } from "./api/businessApi";
import { requestRunHistory } from "./api/runHistoryClient";
import App from "./App.vue";
import { orderFixtures, overviewFixture } from "./test/fixtures";

vi.mock("./api/businessApi", () => ({
  fetchOrder: vi.fn(),
  fetchOrderOverview: vi.fn(),
}));
vi.mock("./api/runHistoryClient", () => ({
  requestRunHistory: vi.fn(),
  requestRunDetail: vi.fn(),
  requestRunSteps: vi.fn(),
}));

const mockedFetchOrder = vi.mocked(fetchOrder);
const mockedFetchOverview = vi.mocked(fetchOrderOverview);
const mockedRunHistory = vi.mocked(requestRunHistory);
let host: HTMLDivElement | undefined;

afterEach(() => {
  host?.remove();
  host = undefined;
  vi.resetAllMocks();
});

describe("minimal business page", () => {
  it("展示五个固定订单与 ORDER-003 的完整业务视图，并支持切换", async () => {
    mockedFetchOrder.mockImplementation(async (orderId) => ({
      data: orderFixtures.find((item) => item.orderId === orderId)!,
      traceId: `trace-${orderId}`,
    }));
    mockedFetchOverview.mockImplementation(async (orderId) => ({
      data: overviewFixture(orderId),
      traceId: `trace-overview-${orderId}`,
    }));

    host = document.createElement("div");
    document.body.append(host);
    createApp(App).use(createPinia()).mount(host);
    await settleUi();

    for (const order of orderFixtures) {
      expect(host.textContent).toContain(order.orderId);
    }
    expect(host.textContent).toContain("固定演示订单");
    expect(host.textContent).toContain("订单概览");
    expect(host.textContent).toContain("生产执行");
    expect(host.textContent).toContain("质量控制");
    expect(host.textContent).toContain("成果交付");
    expect(host.textContent).toContain("ISSUE-001");
    expect(host.textContent).toContain("COORDINATE_SYSTEM");
    expect(host.textContent).toContain("PENDING");
    expect(host.textContent).toContain("BLOCKED");

    const order005 = host.querySelector<HTMLButtonElement>(
      '[data-order-id="ORDER-005"]',
    );
    order005?.click();
    await settleUi();

    expect(host.querySelector("[data-current-order]")?.textContent).toContain("ORDER-005");
    expect(host.textContent).toContain("READY");
  });

  it("可以从主导航进入Run历史页面并返回业务全景", async () => {
    mockedFetchOrder.mockResolvedValue({ data: orderFixtures[0]!, traceId: "trace-order" });
    mockedFetchOverview.mockResolvedValue({
      data: overviewFixture("ORDER-001"),
      traceId: "trace-overview",
    });
    mockedRunHistory.mockResolvedValue({ items: [], page: 1, page_size: 10, total: 0 });

    host = document.createElement("div");
    document.body.append(host);
    createApp(App).use(createPinia()).mount(host);
    await settleUi();

    host.querySelector<HTMLButtonElement>('[data-testid="run-history-nav"]')?.click();
    await settleUi();
    expect(host.querySelector('[data-testid="run-history-page"]')).toBeTruthy();
    expect(host.textContent).toContain("还没有可查看的运行记录");

    host.querySelector<HTMLButtonElement>('[data-testid="business-view-nav"]')?.click();
    await settleUi();
    expect(host.textContent).toContain("订单业务全景");
  });
});

async function settleUi() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}
