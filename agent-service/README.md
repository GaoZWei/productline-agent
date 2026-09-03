# Agent Service

M3 Python 3.12/FastAPI 服务。当前包含工程基础、Agent 自有数据库连接、结构化日志、
调用 Java 的共享异步 HTTP Client、标准 Tool 错误映射、Tool 基础协议和七个只读业务 Tool；
只读 Tool 已具备显式有限退避重试、Run 内重复调用检测和仅开发环境启用的调试 API。当前还
包含 Session/Message/Run/Step 模型、Alembic迁移、Repository、最小Run/Step生命周期和
Workflow状态/诊断Schema、严格页面与会话上下文、稳定意图与路由Prompt契约、固定LangGraph数据加载节点、
确定性阻塞阶段规则、诊断文案生成和对外诊断API；路由和诊断模型均使用可注入结构化接口，公共OpenAI兼容
Chat Client及五类业务模型适配器已经可发出严格结构化请求，但尚未接入统一路由HTTP入口。M4.2已加入严格知识元数据Schema、文档/分块ORM、pgvector和
全文检索字段；M4.3已实现确定性文档加载和分块，M4.4已实现OpenAI兼容Embedding、批处理、有限重试、
固定1536维pgvector入库和索引版本记录，M4.5～M4.12已实现中文关键词、同版本余弦检索、统一元数据门禁、
RRF混合排序、可降级模型重排、引用结构、固定规范问答图和四策略RAG评测；M7.6-C又提供显式全目录入库命令和
索引就绪查询，但尚未接入统一路由HTTP入口。M5.1～M5.4已扩展动态诊断状态、实现结构化动作决策、可回环LangGraph执行图和
确定性执行限制，但尚无具体动作模型供应商。M6.1～M6.8已加入Approval生命周期、严格复核草稿、安全草稿生成、
执行结果持久化、不暴露给动态模型的复核/返工写Tool、确认HTTP接口、与终态原子提交的Agent操作日志，以及覆盖
未确认、修改、重复、取消、过期、事实变化、无权限和Java异常的安全验收矩阵。

## 本地开发

uv 会按照 `.python-version` 安装/选择 Python 3.12，并根据 `uv.lock` 创建 `.venv`：

```bash
cd agent-service
uv sync --frozen
uv run python -m app.main
```

默认健康检查为 <http://localhost:8000/health>。可使用 `PORT`、`ENVIRONMENT`、
`LOG_LEVEL`、`DATABASE_URL`、`BUSINESS_SERVICE_URL`、四项`BUSINESS_*_TIMEOUT_SECONDS`和
`SESSION_TTL_SECONDS`和`APPROVAL_TTL_SECONDS`覆盖会话及确认单有效期，后者默认900秒。启用Embedding生成时还需设置`EMBEDDING_API_KEY`；Provider、模型、
Base URL、1536维度、批大小、超时、重试和索引版本均可通过对应`EMBEDDING_*`变量配置。

结构化对话模型默认关闭：`MODEL_NAME`为空时，即使预先提供地址或密钥也不会被标记为已配置。启用时必须同时提供
`MODEL_BASE_URL`，`MODEL_PROVIDER`固定为`openai_compatible`并兼容旧值`openai`；本地无鉴权网关允许
`MODEL_API_KEY`为空，非空密钥使用`SecretStr`保存且不得进入日志或版本快照。调用超时、额外重试次数和指数退避可通过
`MODEL_TIMEOUT_SECONDS`、`MODEL_MAX_RETRIES`、`MODEL_INITIAL_BACKOFF_SECONDS`及
`MODEL_MAX_BACKOFF_SECONDS`设置；默认只额外重试一次明确瞬时失败。

T750提供`GET /api/agent/capabilities/model`查询安全的模型配置能力。模型关闭时返回
`{"configured":false,"provider":null,"model_name":null}`；启用时只增加Provider和模型名，不返回Base URL或
API Key。该结果只证明配置通过校验，不探测模型网络，也不代表某次Run已经调用模型。

## 结构化模型调用与LLM Step

`app.clients.model.OpenAICompatibleChatClient`复用应用生命周期内的HTTP连接池，调用OpenAI兼容
`POST /chat/completions`并使用`response_format=json_schema`请求严格结构化输出。供应商成功响应必须包含唯一选择、
助手JSON正文和自洽Token用量，正文还要通过调用方Pydantic Schema；未配置、超时、瞬时上游失败、限流、鉴权、
非法请求、响应外壳错误及输出JSON/Schema错误使用稳定机器码区分，异常文案不会复制供应商响应。

只有超时、网络错误、HTTP 408/425/429及5xx会按配置有限退避重试，参数、鉴权、非法响应和非法结构化输出不会重试。
`ObservedModelInvoker`在真实请求边界创建`LLM` Step，成功时保存供应商实际返回的模型名、输入/输出/总Token、耗时和
实际重试次数，失败时保存稳定错误码及能够确认的配置模型名与重试次数；Prompt、模型正文、API Key和供应商错误正文
均不进入Step。Run历史接口和页面会展示这些独立指标；具体Protocol适配器见下节，但尚未装配到统一生产入口，因此固定诊断仍不调用该Client。

## 现有模型Protocol适配器

