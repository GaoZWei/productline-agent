# Java 业务契约词汇

## 1. 当前范围

本文固定 M0.2 领域模型向后续 Java API、Python Tool 和 Web Console 暴露的状态
字符串。M0.2 尚未定义订单查询或写入端点；HTTP 路径、请求响应结构、错误模型与
Trace ID 将在 M0.4～M0.6 中定义。

JSON 中状态字段必须使用下列大写字符串，不接受数字序号、显示文案或大小写变体。

## 2. 状态枚举

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

## 3. 固定业务断言

`ORDER-003` 的关键契约不得由模型推测或改写：

```text
production_status = COMPLETED
issue_type = COORDINATE_SYSTEM
issue_status = OPEN
review_status = PENDING
delivery_status = BLOCKED
```

这些事实共同支持诊断结论 `blocking_stage = QUALITY_REVIEW`。M0.4 设计响应 DTO 时应
直接复用本文件中的枚举值，不为前端或 Python 创建另一套状态字符串。

## 4. 演进规则

状态契约变化必须：

1. 先确认业务语义和兼容策略；
2. 增加新的 Flyway 迁移，不修改已发布迁移；
3. 同步 Java Enum、实体、DTO 和数据库约束；
4. 同步 Python Schema、前端类型和接口文档；
5. 增加旧值兼容或数据迁移测试，并验证 `ORDER-003` 黄金链路。
