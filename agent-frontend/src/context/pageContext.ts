import type { Order, ProductionTask, QualityIssue } from "../types/business";
import type { PageContext } from "../types/agent";

const CURRENT_SYSTEM = "production-system" as const;
/**
 * 订单详情页上下文
 */
export function createOrderDetailPageContext(order: Order, userRole: string): PageContext {
  return baseContext(order, userRole, {
    current_page: "order-detail",
    task_id: null,
    issue_id: null,
  });
}
/**
 * 任务详情页上下文
 */
export function createTaskDetailPageContext(
  order: Order,
  task: ProductionTask,
  userRole: string,
): PageContext {
  if (task.orderId !== order.orderId) {
    throw new Error("task does not belong to the current order");
  }
  return baseContext(order, userRole, {
    current_page: "task-detail",
    task_id: task.taskId,
    issue_id: null,
  });
}
/**
 * 质量问题上下文
 */
export function createQualityIssuePageContext(
  order: Order,
  task: ProductionTask,
  issue: QualityIssue,
  userRole: string,
): PageContext {
  if (task.orderId !== order.orderId || issue.taskId !== task.taskId) {
    throw new Error("quality issue does not belong to the current task and order");
  }
  return baseContext(order, userRole, {
    current_page: "quality-issue",
    task_id: task.taskId,
    issue_id: issue.issueId,
  });
}

/**
 * 基础上下文创建函数
 */
function baseContext(
  order: Order,
  userRole: string,
  resource: Pick<PageContext, "current_page" | "task_id" | "issue_id">,
): PageContext {
  return {
    current_system: CURRENT_SYSTEM,
    ...resource,
    order_id: order.orderId,
    batch_id: null,
    product_type: order.productType,
    satellite_type: null,
    user_role: userRole,
  };
}
