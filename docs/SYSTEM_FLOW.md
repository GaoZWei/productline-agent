# 系统全链路与业务分支

以2026-10-24当前代码为准。先看业务阶段和三端职责，再看统一入口，最后看两次人工确认。

便于直接查看和分享的业务流程图片见[业务流程图目录](flow/README.md)。

## 阅读说明

- 第1节虚线表示业务上应有的阶段流转；当前未实现覆盖全部阶段的自动状态机。
- 其余图的实线表示已有调用或处理分支，虚线或标注“未实现”的节点表示后续能力。
- 业务事实来自Java，模型负责路由、动作选择、规范归纳和草稿，正式诊断阶段由确定性规则判断。
- 当前“返工成功”指成功创建返工任务，不代表成果已修正、问题已关闭或订单已交付。

## 1. 订单业务阶段

```mermaid
flowchart TD
    Created["创建订单 CREATED"]
    Production["生产 PRODUCING"]
    Quality["质检 QUALITY_CHECKING"]
    Review["复核 REVIEWING"]
    Ready["交付准备 READY_FOR_DELIVERY"]
    Delivering["交付中 DELIVERING"]
    Delivered["已交付 DELIVERED"]
    ProductionBlocked["生产失败或阻塞<br/>检查失败任务和步骤"]
    OpenIssue["质量问题 OPEN / PROCESSING<br/>核查并形成处理结论"]
    PendingReview["问题RESOLVED<br/>等待复核或缺少复核记录"]
    Rework["复核要求返工 REWORK_REQUIRED<br/>走独立确认和创建返工分支"]
    Rejected["复核驳回 REJECTED"]
    Repair["实际修正成果、重新检查、关闭问题<br/>后续处理未实现"]
    DeliveryBlocked["交付未准备或失败<br/>NOT_READY / BLOCKED / FAILED"]
    DeliveryRepair["补齐交付条件或处理交付失败<br/>完整流转未实现"]
    Created -.-> Production
    Production -. "任务及步骤完成" .-> Quality
    Production -. "任务或步骤失败" .-> ProductionBlocked
    ProductionBlocked -. "排除故障后恢复：未实现" .-> Production
    Quality -. "发现未关闭问题" .-> OpenIssue
    OpenIssue -.-> Review
    Quality -. "问题已处理" .-> PendingReview
    PendingReview -.-> Review
    Quality -. "无问题且其他交付条件满足" .-> Ready
    Review -. "通过且其他交付条件满足" .-> Ready
    Review -. "要求返工" .-> Rework
    Review -. "驳回" .-> Rejected
    Rework -. "创建任务后仍需实际处理" .-> Repair
    Rejected -.-> Repair
    Repair -. "重新检查并提交复核" .-> Quality
    Ready -. "开始交付" .-> Delivering
    Ready -. "条件不足" .-> DeliveryBlocked
    Delivering -. "交付失败" .-> DeliveryBlocked
    DeliveryBlocked -.-> DeliveryRepair
    DeliveryRepair -.-> Ready
    Delivering -. "交付完成" .-> Delivered
```

- 生产任务COMPLETED只代表生产完成；问题尚未解决时可复核并要求返工，不能直接APPROVED。
- 订单BLOCKED表示受阻，不是固定的独立阶段；需要结合任务、质检、复核和交付事实判断原因。
- 当前提交复核只新增复核记录并递增任务版本，不自动关闭问题或推进订单、交付状态。

## 2. 三端职责与数据归属

```mermaid
flowchart LR
    User["用户"]
    Web["Web Console<br/>订单详情、Agent抽屉、确认卡片、运行历史"]
    Java["Java业务服务<br/>事实、权限、状态、幂等、审计及最终写入"]
    BusinessDB[("业务表<br/>订单、任务、步骤、问题、复核、返工、交付")]
    Agent["Python Agent服务<br/>上下文、路由、Workflow、RAG、Approval"]
    Tools["受控Java Tools<br/>参数、权限、资源范围、去重和超时"]
    Model["模型Provider<br/>意图、动作、重排、回答、草稿"]
    Knowledge[("知识表及向量<br/>文档、版本、Chunk、Embedding")]
    Runtime[("Agent运行表<br/>Session、Message、Run、Step、Approval、操作日志")]
    User --> Web
    Web -->|"列表及overview"| Java
    Java --> BusinessDB
    Web -->|"消息、确认、取消、返工确认单"| Agent
    Agent --> Tools
    Tools -->|"HTTP；写入必须经过人工确认"| Java
    Agent --> Model
    Agent --> Knowledge
    Agent --> Runtime
    Agent -->|"SSE及结构化结果"| Web
```

