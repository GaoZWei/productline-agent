# 当前开发状态

- 当前里程碑：M7运行观测、生产闭环集成与统一评测（进行中）
- 当前子阶段：M7.6-B现有模型协议适配已完成（T754～T758，已到停止线；下一任务T759）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T670、T701～T758
- 当前场景：Router、Action、规范回答、Rerank和Review草稿五类现有Protocol均可把版本化Prompt与严格输出Schema交给公共OpenAI兼容Client；实体证据、只读动作注册、引用白名单、候选身份和草稿事实仍由既有确定性组件复核，但固定诊断仍是唯一生产诊断入口
- 通过测试：`make test-model-adapters`定向65/65，Python完整回归567/567（另51条外部环境测试按条件跳过），`make test-agent-e2e`跨服务黄金链路10/10；新增核心文件Ruff与格式检查通过，完整mypy 170文件通过
- 失败测试：无；Ruff格式检查仍会报告既有文件未统一格式化，本次未做跨阶段机械改写
- 当前阻塞：无外部阻塞；进入异常注入前必须先补齐知识库入库命令、统一Agent API、四个Skill生产分发和Approval页面接线
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：T754～T758新增五个单一职责模型协议适配器，将现有Prompt和业务载荷序列化为数据消息并复用公共结构化Client；非法实体、未注册动作、未知引用、候选缺失/替换和越界草稿继续由原组件拒绝，适配器不持有Tool、Approval或业务写入能力
- M7.5当前边界：页面展示当次执行证据而非当前Java业务事实；历史诊断不符合当前Schema时不会补造正文，当前仍使用offset分页且只允许本人REVIEWER，尚无审计主管跨用户视图、游标分页或操作日志聚合展示
- M7.6计划边界：T749～T781拆为模型底座、协议适配、知识入库、统一入口、只读Skill、Review/Approval和页面验收七个批次；当前完成T749～T758模型底座和协议适配，固定`/api/agent/order-diagnosis`仍是唯一生产诊断入口
- T754～T758当前边界：五类适配器已使用真实公共Client配合本地HTTP Stub验证，但尚未接入统一Agent API、生产Workflow或逐LLM Step观测上下文，也没有主动调用本地配置中的真实外部模型；后续生产编排需注入带Run/Step上下文的观测Client
- T750当前边界：能力查询只证明当前进程配置通过校验，不探测模型网络、不产生LLM Step，也不代表模型实际参与了Router、生成或Run
- 已知非阻塞问题：诊断侧边栏尚未取得和挂载Approval卡片，因而通用时间线虽支持Approval与写回事件，当前页面生产入口只能实际展示诊断Run和Tool事件；历史页可展示Run关联Approval及修改差异，但尚无独立操作日志聚合页；日志详情当前只允许原确认人读取，尚无审计主管角色或完整RBAC；只有写Tool实际开始执行后的成功、Java 409或其他写失败会生成操作日志，确认前过期或事实重校验产生的`STALE`仍只保留Approval终态；Agent与Java日志尚无统一聚合接口，只能通过Java Trace关联；当前草稿Workflow只创建`SUBMIT_REVIEW` Approval，`CREATE_REWORK` Approval的生产编排尚未接线；确认服务不重新运行RAG，引用适用性仍以草稿生成时的检索结果为准；Approval截止时间由`created_at`和当前`APPROVAL_TTL_SECONDS`计算，修改配置会影响尚未完成的旧Approval；写请求发生非业务冲突失败后进入终态`FAILED`，需要新建Approval再次授权；若进程在Java成功后、保存日志和`SUCCEEDED`前崩溃，Approval可能停在`EXECUTING`，Java幂等可防重复写但目前没有自动恢复任务；首个返工类型只覆盖黄金场景`COORDINATE_SYSTEM_FIX`；五类模型协议适配器尚未接入统一API和生产Workflow，逐LLM Step观测需要在后续生产编排中绑定Run/Step上下文；应用内浏览器仍无可用实例，M7.4和M7.5已由DOM交互、生产构建及真实代理联调验证，但尚缺真实视觉截图检查；逐LLM Step已具备模型名、输入输出Token、耗时和重试次数，但尚无生产业务路径调用，Run Token仍由上层调用方在终态汇总；默认6轮不足以完成ORDER-003所需的订单、任务、质检、复核、交付、规范检索及FINISH全链路，M5.6通过显式10轮配置完成该路径；8次Tool预算当前通常不可达，但作为独立外部调用上限保留；规范问答的安全无结论响应视为已完成检索尝试但不会形成规范结论，M6.3会拒绝据此生成Approval；全量Ruff和格式检查仍受既有文件问题影响；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互或Run/Step持久化；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验契约；权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；SSE历史只保存在单个Agent进程的有界内存中，暂不支持跨实例或进程重启续接；未预期节点异常可能遗留RUNNING Step；Tool Step仍没有重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一阶段：T759知识库全目录入库命令，复用现有文档准备、解析、Embedding和Repository，并保持启动阶段不隐式访问外部Embedding服务
