# M0.3 固定业务数据

## 1. 使用范围

本文件描述 Java 业务服务数据库中的确定性演示数据。Flyway 在首次创建数据库时按
`V1 → V2` 顺序建表并写入数据；M0.4 Java 查询接口和 M1 Python Tool 必须把这里的
ID、状态和值作为契约测试输入，不能由模型补造或随机化。

M0.3 只提供数据库事实，尚未提供业务 HTTP 查询接口。

## 2. 固定场景

| 订单 | 订单状态 | 生产任务 / 状态 | 质检问题 / 状态 | 复核状态 | 交付状态 |
| --- | --- | --- | --- | --- | --- |
| `ORDER-001` | `PRODUCING` | `TASK-001` / `RUNNING` | 无 | 无 | `NOT_READY` |
| `ORDER-002` | `BLOCKED` | `TASK-002` / `FAILED` | 无 | 无 | `NOT_READY` |
| `ORDER-003` | `QUALITY_CHECKING` | `TASK-003` / `COMPLETED` | `ISSUE-001` / `OPEN` | `PENDING` | `BLOCKED` |
| `ORDER-004` | `REVIEWING` | `TASK-004` / `COMPLETED` | `ISSUE-002` / `RESOLVED` | `PENDING` | `BLOCKED` |
| `ORDER-005` | `READY_FOR_DELIVERY` | `TASK-005` / `COMPLETED` | `ISSUE-003` / `CLOSED` | `APPROVED` | `READY` |

每个订单固定有一个同序号交付记录 `DELIVERY-001`～`DELIVERY-005`。每个任务固定有
一个同序号生产步骤；`TASK-002` 的 `STEP-002-01` 名称为“影像预处理”，状态为
`FAILED`，供生产失败诊断使用。

所有五个订单的 `product_type` 暂统一为 `DOM`，因为当前里程碑不测试产品类型分支。
如后续确认不同产品类型场景，应新增 Flyway 数据迁移和契约测试，不能改写已应用的
V2。

## 3. ORDER-003 黄金链路

```text
ORDER-003 (QUALITY_CHECKING)
→ TASK-003 (COMPLETED)
→ ISSUE-001 (COORDINATE_SYSTEM, OPEN)
→ REVIEW-003 (PENDING)
→ DELIVERY-003 (BLOCKED)
```

该场景没有预置返工任务。这是有意设计：后续诊断建议是“创建坐标系处理返工任务”，
若提前写入返工任务，会使建议与业务事实冲突。

对接 Java API 或 Python Tool 时，应至少断言：

```text
blocking_stage = QUALITY_REVIEW
根因 = 未关闭的坐标系质量问题 + 质检复核尚未完成
建议 = 创建坐标系处理返工任务 + 处理后重新提交复核
```

## 4. 数据规模和一致性

重置后的固定规模为：

```text
orders = 5
tasks = 5
steps = 5
quality_issues = 3
review_records = 3
rework_tasks = 0
delivery_records = 5
```

业务状态校验器会判定以下组合非法：

1. 生产任务未完成，但订单已经 `DELIVERED`；
2. 存在 `OPEN` 质检问题，但交付状态为 `READY`；
3. 复核状态为 `PENDING`，但订单已经 `DELIVERED`。

M0.3 的校验器只返回稳定违规代码，不自动修改数据，也尚未接入写接口；M0.5 实现写
操作时需要在事务提交前调用，并把违规代码映射到统一错误响应。

## 5. 重置与验收

```bash
make reset-demo
make test-business-data
```

`make reset-demo` 会停止本项目 Compose 服务、删除本项目 PostgreSQL 数据卷、重新
构建并启动 PostgreSQL 和 Java 服务，再等待 Flyway V2 完成。该命令具有破坏性，只
应用于本地演示数据。

成功输出包含固定订单数和数据快照，例如：

```text
M0.3 demo data reset complete.
orders=5
snapshot=d57e54c32e4ef26eb01c76a8ed97a0ce
```

在代码和环境不变时，多次重置的快照必须相同。
