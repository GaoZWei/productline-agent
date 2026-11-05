import { describe, expect, it } from "vitest";

import { overviewFixture } from "../test/fixtures";
import {
  createOrderDetailPageContext,
  createQualityIssuePageContext,
  createTaskDetailPageContext,
} from "./pageContext";

const overview = overviewFixture();
const order = overview.order;
const task = overview.tasks[0]!.task;
const issue = overview.tasks[0]!.qualityIssues[0]!.issue;

describe("page context adapters", () => {
  it("从订单详情生成不包含下级资源的上下文", () => {
    expect(createOrderDetailPageContext(order, "REVIEWER")).toEqual({
      current_system: "production-system",
      current_page: "order-detail",
      order_id: "ORDER-003",
      task_id: null,
      issue_id: null,
      batch_id: null,
      product_type: "DOM",
      satellite_type: null,
      user_role: "REVIEWER",
    });
  });

  it("从任务和质检对象生成带完整父级链路的上下文", () => {
    expect(createTaskDetailPageContext(order, task, "REVIEWER")).toMatchObject({
      current_page: "task-detail",
      order_id: "ORDER-003",
      task_id: "TASK-003",
      issue_id: null,
    });
    expect(createQualityIssuePageContext(order, task, issue, "REVIEWER")).toMatchObject({
      current_page: "quality-issue",
      order_id: "ORDER-003",
      task_id: "TASK-003",
      issue_id: "ISSUE-001",
    });
  });

  it("拒绝在前端组装归属关系矛盾的上下文", () => {
    expect(() =>
      createTaskDetailPageContext(order, { ...task, orderId: "ORDER-004" }, "REVIEWER"),
    ).toThrow("task does not belong");
    expect(() =>
      createQualityIssuePageContext(
        order,
        task,
        { ...issue, taskId: "TASK-004" },
        "REVIEWER",
      ),
    ).toThrow("quality issue does not belong");
  });
});
