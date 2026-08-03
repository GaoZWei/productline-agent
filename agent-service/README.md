# Agent Service

M1.3 Python 3.12/FastAPI 服务。当前包含工程基础、Agent 自有数据库连接、结构化日志、
调用 Java 的共享异步 HTTP Client 和标准 Tool 错误映射；尚未包含具体 Tool、Workflow、
RAG 或模型调用。

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

Client 显式使用 `trust_env=False`，避免内部服务流量被宿主机 HTTP/SOCKS 代理劫持。当前
不会自动重试；`retryable` 只描述故障是否具有技术可恢复性，后续 M1.6 仍须根据只读/写入
风险决定是否允许重试。

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