`app.model_adapters`在公共Client之上分别实现Router、动态Action、规范回答、Rerank和Review草稿五个既有Protocol。
Router和Action适配器原样复用已有版本化System Prompt与JSON数据载荷，并拒绝Prompt声明的响应Schema与唯一Pydantic
契约漂移；另外三个适配器使用各自版本化指令，只把对应请求数据转换为两条Chat消息，不共享业务语义。

适配器只返回已经过公共Client校验的`RouterResult`、`ActionDecision`、`SpecificationAnswerDraft`、`RerankResponse`
或`ReviewDraft`候选。用户原文实体证据、注册表LOW风险和资源身份、citation_id白名单、全部候选覆盖以及草稿任务、问题、
引用白名单仍由原组件二次校验；Review适配器不会取得Tool、Store或Approval执行入口。当前五个适配器可由内部组件注入，
但统一Agent HTTP入口和生产Skill装配仍留在M7.6-D～F，因此固定诊断API的行为不变。

## 知识库全量入库与就绪能力

M7.6-C把现有catalog校验、UTF-8 Loader、标题分块、批量Embedding和`KnowledgeIndexRepository`串成
`KnowledgeIngestionService`。服务会先在内存完成16份文档、80个Chunk和全部向量的校验，全部成功后才在调用方
事务中清理目录外旧文档并替换当前目录的Chunk；重复执行得到相同Chunk身份，不会追加重复记录。

入库只通过显式运维命令触发，Agent启动和能力查询都不会访问Embedding Provider：

```bash
# 在根目录.env中配置EMBEDDING_API_KEY及需要覆盖的EMBEDDING_*参数后执行
make knowledge-ingest
```

命令会确保PostgreSQL已启动、执行Alembic迁移、构建包含`/knowledge-base`的Agent镜像，再运行一次全量入库。
成功时只输出文档数、Chunk数、清理数量和非敏感索引身份；目录/配置错误、Embedding错误和持久化错误分别使用
退出码2、3和4，输出不包含正文、向量、密钥或供应商响应。

`GET /api/agent/capabilities/knowledge-index`只读取文档级统计，返回`NOT_INDEXED`、`INCOMPLETE`、
`INDEX_MISMATCH`或`READY`。只有数据库中的文档身份与当前16份catalog完全一致、每份文档至少有一个Chunk，且
所有文档的Provider、模型、1536维度和索引版本均与当前配置一致时才返回`ready=true`；该查询不会探测外部网络。

## Java HTTP Client

`app.clients.business.BusinessHttpClient` 在 FastAPI lifespan 中创建和关闭，共享连接池，
通过 `BusinessIdentity` 透传用户、角色和可选 Bearer Token，并自动透传当前 Trace ID。
GET 和 POST 成功响应必须同时通过 Java 六字段信封与调用方提供的 Pydantic data Schema；
Java 400/401/403/404/409/500、httpx 网络/超时异常和响应契约错误统一转换为
`ToolException`。POST 强制提供安全格式的幂等键。

Client 显式使用 `trust_env=False`，避免内部服务流量被宿主机 HTTP/SOCKS 代理劫持。Client
自身不重试，只负责把上游失败转换为带 `retryable` 的 `ToolException`；是否重试由具体 Tool
显式绑定的 `RetryPolicy` 决定，避免未来写 Tool 因共享 Client 行为而被意外重放。

## Tool 基础协议

`app.tools.BaseTool` 统一声明名称、说明、Pydantic 输入/输出模型、风险等级、所需权限、整体
超时和最大重试次数。公共 `execute` 先检查权限和输入 Schema，再在整体超时内调用具体 Tool
的 `_execute`，最后校验输出 Schema。标准 `ToolException`、超时、非法输出和未知异常都会
转换为互斥的 `ToolResult(success, data, error)`，未知异常的内部详情只写入结构化日志。

`ToolContext` 携带 `BusinessIdentity`、权限集合、Trace ID、Run ID 和不序列化的内存调用账本。
`ToolRegistry` 按稳定
名称注册和获取 Tool，重复名称会被拒绝而不会静默覆盖。`max_retries` 表示首次调用之外允许的
额外调用次数；只有显式提供 `RetryPolicy` 的 Tool 才会实际重试。M2.1 已建立 Run/Step
持久化基础，但当前 Tool 调试链尚未写入这些表；M6 Approval由独立Workflow和存储服务管理，不经过调试API。

## 人工确认与写 Tool

`ReviewDraft`同时绑定`task_id`和`issue_id`。草稿生成Workflow会强制刷新Java任务和质检问题，只允许模型选择
本次结果中真实存在的问题；用户修改仍需通过同一Schema，并且不能换掉Approval的目标任务。

`write_review_result`和`create_rework_task`只接受`approval_id`与`idempotency_key`，任务、问题、结论、意见和
期望版本全部读取已确认的Approval快照。Tool要求Approval处于`EXECUTING`、待执行名称匹配且调用人就是确认人，
再以Java Client透传身份、Trace和幂等键；Java返回的资源归属、内容及递增版本必须与快照一致，成功摘要才会首次
保存到`execution_result`。幂等重放返回相同业务结果时保留首次Trace，内容不同则拒绝覆盖审计证据。

两个写Tool均为`HIGH`风险、`max_retries=0`，并放在单独的写Tool注册表中，不注册到动态Agent或开发调试API。
`POST /api/agent/approvals/{approval_id}/confirm`接收页面最终ReviewDraft和身份Header，先原子保存修改副本与确认人，
再强制调用`get_task_detail`和`get_quality_issues`刷新Java事实。任务版本或状态、问题归属/状态、坐标系返工类型变化时
进入`STALE`，超时进入`EXPIRED`；只有数据库CAS成功把`CONFIRMED`改为`EXECUTING`的请求才能执行写Tool，随后进入
`SUCCEEDED`或`FAILED`。重复提交已成功的同一确认会读取并返回首次`execution_result`，不会再次调用Java。

