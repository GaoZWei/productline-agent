# 当前开发状态

- 当前里程碑：M7运行观测、生产闭环集成与统一评测（进行中）
- 当前子阶段：M7.6-A模型调用底座（T749～T750已完成，下一任务T751）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T670、T701～T750
- 当前场景：Web主导航可进入运行历史，当前`REVIEWER`分页查看自己Session下的Run；选择记录后并行读取受控详情与按序Step，展示诊断结果、Tool输入输出摘要、规范引用、Approval修改差异和失败定位，不返回消息、完整上下文、Router、版本快照或Tool原始载荷
- 通过测试：T750模型配置、能力Schema/API、版本快照及健康检查定向18/18，Python完整回归541/541（另50条外部环境测试按条件跳过），目标文件Ruff/格式与完整mypy检查通过；既有M7.5后端/API、隔离PostgreSQL、前端构建与Docker真实Web代理验证保持通过
- 失败测试：无；Ruff格式检查仍会报告既有文件未统一格式化，本次未做跨阶段机械改写
- 当前阻塞：无外部阻塞；进入异常注入前必须先补齐具体模型Provider、知识库入库命令、统一Agent API、四个Skill生产分发和Approval页面接线
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：T750新增`GET /api/agent/capabilities/model`，通过严格Schema只公开配置状态、Provider和模型名；关闭状态不保留模型身份，响应从结构上排除Base URL和API Key
- M7.5当前边界：页面展示当次执行证据而非当前Java业务事实；历史诊断不符合当前Schema时不会补造正文，当前仍使用offset分页且只允许本人REVIEWER，尚无审计主管跨用户视图、游标分页或操作日志聚合展示
- M7.6计划边界：T749～T781拆为模型底座、协议适配、知识入库、统一入口、只读Skill、Review/Approval和页面验收七个批次；当前只完成T749配置与T750安全能力查询，固定`/api/agent/order-diagnosis`仍是唯一生产诊断入口
- T749配置边界：只建立模型配置和启用条件，本地无鉴权OpenAI兼容网关允许空API Key；模型HTTP请求仍未实现
- T750当前边界：能力查询只证明当前进程配置通过校验，不探测模型网络、不产生LLM Step，也不代表模型实际参与了Router、生成或Run
- 已知非阻塞问题：诊断侧边栏尚未取得和挂载Approval卡片，因而通用时间线虽支持Approval与写回事件，当前页面生产入口只能实际展示诊断Run和Tool事件；历史页可展示Run关联Approval及修改差异，但尚无独立操作日志聚合页；日志详情当前只允许原确认人读取，尚无审计主管角色或完整RBAC；只有写Tool实际开始执行后的成功、Java 409或其他写失败会生成操作日志，确认前过期或事实重校验产生的`STALE`仍只保留Approval终态；Agent与Java日志尚无统一聚合接口，只能通过Java Trace关联；当前草稿Workflow只创建`SUBMIT_REVIEW` Approval，`CREATE_REWORK` Approval的生产编排尚未接线；确认服务不重新运行RAG，引用适用性仍以草稿生成时的检索结果为准；Approval截止时间由`created_at`和当前`APPROVAL_TTL_SECONDS`计算，修改配置会影响尚未完成的旧Approval；写请求发生非业务冲突失败后进入终态`FAILED`，需要新建Approval再次授权；若进程在Java成功后、保存日志和`SUCCEEDED`前崩溃，Approval可能停在`EXECUTING`，Java幂等可防重复写但目前没有自动恢复任务；首个返工类型只覆盖黄金场景`COORDINATE_SYSTEM_FIX`；当前只有内部Workflow和可替换模型协议，尚无具体草稿模型Provider；应用内浏览器仍无可用实例，M7.4和M7.5已由DOM交互、生产构建及真实代理联调验证，但尚缺真实视觉截图检查；M5.4尚无具体动作模型供应商，M5.7因此诚实记录`configured=false`；Run Token是调用方汇总值，尚无逐LLM Step的模型名、输入输出Token和重试明细；默认6轮不足以完成ORDER-003所需的订单、任务、质检、复核、交付、规范检索及FINISH全链路，M5.6通过显式10轮配置完成该路径；8次Tool预算当前通常不可达，但作为独立外部调用上限保留；规范问答的安全无结论响应视为已完成检索尝试但不会形成规范结论，M6.3会拒绝据此生成Approval；全量Ruff和格式检查仍受既有文件问题影响；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互、Run/Step持久化或具体问答/Rerank模型客户端；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验契约；权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；SSE历史只保存在单个Agent进程的有界内存中，暂不支持跨实例或进程重启续接；未预期节点异常可能遗留RUNNING Step；没有Step重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一阶段：T751 OpenAI兼容Chat HTTP Client，调用Chat Completions并严格校验供应商响应外壳
