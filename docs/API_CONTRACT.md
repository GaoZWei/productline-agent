# Java 业务契约词汇

## 1. 当前范围

本文固定 Java API 向后续 Python Tool 和 Web Console 暴露的查询/写入路径、响应结构与
状态字符串。M0.4 已实现 8 个只读端点，M0.5 已实现提交复核和创建返工两个写端点，
M0.6 已增加统一响应、错误码和 Trace ID，M0.7 已增加仅供开发验证的只读故障模拟。

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

业务 DTO 统一放在响应的 `data` 字段中；集合数据仍包含父资源 ID 和稳定数组，避免调用
方把“父资源存在但暂无关联记录”误判为接口失败。例如：

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "success",
  "data": {
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
  },
  "trace_id": "trace-<uuid>",
  "retryable": false
}
```

`ORDER-003` 总览响应结构如下：

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "success",
  "data": {
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
          "status": "COMPLETED",
          "version": 0
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
  },
  "trace_id": "trace-<uuid>",
  "retryable": false
}
```

集合顺序是确定的：任务、问题、复核和交付按业务 ID 升序，生产步骤按
`sequenceNumber` 升序。

聚合端点保留给页面展示、排障和契约核对。M1 的 Agent Tool 仍应优先映射多个细粒度
端点，让调用路径、证据来源和失败步骤可观测，而不是只暴露一个“大而全” Tool。

M0.6 后调用方必须先校验统一信封，再校验 `data` 中的具体 DTO；不能继续把根节点直接
当作订单、任务或问题对象。

## 3. M0.5 写入端点

| 任务 | 方法与路径 | 请求体 | 成功响应 |
| --- | --- | --- | --- |
| T033 | `POST /api/tasks/{taskId}/review` | `issueId`、`status`、`reviewComment`、`expectedVersion` | `review` 与递增后的 `taskVersion` |
| T034 | `POST /api/tasks/{taskId}/rework` | `sourceIssueId`、`reason`、`expectedVersion` | `reworkTask` 与递增后的 `taskVersion` |

两个写接口都要求以下 Header：

```text
X-User-Id: reviewer-001
X-User-Role: REVIEWER
Idempotency-Key: 调用方为一次业务动作生成的稳定唯一值
```

提交 `ORDER-003` 复核结果的最小请求和响应示例：