当前确认服务按`REVIEWER`演示角色重新构造只读及写权限，Java仍执行最终角色、任务状态、版本和幂等校验。确认前
重校验当前不重新运行RAG；前端已有确认请求客户端，但诊断侧边栏尚未取得和挂载Approval卡片。

确认执行结束时会把最终授权摘要、Java结果或失败机器摘要、用户相对模型原始草稿的字段级修改，以及成功响应的
Java Trace写入`agent_operation_logs`。日志创建与Approval从`EXECUTING`进入`SUCCEEDED`、`STALE`或`FAILED`使用
同一数据库事务，每个Approval最多一条；规范引用只保存文档、版本和Chunk身份，不复制长篇正文。Java已有同名
`operation_logs`业务事务日志，因此Agent使用物理表前缀隔离，且不会直接读取或复用Java表。

原确认人可通过`GET /api/agent/approvals/{approval_id}/operation-log`读取严格详情；其他用户、非`REVIEWER`角色和
不存在的日志分别返回结构化权限或资源错误。前端已有只读Client和运行时响应校验，但尚未建设日志展示页面。

`make test-approval`会统一运行Approval生命周期、草稿、写Tool、确认执行、操作日志和前端契约测试；其中
`tests/test_approval_security.py`把T661～T670连接到模拟Java HTTP写接口，直接断言允许写入的次数、最终提交内容和
`SUCCEEDED`、`STALE`、`FAILED`等终态。该安全矩阵只验证Agent门禁，真实Java权限、版本与幂等边界仍由跨服务E2E验证。

## 只读业务 Tool

应用 lifespan 使用同一个 `BusinessHttpClient` 注册七个 LOW 风险 Tool：
`get_order_detail`、`get_related_tasks`、`get_task_detail`、`get_production_progress`、
`get_quality_issues`、`get_review_result` 和 `get_delivery_status`。它们分别声明 `ORDER_READ`、
`TASK_READ`、`QUALITY_ISSUE_READ`、`REVIEW_READ` 或 `DELIVERY_READ` 权限。

输入只接受安全格式的 `ORDER-*` 或 `TASK-*` 标识；输出严格对应 Java DTO，禁止额外字段、非法
状态和缺失字段。集合接口的空数组是成功事实，不等同于资源不存在。除 Schema 校验外，Tool
还核对响应父 ID 与嵌套资源 ID，阻止形状正确但属于其他订单或任务的数据进入后续 Workflow。

## 只读 Tool 重试

七个只读 Tool 共享一项显式策略：最多额外重试 1 次，首次退避 100 ms，指数倍数为 2，单次
退避上限为 1 秒。当前只有同时满足以下条件的 `ToolException` 才会重试：错误码是
`TOOL_TIMEOUT` 或 `UPSTREAM_UNAVAILABLE`、`retryable=true`，并且还有剩余次数。

参数、权限、404、409、响应 Schema 或资源归属错误不会重试。Java 当前通用 500 信封为
`retryable=false`，因此也不会重试。每个 Tool 的 5 秒整体 timeout 同时覆盖首次请求、退避、
重试请求和输出校验，避免重试把调用时间无限拉长。每次计划重试都会记录 Tool、Run、Trace、
错误码、重试序号和退避毫秒数；当前没有随机抖动、熔断或跨实例重试预算。

## Run 内重复调用检测

`BaseTool.execute` 在权限和输入 Schema 校验后，将稳定 Tool 名与已校验参数规范化并计算
SHA-256 指纹。同一个 Run 复用同一个 `ToolContext` 时，首次逻辑调用会在内存账本占位；相同
Tool 和相同参数的后续调用在发出 HTTP 前返回不可重试的 `DUPLICATE_CALL`。不同 Tool、不同
参数或不同 Run 不冲突，M1.6 在一次逻辑调用内部进行的 retry 也不会被误判为重复调用。

调用方可通过 `execute(..., force_refresh=True)` 显式重新读取事实。刷新只绕过本次门禁，不会
清除账本，因此后续普通同参调用仍会被拦截。账本只保存 64 个十六进制字符的 SHA-256 指纹，
不保存原始 Tool 参数，并使用短锁保证并发相同请求只能有一个进入具体 Tool。

当前账本随 `ToolContext` 生命周期存在，不持久化、不跨 Python 进程或服务实例，也不会仅凭
相同 `run_id` 自动合并两个独立创建的上下文。后续 Workflow 必须为一次 Run 创建并复用同一个
上下文。M2.1 的 Run/Step 表尚未接管这份内存账本，因此当前仍不具备分布式去重。

## Tool 调试 API

`ENVIRONMENT=development` 时注册：

```text
POST /internal/tools/{tool_name}/invoke
```

Swagger UI 位于 <http://localhost:8000/docs>。请求携带目标 Tool 的 `arguments`、调试
`identity`、Python 快速门禁所需 `permissions`、`run_id` 和可选 `force_refresh`；Trace ID 从
`X-Trace-Id` Header 读取。接口不会绕过现有权限、输入、重复检测、重试、Java Client 或输出
Schema，Tool 失败仍以 HTTP 200 返回标准 `ToolResult(success=false, error=...)`。未知 Tool
返回 HTTP 404，请求 Schema 错误返回 HTTP 422，同一 Run 更换身份或权限返回 HTTP 409。

