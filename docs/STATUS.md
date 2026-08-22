# 当前开发状态

- 当前里程碑：M5 动态异常诊断Agent（进行中）
- 当前子阶段：M5.1 Agent State扩展（T501～T507，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T507
- 当前场景：固定订单诊断保持原有路径；共享`OrderDiagnosisState`已增加安全Tool历史、信息缺口、迭代次数和终止原因，`AgentAction`固化七种只读查询与显式结束动作，Observation用参数SHA-256指纹区分调用且不复制原始业务载荷
- 通过测试：Python汇总404通过/38个需外部环境的用例按门禁跳过；M5.1状态契约5/5，相关Workflow回归合计61通过/8个外部E2E跳过；mypy strict（106个源文件）通过；此前真实跨服务E2E最近一次8/8、M4知识与RAG测试91/91、Web 18/18及生产构建、Compose健康检查与配置校验结果保持有效
- 失败测试：开发中先以缺少`AgentAction`导出验证新测试有效；M5.1范围Ruff检查通过，全量Ruff仍被`app/evaluation/rag.py`中21项既有注释标点/行长问题拦截，未在本阶段修改无关M4.12代码；全量格式检查还报告3个既有文件待格式化
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M5.1新增动态Agent动作、Observation、InformationGap和TerminationReason严格契约，扩展订单诊断状态并通过JSON往返测试；固定Workflow使用中性值初始化新增通道，既有诊断行为不变
- 已知非阻塞问题：M5.1只建立状态契约，尚未实现动作决策模型、动态LangGraph循环和执行限额；全量Ruff存在`app/evaluation/rag.py`的21项既有注释标点/行长问题，全量格式检查存在3个既有未格式化文件；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互、Run/Step持久化或具体问答/Rerank模型客户端；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验，权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；诊断没有SSE或Approval，未预期节点异常可能遗留RUNNING Step；没有Step重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T508～T514 实现M5.2动作模型，包括严格ActionDecision、中文决策Prompt、已知事实与Tool描述注入、结构化解析和非法动作回退
