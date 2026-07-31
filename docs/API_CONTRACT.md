# Java 业务契约词汇

## 1. 当前范围

本文固定 Java API 向后续 Python Tool 和 Web Console 暴露的查询路径、响应结构与
状态字符串。M0.4 已实现 8 个只读端点；写接口属于 M0.5，统一错误模型与 Trace ID
属于 M0.6。

JSON 中状态字段必须使用下列大写字符串，不接受数字序号、显示文案或大小写变体。

## 2. 只读查询端点

| 任务 | 方法与路径 | 正常响应 | 关键边界 |
| --- | --- | --- | --- |
| T025 | `GET /api/orders/{orderId}` | `OrderDto` | 未知订单 `404` |
| T026 | `GET /api/orders/{orderId}/tasks` | `OrderTasksResponse` | 无任务为 `tasks: []`；未知订单 `404` |
| T027 | `GET /api/tasks/{taskId}` | `ProductionTaskDto` | 未知任务 `404` |
| T028 | `GET /api/tasks/{taskId}/progress` | `ProductionProgressResponse` | 步骤按 `sequenceNumber` 升序 |
| T029 | `GET /api/tasks/{taskId}/quality-issues?status=OPEN` | `QualityIssueListResponse` | 可省略过滤；非法枚举 `400` |
| T030 | `GET /api/tasks/{taskId}/review` | `ReviewResultResponse` | 无复核为 `reviews: []` |
| T031 | `GET /api/orders/{orderId}/delivery-status` | `DeliveryStatusResponse` | 保留交付记录数组，不猜测“最新记录” |
| T032 | `GET /api/orders/{orderId}/overview` | `OrderOverviewResponse` | 聚合订单、任务、步骤、问题、复核和交付 |

详情对象直接返回 DTO；集合端点返回父资源 ID 和稳定数组，避免调用方把“父资源存在但
暂无关联记录”误判为接口失败。例如：

```json
{
  "taskId": "TASK-003",
  "issues": [
    {
      "issueId": "ISSUE-001",
      "taskId": "TASK-003",
      "issueType": "COORDINATE_SYSTEM",
      "status": "OPEN",
      "description": "成果坐标系与生产规范要求不一致，问题尚未处理。"
    }
  ]
}
```

`ORDER-003` 总览响应结构如下：

```json
{
  "order": {
    "orderId": "ORDER-003",
    "productType": "DOM",
    "status": "QUALITY_CHECKING"
  },
  "tasks": [
    {
      "task": {
        "taskId": "TASK-003",
        "orderId": "ORDER-003",
        "status": "COMPLETED"
      },
      "steps": [
        {
          "stepId": "STEP-003-01",
          "taskId": "TASK-003",
          "stepName": "DOM 生产处理",
          "sequenceNumber": 1,
          "status": "COMPLETED"
        }
      ],
      "qualityIssues": [
        {
          "issue": {
            "issueId": "ISSUE-001",
            "taskId": "TASK-003",
            "issueType": "COORDINATE_SYSTEM",
            "status": "OPEN",
            "description": "成果坐标系与生产规范要求不一致，问题尚未处理。"
          },
          "reviews": [
            {
              "reviewId": "REVIEW-003",
              "issueId": "ISSUE-001",
              "status": "PENDING",
              "reviewComment": null
            }
          ]
        }
      ]
    }
  ],
  "deliveryRecords": [
    {
      "deliveryId": "DELIVERY-003",
      "orderId": "ORDER-003",
      "status": "BLOCKED"
    }
  ]
}
```

集合顺序是确定的：任务、问题、复核和交付按业务 ID 升序，生产步骤按
`sequenceNumber` 升序。

聚合端点保留给页面展示、排障和契约核对。M1 的 Agent Tool 仍应优先映射多个细粒度
端点，让调用路径、证据来源和失败步骤可观测，而不是只暴露一个“大而全” Tool。

M0.4 的错误契约只保证 HTTP 状态：未知父资源为 `404`，非法状态过滤为 `400`。错误
响应体、业务错误码和 Trace ID 尚未稳定，调用方不得依赖 Spring 默认错误 JSON；
这些能力将在 M0.6 统一。

## 3. 状态枚举

### OrderStatus

| 值 | 含义 |
| --- | --- |
| `CREATED` | 订单已创建，尚未进入生产 |
| `PRODUCING` | 正在生产 |
| `QUALITY_CHECKING` | 正在质检或存在待处理质检事项 |
| `REVIEWING` | 正在复核 |
| `READY_FOR_DELIVERY` | 已满足交付条件 |
| `DELIVERING` | 正在交付 |
| `DELIVERED` | 已完成交付 |
| `BLOCKED` | 订单被阻塞 |

### ProductionTaskStatus

`ProductionTask`、`ProductionStep` 和 `ReworkTask` 共用：

| 值 | 含义 |
| --- | --- |
| `PENDING` | 待执行 |
| `RUNNING` | 执行中 |
| `COMPLETED` | 已完成 |
| `FAILED` | 执行失败 |
| `BLOCKED` | 被前置条件或问题阻塞 |

### QualityIssueStatus

| 值 | 含义 |
| --- | --- |
| `OPEN` | 问题已发现且未开始处理 |
| `PROCESSING` | 问题处理中 |
| `RESOLVED` | 已处理，等待或允许复核 |
| `CLOSED` | 已复核关闭 |

### ReviewStatus

| 值 | 含义 |
| --- | --- |
| `PENDING` | 待复核 |
| `APPROVED` | 复核通过 |
| `REJECTED` | 复核拒绝 |
| `REWORK_REQUIRED` | 需要返工 |

### DeliveryStatus

| 值 | 含义 |
| --- | --- |
| `NOT_READY` | 尚未满足交付条件 |
| `READY` | 可交付 |
| `DELIVERING` | 交付处理中 |
| `DELIVERED` | 交付完成 |
| `FAILED` | 交付失败 |
| `BLOCKED` | 被质量、复核或其他业务条件阻塞 |

## 4. 固定业务断言

`ORDER-003` 的关键契约不得由模型推测或改写：

```text
production_status = COMPLETED
issue_type = COORDINATE_SYSTEM
issue_status = OPEN
review_status = PENDING
delivery_status = BLOCKED
```

这些事实共同支持诊断结论 `blocking_stage = QUALITY_REVIEW`。M0.4 响应 DTO 已直接
复用本文件中的枚举值，不为前端或 Python 创建另一套状态字符串。五组固定数据的
完整 ID 映射见 [`DEMO_DATA.md`](DEMO_DATA.md)。

## 5. 演进规则

状态契约变化必须：

1. 先确认业务语义和兼容策略；
2. 增加新的 Flyway 迁移，不修改已发布迁移；
3. 同步 Java Enum、实体、DTO 和数据库约束；
4. 同步 Python Schema、前端类型和接口文档；
5. 增加旧值兼容或数据迁移测试，并验证 `ORDER-003` 黄金链路。