图中按表职责分组；当前本地环境可使用同一PostgreSQL实例，数据库角色尚未完整隔离。
Python运行时代码通过Java Tool取得业务事实，不直接查询Java业务表。

### 业务对象实际关联

```mermaid
flowchart LR
    Order["订单 Order"]
    Task["生产任务 ProductionTask<br/>含version"]
    Step["生产步骤 ProductionStep"]
    Issue["质检问题 QualityIssue"]
    ReviewRecord["复核记录 ReviewRecord"]
    ReworkTask["返工任务 ReworkTask"]
    Delivery["交付记录 DeliveryRecord"]
    Order -->|"一对多"| Task
    Order -->|"一对多"| Delivery
    Task -->|"一对多"| Step
    Task -->|"一对多"| Issue
    Task -->|"一对多"| ReworkTask
    Issue -->|"一对多，可保留多次复核"| ReviewRecord
    Issue -->|"来源问题"| ReworkTask
```

当前没有单独实现QualityTask或DeliveryBatch业务实体。

## 3. 页面与统一Agent入口

```mermaid
flowchart TD
    Open["打开订单页"]
    List["Java GET /api/orders<br/>加载目录，页面搜索与分类"]
    Overview["选择订单，默认ORDER-003<br/>Java GET /api/orders/订单号/overview"]
    Display["展示任务、步骤、问题、复核、已有返工和交付"]
    Message["发送消息 POST /api/agent/messages"]
    Session{"Session有效且属于当前用户？"}
    SessionError["不存在、过期或归属错误<br/>拒绝，不分发Skill"]
    Run["保存本轮Message和Run<br/>加载页面及已确认会话上下文"]
    Router["模型识别意图与提取参数<br/>代码校验原文依据、来源合并和路由门禁"]
    Dispatch{"是否可分发？"}
    Clarify["CLARIFICATION<br/>缺参、多候选、意图不明或置信度不足等"]
    Mismatch["PAGE_ORDER_MISMATCH<br/>诊断目标与页面订单不同"]
    Continue["用户补充或选择受控候选<br/>下一请求重新经过门禁"]
    Switch["确认切换：先加载Java目标订单<br/>成功后切页并用新Session继续"]
    Status["状态查询 OrderStatusSkill"]
    Diagnosis["动态诊断 DiagnosisSkill"]
    Specification["规范问答 SpecificationSkill"]
    Review["复核草稿 ReviewSkill"]
    Fixed["固定诊断按钮<br/>POST /api/agent/order-diagnosis"]
    FixedWorkflow["固定Workflow依次读取Java事实<br/>规则判断阶段；保存Run/Step"]
    Open --> List --> Overview --> Display
    Display --> Message --> Session
    Session -->|"否"| SessionError
    Session -->|"是；无Session则按契约新建"| Run
    Run --> Router --> Dispatch
    Dispatch -->|"普通澄清"| Clarify --> Continue --> Message
    Dispatch -->|"跨订单诊断"| Mismatch
    Mismatch -->|"确认"| Switch --> Message
    Mismatch -->|"取消或目标加载失败"| Display
    Dispatch -->|"订单查询或任务跟踪"| Status
    Dispatch -->|"订单诊断"| Diagnosis
    Dispatch -->|"规范问题"| Specification
    Dispatch -->|"复核草稿"| Review
    Display --> Fixed --> FixedWorkflow
```

同一订单连续对话复用Session，每轮执行仍有独立Run。切换订单清理旧Session/SSE上下文，迟到响应不能覆盖新订单。

### 状态查询的两个分支

