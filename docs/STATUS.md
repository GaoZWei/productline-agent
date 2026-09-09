# 当前开发状态

- 当前里程碑：M7运行观测、生产闭环集成与统一评测（进行中）
- 当前子阶段：M7.7异常注入测试进行中（场景01～08 Java与Tool故障矩阵已完成，场景09～24待开发）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T670、T701～T781，以及M7.7场景01～08
- 当前场景：订单页统一Agent抽屉通过`POST /api/agent/messages`承载状态、动态诊断、规范问答、受控澄清和Review Approval五类结果；同一订单复用Session，每轮消息及确认创建独立SSE，切换订单隔离迟到响应；Review写回与返工分别确认，固定诊断仍作为显式入口保留
- 通过测试：M7.7场景01～08执行`make test-agent-java-fault-matrix`，Java故障注入11/11、隔离Compose Agent矩阵8/8；Python Tool回归118/118，Ruff与mypy定向检查通过。DeepSeek兼容修复此前执行`make test-model-runtime test-model-adapters test-agent-messages`，Python定向48/48、65/65、26/26，隔离PostgreSQL 2/2及1/1，前端定向4/4与生产构建均通过；`deepseek-v4-flash`还完成最小JSON Object真实调用和页面原问验证。本批次未重复执行与故障矩阵无直接变更的全量检查
- 失败测试：最终无断言失败；首次Java编译缺少`MediaType`导入、首次非法JSON测试对带字符集的Content-Type使用了精确匹配，均已修正并由最终命令覆盖
- 当前阻塞：无外部阻塞；M7.7剩余场景09～24尚未开发
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M7.7场景01～08新增默认关闭、仅限只读GET的Java故障类型和参数化Agent全链路矩阵，覆盖连接失败、超时、500/403/404/409、错误JSON与字段缺失，并断言稳定错误映射、有限重试、失败Run/Step及安全提示
- M7.5当前边界：页面展示当次执行证据而非当前Java业务事实；历史诊断不符合当前Schema时不会补造正文，当前仍使用offset分页且只允许本人REVIEWER，尚无审计主管跨用户视图、游标分页或操作日志聚合展示
- M7.6当前边界：T749～T781七个批次已全部完成；统一页面能够操作四个生产Skill及Approval闭环，但真实动态调用仍依赖外部模型配置，规范问答和Review还要求知识索引为`READY`，页面能力标签不代表已探测Provider网络
- T754～T758当前边界：Router、Action、Rerank、规范回答和Review草稿适配器均已接入统一Agent API并绑定同一Run的逐LLM Step；2026-09-07已使用本地DeepSeek配置验证Router与订单状态统一入口，尚未用真实Provider逐一执行Action、Rerank、规范回答和Review草稿
- T759～T761当前边界：`make knowledge-ingest`是唯一主动访问外部Embedding的全量运维入口，本次没有可用外部密钥，真实Provider成功响应未执行；确定性Provider配合真实PostgreSQL已验证16份文档、80个唯一Chunk、重复执行、旧文档清理及索引就绪/版本不匹配状态，能力查询不读取正文或向量
- T762～T773当前边界：统一入口及四个Skill通过结构化模型Stub、Java Tool、确定性Embedding目录和真实PostgreSQL验证；缺参、冲突和意图确认继续由确定性门禁处理，Review只生成草稿，确认与返工由独立确定性API执行且都会刷新Java事实、校验版本并使用幂等写Tool
- T750当前边界：能力查询只证明当前进程配置通过校验，不探测模型网络、不产生LLM Step，也不代表模型实际参与了Router、生成或Run
- M7.7当前边界：场景01～08已完成；连接失败和超时各验证一次有限重试，其他确定性错误不重试；Java注入器默认关闭、只处理GET且不会影响写接口。Tool输入、重复动作、RAG、模型、Agent预算、Approval和SSE异常仍待场景09～24覆盖
- 已知非阻塞问题：历史页可展示Run来源和关联Approval差异，但尚无独立操作日志聚合页；日志详情当前只允许原确认人读取，尚无审计主管角色或完整RBAC；只有写Tool实际开始后的成功、Java 409或其他写失败会生成操作日志，确认前过期或事实重校验`STALE`只保留Approval/Run/Step终态；确认服务不重新运行RAG，引用适用性仍以草稿生成时检索结果为准；写失败需要新建Approval再次授权；若进程在Java成功后、保存日志和终态前崩溃，Java幂等可防重复写但目前没有自动恢复任务；返工只覆盖`COORDINATE_SYSTEM_FIX`；DeepSeek JSON Object只能保证JSON语法，Schema与业务合法性仍依赖本地校验且真实Provider尚未覆盖Action、Rerank、规范回答和Review草稿，Embedding凭据链路也未执行；浏览器技能文件在当前环境缺失，已用组件测试和Docker烟测替代，但尚缺真实浏览器视觉截图；Session/SSE仍是单进程TTL与有界内存实现；演示Header不是完整认证；Java与Python数据库角色尚未隔离
- 下一阶段：继续M7.7异常注入测试；下一最小任务是场景09～10 Tool输入参数错误与重复调用，不提前进入RAG异常或M7.8