```json
{
  "issueId": "ISSUE-001",
  "status": "REWORK_REQUIRED",
  "reviewComment": "需要完成坐标系返工。",
  "expectedVersion": 0
}
```

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "success",
  "data": {
    "review": {
      "reviewId": "REVIEW-WRITE-<uuid>",
      "issueId": "ISSUE-001",
      "status": "REWORK_REQUIRED",
      "reviewComment": "需要完成坐标系返工。"
    },
    "taskVersion": 1
  },
  "trace_id": "trace-<uuid>",
  "retryable": false
}
```

写入约束：

- 只有 `REVIEWER` 角色可调用；缺失用户身份返回 `401`，身份存在但角色不足返回 `403`。
- 生产任务必须为 `COMPLETED`，问题必须属于路径中的任务；不存在的资源返回 `404`，
  状态或归属冲突返回 `409`。
- `PENDING` 不能作为新复核结论，`CLOSED` 问题不能重复复核；只有 `RESOLVED` 问题
  能提交 `APPROVED`。复核接口只追加复核记录，不隐式修改问题、订单或交付状态。
- 创建返工时来源问题不能为 `CLOSED`；同一任务与来源问题已有 `PENDING`、`RUNNING`
  或 `BLOCKED` 返工时返回 `409`。新返工任务初始状态固定为 `PENDING`。
- 相同用户以相同幂等键和完全相同的请求重试，返回首次成功结果且不再次写入；同一键
  更换操作或请求内容返回 `409`。
- 客户端从任务查询读取 `version` 并作为 `expectedVersion` 提交。数据库只在当前版本
  仍匹配时原子递增；并发写同一版本时仅一个成功，其余返回 `409`。
- 每次成功写入在同一事务中保存操作类型、操作者、目标、幂等键哈希和关键业务字段的
  前后状态；重放幂等请求不重复生成日志。

当前 `X-User-Id`/`X-User-Role` 是 M0.5 的最小身份上下文，不等同于真实认证令牌。
Agent Approval、Python 写 Tool 和确认用户校验尚未实现。

## 4. M0.6 统一响应、错误与 Trace ID

成功和失败都固定为：

```json
{
  "success": false,
  "code": "BUSINESS_CONFLICT",
  "message": "task version conflict: expected 0 but was 1",
  "data": null,
  "trace_id": "trace-<uuid>",
  "retryable": false
}
```

| HTTP | `code` | 典型来源 | `retryable` |
| --- | --- | --- | --- |
| `200` | `SUCCESS` | 查询或写入成功 | `false` |
| `400` | `PARAM_VALIDATION_ERROR` | Bean Validation、非法枚举、畸形 JSON、缺少业务参数 | `false` |
| `401` | `PERMISSION_DENIED` | 缺少已认证用户身份 | `false` |
| `403` | `PERMISSION_DENIED` | 用户存在但角色不足 | `false` |
| `404` | `RESOURCE_NOT_FOUND` | 订单、任务或问题不存在 | `false` |
| `409` | `BUSINESS_CONFLICT` | 状态、版本、幂等或重复创建冲突 | `false` |
| `500` | `INTERNAL_SERVER_ERROR` | 未预期系统异常 | `false` |

401 和 403 复用后续 Python Tool 已规划的 `PERMISSION_DENIED`，由 HTTP 状态区分认证缺失
和授权不足。通用 500 不回传内部异常详情，也不默认标记可重试：尤其写请求发生 500 时
结果可能未知，后续 Tool 不得绕过幂等和版本策略自动重试。

Trace ID 规则：

- 调用方可通过 `X-Trace-Id` 透传由字母、数字、点、下划线、冒号或短横线组成的 1～128
  位标识。
- Header 缺失或不符合安全格式时，Java 生成 `trace-<uuid>`，避免超长值或换行等内容
  污染日志。
- 响应 Header `X-Trace-Id` 和响应体 `trace_id` 始终一致；服务日志 MDC 同步保存该值。
- 本统一信封适用于 `/api` 业务接口；Actuator `/health` 保持探针原始结构，但仍返回
  `X-Trace-Id` Header。

## 5. M0.7 开发故障模拟

故障模拟用于后续 Python HTTP Client 和 Tool 错误映射测试，不是业务能力。应用配置
`demo.faults.enabled` 默认为 `false`；Docker Compose 本地开发通过
`DEMO_FAULTS_ENABLED=true` 显式开启。

只有同时满足“功能已开启、HTTP 方法为 GET、路径为 `/api/**`”时才读取模拟 Header。
POST 等写请求始终忽略这些 Header，避免演练逻辑改变写入结果。

| Header | Java 行为 | 后续 Tool 预期验证 |
| --- | --- | --- |
| `X-Demo-Delay-Ms: <0..max>` | 在 Controller 前延迟指定毫秒后正常响应 | 耗时记录、客户端总超时预算 |
| `X-Demo-Fault: timeout` | 默认等待 5000 毫秒后继续正常响应 | `httpx.Timeout` → `TOOL_TIMEOUT` |
| `X-Demo-Fault: server-error` | 经统一异常处理返回 `500/INTERNAL_SERVER_ERROR` | 上游异常映射且不泄露详情 |
| `X-Demo-Fault: invalid-response` | 返回 HTTP 200 和可解析 JSON，但故意不包含 `data` | Pydantic → `RESPONSE_VALIDATION_ERROR` |
| `X-Demo-Fault: permission-denied` | 返回 `403/PERMISSION_DENIED` | 权限错误不可重试 |

未知 `X-Demo-Fault` 或非数字、负数、超过上限的延迟返回
`400/PARAM_VALIDATION_ERROR`。`invalid-response` 仍返回与请求一致的 Trace ID，便于证明
“HTTP 成功不等于 Tool Schema 合法”。延迟和故障 Header 同时存在时先执行普通延迟，再
执行指定故障。

环境配置：

```text
DEMO_FAULTS_ENABLED=false
DEMO_FAULT_MAX_DELAY_MS=2000
DEMO_FAULT_TIMEOUT_DELAY_MS=5000
```

两个延迟配置在 Java 启动时强制限制为不超过 60000 毫秒。该实现通过阻塞开发服务器线程
模拟慢响应，不用于性能或容量测试，生产部署必须保持关闭。

## 6. 状态枚举

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

## 7. 固定业务断言

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

## 8. 演进规则

状态契约变化必须：

1. 先确认业务语义和兼容策略；
2. 增加新的 Flyway 迁移，不修改已发布迁移；
3. 同步 Java Enum、实体、DTO 和数据库约束；
4. 同步 Python Schema、前端类型和接口文档；
5. 增加旧值兼容或数据迁移测试，并验证 `ORDER-003` 黄金链路。