最近128个调试 Run 会在当前进程复用 `ToolContext`，因此跨 HTTP 请求也能验证 M1.7 的
`DUPLICATE_CALL` 和 `force_refresh`。超过上限时按最久未使用顺序淘汰；服务重启、多进程或
多实例不会共享。`test` 和 `production` 环境不注册该路由，OpenAPI 中也不会暴露。

## Agent 运行数据持久化

M2.1 只保存 Agent 自有运行元数据，不复制 Java 订单、任务、质检、复核或交付事实：

```text
agent_sessions  一段连续对话及其用户归属
    ├── agent_messages  用户/助手消息和会话内稳定序号
    └── agent_runs      一次请求、上下文、版本、用量、终止原因与最终结果
            └── agent_steps  上下文、路由、Workflow、Agent、Tool、RAG、LLM、确认和写回步骤
```

`AgentRunRepository` 和 `AgentStepRepository` 提供异步增、删、查。Repository 会 `flush` 以便
尽早发现外键、唯一序号等数据库约束，但不会隐式 `commit`；事务边界由 Run 生命周期调用方
统一控制。删除 Session 会级联其 Message、Run 和 Step，删除 Run 会级联 Step；删除请求消息
只把 Run 的 `request_message_id` 置空，保留已发生的运行记录。

M7.1在Run创建时保存严格`page_context_snapshot`，执行中可通过`record_router_result`保存最终路由对象，终态会原子
写入输入/输出/总Token、Tool逻辑调用次数、毫秒总耗时和稳定终止原因。固定诊断当前不经过统一Router或模型，因此对应
字段分别为`null`和0；迁移前Run也只回填非负计数，不补造历史上下文、耗时或结束原因。模型配置、Router/Agent Prompt、
Tool Schema摘要和RAG策略继续由不可变`version_snapshot`提供，不重复保存第二份版本事实。

M7.2将Step类型固化为`CONTEXT/ROUTER/WORKFLOW/AGENT/TOOL/RAG/LLM/APPROVAL/WRITEBACK`
九种字符串Check Constraint，历史`RULE`记录会在迁移时转为`WORKFLOW`。所有类型共用Step
生命周期的受控摘要入口：压缩空白、遮盖Authorization、密码、API Key以及常见Token/Secret标签，并统一截断到1000字符，但调用方仍不得传入完整
Token、密钥或未经筛选的业务载荷。类型只用于可观测分类，不改变Tool权限或Java业务裁决。

M7.3提供`GET /api/agent/events/{stream_id}`事件流。客户端先生成至少8字符的`stream_id`并建立SSE连接，收到
`connected`注释后，在诊断或Approval确认请求中携带`X-Event-Stream-Id`；服务按流内序号发送Run、路由、Agent动作、
Tool、RAG、Approval和写回状态摘要。连接支持心跳及`Last-Event-ID`短期回放，流按用户隔离并在断开、空闲或终态保留期后
清理。事件历史只保存在当前进程的有界内存中，Run/Step数据库记录仍是持久审计证据，Java Tool仍是业务事实来源。

M7.5提供`GET /api/agent/runs?page=1&page_size=20`、`GET /api/agent/runs/{run_id}`和
`GET /api/agent/runs/{run_id}/steps`。三个入口都通过Run所属Session校验当前`REVIEWER`，他人Run与不存在Run共用404；列表最大页大小100，
按`created_at DESC, run_id DESC`稳定排序。详情只恢复符合严格Schema的历史诊断和Approval原稿/最终稿差异，Step按执行序号返回落库前已经
脱敏截断的输入输出摘要；接口不返回用户消息、完整页面上下文、Router结果、版本快照或Tool原始载荷，也不把历史记录解释成当前Java业务事实。

`RunLifecycleService`实现以下最小状态机：

```text
create_run       → PENDING
mark_running     → PENDING → RUNNING
mark_succeeded   → RUNNING → SUCCEEDED，并保存结果、用量、耗时和终止原因
mark_failed      → RUNNING → FAILED，并保存错误定位、用量、耗时和终止原因
```

状态更新使用`WHERE run_id=? AND status=?`的原子条件更新。并发成功/失败请求只有一个能修改
`RUNNING` Run，另一个得到`InvalidRunTransitionError`，避免最后写入者覆盖先完成的终态。
Repository和Service仍不隐式commit，事务由调用方统一提交。M2.5 Workflow已通过
`DatabaseWorkflowStepRecorder`复用Step生命周期；M6已在独立Approval链中接入`WAITING_APPROVAL`。

`StepLifecycleService`仅允许在`RUNNING` Run下开始Step，并在创建时自动写入`run_id`、序号、
类型、名称、输入摘要和`started_at`。父Run使用`SELECT ... FOR UPDATE`校验，避免Run正在进入终态
时又并发插入新Step。Step从`RUNNING`只能原子进入`SUCCEEDED`或`FAILED`：成功清空错误码，失败
保存机器错误码，两者都保存输出摘要、`finished_at`和毫秒耗时。

