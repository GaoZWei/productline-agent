# 当前开发状态

- 当前里程碑：M7运行观测、生产闭环集成与统一评测（进行中）
- 当前子阶段：M7.6-E三个只读Skill生产接线已完成（T767～T769，已到停止线；下一任务T770）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T670、T701～T769
- 当前场景：`POST /api/agent/messages`已由默认生产分发器接通确定性订单/任务状态、动态订单诊断和带引用规范问答；三者复用统一Session、Run、Step与SSE，状态和诊断业务事实只由Java只读Tool提供，规范结论只由服务端权限与日期过滤后的就绪RAG提供，Review仍明确返回`SKILL_NOT_AVAILABLE`
- 通过测试：`make test-agent-read-skills`单元与既有Workflow回归19/19、隔离PostgreSQL全目录入库及三个只读Skill统一HTTP验收1/1；`make test-agent-messages`单元/HTTP/历史兼容26/26、隔离PostgreSQL验收1/1；Python完整回归587/587（另54条外部环境测试按条件跳过），隔离PostgreSQL完整回归51/51，完整mypy 185文件通过，`make test-agent-e2e`跨服务黄金链路10/10，新增文件Ruff与格式检查、Compose静默校验及Agent镜像构建通过
- 失败测试：最终无断言失败；首次完整PostgreSQL回归发现固定诊断测试仍断言旧RAG版本`hybrid-rrf-rerank-v1`，已同步为代码当前`v2`后重跑51/51；全量Ruff格式检查仍会报告既有文件未统一格式化，本次未做跨阶段机械改写
- 当前阻塞：无外部阻塞；进入异常注入前仍需完成Review/Approval生产闭环和统一页面验收
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：T767～T769新增确定性`OrderStatusWorkflow`和生产Skill分发器，把Java只读Tool、Action模型、动态诊断、知识索引门禁、Query Embedding、Rerank及规范回答接入同一Run；嵌套AGENT、LLM、TOOL和RAG Step共享严格序号，模型Token、Tool次数和动态终止原因进入Run终态
- M7.5当前边界：页面展示当次执行证据而非当前Java业务事实；历史诊断不符合当前Schema时不会补造正文，当前仍使用offset分页且只允许本人REVIEWER，尚无审计主管跨用户视图、游标分页或操作日志聚合展示
- M7.6计划边界：T749～T781拆为模型底座、协议适配、知识入库、统一入口、只读Skill、Review/Approval和页面验收七个批次；当前完成T749～T769，三个只读Skill已进入默认生产分发器，Review和统一页面仍未接线
- T754～T758当前边界：Router、Action、Rerank和规范回答适配器已接入统一Agent API并绑定同一Run的逐LLM Step；Review草稿适配器仍待T771生产接线，本次没有主动调用本地配置中的真实外部模型
- T759～T761当前边界：`make knowledge-ingest`是唯一主动访问外部Embedding的全量运维入口，本次没有可用外部密钥，真实Provider成功响应未执行；确定性Provider配合真实PostgreSQL已验证16份文档、80个唯一Chunk、重复执行、旧文档清理及索引就绪/版本不匹配状态，能力查询不读取正文或向量
- T762～T769当前边界：统一入口及三个只读Skill通过OpenAI兼容本地HTTP Stub、Java Tool Stub、16份确定性Embedding目录和真实PostgreSQL验证，未主动调用当前环境配置的外部模型或Embedding；缺参、冲突和意图确认继续由确定性门禁处理，Review在T770～T773完成前明确失败且不会创建Approval或业务写入
- T750当前边界：能力查询只证明当前进程配置通过校验，不探测模型网络、不产生LLM Step，也不代表模型实际参与了Router、生成或Run
- 已知非阻塞问题：诊断侧边栏尚未取得和挂载Approval卡片，因而通用时间线虽支持Approval与写回事件，当前页面仍未接统一消息入口；历史页可展示Run关联Approval及修改差异，但尚无独立操作日志聚合页；日志详情当前只允许原确认人读取，尚无审计主管角色或完整RBAC；只有写Tool实际开始执行后的成功、Java 409或其他写失败会生成操作日志，确认前过期或事实重校验产生的`STALE`仍只保留Approval终态；Agent与Java日志尚无统一聚合接口，只能通过Java Trace关联；当前草稿Workflow只创建`SUBMIT_REVIEW` Approval，`CREATE_REWORK` Approval的生产编排尚未接线；确认服务不重新运行RAG，引用适用性仍以草稿生成时的检索结果为准；Approval截止时间由`created_at`和当前`APPROVAL_TTL_SECONDS`计算，修改配置会影响尚未完成的旧Approval；写请求发生非业务冲突失败后进入终态`FAILED`，需要新建Approval再次授权；若进程在Java成功后、保存日志和`SUCCEEDED`前崩溃，Approval可能停在`EXECUTING`，Java幂等可防重复写但目前没有自动恢复任务；首个返工类型只覆盖黄金场景`COORDINATE_SYSTEM_FIX`；Review草稿模型尚未绑定统一Run观测；应用内浏览器仍无可用实例，M7.4和M7.5已由DOM交互、生产构建及真实代理联调验证，但尚缺真实视觉截图检查；默认6轮不足以完成ORDER-003所需的订单、任务、质检、复核、交付、规范检索及FINISH全链路，M5.6通过显式10轮配置完成该路径；8次Tool预算当前通常不可达，但作为独立外部调用上限保留；规范问答的安全无结论响应视为已完成检索尝试但不会形成规范结论，M6.3会拒绝据此生成Approval；全量Ruff和格式检查仍受既有文件问题影响；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答尚未接页面问答交互；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验契约；权限和生效日期由服务端提供，但当前权限枚举只有`INTERNAL_REVIEWER`且只查询当前日期有效的`ACTIVE`规范，不支持历史审计as-of查询或第二权限范围；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；全量入库目前只有显式CLI，没有定时任务或HTTP管理入口，且本次未使用真实外部Embedding凭据执行成功入库；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；SSE历史只保存在单个Agent进程的有界内存中，暂不支持跨实例或进程重启续接；未预期节点异常可能遗留RUNNING Step；Tool Step仍没有重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一阶段：T770建立Review来源Run与`WAITING_CONFIRMATION`生命周期，关联最近成功诊断而不篡改来源Run终态，不提前执行Java写操作
