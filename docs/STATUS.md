# 当前开发状态

- 当前里程碑：M2 确定性订单诊断（进行中）
- 当前子阶段：M2.1 Agent 基础数据表（T201～T206，已完成）
- 已完成任务：T001～T153、T201～T206
- 当前场景：Python 已能持久化 Agent Session、Message、Run、Step，并通过 Repository 增删查；Tool 调试链仍使用 M1.7 进程内上下文，尚未接入 M2.2 Run 生命周期或确定性 Workflow
- 通过测试：M2.1 隔离 PostgreSQL 专项5/5，含真实 migration upgrade/check/downgrade、Repository CRUD、级联和唯一约束；Python汇总180通过/3个数据库集成用例按门禁跳过；Ruff和mypy strict（36个文件）均通过；项目开发库迁移到`0001_agent_runtime_base`；最终镜像和三服务smoke通过；完整`make test`通过，含Java 56/56、Web 7/7和生产构建
- 失败测试：最终结果0；测试先行首次因`app.models`尚不存在产生1个预期收集错误；首次数据库测试误连本机5432后改为随机端口隔离容器；首次CRUD测试发现SQLAlchemy查询会自动开启事务，调整调用方事务边界后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M2.1 增加四张 Agent 自有表、首个 Alembic revision、Run/Step Repository 和隔离数据库验收入口
- 已知非阻塞问题：M2.1 表尚未接入Tool/Workflow，状态字段不会自动流转；调试Run上下文与持久化Run仍是两套生命周期；本地Java/Python数据库角色仍未隔离；`/health`只是liveness；未实现Workflow、RAG、Agent UI、SSE或Approval；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T207～T213 实现 M2.2 最小 Run 生命周期及状态流转测试
