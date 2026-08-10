# 当前开发状态

- 当前里程碑：M2 确定性订单诊断（进行中）
- 当前子阶段：M2.5 固定 Workflow 节点（T227～T235，已完成）
- 已完成任务：T001～T153、T201～T235
- 当前场景：Python已用LangGraph固定串联上下文、订单、任务、进度、质检、复核和交付节点；Tool事实按任务稳定合并，标准错误会写入StepError并中断后续节点，Workflow可通过短事务持久化每次Step；诊断规则尚未实现
- 通过测试：M2.5节点专项5/5；M2.4 Schema专项18/18；Python汇总203通过/15个数据库集成用例按门禁跳过；隔离PostgreSQL持久化17/17；Ruff和mypy strict（45个文件）均通过；完整`make test`、三服务smoke、Java 56/56、Web 7/7和生产构建均通过
- 失败测试：最终结果0；测试先行首次因`app.workflows`尚不存在产生1个预期收集错误；开发中修复相邻节点严格zip导致的4个图构建失败，并机械修复既有M2.4讲解注释的全角标点与导入空行
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M2.5增加OrderDiagnosisWorkflow、七个固定加载节点、错误条件路由和DatabaseWorkflowStepRecorder
- 已知非阻塞问题：Workflow尚未创建/结束Run，必须由M2.8调用方提供RUNNING Run；blocking_stage与规则留待M2.6；没有诊断API、崩溃恢复、Step重试次数/Trace持久化或跨实例调用账本；调试Run与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T236～T243 实现 M2.6 确定性诊断规则
