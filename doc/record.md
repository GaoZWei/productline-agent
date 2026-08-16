# 核心功能开发记录

本文件只记录实际功能里程碑或改变运行行为的核心开发。当前测试摘要、问题和下一任务统一查看
`docs/STATUS.md`；纯环境、治理、知识文档、注释语言和视觉调整不记录。

每个功能条目固定使用以下结构：

```text
二级标题：日期 — `[任务编号] 阶段名称`
三级栏目：核心解决的问题、实现的核心代码、实现的核心功能
```

---

## 2026-07-26 — `[T001-T006] M0.1 项目基础环境`

### 核心解决的问题

建立Java业务服务、Python Agent服务和Web控制台可以统一启动、配置和验证的Monorepo基础，避免
后续功能各自维护不一致的开发入口。

### 实现的核心代码

- `docker-compose.yml`：编排PostgreSQL、business-service、agent-service和web-console。
- `Makefile`：提供配置、启动、测试、重置和服务管理入口。
- `scripts/check-foundation.sh`、`scripts/smoke-services.sh`：基础结构与三服务健康检查。

### 实现的核心功能

- 三个服务具备独立构建和健康检查入口，公共配置通过环境变量注入。
- PostgreSQL使用`pgvector/pgvector:pg16`，上层服务按健康依赖顺序启动。
- 根级命令统一封装本地开发和后续自动验收流程。

---

## 2026-07-30 — `[T007-T016] M0.2 业务领域模型设计`

### 核心解决的问题

统一订单、生产、质检、复核和交付对象及状态语义，使Java接口和后续Python Tool共享稳定业务事实，
避免模型面对冲突或自由文本状态。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/domain/model/`：订单、任务、步骤、问题、复核、返工和交付实体。
- `business-service/src/main/java/com/productline/business/domain/enums/`：五组业务状态枚举。
- `business-service/src/main/java/com/productline/business/domain/dto/`：跨层业务DTO。
- `business-service/src/main/resources/db/migration/V1__create_business_domain.sql`：领域表、外键和状态约束。

### 实现的核心功能

- 建立订单到任务、生产步骤、质检问题、复核和交付的父子关系。
- Java枚举与数据库约束使用一致的稳定状态值。
- 聚合关系和校验阻止跨订单、跨任务错误关联。

---

## 2026-07-30 — `[T017-T024] M0.3 固定业务数据`

### 核心解决的问题

为Agent取证路径和诊断结果提供可重复、可重置的业务事实，避免随机数据导致测试结论无法复现。

### 实现的核心代码

- `business-service/src/main/resources/db/migration/V2__seed_fixed_demo_data.sql`：ORDER-001～005固定数据。
- `business-service/src/main/java/com/productline/business/domain/validation/BusinessStateConsistencyValidator.java`：跨对象状态一致性校验。
- `scripts/reset-demo`：重建数据卷并验证固定数据快照。

### 实现的核心功能

- 固化正常生产、生产失败、质检阻塞、复核阻塞和可交付五类订单场景。
- 固化`ORDER-003 → TASK-003 → ISSUE-001 → PENDING review → BLOCKED delivery`黄金链路。
- 数据库约束与业务一致性校验共同阻止不可能的状态组合。

---

## 2026-07-30 21:34 — `[T025-T032] M0.4 Java 查询接口`

### 核心解决的问题

通过稳定Java API向Python提供订单诊断事实，禁止Agent绕过业务服务直接读取业务数据库。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/OrderQueryController.java`：订单、任务和交付查询入口。
- `business-service/src/main/java/com/productline/business/api/TaskQueryController.java`：任务详情、进度、质检和复核查询入口。
- `business-service/src/main/java/com/productline/business/application/BusinessQueryService.java`：只读查询、归属校验和DTO组装。
- `business-service/src/main/java/com/productline/business/api/dto/`：查询响应契约。

### 实现的核心功能

