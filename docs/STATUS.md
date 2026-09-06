# 当前开发状态

- 当前里程碑：M7运行观测、生产闭环集成与统一评测（进行中）
- 当前子阶段：M7.6-F Review与Approval生产闭环已完成（T770～T773，已到停止线；下一任务T774）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T670、T701～T773
- 当前场景：`POST /api/agent/messages`已接通四个业务Skill；Review会创建关联最近成功诊断的新Run，刷新Java事实和带版本规范后返回`WAITING_CONFIRMATION`草稿，确认/取消/过期/STALE/写回终态同步Run与Step；复核成功后可通过显式API创建独立`CREATE_REWORK` Approval，未确认和取消均不调用Java写接口
- 通过测试：`make test-agent-review`单元43/43、隔离PostgreSQL定向3/3、前端17/17；Python完整回归589/589（另55条外部环境测试按条件跳过），隔离PostgreSQL完整回归52/52，完整mypy 187文件通过，前端类型检查及Review/历史定向19/19，`make test-agent-e2e`跨服务黄金链路10/10，本次新增及可独立校验文件Ruff检查通过
- 失败测试：最终无断言失败；首次跨服务回归暴露旧M6测试夹具未创建等待Run与Approval Step，已按生产生命周期修正并重跑10/10；全量Ruff仍会报告既有文件中文全角标点和格式问题，本次未做跨阶段机械改写
- 当前阻塞：无外部阻塞；进入异常注入前仍需完成M7.6-G统一页面验收
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：T770～T773把Review草稿模型接入生产分发器，新增Review/返工Run来源关系、等待确认观测、确认/取消终态联动及独立返工Approval API；APPROVAL与WRITEBACK Step和操作日志跟随CAS执行结果原子收敛，来源诊断Run不再被后续审批改写
- M7.5当前边界：页面展示当次执行证据而非当前Java业务事实；历史诊断不符合当前Schema时不会补造正文，当前仍使用offset分页且只允许本人REVIEWER，尚无审计主管跨用户视图、游标分页或操作日志聚合展示
- M7.6计划边界：T749～T781拆为模型底座、协议适配、知识入库、统一入口、只读Skill、Review/Approval和页面验收七个批次；当前完成T749～T773，四个Skill及Approval后端闭环已接线，统一抽屉页面仍待M7.6-G
- T754～T758当前边界：Router、Action、Rerank、规范回答和Review草稿适配器均已接入统一Agent API并绑定同一Run的逐LLM Step；本次没有主动调用本地配置中的真实外部模型
- T759～T761当前边界：`make knowledge-ingest`是唯一主动访问外部Embedding的全量运维入口，本次没有可用外部密钥，真实Provider成功响应未执行；确定性Provider配合真实PostgreSQL已验证16份文档、80个唯一Chunk、重复执行、旧文档清理及索引就绪/版本不匹配状态，能力查询不读取正文或向量
- T762～T773当前边界：统一入口及四个Skill通过结构化模型Stub、Java Tool、确定性Embedding目录和真实PostgreSQL验证；缺参、冲突和意图确认继续由确定性门禁处理，Review只生成草稿，确认与返工由独立确定性API执行且都会刷新Java事实、校验版本并使用幂等写Tool
- T750当前边界：能力查询只证明当前进程配置通过校验，不探测模型网络、不产生LLM Step，也不代表模型实际参与了Router、生成或Run
- 已知非阻塞问题：统一Agent抽屉尚未接入消息入口和Approval卡片，取消与返工客户端虽已具备但页面按钮编排待M7.6-G；历史页可展示Run来源和关联Approval差异，但尚无独立操作日志聚合页；日志详情当前只允许原确认人读取，尚无审计主管角色或完整RBAC；只有写Tool实际开始后的成功、Java 409或其他写失败会生成操作日志，确认前过期或事实重校验`STALE`只保留Approval/Run/Step终态；确认服务不重新运行RAG，引用适用性仍以草稿生成时检索结果为准；Approval截止时间由`created_at`和当前配置计算；写失败需要新建Approval再次授权；若进程在Java成功后、保存日志和终态前崩溃，Java幂等可防重复写但目前没有自动恢复任务；返工只覆盖`COORDINATE_SYSTEM_FIX`；本次未用真实外部模型或Embedding凭据执行Review；应用内浏览器仍无可用实例，尚缺真实视觉截图检查；全量Ruff仍受既有文件问题影响；规范问答尚未接页面交互；Session/SSE仍是单进程TTL与有界内存实现；演示Header不是完整认证；Java与Python数据库角色尚未隔离
- 下一阶段：T774实现五类统一结果视图映射，让状态、诊断、规范回答、澄清和Approval结果在同一Agent抽屉中可展示
