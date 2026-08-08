# Agent Service

M1.6 Python 3.12/FastAPI 服务。当前包含工程基础、Agent 自有数据库连接、结构化日志、
调用 Java 的共享异步 HTTP Client、标准 Tool 错误映射、Tool 基础协议和七个只读业务 Tool；
只读 Tool 已具备显式、有限的退避重试，尚未包含 Workflow、RAG 或模型调用。

## 本地开发

uv 会按照 `.python-version` 安装/选择 Python 3.12，并根据 `uv.lock` 创建 `.venv`：

```bash
cd agent-service
uv sync --frozen
uv run python -m app.main
```

默认健康检查为 <http://localhost:8000/health>。可使用 `PORT`、`ENVIRONMENT`、
`LOG_LEVEL`、`DATABASE_URL`、`BUSINESS_SERVICE_URL` 和四项
`BUSINESS_*_TIMEOUT_SECONDS` 覆盖配置。

## Java HTTP Client

`app.clients.business.BusinessHttpClient` 在 FastAPI lifespan 中创建和关闭，共享连接池，
通过 `BusinessIdentity` 透传用户、角色和可选 Bearer Token，并自动透传当前 Trace ID。
GET 和 POST 成功响应必须同时通过 Java 六字段信封与调用方提供的 Pydantic data Schema；
Java 400/401/403/404/409/500、httpx 网络/超时异常和响应契约错误统一转换为
`ToolException`。POST 强制提供安全格式的幂等键。

Client 显式使用 `trust_env=False`，避免内部服务流量被宿主机 HTTP/SOCKS 代理劫持。Client
自身不重试，只负责把上游失败转换为带 `retryable` 的 `ToolException`；是否重试由具体 Tool
显式绑定的 `RetryPolicy` 决定，避免未来写 Tool 因共享 Client 行为而被意外重放。

## Tool 基础协议

`app.tools.BaseTool` 统一声明名称、说明、Pydantic 输入/输出模型、风险等级、所需权限、整体
超时和最大重试次数。公共 `execute` 先检查权限和输入 Schema，再在整体超时内调用具体 Tool
的 `_execute`，最后校验输出 Schema。标准 `ToolException`、超时、非法输出和未知异常都会
转换为互斥的 `ToolResult(success, data, error)`，未知异常的内部详情只写入结构化日志。

`ToolContext` 携带 `BusinessIdentity`、权限集合、Trace ID 和 Run ID。`ToolRegistry` 按稳定
名称注册和获取 Tool，重复名称会被拒绝而不会静默覆盖。`max_retries` 表示首次调用之外允许的
额外调用次数；只有显式提供 `RetryPolicy` 的 Tool 才会实际重试。当前没有 Run/Step 持久化
或 Approval。

## 只读业务 Tool

应用 lifespan 使用同一个 `BusinessHttpClient` 注册七个 LOW 风险 Tool：
`get_order_detail`、`get_related_tasks`、`get_task_detail`、`get_production_progress`、
`get_quality_issues`、`get_review_result` 和 `get_delivery_status`。它们分别声明 `ORDER_READ`、
`TASK_READ`、`QUALITY_ISSUE_READ`、`REVIEW_READ` 或 `DELIVERY_READ` 权限。

输入只接受安全格式的 `ORDER-*` 或 `TASK-*` 标识；输出严格对应 Java DTO，禁止额外字段、非法
状态和缺失字段。集合接口的空数组是成功事实，不等同于资源不存在。除 Schema 校验外，Tool
还核对响应父 ID 与嵌套资源 ID，阻止形状正确但属于其他订单或任务的数据进入后续 Workflow。

## 只读 Tool 重试

七个只读 Tool 共享一项显式策略：最多额外重试 1 次，首次退避 100 ms，指数倍数为 2，单次
退避上限为 1 秒。当前只有同时满足以下条件的 `ToolException` 才会重试：错误码是
`TOOL_TIMEOUT` 或 `UPSTREAM_UNAVAILABLE`、`retryable=true`，并且还有剩余次数。

参数、权限、404、409、响应 Schema 或资源归属错误不会重试。Java 当前通用 500 信封为
`retryable=false`，因此也不会重试。每个 Tool 的 5 秒整体 timeout 同时覆盖首次请求、退避、
重试请求和输出校验，避免重试把调用时间无限拉长。每次计划重试都会记录 Tool、Run、Trace、
错误码、重试序号和退避毫秒数；当前没有随机抖动、熔断或跨实例重试预算。

## 测试与质量

```bash
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen mypy app tests
uv run --frozen alembic upgrade head
```

根目录可单独执行：

```bash
make test-agent-client
make test-agent-errors
make test-agent-tool-protocol
make test-tools
```

`unit` 标记不使用外部服务；`integration` 标记覆盖 FastAPI 生命周期、中间件和 HTTP
边界。M1.1 尚无数据库表迁移，因此 Alembic 只建立迁移能力，不创建 Agent 业务表。

## 数据边界

`app.database.Base` 只用于后续 Agent Run、Step、Approval 和 RAG 元数据。Python 服务
不得为 Java 的订单、生产、质检、复核或交付表建立 ORM 映射，也不得绕过 Java API
读取或修改业务事实。

## Docker 启动

```bash
docker compose up --build agent-service
```
