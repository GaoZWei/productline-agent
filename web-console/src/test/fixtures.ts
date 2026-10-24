import type { Order, OrderOverview } from "../types/business";

export const orderFixtures: Order[] = [
  { orderId: "ORDER-001", productType: "DOM", status: "PRODUCING" },
  { orderId: "ORDER-002", productType: "DOM", status: "BLOCKED" },
  { orderId: "ORDER-003", productType: "DOM", status: "QUALITY_CHECKING" },
  { orderId: "ORDER-004", productType: "DOM", status: "REVIEWING" },
  { orderId: "ORDER-005", productType: "DOM", status: "READY_FOR_DELIVERY" },
  ...Array.from({ length: 25 }, (_, i) => ({
    orderId: `ORDER-${String(i + 6).padStart(3, "0")}`,
    productType: "DOM",
    status: ({
      6: "CREATED", 7: "PRODUCING", 8: "PRODUCING", 9: "BLOCKED",
      10: "PRODUCING", 11: "BLOCKED", 19: "REVIEWING", 20: "REVIEWING",
      21: "REVIEWING", 23: "REVIEWING", 24: "READY_FOR_DELIVERY",
      25: "BLOCKED", 26: "DELIVERING", 27: "DELIVERED", 28: "BLOCKED",
    } as Record<number, string>)[i + 6] ?? "QUALITY_CHECKING",
  })),
];

export function overviewFixture(orderId = "ORDER-003"): OrderOverview {
  const order = orderFixtures.find((item) => item.orderId === orderId) ?? orderFixtures[2]!;

  return {
    order,
    tasks: [
      {
        task: {
          taskId: orderId === "ORDER-003" ? "TASK-003" : `TASK-${orderId.slice(-3)}`,
          orderId,
          status:
            orderId === "ORDER-001" ? "RUNNING" : orderId === "ORDER-002" ? "FAILED" : "COMPLETED",
          version: 0,
        },
        steps: [
          {
            stepId: `STEP-${orderId.slice(-3)}-01`,
            taskId: orderId === "ORDER-003" ? "TASK-003" : `TASK-${orderId.slice(-3)}`,
            stepName: "DOM 生产处理",
            sequenceNumber: 1,
            status: "COMPLETED",
          },
        ],
        reworkTasks: [],
        qualityIssues:
          orderId === "ORDER-003"
            ? [
                {
                  issue: {
                    issueId: "ISSUE-001",
                    taskId: "TASK-003",
                    issueType: "COORDINATE_SYSTEM",
                    status: "OPEN",
                    description: "成果坐标系不符合规范",
                  },
                  reviews: [
                    {
                      reviewId: "REVIEW-003",
                      issueId: "ISSUE-001",
                      status: "PENDING",
                      reviewComment: null,
                    },
                  ],
                },
              ]
            : [],
      },
    ],
    deliveryRecords: [
      {
        deliveryId: `DELIVERY-${orderId.slice(-3)}`,
        orderId,
        status:
          orderId === "ORDER-005"
            ? "READY"
            : orderId === "ORDER-001" || orderId === "ORDER-002"
              ? "NOT_READY"
              : "BLOCKED",
      },
    ],
  };
}
