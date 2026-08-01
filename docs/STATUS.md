# 当前开发状态

- 当前里程碑：M1 Python Tool 层（进行中）
- 当前子阶段：M1.1 Python 工程初始化（T101～T108，已完成）
- 已完成任务：T001～T108
- 当前场景：Python Agent 服务已由 uv 管理 Python 3.12，使用 FastAPI 提供健康检查，具备 Agent 自有 SQLAlchemy/Alembic 持久化基础和带 Trace ID 的 JSON 请求日志；尚未调用 Java API、Tool 或模型
- 通过测试：Python M1.1 pytest 6/6、Ruff、mypy 严格检查和 uv 锁文件检查通过；Agent Docker 镜像、Compose 健康检查、Alembic 容器连接通过；完整 `make test` 通过，包含 Java M0 回归 56/56 和 Web 7/7/生产构建
- 失败测试：最终结果 0；测试先行首次收集因 `app.database`、`app.observability` 和 FastAPI 工厂尚未实现而失败；首轮实现后 6 个测试中 1 个 Alembic 路径预期失败，修正为校验展开后的绝对路径；mypy 随后发现测试未收窄 `str | None`，增加显式断言后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M1.1 已建立 FastAPI、配置、异步 SQLAlchemy、Alembic、结构化日志、Trace ID、pytest、Ruff 和 mypy 基线；已更新 `doc/needCare.md` 的 Agent 持久化边界与可观测性关注点
- 已知非阻塞问题：本地开发 Compose 仍让 Python 和 Java 使用同一 PostgreSQL 数据库/角色，当前通过“Python 不定义业务 ORM + 独立 `agent_alembic_version`”保持代码边界，但尚无数据库权限级隔离；`/health` 是存活探针，不检查数据库就绪；Python HTTP Client、Tool、Workflow、RAG、Agent UI、SSE 和 Approval 均尚未实现
- 下一任务：T109 定义 Java Client 配置模型
