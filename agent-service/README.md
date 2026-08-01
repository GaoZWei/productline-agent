# Agent Service

M1.1 Python 3.12/FastAPI 工程基础。当前包含健康检查、环境配置、Agent 自有 SQLAlchemy
连接、Alembic 骨架、JSON 日志和请求 Trace ID；尚未包含 Java HTTP Client、Tool、
Workflow、RAG 或模型调用。

## 本地开发

uv 会按照 `.python-version` 安装/选择 Python 3.12，并根据 `uv.lock` 创建 `.venv`：

```bash
cd agent-service
uv sync --frozen
uv run python -m app.main
```

默认健康检查为 <http://localhost:8000/health>。可使用 `PORT`、`ENVIRONMENT`、
`LOG_LEVEL` 和 `DATABASE_URL` 覆盖配置。

## 测试与质量

```bash
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen mypy app tests
uv run --frozen alembic upgrade head
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