摘要是调用方提供的受控说明，不接收原始业务对象；Service会压缩空白、遮盖常见Bearer Token、
API Key、Password和Secret写法，并截断到1000字符。该规则是最小防护，不等同于完整PII/DLP
识别。M2.5 Workflow只保存订单/任务ID、数量、状态、错误码和retryable等白名单摘要，不把完整
Tool响应写入Step；开发调试API仍未接入持久化Run/Step。

## Workflow状态与诊断Schema

`OrderDiagnosisState`使用`TypedDict`声明固定诊断节点共享的Run、订单、任务、进度、质检、复核、
交付、诊断和错误通道。它主要服务mypy和后续LangGraph节点的静态类型检查，不会在运行时自动
校验字典内容；外部事实仍必须先经过现有Tool Pydantic Schema。

`DiagnosisResult`使用严格、不可变且禁止额外字段的Pydantic模型，包含订单ID、阻塞阶段、阶段说明、
结构化`RootCause`、`Evidence`、`Suggestion`和0～1置信度。`Evidence`当前只接受七个已注册只读Tool、
可定位字段路径和标量值，禁止把模型判断或整段业务响应冒充事实证据；`StepError`只保留稳定
错误码、安全文案、retryable和可选Trace ID，不接收原始响应或异常堆栈。只有尚未获得任何Tool事实的
`INSUFFICIENT_INFORMATION`结果允许证据为空，其他结论仍必须包含字段级证据。

`blocking_stage`由`BlockingStage`限制为`PRODUCTION/PRODUCTION_BLOCKED/QUALITY_REVIEW/REVIEW/
DELIVERY/NONE/INSUFFICIENT_INFORMATION`。`NONE`不得同时携带根因，其他阶段至少需要一个根因。
`DiagnosisNarrative`只允许模型返回阶段说明以及带稳定code的根因和建议文案，不接收订单ID、阻塞
阶段、证据或置信度。

M5.1在同一`OrderDiagnosisState`中增加Tool历史、信息缺口、迭代次数和终止原因。`AgentObservation`
只保存动作、调用参数SHA-256指纹、有界摘要、新信息标记和可选安全错误，不复制原始Tool响应；成功与错误
互斥，失败不能声称获得新信息，`FINISH`只表示终止决策而不能伪装成一次外部观察。现有固定诊断Workflow
以空历史、空缺口、0次迭代和未终止状态初始化这些通道，运行路径和诊断结果保持不变。

M5.2使用`ActionDecision`严格绑定八种动作、执行器名称及参数Schema：六种Java事实查询只能使用对应的已注册
LOW风险Tool，`RETRIEVE_SPEC`使用最小问题参数，`FINISH`不得携带执行器或参数。中文版本化Prompt只注入
强类型Java事实、安全Tool历史、信息缺口、迭代次数和当前实际可用的执行器描述，不使用页面提示冒充事实，
也不暴露未映射的`get_task_detail`。模型对象或纯JSON输出必须通过Schema、当前Registry及状态内资源身份校验；首次非法
输出只纠错一次，二次失败、未知/未注册Tool或模型异常统一回退为不声称业务结论的安全`FINISH`。

M5.3用`DynamicDiagnosisWorkflow`把初始化、动作规划、二次校验、执行、Observation保存、完成判断和结果生成
编译为可回环LangGraph。模型只能选择动作；执行层会再次验证注册表LOW风险属性、参数Schema及订单/任务归属，
随后调用Java只读Tool或显式日期/权限约束的规范问答Workflow。业务Tool结果只合并到对应强类型事实通道，
规范结果独立保存且不会冒充Java事实；`FINISH`由确定性规则区分信息充分和信息不足，Tool失败则保存结构化
Observation并进入异常结束节点。

M5.4使用严格`AgentExecutionLimits`配置默认最多6轮决策、8次Tool调用和连续2次无新增信息。决策轮在模型
返回动作时计数，`FINISH`计入决策但不计入Tool调用；执行前用调用指纹拦截重复逻辑调用，并再次检查动作与
唯一执行器映射、LOW风险、注册状态、参数Schema、资源归属和调用身份权限。预算、重复或无新增信息终止会
保留当前事实生成安全结果，写Tool、未知Tool、动作错配和缺少权限则进入异常出口。

M5.5使用`InformationGapDetector`在初始化及每次Observation后重算场景化信息缺口。订单、至少一个归属
一致的任务和有效交付记录属于基础要求；未完成生产任务补充有效进度，质检阶段补充问题，有问题或进入复核
阶段时补充复核结果，坐标系问题补充一次显式日期和权限范围下的规范检索结果。空质检列表和未查询通过任务
键是否存在区分；规范问答的安全无结论结果只表示检索尝试已经完成，不会转成规范结论。动态`FINISH`及预算
终止只有在缺口清空时才生成场景结论，固定M2.6 Workflow仍使用全量事实完整性规则。

M5.6用五个固定订单验收动态图的最小场景路径，并把每个动态`DiagnosisResult`与固定Workflow完整结果直接
比较：生产中和生产失败查询进度，质检阻塞查询问题、复核及规范，复核阶段直接查询复核，满足交付条件只补
交付；M5.5要求的交付基础事实始终保留。只读Tool首次超时由BaseTool在同一逻辑调用内最多重试一次，成功后
动态图只保存一条Observation；重复、最大轮数、连续无新增信息及写Tool拦截继续复用M5.4回归门禁。

## 会话上下文

