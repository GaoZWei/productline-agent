# 遥感数据产线 Agent

面向遥感数据生产订单、生产任务、质检、复核和交付环节的智能协同 Agent。项目第一阶段以 `ORDER-003` 未交付诊断为黄金链路，按“业务接口 → Tool → 确定性 Workflow → 动态 Agent”的顺序迭代。

当前进度为 **M0.2 业务领域模型设计**：Java 服务已升级为 Spring Boot/JPA/Flyway 工程，包含订单、生产任务、生产步骤、质检问题、复核、返工和交付领域模型；固定演示数据和业务 API 将在后续 M0 任务实现。

## 环境要求

- Docker Engine 或 Docker Desktop（支持 `docker compose`）
- GNU Make
- Java 21、Maven 3.9（运行 Java 领域测试）
- 可选：Python 3.12、Node.js 22（用于脱离 Docker 的本地开发）

## 快速开始

```bash
cp .env.example .env
make config
make dev
```

复制 `.env.example` 后只需修改 `.env` 即可切换端口、数据库和模型配置，不需要修改源码。`.env` 已被 Git 忽略，不应提交真实密钥。

服务默认地址：

| 服务 | 地址 | 健康检查 |
| --- | --- | --- |
| Web 控制台 | <http://localhost:5173> | <http://localhost:5173/health> |
| Python Agent | <http://localhost:8000> | <http://localhost:8000/health> |
| Java 业务服务 | <http://localhost:8080> | <http://localhost:8080/health> |
| PostgreSQL | `localhost:5432` | `pg_isready` |

停止服务：

```bash
make down
```

## 常用命令

```bash
make help             # 查看全部命令
make config           # 展开并校验 Docker Compose 配置
make dev              # 构建并启动全部服务
make dev-business     # 只启动 Java 服务及其依赖
make dev-agent        # 只启动 Python 服务及其依赖
make dev-web          # 只启动 Web 服务及其依赖
make test             # 运行基础检查、服务冒烟和 Java 领域集成测试
make test-business-domain # 单独运行 Java 领域模型测试
make reset-demo       # 删除本地 Compose 数据卷并重建 PostgreSQL
make logs             # 跟踪服务日志
make ps               # 查看服务状态
```

`make reset-demo` 会删除本项目 Docker Compose 管理的本地数据库卷，仅用于重置演示数据。

## 项目结构

```text
.
├── agent-service/       # Python Agent 服务（当前为健康检查骨架）
├── business-service/    # Spring Boot 业务服务与领域模型
├── web-console/         # Vue 前端目标目录（当前为静态启动骨架）
├── doc/                 # 原始需求、细化计划与开发记录
├── docs/                # 路线图、状态和测试报告
├── scripts/             # 根级验证脚本
├── docker-compose.yml
└── Makefile
```

## 开发约束

开始开发前阅读根目录 `AGENTS.md`。每次开发必须：

1. 只完成当前里程碑内的一个可测试任务；
2. 保证固定数据和 `ORDER-003` 黄金链路稳定；
3. 运行任务对应测试并如实更新 `docs/STATUS.md`、`docs/TEST_REPORT.md`；
4. 将核心实现和重要决策追加到 `doc/record.md`。
