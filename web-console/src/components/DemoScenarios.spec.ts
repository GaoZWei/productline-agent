import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import OrderSwitcher from "./OrderSwitcher.vue";
import TaskList from "./TaskList.vue";
import { orderFixtures, overviewFixture } from "../test/fixtures";

let app: App | undefined;
let host: HTMLDivElement | undefined;
afterEach(() => { app?.unmount(); host?.remove(); });
function mount(component: Parameters<typeof createApp>[0], props: Record<string, unknown>) {
  host = document.createElement("div");
  document.body.append(host);
  app = createApp(component, props);
  app.mount(host);
  return host;
}

describe("扩充演示场景", () => {
  it("搜索订单和场景名称，按分类筛选并切换任意 Java 返回订单", async () => {
    const selected: string[] = [];
    const root = mount(OrderSwitcher, { orders: orderFixtures, loading: false,
      selectedOrderId: "ORDER-030", onSelect: (id: string) => selected.push(id) });
    expect(root.querySelectorAll("[data-order-id]")).toHaveLength(30);
    expect(root.textContent).toContain("6 轮决策");
    const input = root.querySelector("input")!;
    input.value = "ORDER-030";
    input.dispatchEvent(new Event("input")); await nextTick();
    expect(root.querySelectorAll("[data-order-id]")).toHaveLength(1);
    root.querySelector<HTMLButtonElement>("[data-order-id]")!.click();
    expect(selected).toEqual(["ORDER-030"]);
    input.value = "云量"; input.dispatchEvent(new Event("input")); await nextTick();
    expect(root.querySelectorAll("[data-order-id]")).toHaveLength(2);
    const select = root.querySelector("select")!;
    select.value = "复核"; select.dispatchEvent(new Event("change")); await nextTick();
    expect(root.querySelectorAll("[data-order-id]")).toHaveLength(1);
    expect(root.textContent).toContain("ORDER-019");
    input.value = "不存在"; input.dispatchEvent(new Event("input")); await nextTick();
    expect(root.textContent).toContain("没有匹配的订单");
  });

  it("返工展示 Java 返回的来源、状态和原因；没有返工时不显示", () => {
    const taskA = overviewFixture().tasks[0]!;
    taskA.reworkTasks = [{ reworkTaskId: "REWORK-030-A-01", taskId: "TASK-030-A",
      sourceIssueId: "ISSUE-030-A-01", status: "RUNNING", reason: "修正坐标系" }];
    taskA.task.taskId = "TASK-030-A";
    const taskB = structuredClone(taskA);
    taskB.task.taskId = "TASK-030-B";
    taskB.reworkTasks = [{ reworkTaskId: "REWORK-030-B-01", taskId: "TASK-030-B",
      sourceIssueId: "ISSUE-030-B-01", status: "COMPLETED", reason: "已处理待复核" }];
    const root = mount(TaskList, { tasks: [taskA, taskB, overviewFixture("ORDER-005").tasks[0]!] });
    expect(root.querySelectorAll('[aria-label="已有返工任务"]')).toHaveLength(2);
    for (const value of ["TASK-030-A", "TASK-030-B", "REWORK-030-A-01", "ISSUE-030-B-01", "RUNNING", "COMPLETED", "已处理待复核"]) {
      expect(root.textContent).toContain(value);
    }
  });
});