```mermaid
flowchart LR
    Intent{"路由意图"}
    OrderTool["ORDER_QUERY<br/>get_order_detail"]
    TaskTool["TASK_TRACKING<br/>get_task_detail"]
    JavaRead["Java只读接口"]
    Result["ORDER_STATUS结果<br/>用Java字段生成确定性状态摘要"]
    Error["参数、权限、资源、上游或响应校验错误<br/>记录失败步骤并返回错误"]
    Intent -->|"订单状态"| OrderTool
    Intent -->|"任务状态"| TaskTool
    OrderTool --> JavaRead
    TaskTool --> JavaRead
    JavaRead -->|"合法响应"| Result
    JavaRead -->|"失败"| Error
```

路由可能调用模型，状态值和摘要由Java事实及代码生成。

## 4. 动态诊断与阶段判断

```mermaid
flowchart TD
    Init["初始化目标、页面范围及调用账本"]
    Round{"达到6轮决策上限？"}
    Plan["模型选择下一步只读动作"]
    Gate{"动作、Schema、权限和资源范围合法？"}
    Limit{"达到8次Tool上限<br/>或动作指纹重复？"}
    Execute["执行只读动作<br/>订单、关联任务、进度、问题、复核、交付或规范检索"]
    Observe["保存Observation、Tool账本和Step"]
    Check["代码检查：还缺哪些事实或规范"]
    Stop{"错误或无新增信息等<br/>是否需要结束？"}
    Reason["记录真实终止原因<br/>预算、主动结束、无新增信息或执行错误"]
    Facts{"生成结果时信息是否充分？"}
    Rules["用已加载Java事实判断正式阶段<br/>生成根因、字段证据与建议"]
    Insufficient["INSUFFICIENT_INFORMATION<br/>保留缺口及终止原因"]
    Safety["异常安全出口<br/>不把调用失败编成业务根因"]
    Init --> Round
    Round -->|"否"| Plan --> Gate
    Round -->|"是"| Reason
    Gate -->|"不合法"| Safety --> Reason
    Gate -->|"合法，FINISH"| Reason
    Gate -->|"合法，只读动作"| Limit
    Limit -->|"达到预算或重复"| Reason
    Limit -->|"允许执行"| Execute --> Observe --> Check --> Stop
    Stop -->|"继续"| Round
    Stop -->|"结束"| Reason
    Reason --> Facts
    Facts -->|"充分"| Rules
    Facts -->|"不足或存在相关错误"| Insufficient
```

达到预算时若所需事实已收齐，仍可返回有依据诊断，同时保留MAX_ITERATIONS等真实原因；不能声称模型主动FINISH。
复杂多任务可能在预算内收不齐事实，不能补造事实或取消信息门禁。

### 正式阶段判断的优先级

```mermaid
flowchart TD
    Complete{"所需事实充分？"}
    PF{"任务或步骤存在<br/>FAILED / BLOCKED？"}
    PA{"任务或步骤存在<br/>PENDING / RUNNING？"}
    QI{"问题存在<br/>OPEN / PROCESSING？"}
    RR{"存在未通过复核<br/>或RESOLVED问题缺少通过复核？"}
    DR{"交付记录存在<br/>NOT_READY / FAILED / BLOCKED？"}
    I["INSUFFICIENT_INFORMATION"]
    PB["PRODUCTION_BLOCKED<br/>生产阻塞"]
    P["PRODUCTION<br/>生产阶段"]
    Q["QUALITY_REVIEW<br/>质量复核"]
    R["REVIEW<br/>复核阶段"]
    D["DELIVERY<br/>交付阶段"]
    N["NONE<br/>无阻塞，不等于已交付"]
    Complete -->|"否"| I
    Complete -->|"是"| PF
    PF -->|"是"| PB
    PF -->|"否"| PA
    PA -->|"是"| P
    PA -->|"否"| QI
    QI -->|"是"| Q
    QI -->|"否"| RR
    RR -->|"是"| R
    RR -->|"否"| DR
    DR -->|"是"| D
    DR -->|"否"| N
```

动态诊断按场景检查缺口，固定诊断要求完整事实集合。当前复核规则会检查已加载的非APPROVED记录，没有“只取最新记录”的自动覆盖机制。
ORDER-026正在交付、ORDER-027已交付，都可能得到NONE，需要结合交付记录区分。

## 5. 知识入库与规范问答

### 显式入库：不会因页面查询自动全量重建

