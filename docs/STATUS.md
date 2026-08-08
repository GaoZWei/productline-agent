# 当前开发状态

- 当前里程碑：M1 Python Tool 层（进行中）
- 当前子阶段：M1.6 Tool 重试（T140～T144，已完成）
- 已完成任务：T001～T144
- 当前场景：七个只读 Tool 对明确可恢复的网络错误和 timeout 最多额外重试一次；参数、权限、资源、冲突、Java 保守 500、响应 Schema 和资源归属错误不重试；尚未实现重复调用检测、调试 API、Workflow 或模型调用
- 通过测试：M1.4 协议 16/16、M1.5/M1.6 RetryPolicy 与七个只读 Tool 92/92、Python 汇总 144/144、M1.1 基础回归 8/8、Ruff 和 mypy strict（26 个文件）均通过
- 失败测试：实现最终相关测试 0；完整 `make test` 在受限执行环境中因无法访问 `127.0.0.1:18000` 而停止在三服务 smoke，Java/Web 目标未执行；M1.6 测试先行先暴露既有 Tool Schema 名称拼写回归，修复后按预期因 `RetryPolicy` 尚不存在产生 1 个导入错误
- 当前阻塞：代码无阻塞；当前执行环境禁止访问宿主机本地服务，无法在本次验收中重复完成真实 Java 重试成功链路和三服务 smoke
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M1.6 增加显式只读 `RetryPolicy`、封顶指数退避、总 timeout 预算和重试结构化日志；七个 Tool 已通过确定性 transient failure/timeout 测试
- 已知非阻塞问题：本地开发数据库仍无角色级隔离；`/health` 仍只是 liveness；当前重试无随机抖动、熔断或跨实例预算；Java 通用 500 为 `retryable=false`；`DUPLICATE_CALL` 等待 M1.7；未实现调试 API、Workflow、RAG、Agent UI、SSE 或 Approval
- 下一任务：T145 定义单次 Run 的 Tool 调用签名
