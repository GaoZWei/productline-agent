# 当前开发状态

- 当前里程碑：M2 确定性订单诊断（进行中）
- 当前子阶段：M2.7 诊断文案生成（T244～T250，已完成）
- 已完成任务：T001～T153、T201～T250
- 当前场景：固定LangGraph在规则裁决后生成完整`DiagnosisResult`；`ORDER-003`稳定输出质量复核阻塞、未关闭坐标系问题与待复核根因、Tool字段证据和两条处理建议；可选模型只能按稳定code整理说明，异常或无效输出回退规则结果
- 通过测试：M2.7规则文案与Workflow专项20/20；Python汇总235通过/15个数据库集成用例按门禁跳过；隔离PostgreSQL持久化17/17；Ruff和mypy strict（49个文件）均通过；此前完整`make test`、三服务smoke、Java 56/56、Web 7/7和生产构建结果保持有效，本次未重复无关模块
- 失败测试：最终代码测试0；首次从`agent-service`子目录调用根级`make test-diagnosis-generation`因执行目录错误失败，切换仓库根目录后20/20通过；质量检查曾发现新增和既有相关Workflow文件的31个全角标点/格式告警，已机械修复并通过复检
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M2.7增加完整规则诊断装配、`DiagnosisNarrative`模型输出Schema、稳定code保护、LLM Step和模型失败回退
- 已知非阻塞问题：当前只提供供应商无关的模型适配接口，尚未装配具体模型客户端、Prompt版本或真实模型评测；Workflow尚未创建/结束Run，必须由M2.8调用方提供RUNNING Run；没有诊断API、崩溃恢复、Step重试次数/Trace持久化或跨实例调用账本；调试Run与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T251～T258 实现 M2.8 诊断 API