`SessionContext`只持久化当前订单/任务、上一轮意图、已确认参数、候选对象、最近诊断Run和待确认动作
草稿，不复制Java订单、质检或交付响应。会话通过`agent_sessions.context` JSON保存，并由严格Pydantic
Schema在读写边界重新校验；`expires_at`实现默认30分钟滑动TTL。

`POST /api/agent/sessions`创建会话，`GET /api/agent/sessions/{session_id}`读取未过期上下文，
`DELETE`清除会话及级联的Message、Run和Step。所有操作校验用户归属；跨用户返回403，过期读取或
诊断返回410。所有者可以删除过期会话。服务端上下文更新会延长TTL，只读GET不会延长。

## 意图路由契约

M3.3定义`ORDER_QUERY/ORDER_DIAGNOSIS/TASK_TRACKING/SPEC_QA/REVIEW_GENERATION/UNKNOWN`六类
稳定意图。只读意图目录统一声明进入业务Skill前的必填参数：订单查询和诊断需要`order_id`，任务跟踪和
复核草稿需要`task_id`，规范问答不强制业务ID；意图分别映射到规划中的`OrderStatusSkill`、
`DiagnosisSkill`、`SpecificationSkill`和`ReviewSkill`，`UNKNOWN`不映射任何Skill。

`RouterResult`严格约束0～1置信度、有界业务实体、准确`missing_fields`和`need_clarification`。
缺少必填参数时必须澄清；`UNKNOWN`无论是否提取到实体都必须澄清且`can_dispatch=false`。

`router-v3`中文System Prompt直接从意图目录生成中文意图语义、必填参数和目标Skill，页面与会话上下文以
受控JSON数据注入，并明确它们只是提示而非业务事实。模型适配器同时收到由`RouterResult`生成的JSON
Schema；输出可为对象或纯JSON文本，Markdown围栏和额外说明会被拒绝。首次Schema失败追加固定纠错指令
重试一次，二次失败或模型异常返回置信度0、无实体、必须澄清的`UNKNOWN`。`entities`只允许包含本轮消息
明确给出的实体，页面和会话值由服务端合并器按`USER_MESSAGE > CONFIRMED_SESSION > PAGE_CONTEXT >
SESSION_CANDIDATE`选择并保留来源。不同值会生成冲突记录；最高优先级仍有多个值时不选择任何值。当前没有
具体模型供应商、HTTP入口或动态Skill分发。

模型实体还必须能在本轮`user_message`中匹配到独立文本证据，否则按非法输出重试并回退`UNKNOWN`，防止
页面或会话值被模型升级为`USER_MESSAGE`。`RoutingDecision`按`UNKNOWN`、未解决冲突、必填参数缺失、
低置信度、中置信度确认和模型主动澄清的顺序生成确定性问题。高置信度且参数完整时为`READY`；中置信度
需要用户确认，低置信度要求重新描述。候选选择或缺参补充会标记为`USER_MESSAGE`并恢复原意图，无需再次
调用模型。当前决策和恢复仍是内部组件，尚未接入HTTP或持久化路由Run。

M3.7在`evaluation/router_cases.jsonl`保存60条固定路由期望，严格覆盖明确意图、同义表达、页面和会话
指代、缺参、多候选、意图混淆及无关请求。`RouterEvaluationSubject`允许注入真实模型、离线回放或测试
替身；执行器计算意图准确率、参数完整率和六意图混淆矩阵，并可输出不含用户消息及上下文的JSONL失败
样本。仓库当前只用可控Subject验收评测基础设施，没有具体模型Provider，因此不声明真实模型准确率。
`make eval-router`可重复验证数据分布、指标和失败输出。

## 演示规范文档

M4.1在仓库根目录`knowledge-base/`准备14份当前有效规范和2份历史失效规范，覆盖DOM生产、质量、坐标系、
复核与交付。Markdown只保存标题化演示正文，`catalog.json`集中保存稳定文档ID、相对路径、计划要求的八个
检索元数据字段、生命周期和历史替代关系。全部正文明确标记为演示数据，不能解释为真实行业标准。

`DocumentCatalog`会严格解析目录，拒绝额外字段、重复ID/路径、不安全Markdown路径、生命周期与目录位置不一致、
日期倒置及无效替代关系。`ACTIVE`文档没有失效日期，`HISTORICAL`文档必须具有失效日期并指向同类型有效版本；
后续Loader不得根据文件名猜测元数据。

M4.2通过`knowledge_documents`保存文档身份、内容哈希、八个过滤元数据字段、生命周期和替代关系，通过
`knowledge_chunks`保存所属文档、顺序、章节路径、正文哈希和token数。分块表使用固定`VECTOR(1536)`列，并用
PostgreSQL生成列维护基于`search_document`的`to_tsvector('simple', ...)`；文档表记录当前Embedding
Provider、模型、维度、索引版本和入库时间。`search_vector`使用GIN索引，Embedding使用余弦HNSW索引；
检索时的元数据查询门禁由M4.7 Repository统一执行。`make test-knowledge-models`会同时验证Schema/ORM和
隔离PostgreSQL迁移。

M4.3的`DocumentLoaderRegistry`只按显式`.md`/`.txt`扩展名选择Loader，统一要求UTF-8并在哈希前规范化BOM和
换行符。Markdown一级标题必须与目录标题一致；`HeadingDocumentChunker`忽略代码围栏内的伪标题，保存完整
章节路径，并对超长章节先按段落、再按句末或字符上限切分。Chunk ID由文档ID、章节路径和内容哈希生成，
不依赖全局顺序；`DocumentProcessingPipeline`在任何数据库或模型调用前拦截规范化后正文相同的不同文档。
`make test-knowledge-loading`验证当前16份目录、两种Loader、超长切分、稳定ID和重复检测。