- 提供订单详情、关联任务、任务详情、生产进度、质检问题、复核结果和交付状态查询。
- 空集合与资源不存在使用不同语义，列表结果按稳定业务顺序返回。
- 子资源查询校验父子归属，为细粒度Tool提供可信事实接口。

---

## 2026-07-31 21:36 — `[T033-T037] M0.5 Java 写接口`

### 核心解决的问题

为后续Approval确认后的业务回写提供权威Java入口，并防止越权、重复写入和并发覆盖。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/TaskWriteController.java`：复核提交和返工创建接口。
- `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java`：权限、状态、版本、幂等和事务校验。
- `business-service/src/main/java/com/productline/business/domain/model/IdempotencyRecord.java`、`OperationLog.java`：幂等结果与操作日志。
- `business-service/src/main/resources/db/migration/V3__add_write_safety_support.sql`：写安全表和约束。

### 实现的核心功能

- 支持提交复核结果和创建返工任务两类写操作。
- 写入前校验身份、权限、当前状态和乐观版本，冲突时拒绝覆盖。
- 相同幂等键返回首次结果，业务写入与操作日志在同一事务完成。

---

## 2026-07-31 22:11 — `[T038-T044] M0.6 Java 统一异常`

### 核心解决的问题

统一Java成功与失败响应，使Python Client和Workflow可以依赖机器错误码、重试属性和Trace ID处理
跨服务异常，而不是解析自由文本。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/response/ApiResponse.java`、`ApiResponseCode.java`：统一响应信封和错误码。
- `business-service/src/main/java/com/productline/business/api/error/GlobalApiExceptionHandler.java`：异常到HTTP与业务错误的集中映射。
- `business-service/src/main/java/com/productline/business/api/trace/TraceIdFilter.java`：Trace ID校验、生成和响应透传。
- `business-service/src/main/java/com/productline/business/api/response/ApiSuccessResponseAdvice.java`：成功结果统一封装。

### 实现的核心功能

- 所有接口使用`success/code/message/data/trace_id/retryable`六字段信封。
- 参数、认证、权限、资源、冲突和系统异常拥有稳定错误语义。
- 写操作冲突保持保守不可重试，安全Trace ID贯穿请求和响应。

---

## 2026-07-31 22:42 — `[T045-T049] M0.7 故障模拟`

### 核心解决的问题

