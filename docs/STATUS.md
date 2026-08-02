# 当前开发状态

- 当前里程碑：M1 Python Tool 层（进行中）
- 当前子阶段：M1.2 Java HTTP Client（T109～T117，已完成）
- 已完成任务：T001～T117
- 当前场景：Python 已通过共享 `httpx.AsyncClient` 调用 Java，支持身份/Token/Trace、GET/POST、幂等键、分项超时和严格成功信封/data Schema 校验；尚未实现 Tool、统一错误映射、重试或模型调用
- 通过测试：Python M1.1 6/6、M1.2 10/10、Ruff、mypy strict、uv 锁文件、Agent 生产镜像和真实容器 `ORDER-003` 调用均通过；完整 `make test` 通过，包含 Java M0 回归 56/56 和 Web 7/7/生产构建
- 失败测试：最终结果 0；测试先行因 `app.clients` 不存在而收集失败；首轮实现 8/10，宿主机 SOCKS 代理导致两个无 Mock Client 初始化失败，设置内部调用 `trust_env=False` 后 10/10；质量检查发现 Python 3.12 泛型写法及既有注释格式问题，修正后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M1.2 已完成 Java Client 配置、生命周期、请求封装和响应门禁，并在 Compose 内真实读取 `ORDER-003=QUALITY_CHECKING`、透传 `trace-m12-real`
- 已知非阻塞问题：本地开发数据库仍无角色级隔离；`/health` 仍只是 liveness；HTTP 4xx/5xx、超时和响应校验错误尚未映射为 Tool 标准错误，未实现自动重试、端点业务 DTO、Tool、Workflow、RAG、Agent UI、SSE 或 Approval
- 下一任务：T118 定义 `ToolException` 基类
