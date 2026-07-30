# M0.2 业务领域模型

## 1. 目标与边界

M0.2 为 Java `business-service` 建立订单生产链路的持久化模型，使业务事实能够由
Spring Data JPA 通过 PostgreSQL 查询。当前阶段只定义实体、DTO、状态枚举、数据库
约束和 Repository，不提供订单业务 HTTP 接口，也不写入 M0.3 的固定演示数据。

业务聚合以 `Order` 为根，关系如下：

```mermaid
erDiagram
    ORDER ||--o{ PRODUCTION_TASK : contains
    ORDER ||--o{ DELIVERY_RECORD : has
    PRODUCTION_TASK ||--o{ PRODUCTION_STEP : contains
    PRODUCTION_TASK ||--o{ QUALITY_ISSUE : finds
    PRODUCTION_TASK ||--o{ REWORK_TASK : schedules
    QUALITY_ISSUE ||--o{ REVIEW_RECORD : reviewed_by
    QUALITY_ISSUE o|--o{ REWORK_TASK : causes
```

概念架构中的 `QualityTask` 和 `DeliveryBatch` 是后续可扩展的业务容器。M0.2 任务清单
没有要求其实体、DTO 或数据库表，因此当前将 `QualityIssue` 直接归属
`ProductionTask`，将 `DeliveryRecord` 直接归属 `Order`。若后续出现一次质检包含多个
问题、一次交付批次包含多个记录的业务需求，应通过新的 Flyway 迁移增加容器和外键，
不能改写已经执行的 `V1` 迁移。

## 2. 聚合与数据流

创建完整业务链路时，由聚合根维护双向关系：

```text
Order.addTask
→ ProductionTask.addStep / addQualityIssue / addReworkTask
→ QualityIssue.addReviewRecord
→ Order.addDeliveryRecord
→ OrderRepository.save
→ JPA 级联持久化整个聚合
```

查询时既可以从 `OrderRepository` 沿只读集合导航，也可以通过各对象的 Repository
按业务 ID 独立定位。集合只暴露不可修改视图，调用方不能绕过聚合方法破坏归属关系。

## 3. 实体与数据库映射

| Java 实体 | 数据库表 | 主键 | 关键字段 | 上级对象 |
| --- | --- | --- | --- | --- |
| `Order` | `production_orders` | `order_id` | `product_type`, `status` | 聚合根 |
| `ProductionTask` | `production_tasks` | `task_id` | `status` | `order_id` |
| `ProductionStep` | `production_steps` | `step_id` | `step_name`, `sequence_number`, `status` | `task_id` |
| `QualityIssue` | `quality_issues` | `issue_id` | `issue_type`, `status`, `description` | `task_id` |
| `ReviewRecord` | `review_records` | `review_id` | `status`, `review_comment` | `issue_id` |
| `ReworkTask` | `rework_tasks` | `rework_task_id` | `status`, `reason` | `task_id`，可选 `source_issue_id` |
| `DeliveryRecord` | `delivery_records` | `delivery_id` | `status` | `order_id` |

所有主键均使用稳定、可读的业务 ID，例如 `ORDER-003` 和 `ISSUE-001`，不由数据库随机
生成。枚举通过 `EnumType.STRING` 保存，便于数据库、Java、Python 和前端共享同一词汇，
并避免枚举位置变化造成历史数据含义改变。

## 4. 关系、约束与删除规则

- `Order` 删除时级联删除其生产任务与交付记录。
- `ProductionTask` 删除时级联删除步骤、质检问题与返工任务。
- `QualityIssue` 删除时级联删除复核记录；被返工任务引用时，
  `source_issue_id` 置空，返工历史仍保留到所属生产任务删除为止。
- 同一生产任务内 `sequence_number` 唯一且必须大于零。
- 所有状态字段同时受到 Java 枚举和 PostgreSQL `CHECK` 约束保护。
- 实体构造器拒绝空业务 ID、空必填文本或空状态。
- 子对象一旦加入聚合，不允许重新挂接到另一个订单、任务或质检问题。
- 返工任务只能引用与自己属于同一生产任务的质检问题。

JPA 使用 `ddl-auto=validate`，启动时只校验映射，不自动改表；数据库结构只允许通过
Flyway 版本化迁移演进。

## 5. 跨服务状态词汇

状态值是未来 Java API、Python Tool 与前端契约的固定字符串，完整定义见
`docs/API_CONTRACT.md`。当前模型包含：

- `OrderStatus`
- `ProductionTaskStatus`（生产步骤和返工任务复用）
- `QualityIssueStatus`
- `ReviewStatus`
- `DeliveryStatus`

新增、删除或重命名状态属于接口与数据契约变更，必须同步 Java 枚举、Flyway 约束、
DTO、接口文档及跨服务契约测试。

## 6. ORDER-003 黄金链路

M0.2 Repository 集成测试在独立 PostgreSQL 容器中临时创建并查询：

```text
ORDER-003 (QUALITY_CHECKING)
→ TASK-003 (COMPLETED)
→ ISSUE-001 (COORDINATE_SYSTEM, OPEN)
→ REVIEW-003 (PENDING)
→ DELIVERY-003 (BLOCKED)
```

测试事务结束后数据回滚，因此不会冒充 M0.3 固定数据。M0.3 必须通过独立、可重置的
种子迁移或初始化机制真正创建 `ORDER-001`～`ORDER-005`。