提供可控且可重复的Java故障输入，使Python Tool的超时、上游异常、响应校验和权限路径能够自动测试。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/fault/DemoFaultInterceptor.java`：读取故障头并注入受控失败。
- `business-service/src/main/java/com/productline/business/api/fault/DemoFaultProperties.java`：环境开关和延迟上限。
- `business-service/src/main/java/com/productline/business/api/fault/DemoFaultWebConfiguration.java`：仅对只读查询路径注册拦截器。

### 实现的核心功能

- 支持延迟、超时、500、字段缺失和权限失败场景。
- 故障模拟默认关闭，仅在开发环境显式启用，并限制延迟范围。
- 写接口不接受故障注入，避免测试机制影响业务回写。

---

## 2026-07-31 23:11 — `[T050-T057] M0.8 最小前端业务页面`

### 核心解决的问题

提供五个固定订单的业务事实展示和快速切换页面，为后续Agent交互保留明确的订单上下文载体。

### 实现的核心代码

- `web-console/src/App.vue`：订单页面整体编排和异常展示。
- `web-console/src/stores/orderStore.ts`：订单选择、并发加载和错误状态管理。
- `web-console/src/api/businessClient.ts`、`businessApi.ts`：Java响应信封解析和业务查询封装。
- `web-console/src/components/`：订单概览、任务、质检、交付和订单切换组件。

### 实现的核心功能

- 展示ORDER-001～005的订单、任务、质检和交付事实。
- 快速切单时抑制过期响应覆盖当前订单，错误结果保留Trace ID并支持重试。
- 页面具备桌面和移动端布局，但尚未包含Agent对话或诊断卡片。

---

## 2026-07-31 23:54 — `[T101-T108] M1.1 Python 工程初始化`

### 核心解决的问题

建立可持续承载Client、Tool、Workflow和运行记录的Python Agent服务骨架，并明确其自有数据与Java
业务事实的边界。

### 实现的核心代码

- `agent-service/pyproject.toml`、`uv.lock`、`.python-version`：Python版本、依赖和质量工具。
- `agent-service/app/main.py`：FastAPI入口、lifespan和健康检查。
- `agent-service/app/settings.py`、`database.py`：配置、异步Engine和Session工厂。
- `agent-service/app/observability.py`、`migrations/`：结构化日志、Trace上下文和Alembic基础。

### 实现的核心功能

- 使用uv固定Python 3.12依赖，提供FastAPI/Uvicorn标准启动方式。
- 建立异步SQLAlchemy和Alembic连接，但不映射Java订单、任务等业务表。
- 请求Trace ID通过`ContextVar`隔离并进入结构化日志。

---

## 2026-08-01 18:54 — `[T109-T117] M1.2 Java HTTP Client`

### 核心解决的问题

为全部Tool提供统一、强类型的Java HTTP调用通道，集中处理连接生命周期、身份上下文、Trace和响应契约。

### 实现的核心代码

- `agent-service/app/clients/business.py`：`BusinessHttpClient`及GET、POST、信封解析和Schema校验。
- `agent-service/app/schemas/business.py`：业务身份、Java响应信封和调用上下文Schema。
- `agent-service/app/settings.py`：业务服务地址和connect/read/write/pool超时配置。
- `agent-service/app/main.py`：共享AsyncClient的创建与关闭。

### 实现的核心功能

- 复用`httpx.AsyncClient`连接池访问Java服务。
- 透传用户、角色、可选Token、Trace ID和写请求幂等键。
- 同时校验外层Java信封与内层调用方Pydantic data Schema，字段缺失不会进入Tool层。

---

## 2026-08-03 21:16 — `[T118-T126] M1.3 标准错误模型`

### 核心解决的问题

把Java业务失败、HTTP错误、网络异常和响应校验失败收敛成Workflow可稳定分支的Tool错误语义。

### 实现的核心代码

- `agent-service/app/errors.py`：`ToolErrorCode`、`ToolError`和`ToolException`层次。
- `agent-service/app/clients/business.py`：HTTP、Java code、Trace和retryable一致性校验及错误转换。
- `agent-service/tests/test_tool_errors.py`：标准错误映射契约。

### 实现的核心功能

- 区分参数、认证、权限、资源、冲突、超时、网络、上游和响应校验错误。
- Java失败先转换为`ToolException`，再由Tool协议形成结构化`ToolResult.error`。
- 原始响应和内部异常不会直接暴露给模型或Workflow。

---

## 2026-08-04 21:51 — `[T127-T132] M1.4 Tool 基础协议`

### 核心解决的问题

定义所有Tool一致的输入、输出、权限、风险和注册方式，使Workflow或Agent不能绕过公共执行门禁。

### 实现的核心代码

- `agent-service/app/tools/base.py`：泛型`BaseTool`、风险等级和统一执行模板。
- `agent-service/app/tools/models.py`：`ToolContext`、`ToolMetadata`和互斥`ToolResult`。
- `agent-service/app/tools/registry.py`：`ToolRegistry`注册、查找和重复名称保护。

### 实现的核心功能

- Tool执行统一经过权限、输入Schema、整体超时、输出Schema和异常转换。
- 成功结果和错误结果互斥，调用方不需要依赖异常文本判断。
- Registry集中管理稳定Tool名称，为固定Workflow和后续动态选路提供同一入口。

---

## 2026-08-07 21:40 — `[T133-T139] M1.5 七个只读 Tool`

### 核心解决的问题

把订单诊断所需Java查询接口转换为可独立调用的细粒度Tool，并阻止父子资源串线和响应结构漂移。

### 实现的核心代码

- `agent-service/app/schemas/tools.py`：七个Tool的严格输入输出和业务事实Schema。
- `agent-service/app/tools/readonly.py`：订单、任务、进度、质检、复核和交付Tool及装配工厂。
- `agent-service/app/main.py`：在lifespan中使用共享Client构建只读Tool Registry。

### 实现的核心功能

- 提供订单详情、关联任务、任务详情、生产进度、质检问题、复核结果和交付状态七个Tool。
- 每个Tool拥有最小权限和明确Pydantic Schema，空集合保持成功语义。
- 请求ID、响应父ID和子资源ID必须一致，否则返回响应校验失败。

---

## 2026-08-08 — `[T140-T144] M1.6 Tool 重试`

### 核心解决的问题

允许只读Tool对瞬时故障进行有限重试，同时避免不可重试错误和超时预算被无限放大。

### 实现的核心代码

- `agent-service/app/tools/retry.py`：`RetryPolicy`、次数、退避和错误白名单。
- `agent-service/app/tools/base.py`：在整体超时预算内执行单次调用或重试。
- `agent-service/tests/test_retry_policy.py`：调用次数、退避和预算边界。

### 实现的核心功能

- 仅网络、超时和明确上游临时异常等白名单错误允许重试。
- 同时要求Tool为只读、错误码可重试且`retryable=true`。
- 重试次数和指数退避封顶，并受一次Tool调用的总超时预算约束。

---

## 2026-08-08 — `[T145-T149] M1.7 重复调用检测`

### 核心解决的问题

阻止Agent在同一Run内用相同参数反复调用同一Tool，同时保留显式获取最新事实的能力。

### 实现的核心代码

- `agent-service/app/tools/deduplication.py`：规范化参数指纹和`RunToolCallLedger`并发账本。
- `agent-service/app/tools/models.py`：Run级账本和`force_refresh`调用上下文。
- `agent-service/app/tools/base.py`：执行前占位、成功确认和失败释放。

### 实现的核心功能

- Tool名称与规范化参数生成SHA-256指纹，相同Run内重复调用返回`DUPLICATE_CALL`。
- 并发相同调用只有一个进入下游，失败调用释放占位以允许后续重试。
- `force_refresh`显式绕过去重以重新读取最新Java事实，不复用旧结果缓存。

---

## 2026-08-08 — `[T150-T153] M1.8 Tool 调试接口`

### 核心解决的问题

在没有Workflow或动态Agent时，通过HTTP和Swagger独立验证Tool，同时保证调试能力不会进入生产路由。

### 实现的核心代码

- `agent-service/app/api/tool_debug.py`：调试请求Schema、Run上下文存储和Tool调用端点。
- `agent-service/app/main.py`：仅development环境注册调试Router。
- `agent-service/tests/integration/test_tool_debug_api.py`：路由、身份、去重和刷新边界。

### 实现的核心功能

- 提供`POST /internal/tools/{tool_name}/invoke`并返回标准`ToolResult`。
- 相同调试Run跨HTTP请求复用身份、权限和调用账本，身份变化被拒绝。
- 上下文存储有容量上限且仅进程内有效，不承担生产认证或持久化。

---

## 2026-08-08 — `[T201-T206] M2.1 Agent 基础数据表`

### 核心解决的问题

建立Agent会话和执行历史的自有持久化结构，为Workflow观测、失败定位和结果追踪提供数据基础。

### 实现的核心代码

- `agent-service/app/models/agent_runtime.py`：Session、Message、Run和Step SQLAlchemy模型。
- `agent-service/app/repositories/agent_runtime.py`：Run与Step异步Repository。
- `agent-service/migrations/versions/0001_agent_runtime_base.py`：四张Agent表及约束迁移。
- `scripts/test-agent-persistence.sh`：隔离PostgreSQL迁移与持久化验收。

### 实现的核心功能

- 保存会话归属、消息顺序、单次Run及其Step执行记录。
- 使用外键、唯一序号和级联关系保证执行历史结构一致。
- Python只管理`agent_*`表，不映射或直接读写Java业务表。

---

## 2026-08-09 17:30 — `[T207-T213] M2.2 最小 Run 生命周期`

### 核心解决的问题

让一次Agent请求拥有可审计的开始和终态，并防止并发成功、失败请求互相覆盖结果。

### 实现的核心代码

- `agent-service/app/services/run_lifecycle.py`：`RunLifecycleService`及状态流转异常。
- `agent-service/app/repositories/agent_runtime.py`：基于期望旧状态的Run条件更新。
- `agent-service/app/models/agent_runtime.py`：Run状态、结果快照和失败字段。

### 实现的核心功能

- 支持`PENDING → RUNNING → SUCCEEDED/FAILED`最小状态机。
- 成功保存JSON结果快照，失败保存错误码和失败步骤，两个终态字段互斥。
- 并发终态通过数据库条件更新保证只有一个请求成功写入。

---

## 2026-08-09 18:00 — `[T214-T220] M2.3 最小 Step 记录`

### 核心解决的问题

记录Run内部每个动作的状态、耗时和安全摘要，使Workflow失败可以定位到具体上下文、Tool或规则步骤。

### 实现的核心代码

- `agent-service/app/services/step_lifecycle.py`：`StepLifecycleService`、摘要保护和终态流转。
- `agent-service/app/repositories/agent_runtime.py`：Step创建、查询和条件终态更新。
- `agent-service/app/models/agent_runtime.py`：Step类型、状态、摘要、错误和耗时字段。

### 实现的核心功能

- 仅允许在RUNNING父Run下创建Step，并保持同Run序号唯一。
- Step从RUNNING原子进入SUCCEEDED或FAILED，记录起止时间和毫秒耗时。
- 摘要压缩空白、遮盖常见凭据并截断长度，不保存完整业务载荷。

---

## 2026-08-09 19:38 — `[T221-T226] M2.4 Workflow 状态模型`

### 核心解决的问题

建立LangGraph节点共享状态与最终诊断结果的强类型契约，约束根因、证据、建议和错误如何在节点间传递。

### 实现的核心代码

- `agent-service/app/schemas/workflow.py`：`OrderDiagnosisState`、`DiagnosisResult`、`RootCause`、`Evidence`、`Suggestion`和`StepError`。
- `agent-service/app/schemas/__init__.py`：Workflow Schema公共导出。
- `agent-service/tests/test_workflow_schemas.py`：严格字段、证据来源和结果互斥契约。

### 实现的核心功能

- TypedDict约束节点共享状态，Pydantic负责运行时边界校验。
- Evidence只能引用已注册只读Tool的具体字段和标量值，模型不能充当业务事实来源。
- `NONE`阶段禁止根因，其他阶段必须包含根因；未知字段和非法代码被拒绝。

---

## 2026-08-09 20:15 — `[T227-T235] M2.5 固定 Workflow 节点`

### 核心解决的问题

按固定顺序收集订单诊断所需Java事实，在进入业务判断前保证数据归属稳定、调用可追踪且失败立即中断。

### 实现的核心代码

- `agent-service/app/workflows/order_diagnosis.py`：`OrderDiagnosisWorkflow`、固定加载节点、状态合并和错误路由。
- `agent-service/app/workflows/recording.py`：`WorkflowStepRecorder`与数据库短事务适配。
- `agent-service/tests/test_order_diagnosis_workflow.py`：黄金链路、多任务合并和失败中断。

### 实现的核心功能

- LangGraph固定串联上下文、订单、任务、进度、质检、复核和交付加载节点。
- 多任务事实按`task_id`稳定排序和聚合，节点只返回自己负责的增量状态。
- Tool失败转换为`StepError`并停止下游；Step开始和结束使用短事务，Java等待期间不持有数据库锁。

---

## 2026-08-10 20:49 — `[T236-T243] M2.6 确定性诊断规则`

### 核心解决的问题

在Java事实加载完成后，以可重复的代码规则稳定判断订单卡在哪个业务阶段，并避免缺失事实被误报为正常。

### 实现的核心代码

- `agent-service/app/schemas/workflow.py`：`BlockingStage`、`RuleDecision`和规则决策状态通道。
- `agent-service/app/workflows/diagnosis_rules.py`：事实完整性、归属校验和阶段优先级规则。
- `agent-service/app/workflows/order_diagnosis.py`：`diagnose_by_rules`节点及RULE Step记录。
- `agent-service/tests/test_diagnosis_rules.py`：五订单、信息不足和规则优先级用例。

### 实现的核心功能

- 固定输出生产中、生产阻塞、质检、复核、交付、无阻塞或信息不足七种机器阶段。
- 先校验事实完整性，再按生产、质检、复核、交付的最早阶段优先判断。
- `RuleDecision`与最终`DiagnosisResult`分离，后续模型或文案节点不能重新决定阻塞阶段。

---

## 2026-08-10 — `[T244-T250] M2.7 诊断文案生成`

### 核心解决的问题

把稳定阻塞阶段转换为可读且可追溯的完整诊断结果，并在模型整理表达失败时保持确定性输出可用。

### 实现的核心代码

- `agent-service/app/workflows/diagnosis_generation.py`：规则文案装配、模型文案Schema校验与安全合并。
- `agent-service/app/schemas/workflow.py`：阶段说明和`DiagnosisNarrative`结构化模型输出契约。
- `agent-service/app/workflows/order_diagnosis.py`：规则生成、可选模型改写和回退Step。
- `agent-service/tests/test_diagnosis_generation.py`：各阻塞阶段、黄金订单和模型边界用例。

### 实现的核心功能

- 为七类规则裁决生成阶段说明、稳定根因、Tool字段证据、建议和置信度。
- 模型只能改写带稳定code的说明文字，不能覆盖订单、阻塞阶段、证据或置信度。
- 模型调用失败、Schema无效或稳定code变化时记录失败LLM Step并回退规则结果。

---

## 2026-08-12 — `[T251-T257] M2.8 诊断 API`

### 核心解决的问题

把固定诊断Workflow变成可调用且可追踪的HTTP链路，并让成功结果和失败位置都有持久化Run证据。

### 实现的核心代码

- `agent-service/app/api/order_diagnosis.py`：请求身份、成功响应和稳定错误HTTP映射。
- `agent-service/app/services/order_diagnosis.py`：一次性请求上下文、Run生命周期和Workflow编排。
- `agent-service/app/schemas/agent.py`：诊断请求、响应和错误Schema。
- `agent-service/tests/test_order_diagnosis_api.py`：黄金结果、数据库终态、Tool失败和异常用例。

### 实现的核心功能

- `POST /api/agent/order-diagnosis`返回Run、Trace和完整诊断结果。
- 每次请求创建Session、用户Message和Run，成功保存结果快照，失败保存错误码和失败节点。
- Tool错误映射为稳定HTTP响应，未预期Workflow异常不回传内部详情。

---

## 2026-08-12 — `[T258-T267] M2.9 前端 Agent 侧边栏`

### 核心解决的问题

把当前订单接入可演示的诊断界面，并让确定性结论、字段级事实证据和失败位置都能被用户审查。

### 实现的核心代码

- `web-console/src/components/AgentDiagnosisDrawer.vue`：请求状态、诊断结果和结构化错误展示。
- `web-console/src/api/agentClient.ts`：诊断契约校验、演示身份Header和错误归一化。
- `web-console/server.mjs`：开发与生产环境的同源Agent API代理。
- `web-console/src/components/AgentDiagnosisDrawer.spec.ts`：黄金诊断、加载状态和错误展示用例。

### 实现的核心功能

- 从当前业务快照取得订单上下文，提交用户问题并防止切换订单时展示过期结果。
- 分区展示阻塞环节、稳定根因、Tool字段路径和值、建议及Run/Trace。
- 明确建议尚未执行，并显示可重试错误、失败步骤和Trace定位信息。

---

## 2026-08-12 — `[T268-T275] M2.10 诊断 E2E 验收`

### 核心解决的问题

在真实Java、真实HTTP和隔离PostgreSQL边界上验证完整诊断链路，避免单元Mock掩盖跨服务契约、
固定数据、超时映射或运行持久化问题。

### 实现的核心代码

- `agent-service/tests/e2e/test_order_diagnosis.py`：五单、Run/Step、字段证据和三类失败验收。
- `scripts/test-agent-e2e.sh`：隔离服务启动、健康门禁、环境注入和资源清理。
- `Makefile`：`test-agent-e2e`可重复验收入口。

### 实现的核心功能

- 五个固定订单通过真实只读Tool得到计划约定的五种阻塞阶段。
- 成功诊断保存顺序连续的全部Tool Step和严格Schema结果，黄金场景保留四条字段证据。
- 不存在订单、真实Java超时和HTTP成功但字段缺失都保存FAILED Run并定位失败Tool节点。

---

## 2026-08-13 — `[T301-T309] M3.1 页面上下文`

### 核心解决的问题

让诊断请求携带当前页面业务对象，同时防止客户端伪造订单、任务、质检问题归属或角色提示影响诊断。

### 实现的核心代码

- `web-console/src/context/pageContext.ts`：订单、任务和质检页面Context Adapter。
- `agent-service/app/schemas/context.py`：页面类型及严格`PageContext`契约。
- `agent-service/app/workflows/order_diagnosis.py`：请求一致性和Java事实归属重校验节点。
- `agent-service/app/api/order_diagnosis.py`：诊断角色门禁及上下文身份一致性检查。

### 实现的核心功能

- 前端从已有业务对象生成明确页面上下文，并随诊断请求传输。
- 服务端先校验请求订单与身份角色，再用Java Tool事实校验订单、产品、任务和质检问题归属。
- 伪造上下文在规则裁决前以稳定错误终止并保存失败Run/Step，不把页面参数当成业务事实。

---

## 2026-08-13 — `[T310-T318] M3.2 会话上下文`

### 核心解决的问题

让同一用户的后续请求继承当前订单或任务等最小业务指代，同时以用户所有权、过期策略和Java事实
重校验防止跨用户、过期或历史上下文直接驱动业务结论。

### 实现的核心代码

- `agent-service/app/schemas/session.py`：严格会话上下文、待确认草稿和页面合并契约。
- `agent-service/app/services/session_context.py`：创建、读取、更新、清除、身份隔离与滑动TTL。
- `agent-service/migrations/versions/0002_session_context.py`：会话JSON上下文和过期时间迁移。
- `agent-service/app/services/order_diagnosis.py`：会话复用、消息续号、上下文继承和最近Run更新。
- `agent-service/app/api/sessions.py`：会话创建、读取和清除HTTP接口。

### 实现的核心功能

- 保存当前订单/任务、上一轮意图、已确认参数、候选对象、最近诊断Run和待确认操作草稿。
- 首轮诊断返回会话ID，后续请求可继承订单或任务；每轮仍重新加载并校验Java业务事实。
- 会话按用户隔离并默认30分钟滑动过期，过期会话禁止读取和诊断，所有者仍可显式清除。

---

## 2026-08-15 — `[T319-T323] M3.3 意图定义`

### 核心解决的问题

统一自然语言路由使用的稳定意图、必填业务参数和目标Skill，并阻止缺参或无法识别的结果直接进入业务执行。

### 实现的核心代码

- `agent-service/app/routing/intent_catalog.py`：意图、参数、业务Skill及完整只读映射目录。
- `agent-service/app/schemas/routing.py`：路由实体、结构化结果、自洽缺参和安全分发契约。
- `agent-service/app/schemas/session.py`：会话上一轮意图收紧为稳定`Intent`枚举。

### 实现的核心功能

- 六类意图均具有明确的必填参数和唯一Skill映射，`UNKNOWN`明确无执行目标。
- `RouterResult`拒绝虚假或重复缺参，缺少必填参数时必须进入澄清。
- `UNKNOWN`强制澄清且永远不可分发，为后续模型路由提供确定性安全回退。
