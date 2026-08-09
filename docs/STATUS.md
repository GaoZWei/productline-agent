# 当前开发状态

- 当前里程碑：M2 确定性订单诊断（进行中）
- 当前子阶段：M2.4 Workflow 状态模型（T221～T226，已完成）
- 已完成任务：T001～T153、T201～T226
- 当前场景：Python已定义固定订单诊断共享状态、结构化根因、可追溯Tool字段证据、建议、步骤错误和诊断结果Schema；Run/Step与Tool尚未由Workflow自动接线，固定节点和诊断规则尚未实现
- 通过测试：M2.4 Schema专项18/18；Python汇总198通过/14个数据库集成用例按门禁跳过；Ruff和mypy strict（41个文件）均通过；完整`make test`、三服务smoke、M2.1～M2.3持久化16/16、Java 56/56、Web 7/7和生产构建均通过
- 失败测试：最终结果0；测试先行首次因`app.schemas.workflow`尚不存在产生1个预期收集错误；开发中还修复4个新Schema全角标点、7个既有M2.3讲解注释标点、1个测试导入排序，以及PEP 695类型别名无法被`get_args`直接枚举导致的1个契约断言失败
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M2.4增加OrderDiagnosisState、DiagnosisResult、RootCause、Evidence、Suggestion和StepError严格契约
- 已知非阻塞问题：M2.4只有状态和Schema、没有Workflow执行；blocking_stage正式枚举留待M2.6；Run/Step生命周期尚未接入Tool/Workflow；调试Run上下文与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T227～T235 实现 M2.5 固定 Workflow 节点
