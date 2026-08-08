# 当前开发状态

- 当前里程碑：M1 Python Tool 层（进行中）
- 当前子阶段：M1.5 只读 Tool（T133～T139，已完成）
- 已完成任务：T001～T139
- 当前场景：七个只读 Tool 已通过 Java API 查询订单、任务、生产进度、质检、复核和交付事实；应用 lifespan 已注册完整 Tool 集合；尚未实现自动重试、重复调用检测、调试 API、Workflow 或模型调用
- 通过测试：Python M1.1 7/7、M1.2 10/10、M1.3 18/18、M1.4 16/16、M1.5 69/69、Python 汇总 120/120、Ruff 和 mypy strict 均通过；七个 Tool 真实调用 Java 固定数据 7/7；完整 `make test` 通过，包含三服务 smoke、Java M0 回归 56/56 和 Web 7/7/生产构建
- 失败测试：最终结果 0；M1.5 测试先行因只读 Tool 导出尚不存在产生 1 个收集错误；首次质量检查报告 21 项导出排序、中文教学注释格式及固定业务中文标点问题，保留语义调整排版并定点豁免业务原文后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M1.5 建立七个细粒度只读 Tool、严格端点 DTO、资源归属一致性校验和应用级注册；`ORDER-003` 全链路真实调用 7/7
- 已知非阻塞问题：本地开发数据库仍无角色级隔离；`/health` 仍只是 liveness；`max_retries=1` 尚未由策略执行，所有失败仍只调用一次；`DUPLICATE_CALL` 等待 M1.7；未实现调试 API、Workflow、RAG、Agent UI、SSE 或 Approval；Java 测试仍有 Mockito 动态 Agent 的未来 JDK 兼容警告
- 下一任务：T140 定义只读 `RetryPolicy`
