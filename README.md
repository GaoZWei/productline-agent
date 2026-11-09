# 遥感数据产线 Agent

面向遥感数据生产订单、任务、质检、复核和交付环节的协同 Agent。页面采集上下文，Python 编排 Tool、Workflow、规范检索和人工确认，Java 提供业务事实并完成权限、状态、版本和幂等校验后的最终写入。

M7 已完成；当前推进 M8 人工返工执行与再次复核闭环，M8.1 领域、契约及存储已验收，M8.2 已接入 T806 详情及 T807～T809 Java开始、异常与受控恢复，独立确认及页面仍待后续接线。知识库保留在 KB-03.10，统一知识读源选择仍待开发。最新进度、实际验证和下一最小任务统一查看[当前状态](docs/STATUS.md)。

目前页面支持订单状态查询、动态诊断、带版本引用的规范问答、复核与返工创建的独立人工确认，以及 Run/Step 历史和 SSE 步骤展示。知识库已有上传、修订、预览与原件管理接口，发布/索引等内部应用完成至 KB-03.10，默认问答尚未切源。M8 新返工处理与再次复核尚未完成页面和 Agent 接线；真实模型与索引能力依赖配置和就绪状态，小样本验收不代表完整质量评测。

## 文档入口

从[文档总导航](docs/README.md)选择阅读路径：

| 目的 | 入口 |
|---|---|
| 理解系统职责与完整调用链 | [系统全链路](docs/architecture/SYSTEM_FLOW.md) |
| 启动后演示、查看固定场景和重置说明 | [演示链路](docs/demo/AGENT_DEMO_FLOW.md)、[演示数据](docs/demo/DEMO_DATA.md)、[重置手册](docs/demo/DEMO_RESET.md) |
| 参与开发 | [开发规则](AGENTS.md)、[详细计划](docs/planning/detailed-plan.md) |
| 了解知识库需求和管理边界 | [知识库导航](docs/knowledge/README.md) |
| 准备面试或学习工程实现 | [面试准备](docs/interview/Agent-Question-Plan.md)、[Python 学习手册](docs/learning/pythonKnowledge.md) |

## 环境要求

- Docker Engine 或 Docker Desktop（支持 `docker compose`）、GNU Make。
- 本机开发和测试：Java 21、Maven 3.9、uv（管理 Python 3.12）、Node.js 22。

## 快速开始

```bash
cp .env.example .env
make config
make dev
```

在 `.env` 中设置端口、数据库和模型参数；不要提交真实密钥。服务启动不代表模型已配置或知识索引已就绪，模型及入库步骤见 [Agent 服务说明](agent-service/README.md)。

| 服务 | 默认地址 | 健康检查 |
|---|---|---|
| Web 控制台 | <http://localhost:5173> | `/health` |
| Python Agent | <http://localhost:8000> | `/health` |
| Java 业务服务 | <http://localhost:8080> | `/health` |
| PostgreSQL | `localhost:5432` | `pg_isready` |

## 常用命令

```bash
make help        # 全部命令及用途
make config      # 展开并校验 Compose 配置
make dev         # 构建并启动全部服务
make validate    # 基础目录、文件和 Compose 检查
make quality     # Python Ruff 与 mypy 检查
make test-web    # 前端测试与构建
make logs        # 跟踪服务日志
make ps          # 查看服务状态
make down        # 停止服务
```

领域测试和独立启动方式见 [Java](business-service/README.md)、[Python](agent-service/README.md)、[Web](agent-frontend/README.md) 的模块说明。`make test` 的实际范围以 Makefile 依赖为准，不能代替所有后续领域验收入口。

`make reset-demo` 会删除本项目 Compose 管理的数据库卷，清除 Agent 历史、Approval 和知识向量；执行前按[重置手册](docs/demo/DEMO_RESET.md)保存证据，完整恢复还需 Agent 迁移和知识入库。

## 项目结构与开发约定

```text
.
├── agent-service/       # FastAPI、Tool、Workflow/Agent、RAG、Approval 和运行记录
├── business-service/    # Java 业务事实、权限、一致性、幂等与最终写入
├── agent-frontend/      # Vue 订单全景、Agent 交互、人工确认和运行历史
├── knowledge-base/      # 固定演示规范及 catalog，独立于管理说明
├── docs/                # 项目文档、计划、演示、学习与面试资料的统一入口
├── scripts/             # 根级检查、验收和演示辅助脚本
├── AGENTS.md            # 开发规则与按需阅读顺序
├── docker-compose.yml
└── Makefile
```

开发前阅读 [AGENTS.md](AGENTS.md)，按当前任务最小范围阅读和验证。`ORDER-003` 黄金链路、Java 业务事实边界和人工确认规则必须保持。