```mermaid
flowchart LR
    CLI["显式执行knowledge-ingest"]
    Source["读取规范目录、版本、适用日期及权限"]
    Chunk["文档校验、分块和固定Chunk身份"]
    Embedding["Embedding Provider分批生成向量"]
    DB["事务更新文档、Chunk及向量"]
    Ready["核对模型、维度、索引版本和文档数量<br/>READY能力查询"]
    Fail["失败保留旧已提交数据<br/>本次不提交部分新数据"]
    CLI --> Source --> Chunk --> Embedding
    Embedding -->|"全部成功"| DB
    Embedding -->|"失败"| Fail
    DB -->|"事务提交"| Ready
    DB -->|"失败回滚"| Fail
```

### 在线检索与回答

```mermaid
flowchart TD
    Question["规范问题<br/>也可来自诊断或复核Workflow"]
    Ready{"索引身份和状态可用？"}
    Rewrite["确定性规范化查询<br/>服务端适用日期、权限及版本过滤"]
    Keyword["关键词召回"]
    Vector["查询Embedding及向量召回"]
    RRF["RRF按名次融合、去重及截取候选"]
    Rerank["模型重排<br/>独立超时预算"]
    Gate{"重排可用且有候选？"}
    Generate["模型根据候选生成回答和引用ID"]
    Cite{"输出Schema及引用白名单合法？"}
    Answer["ANSWERED<br/>正文、文档版本、章节和Chunk引用"]
    Error["索引或上游错误<br/>不形成规范结论"]
    Safe["安全回答<br/>无证据：INSUFFICIENT_CONTEXT<br/>重排降级：RERANK_UNAVAILABLE"]
    Invalid["GENERATION_FAILED<br/>不返回失败模型文案或候选引用"]
    Question --> Ready
    Ready -->|"否"| Error
    Ready -->|"是"| Rewrite
    Rewrite --> Keyword
    Rewrite --> Vector
    Keyword --> RRF
    Vector --> RRF
    RRF --> Rerank --> Gate
    Gate -->|"否"| Safe
    Gate -->|"是"| Generate --> Cite
    Cite -->|"是"| Answer
    Cite -->|"否或生成失败"| Invalid
    Keyword -->|"检索失败"| Error
    Vector -->|"检索失败"| Error
    Rerank -->|"非超时失败，关闭失败"| Error
```

已校验引用是否来自本次候选集合；尚未实现逐句语义证据绑定、完整的“引用是否支持每句话”检查及自动历史引用迁移。
重排超时降级提供安全答复，不取消证据门禁。

## 6. 复核草稿与独立返工确认

```mermaid
flowchart TD
    Request["用户请求生成复核草稿"]
    Source{"同Session有合法成功来源诊断？"}
    Error["停止并返回错误<br/>不生成可执行确认单"]
    Refresh["新Run读取Java任务和问题<br/>校验目标属于来源诊断订单"]
    RAG["检索当前适用规范<br/>必须有可用回答和引用"]
    Draft["模型生成ReviewDraft<br/>问题、结论、意见、返工建议、规范引用"]
    Validate{"Schema、问题归属及引用合法？"}
    Save["保存草稿和任务版本<br/>SUBMIT_REVIEW Approval等待确认"]
    User{"用户操作"}
    Cancel["取消确认单，不写Java"]
    Confirm["复核确认<br/>进入第7节公共写入门禁"]
    Result{"复核写入成功？"}
    Fail["保留失败或失效状态<br/>不自动重发业务写入"]
    Need{"已成功确认的草稿要求返工？"}
    Done["结束本次复核，不创建返工"]
    Create["用户显式创建返工确认单<br/>从成功SUBMIT_REVIEW证据派生"]
    Approval["独立新Run及CREATE_REWORK Approval<br/>绑定复核写入后的任务版本"]
    Choice{"第二次人工确认"}
    Write["再次经过第7节门禁<br/>Java创建PENDING返工任务"]
    Stop["取消或暂不处理，不执行返工写入"]
    Future["实际修正成果、关闭问题、再次复核及最终交付<br/>后续处理未实现"]
    Request --> Source
    Source -->|"否"| Error
    Source -->|"是"| Refresh --> RAG --> Draft --> Validate
    Refresh -->|"事实错误"| Error
    RAG -->|"证据不足或失败"| Error
    Validate -->|"否"| Error
    Validate -->|"是"| Save --> User
    User -->|"编辑后确认"| Confirm --> Result
    User -->|"取消"| Cancel
    User -->|"暂不处理"| Save
    Result -->|"否"| Fail
    Result -->|"是"| Need
    Need -->|"否"| Done
    Need -->|"是，用户选择创建"| Create --> Approval --> Choice
    Choice -->|"确认"| Write
    Choice -->|"取消或暂不处理"| Stop
    Write -. "创建任务不等于完成处理" .-> Future
```