M4.4的`EmbeddingProvider`协议隔离具体供应商；首个适配器使用OpenAI兼容`POST /embeddings`契约，显式发送
批量输入、模型、float编码和1536维度，并按响应`index`恢复输入顺序。响应数量、索引、维度和数值有限性均需
通过校验。`EmbeddingBatchGenerator`仅对超时、网络、429和5xx执行有界指数退避，认证、请求和响应结构错误
不会重试；全部批次先在内存成功，随后`KnowledgeIndexRepository`在调用方事务中替换文档Chunk并记录同一
索引版本，避免部分批次落库。`make test-knowledge-embedding`使用MockTransport与隔离PostgreSQL验收，不调用
真实外部Provider。

M4.5在入库时把章节标题、原文和中文连续文本的双字词元写入`search_document`，查询侧使用同一NFKC和双字
规则生成安全词元，再由`plainto_tsquery('simple', ...)`匹配GIN索引并以`ts_rank_cd`返回归一化关键词分数。
空查询、单个中文字符、超长输入和过多词元会在进入SQL前被拒绝。双字词元是无额外分词依赖的确定性第一版，
不等同于完整中文语义分词。`make test-knowledge-keyword`验证查询契约和真实PostgreSQL结果。

M4.6复用`EmbeddingBatchGenerator`的Provider、错误分类和有限重试生成单条Query Embedding；检索Repository
只比较Provider、模型、1536维度和`index_version`完全相同的文档，使用余弦距离升序命中HNSW索引，并向上层
返回`1 - distance`相似度。TopK限制为1～100，相似度阈值限制为-1～1，错误维度、非有限值和零向量会被
拒绝。`make test-knowledge-vector`验证索引版本隔离、顺序、分数、TopK和阈值。

M4.7用严格`KnowledgeSearchFilter`统一关键词与向量检索范围；`effective_at`和`permission_scope`是必填的
安全边界，产品类型、卫星类型、文档类型和规范版本按需精确匹配。Repository只允许`ACTIVE`且已生效、
未过期的文档参与候选排序，并在`ORDER BY`与`LIMIT`前应用全部条件，避免不相关Chunk占据TopK。
`make test-knowledge-filters`验证跨产品、元数据差异、历史失效和未来规范不会误召回。

M4.8的`fuse_hybrid_results`不直接相加量纲不同的关键词分数和余弦相似度，而是使用固定`k=60`的RRF融合
两路1-based排名。同一`chunk_id`跨通道只保留一次，冲突载荷会关闭失败；同文档、同章节且`chunk_index`
连续的命中在最终TopK前按原文顺序合并，并保留全部Chunk ID、内容哈希、原始分数和最佳通道名次。
`make test-knowledge-hybrid`同时验证纯融合契约和真实PostgreSQL候选；当前融合层不负责生成查询或扩大候选池。

M4.9用供应商无关`Reranker`接口接收查询和M4.8候选，模型输出必须为每个稳定候选身份返回唯一、完整且位于
0～1的相关性分数。服务按分数降序重排，分数相同则保持原RRF顺序，低于显式阈值的片段不会进入下游；
原始`RetrievalResult`始终保留，不用模型分数覆盖关键词、向量或RRF证据。调用超时会返回带`TIMEOUT`标记的
原顺序结果，并因分数未知而跳过低相关过滤；非超时调用失败和结构错误分别以安全异常关闭失败。
`make test-knowledge-rerank`验证重排前后顺序、阈值边界、超时降级、模型异常和不可信响应。

M4.10让关键词和向量Repository在既有SQL连接中同时返回规范标题与版本，融合和重排阶段继续保留这些字段。
`build_citations`把每个重排结果转换为文档、版本、章节、主Chunk、全部合并Chunk、正文和可空相关性分数；
重排超时时不会拿RRF分数冒充相关性。Web的`KnowledgeCitationCard`展示引用身份，并允许用户展开或收起原文。

M4.11的`KnowledgeRetrievalPipeline`对关键词和向量通道复用同一`KnowledgeSearchFilter`，随后执行RRF融合；
`SpecificationQaWorkflow`固定串联Query Rewrite、Metadata Builder、Retrieval、Rerank、相关性检查和带引用生成。
页面产品/卫星字段只用于收窄候选，权限范围和生效日期必须由调用方显式提供。回答模型只能返回既有主Chunk
身份；无候选、Rerank超时或生成结构/引用异常时返回不带引用和规范结论的安全回答。`SpecificationSkill`
只接受已通过确定性门禁的`SPEC_QA`决策。当前这些能力是内部组件，尚未接入统一HTTP和页面问答交互。

M4.12在`evaluation/rag_cases.jsonl`固定保存50条问题及其预期文档、完整章节路径和安全过滤条件。
`KnowledgeRagEvaluationSubject`把当前关键词、向量、RRF和Reranker实现接入同一策略边界，`evaluate_rag`
按“文档ID与完整章节同时命中”计算Hit@5和MRR，并按全部Top5片段计算无关片段占比。无命中样本区分
无结果、文档未命中和章节未命中，输出只包含稳定身份与章节，不保存问题或正文。仓库用可控Subject验证
评测数学和四策略执行链，不把替身结果声明为真实Provider质量；`make eval-rag`可重复运行完整验收。

