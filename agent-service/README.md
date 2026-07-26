# Agent Service

M0.1 提供的 Python 可启动骨架。它只暴露 `/health`，不包含 Agent、Tool、数据库访问或业务逻辑。

使用 Docker 启动：

```bash
docker compose up --build agent-service
```

使用本机 Python 启动：

```bash
cd agent-service
PORT=8000 python3 -m app.main
```