复核草稿生成时只读Java；创建第二张返工Approval也不等于已经创建Java返工任务，两次人工确认互不代替。
相同成功复核已有对应返工Approval时复用已有结果。当前Agent返工类型仅COORDINATE_SYSTEM_FIX，非坐标系场景本轮只读验证。

## 7. 公共写入门禁与失败分支

```mermaid
flowchart TD
    Click["用户点击复核或返工确认"]
    Owner["校验身份、权限和确认单归属"]
    Status{"确认单状态"}
    Replay["SUCCEEDED且确认人及草稿一致<br/>返回已有结果"]
    Reject["执行中或其他不可确认状态<br/>冲突或拒绝，不再写入"]
    Expiry{"确认窗口已过期？"}
    Expired["EXPIRED，不执行写入"]
    Confirmed["保存最终草稿及确认人<br/>WAITING_CONFIRMATION → CONFIRMED"]
    Fresh["重读Java任务和问题<br/>核对版本、COMPLETED、归属、问题状态及返工类型"]
    Stale["STALE，需基于最新事实重新生成"]
    Lock{"数据库条件更新<br/>CONFIRMED → EXECUTING成功？"}
    Write["唯一执行者调用写Tool<br/>幂等键及expectedVersion"]
    Java["Java最终校验<br/>权限、幂等、版本、状态、归属、重复返工"]
    Transaction["同一Java事务<br/>新增复核或返工、版本递增、幂等结果、审计"]
    Success["保存SUCCEEDED及操作日志<br/>完成Run/Step并推送事件"]
    Failure["按错误保存STALE或FAILED<br/>记录适用的写入失败日志"]
    Click --> Owner --> Status
    Status -->|"已成功且相同确认"| Replay
    Status -->|"EXECUTING或已取消、失败、失效、过期等"| Reject
    Status -->|"等待确认或已确认待执行"| Expiry
    Expiry -->|"是"| Expired
    Expiry -->|"否，首次确认"| Confirmed --> Fresh
    Expiry -->|"否，同一已确认草稿"| Fresh
    Fresh -->|"事实变化或不满足条件"| Stale
    Fresh -->|"通过且再次确认未过期"| Lock
    Lock -->|"否"| Reject
    Lock -->|"是"| Write --> Java
    Java -->|"通过"| Transaction
    Java -->|"拒绝或失败"| Failure
    Transaction -->|"提交成功"| Success
    Transaction -->|"失败回滚"| Failure
```

- EXECUTING由Python确认服务通过数据库条件更新设置；只有抢到执行权的请求才调用写Tool。
- Java用expectedVersion和幂等记录防重复；同一键不同请求内容会冲突。
- 复核要求任务COMPLETED、问题属于任务且未CLOSED；APPROVED只能用于RESOLVED问题。
- 返工要求问题未CLOSED；同任务、同问题已有PENDING/RUNNING/BLOCKED返工时拒绝重复创建。
- 到期检查发生在相关请求中，不表示存在后台定时扫描。确认前不重新运行RAG，规范适用性仍以草稿生成时检索为准。
- Python与Java没有跨服务原子事务。Java提交后若Python崩溃，幂等可防重复写；当前没有自动恢复任务。

## 8. 可观测性与异常处理

```mermaid
flowchart LR
    Work["消息、固定诊断、确认及返工执行"]
    Run["Run<br/>状态、结果、错误、真实终止原因"]
    Step["Step<br/>上下文、路由、模型、Tool、RAG、等待确认、写入"]
    Events["SSE有界订阅及有限重放"]
    Page["页面实时步骤"]
    History["持久化历史页<br/>详情、Step、耗时、失败位置"]
    Disconnect["断线或慢消费者<br/>重连可补有限保留事件，不取消Run"]
    Timeout["页面请求等待超时<br/>查询历史，不自动重发写入"]
    Error["权限、参数、资源、超时、上游或响应校验错误"]
    Safe["对应层停止或安全降级<br/>保存已有记录；初始化失败可能无Run"]
    Work --> Run
    Work --> Step
    Work --> Events --> Page
    Run --> History
    Step --> History
    Events --> Disconnect
    Page --> Timeout --> History
    Work --> Error --> Safe --> History
```

