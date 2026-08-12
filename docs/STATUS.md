# 当前开发状态

- 当前里程碑：M2 确定性订单诊断（进行中）
- 当前子阶段：M2.8 诊断 API（T251～T257，已完成）
- 已完成任务：T001～T153、T201～T257
- 当前场景：`POST /api/agent/order-diagnosis`创建一次性Session、用户Message和RUNNING Run，执行固定Workflow后返回Run、Trace与完整诊断；`ORDER-003`成功保存9个Step及诊断快照，Tool失败和未预期Workflow异常保存FAILED Run并返回安全结构化错误
- 通过测试：M2.8 API专项6/6；Python汇总238通过/18个数据库集成用例按门禁跳过；隔离PostgreSQL持久化与API共23/23；Ruff和mypy strict（53个文件）均通过；此前完整`make test`、三服务smoke、Java 56/56、Web 7/7和生产构建结果保持有效，本次未重复无关模块
- 失败测试：最终结果0；本次未出现代码测试失败，开发中Ruff发现相关文件12个排序、全角标点和行宽告警，已机械修复并通过复检
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M2.8增加诊断请求/响应/错误Schema、HTTP入口、请求级Session/Message/Run编排、结果快照、Tool错误HTTP映射和异常Run收口
- 已知非阻塞问题：当前身份Header和一次性Session分别只是最小身份上下文与运行归属，不是完整认证或多轮会话；未预期节点异常可能遗留RUNNING Step，尚无崩溃恢复；具体模型客户端、Prompt版本和真实模型评测未装配；没有Step重试次数/Trace持久化或跨实例调用账本；调试Run与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T258～T267 实现 M2.9 前端 Agent 侧边栏