## 固定 Workflow 节点

`OrderDiagnosisWorkflow`使用LangGraph `StateGraph`固定串联：

```text
load_context
→ load_order
→ load_tasks
→ load_progress
→ load_quality
→ load_review
→ load_delivery
→ validate_page_context
→ diagnose_by_rules
→ generate_diagnosis
→ refine_diagnosis（可选模型）
```

`load_context`校验Run、请求订单、页面订单和身份角色一致性并初始化全部状态通道；其余加载节点只通过
现有只读Tool读取Java事实。任务列表按`task_id`稳定排序，进度、质检和复核以`task_id`为键一次性
合并。`validate_page_context`再用已加载的订单、任务和质检事实校验资源归属，页面提示不参与业务裁决。

Tool标准失败转换为`StepError`后，条件边直接进入`END`，因此失败节点后的Tool不会继续执行。
每次Workflow实例绑定一个`ToolContext`且只能运行一次，确保Run内重复调用账本不会被跨Run误用。
`WorkflowStepRecorder`用于测试替换，生产适配`DatabaseWorkflowStepRecorder`会在动作前后分别开启
短事务记录Step，Java HTTP等待期间不持有数据库锁。

`diagnose_by_rules`只消费前序Tool事实，不再发HTTP请求。规则先检查订单、任务、进度、质检、复核
和交付事实是否完整，再按“生产失败 → 生产中 → 未关闭质检 → 未通过复核 → 交付阻塞 → 无阻塞”
返回最早阶段；缺失或归属矛盾时返回`INSUFFICIENT_INFORMATION`。

`generate_diagnosis`根据机器裁决装配阶段说明、稳定根因、Tool字段证据、建议和置信度，并以`RULE`
Step记录。`refine_diagnosis`只有在调用方注入`DiagnosisNarrativeModel`时才执行模型调用；模型结果先
经过严格Schema校验，再检查根因code和建议action type与规则结果完全一致，最后只覆盖说明文字。
调用异常或结构无效会记录失败的`LLM` Step并保留规则诊断，不写入Workflow业务错误通道。当前只
提供供应商无关的模型适配接口，具体模型客户端留给后续运行时装配。

## 订单诊断 API

`POST /api/agent/order-diagnosis`首次调用接收`order_id`、`user_message`和`page_context`，最小身份通过
`X-User-Id`与`X-User-Role` Header提供，可选Bearer Token继续透传Java。当前只允许`REVIEWER`调用，
并要求页面角色提示与Header一致；Header仍只是开发阶段身份上下文，不是完整认证系统。Python授予该
固定只读Workflow所需的内部Tool能力，订单、任务与质检归属最终仍由Java事实重新确认。

首次请求创建Session，成功响应返回`session_id`；后续请求可只提交该ID和问题，从会话继承当前订单或
任务。每轮都会追加用户Message并创建Run，先提交`RUNNING`再执行Workflow。继承值仍经过页面Schema与
Java事实重校验，不能成为业务事实。成功响应返回`run_id`、`session_id`、`trace_id`和完整结果，同时把结果JSON
快照保存到`SUCCEEDED` Run。标准Tool失败按稳定错误码映射为HTTP 400/403/404/409/502/504，Run
保存错误码和失败节点；未预期Workflow异常返回安全的`WORKFLOW_EXECUTION_ERROR`且不泄露异常。

## 测试与质量

```bash
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen mypy app tests
uv run --frozen alembic upgrade head
```

根目录可单独执行：

```bash
make test-agent-client
make test-agent-errors
make test-agent-tool-protocol
make test-tools
make test-agent-persistence
make test-run-lifecycle
make test-step-lifecycle
make test-workflow-schemas
make test-workflow-nodes
make test-diagnosis-rules
make test-diagnosis-generation
make test-diagnosis-api
make test-page-context
make test-session-context
make test-knowledge-docs
make test-knowledge-models
make test-knowledge-loading
make test-knowledge-embedding
make test-knowledge-keyword
make test-knowledge-vector
make test-knowledge-citations
make test-specification-qa
make eval-rag
make test-agent-e2e
```

`make test-agent-e2e`使用独立 Compose 项目启动临时 PostgreSQL 和真实 Java 服务，在 pytest
进程内运行完整 Agent API 生命周期，验证五个固定订单、Run/Step持久化、订单不存在、Java超时和
非法响应。异常通过测试专用Transport注入Java已有演示故障Header，不暴露新的生产API入口；完成后
自动删除本次容器、网络、数据卷和临时业务镜像。

`unit` 标记不使用外部服务；`integration` 标记覆盖 FastAPI 生命周期、中间件和 HTTP
边界及 PostgreSQL 持久化。`make test-agent-persistence` 使用随机宿主端口和临时数据目录启动
隔离 PostgreSQL，完成后自动删除，避免误用本机或开发数据库。

## 数据边界

`app.database.Base` 当前只映射 Agent Session、Message、Run、Step及知识文档/分块，并可继续承载Approval。
知识表只保存规范及检索数据，不复制业务事实。Python服务
不得为 Java 的订单、生产、质检、复核或交付表建立 ORM 映射，也不得绕过 Java API
读取或修改业务事实。

## Docker 启动

```bash
docker compose up --build agent-service
```
