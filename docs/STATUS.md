# 当前开发状态

- 当前里程碑：M3 页面上下文与路由（进行中）
- 当前子阶段：M3.3 意图定义（T319～T323，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T323
- 当前场景：六类稳定意图已定义必填业务参数和四类业务Skill映射；`RouterResult`严格校验意图、置信度、实体、缺参和澄清状态，`UNKNOWN`明确不可分发；实际自然语言识别仍待M3.4接入
- 通过测试：真实跨服务E2E 8/8；Python汇总261通过/31个需外部环境的用例按门禁跳过；M3.3意图契约13/13；隔离PostgreSQL持久化与API 30/30；Web最近一次7个测试文件16/16及生产构建通过；Ruff和mypy strict（65个源文件）通过；Compose配置最近一次校验通过
- 失败测试：最终结果0；开发中发现并修正`SessionContext.previous_intent`从自由稳定码收紧为`Intent`枚举后的静态类型联动，以及既有中文注释触发的Ruff歧义标点门禁
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M3.3增加`Intent`、`RoutingParameter`、`BusinessSkill`和只读意图目录，建立严格`RouterEntities/RouterResult`契约、准确缺参校验及`UNKNOWN`强制澄清门禁；会话上一轮意图收紧为同一枚举
- 已知非阻塞问题：当前只有路由契约，没有M3.4 Prompt、具体模型解析或实际自然语言分发；置信度分级、参数合并与澄清状态机仍待M3.5～M3.6；TTL目前只阻止继续访问，尚无后台物理清理；首次诊断若在成功响应前失败，调用方拿不到该轮新建的`session_id`；清除会话会级联删除其Agent Message/Run/Step，尚无归档策略；当前只有订单业务页实际接入Adapter，任务与质检页面尚未建设；`batch_id`和`satellite_type`没有Java事实可供重校验；演示身份Header不是完整认证；诊断仍为单次HTTP响应，没有SSE，建议不能确认执行；未预期节点异常可能遗留RUNNING Step，尚无崩溃恢复；具体模型客户端、Prompt版本和真实模型评测未装配；没有Step重试次数/Trace持久化或跨实例调用账本；调试Run与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T324～T330 实现 M3.4 路由Prompt、上下文注入、结构化解析、一次重试和`UNKNOWN`回退
