# 遥感数据产线 Agent

面向遥感数据生产订单、生产任务、质检、复核和交付环节的智能协同 Agent。项目第一阶段以 `ORDER-003` 未交付诊断为黄金链路，按“业务接口 → Tool → 确定性 Workflow → 动态 Agent”的顺序迭代。

当前进度为 **M1.7 重复调用检测**：Python 服务已通过七个独立只读 Tool 覆盖订单、任务、
生产进度、质检、复核和交付查询，具备严格事实 Schema、有限读重试，以及单次 Run 内相同
Tool 与参数的重复调用拦截。当前尚未实现 Tool 调试 API、Workflow 或模型调用。

## 环境要求

- Docker Engine 或 Docker Desktop（支持 `docker compose`）
- GNU Make
- Java 21、Maven 3.9（运行 Java 领域测试）
- uv（自动安装和管理项目要求的 Python 3.12）
- Node.js 22（运行前端本地测试和构建）

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
make test-agent-foundation # 验证 M1.1 Python 工程基础
make test-agent-client # 验证 M1.2 Java HTTP Client
make test-agent-errors # 验证 M1.3 标准错误模型
make test-agent-tool-protocol # 验证 M1.4 Tool 基础协议
make test-tools        # 验证 M1.4～M1.7 Tool 协议、只读调用、重试和重复检测
make quality          # 运行 Ruff 和 mypy 严格检查
make agent-migrate    # 执行 Agent 自有数据库迁移
make test-business-domain # 单独运行 Java 领域模型测试
make test-business-data   # 单独验证固定数据和业务状态组合
make test-java-contract   # 单独验证 8 个 Java 只读查询接口
make reset-demo       # 删除本地数据卷并重建 PostgreSQL、Java 和固定数据
make logs             # 跟踪服务日志
make ps               # 查看服务状态
```

`make reset-demo` 会删除本项目 Docker Compose 管理的本地数据库卷，仅用于重置演示数据；成功后输出订单数和确定性数据快照。固定 ID、状态与后续 Tool 对接注意事项见 [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md)，查询路径和响应结构见 [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)。

## 项目结构

```text
.
├── agent-service/       # FastAPI Agent 服务、Agent 自有持久化和后续 Tool/Workflow
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
4. 将核心实现和重要决策追加到 `doc/record.md`；
5. 评估本次开发的 Agent 面试价值，只有有价值时才更新 `doc/needCare.md`。
