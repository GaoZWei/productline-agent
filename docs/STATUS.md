# 当前开发状态

- 当前里程碑：M1 Python Tool 层（已完成，停在 M1 验收线）
- 当前子阶段：M1.8 Tool 调试接口（T150～T153，已完成）
- 已完成任务：T001～T153
- 当前场景：开发环境可通过 `POST /internal/tools/{tool_name}/invoke` 和 Swagger 脱离 Agent 调用七个只读 Tool；请求仍经过身份/权限、输入 Schema、Run 内去重、有限重试、Java Client 和输出 Schema，`test`/`production` 不注册该路由；尚未实现 Workflow 或模型调用
- 通过测试：M1.4 协议 16/16，M1.5～M1.8 Tool/重试/去重/调试 API 127/127，Python汇总179/179，Ruff和mypy strict（31个文件）均通过；真实调试 API 对 `ORDER-003` 完成首次成功、重复拦截和强制刷新；完整 `make test` 通过，含三服务 smoke、Java 56/56、Web 7/7 和生产构建
- 失败测试：最终结果0；测试先行时开发路由尚不存在，产生6个预期失败；首次质量检查发现19项中文标点、导入排序和工作区既有M1.7讲解注释格式问题，保留说明含义并修正后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M1.8 增加开发专用 Tool 调试路由、标准 ToolResult、Swagger 示例、有界 Run 上下文复用以及生产环境隐藏门禁
- 已知非阻塞问题：调试 Run 上下文最多保留128个且只在单进程内存在，淘汰、服务重启或多实例不会共享；本地开发数据库仍无角色级隔离；`/health`只是liveness；未实现Run/Step、Workflow、RAG、Agent UI、SSE或Approval；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T201 创建 Agent Session/Message/Run/Step 基础数据模型（进入 M2 前需用户确认）