- SSE及Session运行上下文包含单进程TTL和有界内存能力，持久化Run历史不等于无限事件重放。
- 只读Java Tool只对明确瞬时错误有限重试；参数、权限、资源或响应不合法不能靠重试绕过。
- 写Tool实际开始后适用的成功或失败才产生对应操作日志；确认前取消、过期或STALE主要看Approval、Run与Step。
- 确认阶段顶部Tool计数存在遗漏，人工等待计入部分Run耗时；分析时结合WRITEBACK Step和Java审计。

## 9. 30单场景对应的验证分支

| 分支 | 代表订单 | 用途及边界 |
| --- | --- | --- |
| 无任务 | 006 | 事实不足 |
| 生产中 | 001、007、008、010 | 未开始、多步骤运行、部分任务未完成 |
| 生产阻塞 | 002、009、011 | 失败步骤与多任务阻塞 |
| 单坐标系问题 | 003、012 | 质检、复核与返工；003当前已有人工返工，012满足从头演示的基础数据条件 |
| 非坐标系问题 | 013～015、019 | 云量、几何、辐射等，只读验证 |
| 同任务多问题 | 016、017 | 其他问题已关闭不代表当前未关闭问题可放行 |
| 多任务预算 | 018、023、030 | 缺口未齐保留信息不足与真实终止原因 |
| 复核未通过或缺失 | 004、020～023 | PENDING、REJECTED、REWORK_REQUIRED、缺少记录 |
| 交付准备或失败 | 024、025、028 | 未准备、失败、多交付记录 |
| 无阻塞 | 005、026、027 | 区分可交付、交付中、已交付 |
| 已有返工 | 029、030；当前003 | PENDING、RUNNING、COMPLETED，不把创建任务当成实际修复完成 |

固定数据见[DEMO_DATA](DEMO_DATA.md)，历史真实演示见[AGENT_DEMO_FLOW](AGENT_DEMO_FLOW.md)。
本图未新增真实模型调用；场景覆盖和受控测试不代表真实模型准确率。

## 10. 核心代码索引

| 文件 | 职责 |
| --- | --- |
| [BusinessQueryService.java](../business-service/src/main/java/com/productline/business/application/BusinessQueryService.java) | Java目录与详情事实聚合 |
| [BusinessWriteService.java](../business-service/src/main/java/com/productline/business/application/BusinessWriteService.java) | 最终权限、版本、幂等、复核及返工写入 |
| [orderStore.ts](../web-console/src/stores/orderStore.ts) | 订单加载与迟到响应隔离 |
| [AgentWorkspaceDrawer.vue](../web-console/src/components/AgentWorkspaceDrawer.vue) | 消息、切页、SSE和人工确认 |
| [agent_messages.py](../agent-service/app/services/agent_messages.py) | Session/Run、上下文路由、澄清与分发 |
| [production_agent_skills.py](../agent-service/app/services/production_agent_skills.py) | 四个Skill的生产装配 |
| [order_status.py](../agent-service/app/workflows/order_status.py) | 订单查询与任务跟踪 |
| [dynamic_diagnosis.py](../agent-service/app/workflows/dynamic_diagnosis.py) / [diagnosis_rules.py](../agent-service/app/workflows/diagnosis_rules.py) | 动作循环、信息缺口与正式阶段 |
| [specification_qa.py](../agent-service/app/workflows/specification_qa.py) | 规范检索、重排、回答及引用门禁 |
| [knowledge_ingestion.py](../agent-service/app/services/knowledge_ingestion.py) | 知识入库与失败保留旧数据 |
| [review_draft.py](../agent-service/app/workflows/review_draft.py) | 来源诊断、最新事实、规范及草稿 |
| [approval_orchestration.py](../agent-service/app/services/approval_orchestration.py) | 取消及独立返工确认单 |
| [approval_confirmation.py](../agent-service/app/services/approval_confirmation.py) | 确认、过期/失效、执行权及写Tool |
