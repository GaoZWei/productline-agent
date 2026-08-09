# 当前开发状态

- 当前里程碑：M2 确定性订单诊断（进行中）
- 当前子阶段：M2.2 最小 Run 生命周期（T207～T213，已完成）
- 已完成任务：T001～T153、T201～T213
- 当前场景：Python可创建PENDING Run，并原子流转到RUNNING和SUCCEEDED/FAILED，成功保存标准JSON结果，失败保存错误码和错误步骤；Tool调试链尚未自动创建Run/Step，确定性Workflow未实现
- 通过测试：M2.2隔离PostgreSQL专项5/5，覆盖成功、失败、非法流转、参数校验、资源不存在和并发终态竞争；M2.1～M2.2持久化汇总10/10；Python汇总180通过/8个数据库集成用例按门禁跳过；Ruff和mypy strict（38个文件）均通过；最终Agent镜像、三服务smoke、Java 56/56、Web 7/7和生产构建均通过
- 失败测试：最终结果0；测试先行首次因`app.services`尚不存在产生1个预期收集错误；首次质量检查发现既有M2.1中文学习注释格式漂移，保留含义并机械修正后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M2.2增加RunLifecycleService、内部生命周期异常、标准JSON结果校验和Repository compare-and-set状态更新
- 已知非阻塞问题：Run生命周期尚未接入Tool/Workflow，Step不会自动记录；`WAITING_APPROVAL`和`CANCELLED`只有枚举、没有操作；调试Run上下文与持久化Run仍是两套生命周期；本地Java/Python数据库角色仍未隔离；`/health`只是liveness；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T214～T220 实现 M2.3 最小 Step 记录、摘要、错误和耗时
