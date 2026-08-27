# Business Service

Java 21 + Spring Boot 3.5 + Spring Data JPA + Flyway 的遥感数据产线业务服务。当前已提供固定演示数据、查询/写入接口、统一响应和 Trace ID，以及 M0.7 开发故障模拟。

使用 Docker 启动：

```bash
docker compose up --build business-service
```

使用本机 JDK/Maven 测试：

```bash
mvn --file business-service/pom.xml test
```

服务使用以下环境变量连接 PostgreSQL：

```text
SPRING_DATASOURCE_URL
SPRING_DATASOURCE_USERNAME
SPRING_DATASOURCE_PASSWORD
PORT
```

健康检查继续兼容 `GET /health`。

## M0.5 写接口契约

| 接口 | 请求体 | 成功结果 |
| --- | --- | --- |
| `POST /api/tasks/{taskId}/review` | `issueId`、`status`、`reviewComment`、`expectedVersion` | 新复核记录和递增后的 `taskVersion` |
| `POST /api/tasks/{taskId}/rework` | `sourceIssueId`、`reason`、`expectedVersion` | `PENDING` 返工任务和递增后的 `taskVersion` |

两个接口都必须携带 `X-User-Id`、`X-User-Role: REVIEWER` 和 `Idempotency-Key`。`expectedVersion` 来自任务查询响应的 `version`；状态已经变化或两个请求并发修改同一版本时返回 `409`。相同用户以相同幂等键和相同请求重试时返回第一次结果，不会重复写入；同一幂等键改作其他请求时返回 `409`。

服务端生成的复核、返工和操作日志ID统一使用大写UUID片段，确保返回值满足Python侧业务标识契约，并可直接进入
写Tool的强类型响应和Approval执行结果。

M0.5 只建立 Java 侧最小权限上下文，Header 尚未连接真实认证系统。

独立验收：

```bash
make test-java-write
```

## M0.6 统一响应

所有 `/api` 业务端点使用以下响应结构；Actuator `/health` 保持原生健康检查结构。

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "success",
  "data": {},
  "trace_id": "trace-<uuid>",
  "retryable": false
}
```

调用方可通过 `X-Trace-Id` 透传 1～128 位安全字符组成的链路 ID；缺失或非法时服务会生成新 ID，并始终在响应 Header 与响应体中返回相同值。当前错误码包括 `PARAM_VALIDATION_ERROR`、`RESOURCE_NOT_FOUND`、`PERMISSION_DENIED`、`BUSINESS_CONFLICT` 和 `INTERNAL_SERVER_ERROR`。通用错误均不建议自动重试，尤其写操作必须沿用幂等和版本策略。

独立验收：

```bash
make test-java-errors
```

## M0.7 开发故障模拟

故障模拟默认关闭，Docker Compose 本地开发显式开启。它只作用于 `GET /api/**`，不会
注入复核或返工写接口：

| Header | 行为 |
| --- | --- |
| `X-Demo-Delay-Ms: 500` | 响应前延迟 500 毫秒，默认最大 2000 毫秒 |
| `X-Demo-Fault: timeout` | 默认保持连接 5000 毫秒后继续正常查询，用于触发短超时客户端 |
| `X-Demo-Fault: server-error` | 返回统一 `500/INTERNAL_SERVER_ERROR` |
| `X-Demo-Fault: invalid-response` | 返回 HTTP 200，但故意缺少必需的 `data` 字段 |
| `X-Demo-Fault: permission-denied` | 返回统一 `403/PERMISSION_DENIED` |

裸机启动时需显式设置 `DEMO_FAULTS_ENABLED=true`；生产环境不得启用。延迟和超时上限可
通过 `DEMO_FAULT_MAX_DELAY_MS`、`DEMO_FAULT_TIMEOUT_DELAY_MS` 调整，服务端硬上限均为
60000 毫秒。

独立验收：

```bash
make test-java-faults
```
