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

- `docker-compose.yml`：编排PostgreSQL、business-service、agent-service和agent-frontend。
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

- `agent-frontend/src/App.vue`：订单页面整体编排和异常展示。
- `agent-frontend/src/stores/orderStore.ts`：订单选择、并发加载和错误状态管理。
- `agent-frontend/src/api/businessClient.ts`、`businessApi.ts`：Java响应信封解析和业务查询封装。
- `agent-frontend/src/components/`：订单概览、任务、质检、交付和订单切换组件。

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

- `agent-frontend/src/components/AgentDiagnosisDrawer.vue`：请求状态、诊断结果和结构化错误展示。
- `agent-frontend/src/api/agentClient.ts`：诊断契约校验、演示身份Header和错误归一化。
- `agent-frontend/server.mjs`：开发与生产环境的同源Agent API代理。
- `agent-frontend/src/components/AgentDiagnosisDrawer.spec.ts`：黄金诊断、加载状态和错误展示用例。

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

- `agent-frontend/src/context/pageContext.ts`：订单、任务和质检页面Context Adapter。
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

---

## 2026-08-16 — `[T324-T330] M3.4 路由 Prompt`

### 核心解决的问题

让模型路由在受控上下文和唯一JSON Schema下输出结构化结果，并在非法输出或模型故障时稳定停止而非猜测。

### 实现的核心代码

- `agent-service/app/routing/prompt.py`：版本化System Prompt、页面/会话JSON注入和输出Schema生成。
- `agent-service/app/services/intent_router.py`：模型协议、对象与JSON解析、一次重试和`UNKNOWN`回退。
- `agent-service/app/routing/intent_catalog.py`：意图语义与已有必填参数、Skill目录同源维护。

### 实现的核心功能

- 将用户消息、严格页面上下文和有界会话上下文编码为数据载荷，明确禁止作为业务事实或指令。
- 从`RouterResult`生成JSON Schema，拒绝Markdown、计划外意图、虚假缺参和不完整字段。
- 首次Schema失败只重试一次，模型异常或二次失败返回无实体、不可分发的`UNKNOWN`。

---

## 2026-08-16 — `[T331-T336] M3.5 参数合并优先级`

### 核心解决的问题

让路由参数保留可审查来源，并以服务端固定优先级解决用户输入、已确认会话、页面提示和临时候选之间的竞争。

### 实现的核心代码

- `agent-service/app/schemas/routing.py`：实体提取、来源化实体、冲突和合并结果契约。
- `agent-service/app/routing/entity_merge.py`：四级参数收集、字段复验、优先级选择和冲突检测。
- `agent-service/app/routing/prompt.py`：只允许从本轮用户消息提取实体的`router-v3`约束。

### 实现的核心功能

- 用户本轮明确参数优先于已确认会话、当前页面和上一轮临时候选，模型不能借上下文伪造用户输入来源。
- 相同实体值去重并保留最高来源；不同值保留全部候选和是否已由优先级解决的结果。
- 最高优先级出现多个不同值时保持字段未解析，不让低优先级页面提示替代用户澄清。

---

## 2026-08-16 — `[T337-T343] M3.6 置信度和澄清`

### 核心解决的问题

把模型置信度和来源化实体合并结果收口为确定性分发门禁，并让缺参、冲突和中低置信度能够安全进入澄清。

### 实现的核心代码

- `agent-service/app/schemas/routing.py`：置信度、澄清请求、用户选择和最终路由决策契约。
- `agent-service/app/routing/decision.py`：分级、问题生成、候选选择、意图确认和决策恢复。
- `agent-service/app/services/intent_router.py`：模型实体的本轮用户原文证据校验。

### 实现的核心功能

- 高置信度且参数完整才可直接分发，中置信度必须确认，低置信度必须重新描述。
- 服务端从合并实体重新计算缺参，并为缺参和未解决候选冲突生成稳定中文问题与选项。
- 用户选择或补参后保留原意图恢复确定性决策；模型复制上下文而没有用户原文证据时按非法输出回退。

---

## 2026-08-16 — `[T344-T354] M3.7 路由评测数据`

### 核心解决的问题

让路由意图、参数和澄清结果能够在固定样本上重复评测，并以结构化指标和脱敏失败样本定位回归。

### 实现的核心代码

- `agent-service/evaluation/router_cases.jsonl`：八类场景、固定分布的60条路由期望。
- `agent-service/app/evaluation/router.py`：严格加载、可注入Subject、指标、混淆矩阵和失败输出。
- `agent-service/tests/evaluation/test_router_eval.py`：数据分布、指标计算和安全失败文件回归。
- `Makefile`：`make eval-router`可重复验收入口。

### 实现的核心功能

- 覆盖明确意图、同义表达、页面/会话指代、缺参、多候选、意图混淆和无关请求。
- 计算意图准确率、参数完整率和完整六意图混淆矩阵，不把测试替身结果冒充真实模型指标。
- 失败样本只保存用例ID、类别和结构化差异，不复制用户消息、页面上下文或会话上下文。

---

## 2026-08-17 — `[T408-T413] M4.2 知识库数据模型`

### 核心解决的问题

为规范文档和检索分块建立严格、可迁移的元数据边界，使后续加载、向量化与混合检索不依赖文件名猜测或
临时表结构。

### 实现的核心代码

- `agent-service/app/schemas/knowledge.py`：文档类型、生命周期、权限、元数据和目录关系契约。
- `agent-service/app/models/knowledge.py`：知识文档、分块、向量和全文检索SQLAlchemy模型。
- `agent-service/migrations/versions/0003_knowledge_base.py`：pgvector扩展与两张知识表迁移。

### 实现的核心功能

- 严格校验文档路径、有效期、生命周期、唯一身份和历史版本替代关系。
- 将文档过滤元数据与分块正文分离，并通过外键、唯一键和Check Constraint保护一致性。
- 预留Embedding向量列，并由PostgreSQL根据正文自动维护全文检索向量。

---

## 2026-08-17 — `[T414-T422] M4.3 文档解析和分块`

### 核心解决的问题

将受控Markdown和纯文本规范转换为可重复生成的结构化分块，并在任何数据库或模型调用前拦截路径、标题、
编码和重复正文问题。

### 实现的核心代码

- `agent-service/app/knowledge/loaders.py`：统一Loader协议、格式注册表、UTF-8读取和内容规范化。
- `agent-service/app/knowledge/chunking.py`：标题路径、超长切分、词元近似和稳定Chunk ID。
- `agent-service/app/knowledge/pipeline.py`：目录安全解析、处理编排及内容哈希重复检测。

### 实现的核心功能

- 显式支持Markdown和纯文本，拒绝未知格式、空文档、非法UTF-8及Markdown标题不一致。
- Markdown按标题层级保存章节路径，超长内容优先按段落和句末确定性切分。
- Chunk ID不依赖全局顺序，换行规范化后的SHA-256用于批内及既有内容重复检测。

---

## 2026-08-17 — `[T423-T430] M4.4 Embedding入库`

### 核心解决的问题

把确定性分块转换为可验证、可追踪版本的固定维向量，并防止瞬时Provider故障、异常响应或部分批次成功
造成重试失控、向量空间混写和数据库半成品。

### 实现的核心代码

- `agent-service/app/knowledge/embeddings.py`：Provider协议、OpenAI兼容适配器、配置、批处理和有限重试。
- `agent-service/app/repositories/knowledge.py`：文档与Chunk重新索引、向量校验和索引身份持久化。
- `agent-service/app/models/knowledge.py`、`agent-service/migrations/versions/0004_embedding_index.py`：固定维度与索引版本字段。

### 实现的核心功能

- 批量请求固定1536维float向量，按响应索引恢复输入顺序，并拒绝数量、维度或有限性异常。
- 仅对超时、网络、限流和服务端故障执行有界指数退避，认证、请求和响应结构错误立即失败。
- 全部向量生成成功后，在调用方事务中替换目标文档全部Chunk并记录Provider、模型、版本和入库时间。

---

## 2026-08-18 — `[T431-T435] M4.5 关键词检索`

### 核心解决的问题

让未安装专用中文分词扩展的PostgreSQL仍可确定性检索中文章节和规范正文，并为后续混合检索提供独立、
可排序的关键词分数。

### 实现的核心代码

- `agent-service/app/knowledge/search.py`：NFKC规范化、中文双字词元、检索文档和结果契约。
- `agent-service/app/repositories/knowledge_search.py`：安全tsquery、GIN匹配和关键词排名。
- `agent-service/migrations/versions/0005_keyword_search.py`：检索文本回填、生成tsvector和GIN索引。

### 实现的核心功能

- 入库时把章节标题、原文和去重中文双字词元写入可审查检索文档。
- 查询输入在进入SQL前执行长度、词元数量和有效性门禁，并通过`plainto_tsquery`消除操作符注入语义。
- 使用GIN匹配和归一化`ts_rank_cd`分数返回稳定Chunk结果。

---

## 2026-08-18 — `[T436-T441] M4.6 向量检索`

### 核心解决的问题

把自然语言查询转换成与文档相同向量空间的Query Embedding，并用一致的相似度方向、TopK和阈值控制语义
召回，避免跨模型版本比较或直接暴露方向相反的距离。

### 实现的核心代码

- `agent-service/app/knowledge/embeddings.py`：单条Query Embedding和零向量校验。
- `agent-service/app/repositories/knowledge_search.py`：索引身份过滤、余弦距离查询和相似度结果。
- `agent-service/migrations/versions/0006_vector_search.py`：1536维向量余弦HNSW索引。

### 实现的核心功能

- Query复用文档Provider、模型、维度、索引版本和有限重试策略。
- 只在索引身份完全一致且向量有效的文档中，按余弦距离升序执行HNSW近邻查询。
- 对上层返回`1 - distance`相似度，并强制TopK为1～100、阈值为-1～1。

---

## 2026-08-19 — `[T442-T449] M4.7 元数据过滤`

### 核心解决的问题

让关键词和向量召回在排名前执行同一套业务、时效和权限门禁，避免跨产品、历史或尚未生效的规范进入
候选结果。

### 实现的核心代码

- `agent-service/app/schemas/knowledge.py`：严格检索过滤契约和必填安全边界。
- `agent-service/app/repositories/knowledge_search.py`：两种检索共享的元数据SQL条件。

### 实现的核心功能

- 强制调用方提供检索生效日期和权限范围，只允许当前有效且未过期的规范参与召回。
- 按需精确过滤产品类型、卫星类型、文档类型和规范版本。
- 在关键词或向量排序与TopK之前应用过滤条件，阻止不相关候选占据结果名额。

---

## 2026-08-19 — `[T450-T456] M4.8 混合检索`

### 核心解决的问题

把量纲不同且可能重复的关键词与向量候选转换为统一、稳定、可审查的混合结果，避免直接相加原始分数或
让同一Chunk和相邻碎片重复占据TopK。

### 实现的核心代码

- `agent-service/app/knowledge/hybrid.py`：RetrievalResult、RRF融合、去重、相邻片段合并和稳定排序。
- `agent-service/app/knowledge/search.py`：检索结果补充文档内Chunk顺序。

### 实现的核心功能

- 使用固定RRF排名常数融合两路1-based名次，同时保留原始分数和各通道最佳排名。
- 按`chunk_id`合并两路命中并拒绝同一身份的冲突载荷，避免静默拼接不一致内容。
- 在最终TopK前合并同文档、同章节、连续Chunk，并保留全部Chunk ID、顺序和内容哈希。

---

## 2026-08-19 — `[T457-T461] M4.9 Rerank`

### 核心解决的问题

让混合召回候选按当前查询的模型相关性重新排序并拦截低分片段，同时防止超时、缺失分数、重复身份或
异常模型结构污染后续RAG上下文。

### 实现的核心代码

- `agent-service/app/knowledge/reranking.py`：Reranker协议、严格响应、重排结果、阈值门禁和超时降级。
- `agent-service/tests/knowledge/test_reranking.py`：重排前后、稳定同分、低相关拦截和失败边界测试。

### 实现的核心功能

- 将查询与最小候选载荷交给可注入Reranker，并要求0～1分数唯一且完整覆盖全部候选。
- 按模型分数稳定重排且保留原始RetrievalResult，低于阈值的片段不会进入正常结果。
- 超时显式回退原RRF顺序且跳过未知分数过滤；其他调用失败和不可信响应关闭失败。

---

## 2026-08-20 — `[T462-T468] M4.10 引用结构`

### 核心解决的问题

让规范回答依据能够定位到具体文档版本、章节和全部原始Chunk，并让用户按需查看引用原文，避免合并片段后
丢失来源或把不同量纲的RRF分数伪装成模型相关性。

### 实现的核心代码

- `agent-service/app/schemas/knowledge.py`、`app/knowledge/citations.py`：严格Citation及重排结果转换。
- `agent-service/app/repositories/knowledge_search.py`：检索时透传规范标题和版本。
- `agent-frontend/src/components/KnowledgeCitationCard.vue`：引用身份、分数和原文展开卡片。

### 实现的核心功能

- 引用保存文档ID、名称、版本、章节、主Chunk、全部合并Chunk、正文和可空重排分数。
- 主Chunk必须匹配完整Chunk列表首项，重复身份、非法分数和不完整结构被拒绝。
- 前端默认隐藏长原文，可查看和收起；未获得重排分数时显示未评分。

---

## 2026-08-20 — `[T469-T476] M4.11 规范问答 Workflow`

### 核心解决的问题

把分离的检索、重排和引用组件组成可路由的确定性规范问答链，并阻止无结果、重排不可用或模型引用异常时
生成缺少规范依据的结论。

### 实现的核心代码

- `agent-service/app/knowledge/retrieval.py`：Query Embedding、双路召回和RRF统一入口。
- `agent-service/app/workflows/specification_qa.py`：固定问答图、生成门禁、安全回答和SpecificationSkill。
- `agent-service/app/schemas/specification.py`：回答草稿、终态和带引用结果契约。

### 实现的核心功能

- 确定性规范化查询，并将显式日期/权限与页面可选产品、卫星提示合并为统一过滤器。
- 固定执行关键词、向量、RRF、Rerank和充足性检查，只在可信候选存在时调用回答模型。
- 模型只能选择既有引用身份；无结果、重排超时及生成失败返回不同状态的无结论安全回答。

---

## 2026-08-22 — `[T477-T487] M4.12 RAG 评测`

### 核心解决的问题

为规范检索建立固定问题、预期文档和预期章节组成的可重复质量基线，统一比较四种策略，避免用少量演示
查询或不同相关口径主观判断RAG效果。

### 实现的核心代码

- `agent-service/app/evaluation/rag.py`：`RagEvaluationCase`、`KnowledgeRagEvaluationSubject`、`evaluate_rag`和安全失败样本。
- `agent-service/evaluation/rag_cases.jsonl`：50条带统一日期、权限、产品和卫星过滤条件的标注问题。

### 实现的核心功能

- 用文档ID和完整章节路径同时命中定义相关片段，并计算Hit@5、MRR和无关片段占比。
- 在相同过滤契约下执行纯向量、关键词、混合及混合加重排四种策略，Rerank降级时拒绝冒充重排质量。
- 失败样本区分无结果、文档未命中和章节未命中，只输出稳定身份和章节，不记录问题或正文。

---

## 2026-08-22 — `[T501-T507] M5.1 Agent State 扩展`

### 核心解决的问题

让订单诊断状态能够稳定描述动态Agent的动作观察、剩余信息缺口、迭代进度和终止原因，避免后续循环只能
依赖模型临时文本判断历史与停止条件。

### 实现的核心代码

- `agent-service/app/schemas/workflow.py`：`AgentAction`、`AgentObservation`、`InformationGap`、`AgentTerminationReason`和扩展后的`OrderDiagnosisState`。
- `agent-service/tests/test_agent_state.py`：动作边界、观察一致性和完整状态JSON往返测试。

### 实现的核心功能

- 固化七种只读动作和显式`FINISH`动作，以及信息充分、不足、执行异常和四类安全预算终止原因。
- Tool历史只保存动作、参数指纹、安全摘要、新信息标记和结构化错误，不复制原始业务载荷。
- 固定Workflow为新增通道提供中性初始值，保持既有确定性诊断路径和黄金结果不变。

---

## 2026-08-22 — `[T508-T514] M5.2 动作模型`

### 核心解决的问题

把模型的下一步建议限制为可执行的只读动作，并阻止未知Tool、动作与参数错配、未注册执行器或异常模型输出
越过动态Agent的决策边界。

### 实现的核心代码

- `agent-service/app/schemas/action.py`：动作到执行器和参数Schema的唯一映射及`ActionDecision`。
- `agent-service/app/workflows/action_prompt.py`、`action_decision.py`：事实与Tool目录注入、解析、纠错和安全回退。
- `agent-service/tests/test_action_decision.py`：动作映射、Prompt载荷、可用性校验和模型失败测试。

### 实现的核心功能

- 六种Java查询、规范检索和结束动作分别绑定唯一执行器与严格参数，订单和任务ID还必须来自当前状态。
- Prompt只注入已校验业务事实、安全历史、缺口和实际注册的LOW风险Tool描述，页面提示不作为业务事实进入。
- 对象与纯JSON输出共享Schema校验，非法输出纠错一次，未知或不可用动作及模型异常安全结束且不泄露响应。

---

## 2026-08-22 — `[T515-T523] M5.3 LangGraph 动态图`

### 核心解决的问题

把模型的一次动作建议连接成可回环的动态诊断执行链，并确保动作校验、Tool执行、事实合并、完成判断和异常
结束都有确定性节点负责，避免模型直接操纵业务事实或执行失败后继续生成可靠性不明的结论。

### 实现的核心代码

- `agent-service/app/workflows/dynamic_diagnosis.py`：`DynamicDiagnosisWorkflow`、`DynamicDiagnosisState`和八个图节点。
- `agent-service/app/schemas/workflow.py`、`app/workflows/diagnosis_generation.py`：动态终止原因和无事实时的信息不足结果边界。
- `agent-service/tests/test_dynamic_diagnosis_workflow.py`：黄金循环、主动安全结束和Tool异常路径。

### 实现的核心功能

- 编译决策、校验、执行、观察、完成判断和结束分支；每轮只执行一个经过二次校验的LOW风险动作。
- Java Tool结果写入对应强类型事实通道，规范问答显式携带日期与权限并独立保存，不参与业务根因裁决。
- `FINISH`以规则区分信息充分或不足；Tool失败保存安全Observation和StepError，并输出不伪造证据的信息不足结果。

---

## 2026-08-24 — `[T524-T531] M5.4 Agent 执行限制`

### 核心解决的问题

阻止动态诊断在模型不结束、持续重复查询或选择非法执行器时无限消耗资源，并让每一种预算终止和执行拒绝都
进入确定性、可审计的图分支。

### 实现的核心代码

- `agent-service/app/workflows/dynamic_diagnosis.py`：`AgentExecutionLimits`、三阶段限制检查和预算路由。
- `agent-service/app/schemas/workflow.py`：`iteration_count`决策轮次语义。
- `agent-service/tests/test_dynamic_diagnosis_workflow.py`：无限循环、Tool上限、重复、无新增信息和非法动作测试。

### 实现的核心功能

- 默认最多6轮决策、8次Tool调用和连续2次无新增信息，测试可通过严格配置独立验证各预算。
- 调用指纹在BaseTool前拦截重复逻辑调用；决策轮与Tool调用分开计数，`FINISH`只占用决策轮。
- 执行前复核动作唯一映射、LOW风险、Registry、参数、资源归属和权限，拦截写Tool、未知Tool及缺权调用。

---

## 2026-08-25 — `[T532-T538] M5.5 信息充分度判断`

### 核心解决的问题

让动态诊断按当前业务场景确定仍缺少的事实, 避免模型主观宣布信息充分, 也避免固定全量事实规则迫使所有
订单查询与当前阶段无关的数据。

### 实现的核心代码

- `agent-service/app/workflows/information_gaps.py`：`InformationGapDetector`和基础、生产、质检、复核、交付及规范规则。
- `agent-service/app/workflows/diagnosis_rules.py`：`evaluate_dynamic_diagnosis_rules`场景化规则入口。
- `agent-service/app/workflows/dynamic_diagnosis.py`：初始化、Observation后重算缺口以及动态结束判断。
- `agent-service/tests/test_information_gaps.py`：场景化缺口、嵌套事实有效性和动态结论测试。

### 实现的核心功能

- 基础事实校验订单归属、非空任务及有效交付记录, 再按订单和任务状态补充进度、质检、复核与规范要求。
- 通过任务键区分“已查询且没有问题”和“尚未查询”, 并校验进度、问题、复核及交付的父子资源归属。
- 缺口进入动作Prompt并在每轮后更新；`FINISH`或预算终止仍有缺口时只生成信息不足结果, 固定Workflow保持原规则。

---

## 2026-08-25 — `[T539-T549] M5.6 动态路径测试`

### 核心解决的问题

验证动态Agent不仅能运行单个节点, 还会针对五种稳定业务阶段执行受控的最小查询组合, 并确保动态路径没有
改变固定Workflow已经建立的诊断基线。

### 实现的核心代码

- `agent-service/tests/test_dynamic_diagnosis_paths.py`：五订单参数化路径、固定Workflow对照和动态超时恢复测试。
- `agent-service/tests/test_dynamic_diagnosis_workflow.py`：重复、最大轮数、连续无新增信息和非法写Tool回归。
- `agent-service/app/tools/base.py`、`retry.py`：被跨层路径验证的只读Tool有限重试边界。

### 实现的核心功能

- ORDER-001～005分别覆盖生产、生产阻塞、质量复核、等待复核和可交付路径, 且动态结果与固定结果完全一致。
- 只读Tool首次超时只额外重试一次, 恢复后图中保存单条成功Observation, 不把物理重试误计为模型动作。
- 复用确定性限制测试证明重复调用、预算耗尽、无新增信息和写Tool选择不会绕过动态图门禁。

---

## 2026-08-26 — `[T550-T555] M5.7 版本记录`

### 核心解决的问题

让历史Run能够识别创建时对应的Prompt、模型配置、Tool契约和RAG策略, 避免组件升级后只能看到结果却无法
确认执行环境, 同时不把密钥或大段运行载荷写入版本证据。

### 实现的核心代码

- `agent-service/app/schemas/versioning.py`：严格版本快照Schema和诚实的历史不可恢复状态。
- `agent-service/app/versioning.py`：Prompt、模型、Tool Schema摘要和RAG策略的统一快照构造。
- `agent-service/app/services/run_lifecycle.py`、`models/agent_runtime.py`：创建时强制关联并冻结Run版本。
- `agent-service/migrations/versions/0007_run_version_snapshot.py`：旧Run回填与非空字段迁移。

### 实现的核心功能

- 记录Router与Agent Prompt版本；真实模型未配置时显式保存未配置状态, 配置后记录名称和非敏感参数。
- 对排序后的Tool输入/输出Schema、安全等级和权限计算稳定SHA-256, 并记录RAG策略与Embedding索引版本。
- 新Run必须保存完整快照；迁移前Run标记为不可恢复, 终态流转不能修改版本字段。

---

## 2026-08-26 — `[T601-T609] M6.1 Approval 数据模型`

### 核心解决的问题

为模型提出的业务写操作建立独立、可审查且可并发校验的持久化边界，保留原始草稿、用户修改、目标版本和
确认事实，防止跳过确认、重复确认或并发覆盖后进入执行阶段。

### 实现的核心代码

- `agent-service/app/models/approval.py`：Approval稳定枚举、持久化字段和数据库约束。
- `agent-service/app/repositories/approval.py`：按预期状态比较更新的持久化操作。
- `agent-service/app/services/approval_lifecycle.py`：草稿快照、修改副本和确定性状态流转。
- `agent-service/migrations/versions/0008_approval_records.py`：Approval表、Run关联、约束和索引迁移。

### 实现的核心功能

- 原始Agent草稿与用户修改副本分开保存，执行侧可确定性选择修改副本且不丢失审查基线。
- 固化`SUBMIT_REVIEW`/`CREATE_REWORK`与对应写Tool的一一映射，同时保存目标任务和乐观锁版本。
- 状态迁移使用比较更新阻止跳步与并发覆盖；确认后禁止修改，来源Run删除时仍保留Approval审计证据。

---

## 2026-08-26 — `[T610-T615] M6.2 复核草稿 Schema`

### 核心解决的问题

阻止模型生成内容或用户修改以任意JSON进入Approval，避免非最终复核结论、超长文案、无效或重复引用、返工
结论矛盾及目标任务漂移一直延迟到业务写入阶段才暴露。

### 实现的核心代码

- `agent-service/app/schemas/approval.py`：Conclusion、ReworkSuggestion、ReviewDraft及规范引用校验。
- `agent-service/app/services/approval_lifecycle.py`：创建、修改和读取最终草稿时统一应用ReviewDraft契约。
- `agent-service/tests/test_approval_schemas.py`：字段长度、跨字段关系、引用和不可变性测试。

### 实现的核心功能

- 复核结论只允许`APPROVED`、`REJECTED`或`REWORK_REQUIRED`，明确排除Java不接受的`PENDING`。
- 返工结论、是否返工与返工类型必须一致，复核意见上限与Java接口的1000字符约束对齐。
- 规范依据复用Citation版本和Chunk身份并拒绝重复来源；草稿同时携带任务和质检问题身份，用户修改不得替换影响对象。

---

## 2026-08-26 — `[T616-T623] M6.3 草稿生成 Workflow`

### 核心解决的问题

避免直接根据历史诊断或模型自由输出生成待确认内容；草稿保存前重新读取Java任务与质检事实、取得现行规范引用，
并在任何事实、引用或结构不可信时关闭失败且不执行写操作。

### 实现的核心代码

- `agent-service/app/workflows/review_draft.py`：`ReviewDraftGenerationWorkflow`、模型输入契约、事实与引用门禁。
- `agent-service/app/services/review_draft_store.py`：`DatabaseReviewDraftStore`短事务读取和Approval/Run原子保存。
- `agent-service/app/repositories/agent_runtime.py`、`app/services/run_lifecycle.py`：最近诊断定位与`WAITING_APPROVAL`转换。

### 实现的核心功能

- 只接受会话最近的`SUCCEEDED`诊断Run，并从JSON快照恢复严格`DiagnosisResult`，不回退使用更旧诊断。
- 强制刷新任务详情和质检问题，校验任务所属订单后检索当前日期、权限范围内的规范依据。
- 模型草稿必须保持目标任务不变、选择刷新结果中的质检问题并只引用RAG白名单；Approval和Run原子进入等待确认，全流程不调用Java写接口。

---

## 2026-08-26 — `[T624-T633] M6.4 前端确认卡片`

### 核心解决的问题

让用户在授权前看清复核草稿的影响对象、目标版本、问题摘要和规范依据，并能修改最终意见与结论；通过二次确认和
本地提交锁避免误触、空意见及连续点击把同一人工决定重复发送给后续接口。

### 实现的核心代码

- `agent-frontend/src/types/agent.ts`：与后端Approval、ReviewDraft和状态枚举对齐的前端契约。
- `agent-frontend/src/components/ReviewApprovalCard.vue`：草稿展示、编辑、引用、二次确认和事件边界。
- `agent-frontend/src/components/ReviewApprovalCard.spec.ts`：内容展示、编辑归一化、结论联动和防重复交互测试。

### 实现的核心功能

- 展示任务ID、质检问题ID、目标版本、问题摘要和可展开的完整规范引用，用户只能编辑复核意见与最终结论。
- 结论切换时确定性同步返工建议，确认事件携带去除首尾空格后的完整草稿，取消事件只携带Approval身份。
- 非待确认状态、父级提交中和本地已触发操作都会禁用按钮；组件不调用HTTP或Java写接口。

---

## 2026-08-27 — `[T634-T646] M6.5 写 Tool`

### 核心解决的问题

防止模型或调用方在用户确认后重新指定任务、质检问题、版本或文案，并避免写接口重放产生重复业务记录；Java成功
响应还必须留下可追溯、不可被不同结果覆盖的Approval执行证据。

### 实现的核心代码

- `agent-service/app/tools/write.py`、`app/schemas/write_tools.py`：两个高风险写Tool及其严格请求、响应契约。
- `agent-service/app/services/approval_execution_store.py`、`app/repositories/approval.py`：执行快照读取和首次结果比较保存。
- `agent-service/app/models/approval.py`、`migrations/versions/0009_approval_execution_result.py`：执行结果字段与数据库约束。
- `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java`：动态业务标识统一为大写安全格式。

### 实现的核心功能

- 写Tool只接收Approval身份和幂等键，业务请求完全映射自`EXECUTING`确认快照，并校验待执行Tool和当前确认人。
- 复核回写核对问题、结论、意见和递增版本；返工创建还限制受支持类型，并保存Java返回的新资源身份。
- 两个Tool均不自动重试且不暴露给动态模型；相同Java业务结果的幂等重放保留首次Trace，不同结果不能覆盖执行证据。

---

## 2026-08-27 — `[T647-T654] M6.6 确认前重新校验`

### 核心解决的问题

防止用户确认后业务版本、任务状态或质检问题已经变化却继续按旧草稿写入，并阻止连续点击、多标签页和并发请求让
同一Approval多次进入Java写接口。

### 实现的核心代码

- `agent-service/app/services/approval_confirmation.py`：确认快照、有效期、事实刷新、CAS执行锁和终态裁决。
- `agent-service/app/api/approvals.py`、`app/schemas/approval_execution.py`：严格确认HTTP请求、成功结果和错误契约。
- `agent-service/app/main.py`：应用生命周期注册独立写Tool注册表和Approval确认路由。
- `agent-frontend/src/api/agentClient.ts`：确认请求、写入结果校验及Approval错误映射。

### 实现的核心功能

- 原子保存用户最终草稿与确认人，默认15分钟有效期；确认人、请求草稿或角色不一致时不读取Java、更不执行写Tool。
- 强制刷新任务和质检问题，版本、任务状态、问题归属/状态或返工类型变化时以`STALE`关闭，不把旧确认用于新事实。
- 数据库比较更新只允许一个请求进入`EXECUTING`；成功保存`SUCCEEDED`和执行结果，写冲突进入`STALE`，其他写失败进入`FAILED`，成功重放直接返回首次结果。

---

## 2026-08-27 — `[T655-T660] M6.7 操作日志`

### 核心解决的问题

补齐人工授权写操作的Agent侧审计证据，使模型原始草稿、用户最终修改、实际写结果或失败状态和Java Trace能够按
一次Approval关联查询，同时避免与Java已有业务事务日志混表。

### 实现的核心代码

- `agent-service/app/models/operation_log.py`、`migrations/versions/0010_operation_logs.py`：隔离的Agent操作日志表和约束。
- `agent-service/app/services/operation_log.py`、`app/schemas/operation_log.py`：受控摘要、字段差异构建和严格详情契约。
- `agent-service/app/services/approval_confirmation.py`：日志创建与Approval终态的原子提交。
- `agent-service/app/api/approvals.py`、`agent-frontend/src/api/agentClient.ts`：按Approval读取日志及前端运行时校验。

### 实现的核心功能

- 每个Approval最多保存一条成功或失败操作日志，写前摘要来自最终授权草稿，写后摘要来自严格Tool结果或机器错误。
- 用户修改按稳定字段路径比较；规范依据只保留文档、版本和Chunk身份，不把长篇引用正文复制到日志。
- 日志与`SUCCEEDED`、`STALE`或`FAILED`终态同事务提交；详情接口只允许当前最小权限模型下的原确认人读取。

---

## 2026-08-28 — `[T701-T710] M7.1 Run 完整字段`

### 核心解决的问题

补齐一次Run实际使用的页面上下文、最终路由、Token与Tool调用统计、总耗时和终止原因，使成功与失败运行都能直接
回答“带着什么上下文、经过什么决策、用了多少资源以及为什么结束”，同时不为历史记录补造原本不存在的执行事实。

### 实现的核心代码

- `agent-service/app/models/agent_runtime.py`、`migrations/versions/0011_run_observability.py`：Run运行字段、约束和兼容迁移。
- `agent-service/app/schemas/run_observability.py`：输入、输出和总Token的严格一致性契约。
- `agent-service/app/services/run_lifecycle.py`、`repositories/agent_runtime.py`：页面/路由快照保存及终态用量、耗时原子更新。
- `agent-service/app/services/order_diagnosis.py`：固定诊断Run接入实际页面、Tool调用和终止摘要。

### 实现的核心功能

- Run创建时冻结最终解析后的PageContext，活动Run可保存严格Router结果，不记录用户消息或Java响应作为上下文快照。
- 成功和失败终态统一保存自洽Token计数、Tool逻辑调用数、非负毫秒耗时和大写稳定终止原因，并继续使用数据库CAS裁决唯一终态。
- 模型、Prompt、Tool Schema与RAG版本复用M5.7不可变快照；无Router/模型路径和迁移前历史Run明确保留空值或零计数。

---

## 2026-08-29 — `[T711-T720] M7.2 Step 完整类型`

### 核心解决的问题

将只能表达四类早期Workflow动作的Step扩展为九种稳定执行分类，使路由、动态决策、规范检索、人工确认和写回不再被混入模型、Tool或模糊的RULE记录。

### 实现的核心代码

- `agent-service/app/models/agent_runtime.py`、`migrations/versions/0012_step_types.py`：九种Step枚举、数据库约束和新旧分类转换。
- `agent-service/app/workflows/order_diagnosis.py`：固定诊断的规则裁决与文案生成改用`WORKFLOW` Step。
- `agent-service/app/services/step_lifecycle.py`：九种类型共用的父Run校验、摘要脱敏、长度截断和原子终态入口。

### 实现的核心功能

- Step可按`CONTEXT/ROUTER/WORKFLOW/AGENT/TOOL/RAG/LLM/APPROVAL/WRITEBACK`稳定落库，并保留原有Run关联、序号、状态、错误和耗时语义。
- 旧`RULE`在升级时转为`WORKFLOW`；降级时不受旧约束支持的新类型收敛为`RULE`，避免迁移被历史数据阻断。
- 所有类型的输入与输出均复用同一摘要保护边界；类型是可观测语义，不会给模型增加执行权限或代替Java业务校验。

---

## 2026-08-29 — `[T721-T730] M7.3 SSE 事件服务`

### 核心解决的问题

让页面可以在诊断、规范检索、人工确认和写回执行期间看到有序进度，并在短暂断线后从最后事件继续，而不是只能等待
同步HTTP最终结果或把网络中断误判成业务失败。

### 实现的核心代码

- `agent-service/app/schemas/events.py`、`app/services/run_events.py`：严格事件契约、有界流历史、回放、心跳和订阅清理。
- `agent-service/app/api/run_events.py`、`app/api/order_diagnosis.py`、`app/api/approvals.py`：用户隔离SSE入口及请求与事件流绑定。
- `agent-service/app/workflows/recording.py`、`app/workflows/specification_qa.py`：Tool与RAG阶段的安全事件发布。
- `agent-service/app/services/order_diagnosis.py`、`app/workflows/review_draft.py`、`app/services/approval_confirmation.py`：Run、诊断、Approval和写回终态发布。

### 实现的核心功能

- 15种稳定事件共用流内递增身份、Trace、可选Run/Step身份和受限JSON数据，拒绝常见凭据键、过深结构和超大内容。
- 客户端先连接自生成流标识，再通过请求头绑定诊断或确认；不同用户不能订阅或发布到对方事件流。
- 心跳维持空闲连接，`Last-Event-ID`回放有界历史，终态与断开会清理订阅；事件只提供进度，不替代Run/Step或Java事实。

---

## 2026-08-29 — `[T731-T738] M7.4 前端实时步骤展示`

### 核心解决的问题

把后端有序SSE事件转换为用户能理解的实时执行步骤，使诊断期间可以区分连接、Run、Tool、RAG、人工确认、写回和失败状态，并在短暂断线后从最后事件续接。

### 实现的核心代码

- `agent-frontend/src/api/runEventClient.ts`、`src/types/runEvents.ts`：带身份的流连接、严格事件解析、有限重连和错误契约。
- `agent-frontend/src/observability/runEventTimeline.ts`、`src/components/AgentRunTimeline.vue`：纯事件归并、步骤状态、失败定位和耗时展示。
- `agent-frontend/src/components/AgentDiagnosisDrawer.vue`、`src/api/agentClient.ts`：先连接再诊断的流标识绑定及生命周期清理。
- `agent-frontend/server.mjs`：生产同源代理的SSE专用上游不可用响应。

### 实现的核心功能

- 浏览器使用Fetch流读取SSE，以便同时发送用户身份和`Last-Event-ID`；连接确认后才发诊断请求，避免遗漏最早事件。
- 重连回放按序号去重并拒绝不连续或结构非法的事件；切单、重试和组件卸载会关闭旧连接，避免旧Run污染当前订单。
- 开始/完成事件被配对为可读时间线并计算耗时，失败码定位到正在执行的步骤；最终诊断仍来自严格HTTP响应，不用进度事件替代业务结果。

---

## 2026-08-30 — `[T739-T748] M7.5 Run 历史页面`

### 核心解决的问题

为已经持久化的Run建立用户隔离的列表、详情和Step查询入口，并把历史证据组织成可分页、可重试的Web页面，使刷新后仍能回看诊断、规范依据、人工修改和失败位置。

### 实现的核心代码

- `agent-service/app/schemas/run_history.py`、`app/services/run_history.py`：Run列表/详情、Step时间线、诊断结果和Approval历史的严格投影。
- `agent-service/app/repositories/agent_runtime.py`、`app/repositories/approval.py`：Session所有者联表校验、稳定分页及Run关联记录查询。
- `agent-service/app/api/runs.py`：Run列表、详情和Step只读HTTP入口及统一安全错误。
- `agent-frontend/src/api/runHistoryClient.ts`、`src/components/RunHistoryPage.vue`：运行时响应校验、列表/详情隔离加载和完整历史视图。

### 实现的核心功能

- 当前用户只能查询自己Session下的Run，不存在和他人Run共用404；列表按`created_at DESC, run_id DESC`稳定分页，详情与Step每次重新校验所有权。
- 页面选择Run后并行读取详情与步骤，以九类Step展示受控输入输出摘要，并分别呈现诊断结果、规范引用、Approval原稿/最终稿差异及错误码、失败步骤和终止原因。
- 历史页面不读取Java业务表，列表和详情均不返回用户消息、完整上下文、Router或版本快照，Tool也只展示落库前已脱敏截断的摘要。

---

## 2026-08-31 — `[T749] M7.6-A 模型配置与环境变量校验`

### 核心解决的问题

修正Compose虽然传入模型地址和密钥、但Settings未声明字段而静默忽略的问题，并防止只有模型名称、没有可调用地址的
半配置状态被记录为已启用模型。

### 实现的核心代码

- `agent-service/app/settings.py`：OpenAI兼容Provider、模型地址、SecretStr密钥、启用条件和跨字段校验。
- `agent-service/app/versioning.py`：Run版本快照复用统一`model_configured`判定。
- `.env.example`、`docker-compose.yml`：统一`openai_compatible`默认值和启用说明。

### 实现的核心功能

- 旧`openai`配置会规范为`openai_compatible`，其他未支持Provider在配置加载阶段关闭失败。
- 空`MODEL_NAME`明确保持模型关闭；非空模型名称必须同时提供合法HTTP(S) Base URL，本地无鉴权网关允许空密钥。
- 模型密钥使用`SecretStr`保存，Run版本快照只记录非敏感Provider、模型名和生成参数，不保存地址或密钥。

---

## 2026-08-31 — `[T750] M7.6-A 模型能力查询Schema与服务`

### 核心解决的问题

让页面和运维能够通过稳定接口判断模型配置是否已经启用，避免读取进程环境、解析日志或把健康检查误当成模型能力；
同时防止查询接口泄露模型网关地址和API Key。

### 实现的核心代码

- `agent-service/app/schemas/model_capabilities.py`：模型配置能力的严格响应契约和状态一致性校验。
- `agent-service/app/services/model_capabilities.py`：从校验后Settings投影非敏感模型身份。
- `agent-service/app/api/model_capabilities.py`、`app/main.py`：只读能力查询路由和应用服务接线。

### 实现的核心功能

- `GET /api/agent/capabilities/model`稳定返回配置状态、Provider和模型名，关闭状态不会保留无效模型身份。
- Schema拒绝“已启用却没有模型身份”及“已关闭却仍宣称模型身份”的矛盾响应。
- 能力查询不返回Base URL或API Key，也不发网络请求；它只证明配置通过校验，不证明模型可达或实际参与Run。

---

## 2026-08-31 — `[T751-T753] M7.6-A 结构化模型调用与LLM Step观测`

### 核心解决的问题

把已校验的模型配置落实为可复用的真实HTTP调用边界，并为每次模型请求提供稳定错误、有限重试和独立Step指标，使后续业务适配器不必各自处理供应商协议或从文本摘要中推断Token和重试情况。

### 实现的核心代码

- `agent-service/app/clients/model.py`：Chat Completions请求、响应外壳、结构化输出、错误映射、有限重试和调用指标。
- `agent-service/app/services/model_invocation.py`、`app/workflows/recording.py`：模型调用与LLM Step生命周期的观测接线。
- `agent-service/app/models/agent_runtime.py`、`migrations/versions/0013_llm_step_observability.py`：LLM模型身份、Token和重试次数的独立持久化字段与约束。
- `agent-service/app/schemas/run_history.py`、`agent-frontend/src/components/RunHistoryPage.vue`：LLM Step指标的受控历史投影与展示。

### 实现的核心功能

- 共享Client向OpenAI兼容`/chat/completions`发送JSON Schema请求，依次校验HTTP状态、响应外壳、纯JSON正文和调用方Pydantic Schema。
- 未配置、超时、上游不可用、限流、鉴权、非法请求、非法响应和非法输出使用稳定错误码区分；仅瞬时错误按配置有限退避重试，错误文案不复制供应商正文。
- LLM Step成功时保存实际响应模型名、自洽输入/输出/总Token、耗时和重试次数，失败时保存稳定错误及可确认指标；Prompt、模型正文和凭据不落库，业务Protocol仍留待后续批次适配。

---

## 2026-09-01 — `[T754-T758] M7.6-B 现有模型协议适配`

### 核心解决的问题

把Router、动作决策、规范回答、Rerank和Review草稿五种既有模型Protocol分别接到公共结构化Client，避免各业务组件重复实现供应商HTTP协议，也避免一个通用适配器混淆不同业务语义和权限边界。

### 实现的核心代码

- `agent-service/app/model_adapters.py`：五类单一职责适配器、版本化系统Prompt、输入JSON序列化和Prompt Schema一致性校验。
- `agent-service/app/versioning.py`：把规范回答、Rerank和Review草稿Prompt版本及模型重试参数纳入可重放版本快照。
- `agent-service/tests/test_model_adapters.py`：公共Client请求、五类业务载荷和既有确定性门禁的组合测试。
- `Makefile`：模型协议适配独立验收入口。

### 实现的核心功能

- 五类适配器统一发送system与data消息，并把各自严格Pydantic Schema交给公共Client；输入作为JSON数据处理，不从候选内容中执行指令。
- Router实体证据、Action注册表与参数、回答引用ID、Rerank候选完整性及Review草稿事实关联仍由原组件二次校验，结构合法但业务越界的输出不会被直接采用。
- Review草稿适配器只生成候选草稿，不持有Tool注册表、Approval Store或执行能力；本批次不新增生产API和业务写入。

---

## 2026-09-01 — `[T759-T761] M7.6-C 知识库可运行入库`

### 核心解决的问题

把已经独立存在的目录校验、文档解析、分块、Embedding和Repository组合成可主动执行的全量入库链路，并提供索引就绪状态，避免服务启动隐式访问外部Provider或仅凭配置推断RAG已经可用。

### 实现的核心代码

- `agent-service/app/services/knowledge_ingestion.py`、`app/cli/knowledge_ingest.py`：全目录处理、全部向量先成功、事务内重建和稳定CLI退出码。
- `agent-service/app/repositories/knowledge.py`：目录外文档清理及不读取正文/向量的文档级索引统计。
- `agent-service/app/services/knowledge_index_capabilities.py`、`app/api/knowledge_index_capabilities.py`：目录完整性、Chunk存在性和索引身份就绪判断及只读HTTP入口。
- `agent-service/Dockerfile`、`docker-compose.yml`、`Makefile`：把知识目录加入Agent镜像并提供迁移后显式入库和独立验收入口。

### 实现的核心功能

- CLI先验证catalog、读取和分块全部文档，再批量生成全部Embedding；任何前置失败都不写数据库，目录外旧文档清理和当前目录重建在同一事务内提交。
- 全量命令可重复执行，稳定Chunk身份会替换旧索引而不追加重复记录；输出只包含数量、清理结果和非敏感索引身份，配置/输入、Embedding和持久化失败使用不同退出码。
- 能力查询使用四态结果区分未入库、不完整、索引身份不匹配和可用，只有目录身份、每文档Chunk及当前Provider/模型/维度/版本全部一致才就绪，查询和服务启动都不访问外部Embedding。

---

## 2026-09-03 — `[T762-T766] M7.6-D 统一Agent入口与路由闭环`

### 核心解决的问题

把已经存在的Session、模型Router、实体合并、澄清、Run/Step和SSE组件收口到唯一生产消息入口，避免自然语言请求只能走固定诊断，或模型故障被静默伪装成可执行路由结果。

### 实现的核心代码

- `agent-service/app/schemas/agent_messages.py`：统一消息、澄清选择、五类结果Envelope和安全错误契约。
- `agent-service/app/services/agent_messages.py`：`AgentMessageService`请求生命周期、观测Router调用、澄清续接及`AgentSkillDispatcher`边界。
- `agent-service/app/api/agent_messages.py`、`app/main.py`：统一能力查询、消息HTTP入口、身份/SSE接线和默认未接线Skill错误。
- `agent-service/app/repositories/agent_runtime.py`：最近有效结果查询同时排除SQL空值与JSON空值，避免当前运行中的Run覆盖澄清来源。
- `agent-service/app/services/run_history.py`：统一结果历史恢复及既有固定诊断快照兼容。

### 实现的核心功能

- `POST /api/agent/messages`可创建或复用本人Session，持久化用户消息和Run，并为上下文、每次Router模型调用、路由门禁及Skill分发记录有序Step和SSE终态。
- 参数仍按用户本轮输入、已确认Session、页面提示、Session候选的固定优先级合并；澄清选择必须引用同一Session中最近返回结果的成功澄清Run，低置信度、缺参、冲突和意图确认都不能绕过服务端门禁。
- 统一结果以`kind`区分状态、诊断、规范回答、澄清和Approval；历史接口继续保留固定诊断字段，同时提供统一Envelope，模型未配置、不可用、两次结构化输出非法和Skill未接线均返回独立稳定错误。

---

## 2026-09-03 — `[T767-T769] M7.6-E 三个只读Skill生产接线`

### 核心解决的问题

把订单/任务状态、动态诊断和规范问答从独立Workflow测试组件接入统一Agent消息入口，使生产Router通过门禁后能够执行真实只读链路，同时保持Java业务事实、RAG规范依据和模型决策互不越权。

### 实现的核心代码

- `agent-service/app/workflows/order_status.py`：订单与任务状态的确定性意图校验、Java Tool调用和最小结果投影。
- `agent-service/app/services/production_agent_skills.py`：三个只读Skill分发、Action循环装配、知识索引门禁、服务端权限/日期及嵌套Step观测。
- `agent-service/app/services/agent_messages.py`、`app/workflows/recording.py`：Skill请求级Run上下文、模型/Tool用量聚合和AGENT、LLM、TOOL、RAG记录能力。
- `agent-service/app/main.py`：生产分发器、七个只读Tool和按配置惰性启用的Query Embedding Provider应用接线。

### 实现的核心功能

- 状态查询按`ORDER_QUERY`或`TASK_TRACKING`唯一调用对应Java只读Tool，返回的标识、状态和摘要均从已校验Tool结果投影，不调用模型补造业务事实。
- 动态诊断在同一Run内让Action模型选择注册表中的LOW风险动作，再由确定性Workflow校验参数、资源归属、权限、重复调用及执行预算；模型调用、动作轮次和Tool调用分别形成有序Step，Action模型失败会保留稳定错误并使Turn失败，不会冒充正常信息不足。
- 规范问答先校验完整索引身份，以服务端角色和当前日期执行元数据过滤，再运行Query Embedding、双路召回、RRF、Rerank和引用白名单回答；索引或Embedding未就绪返回稳定错误，不回退为无引用规范结论。

---

## 2026-09-06 — `[T770-T773] M7.6-F Review与Approval生产闭环`

### 核心解决的问题

把Review草稿从独立组件接入统一Agent入口，并让来源诊断、人工等待、确认写回和独立返工授权形成可追溯生命周期，
避免复用诊断Run终态、未确认写入或把返工建议当成复核授权的一部分。

### 实现的核心代码

- `agent-service/app/services/production_agent_skills.py`、`app/workflows/review_draft.py`：Review生产分发、事实/规范刷新及结构化草稿生成。
- `agent-service/app/services/review_draft_store.py`、`app/services/approval_run_lifecycle.py`：Approval草稿、来源Run、APPROVAL/WRITEBACK Step和等待/终态原子联动。
- `agent-service/app/services/approval_confirmation.py`、`app/services/approval_orchestration.py`：确认执行、取消、失效和独立返工Approval编排。
- `agent-service/app/api/approvals.py`、`migrations/versions/0014_review_source_run.py`：确认/取消/返工HTTP入口及Run来源关系。

### 实现的核心功能

- Review消息创建新的`WAITING_APPROVAL` Run并关联同一Session最近成功诊断，来源诊断保持`SUCCEEDED`；草稿生成只调用只读Java Tool、RAG和模型，不调用写Tool。
- 用户确认后重新读取Java事实并以Approval CAS抢占唯一执行权，成功、写失败、业务冲突、过期和取消同步结束APPROVAL/WRITEBACK Step及Run，重复确认只返回已保存结果。
- `CREATE_REWORK`只能从已成功且明确要求返工的复核显式创建独立Run和第二个Approval；重复创建返回既有活动授权，终态失败或取消后可重新授权，复核与返工分别确认、分别写入且各自幂等。

---

## 2026-09-07 — `[T774-T781] M7.6-G 统一页面与端到端验收`

### 核心解决的问题

把后端统一消息、五类结果、SSE和Approval能力接入订单页唯一Agent抽屉，使状态查询、动态诊断、规范问答、澄清和人工确认不再分散于未接线组件，并以可重复集成测试证明模型失败不会伪装成功。

### 实现的核心代码

- `agent-frontend/src/api/agentClient.ts`、`src/types/agent.ts`：统一能力/消息Client、五类判别联合类型及运行时响应校验。
- `agent-frontend/src/components/AgentWorkspaceDrawer.vue`、`AgentResultView.vue`：Session/SSE编排、异步请求隔离、结果分派、澄清和Review/返工确认交互。
- `agent-service/tests/test_agent_persistence.py`：真实PostgreSQL、Java HTTP边界、模型Stub和确定性Embedding下的四Skill统一入口集成。
- `scripts/test-agent-page-e2e.sh`、`Makefile`：生产镜像、迁移、同源代理、固定诊断及模型失败语义的一键隔离验收。

### 实现的核心功能

- 同一订单复用Session，每次统一消息和Approval确认使用新SSE流；切换订单会关闭旧流并用请求序号拒绝迟到结果，重试只重放当前失败请求。
- 页面按`kind`分别展示Java状态事实、动态诊断证据、带版本Chunk的规范回答、服务端受控澄清候选和可编辑Approval；复核与返工分别二次确认，取消不写Java。
- 四Skill集成验证Review基于同Session最近成功诊断创建独立等待Run，刷新Java任务/质检事实和规范引用后只保存草稿；Docker烟测验证动态模型未配置返回稳定错误且固定诊断仍可用。

---

## 2026-09-07 — `[T751-T753兼容修复] M7.6-A DeepSeek JSON Object适配`

### 核心解决的问题

修复公共模型Client固定发送`response_format=json_schema`导致DeepSeek Chat Completions拒绝统一Agent请求的问题，同时避免为了兼容供应商而取消本地结构校验。

### 实现的核心代码

- `agent-service/app/settings.py`、`app/clients/model.py`：结构化输出模式配置、JSON Object请求及Schema系统指令。
- `agent-service/app/versioning.py`：把实际响应格式写入非敏感Run版本快照。
- `.env.example`、`docker-compose.yml`：部署参数透传和DeepSeek模式说明。

### 实现的核心功能

- 默认保留原有`json_schema`协议，DeepSeek显式选择`json_object`，不再依赖模型名或网关地址进行隐式猜测。
- JSON Object模式把目标Pydantic Schema加入系统指令，并可显式关闭DeepSeek思考模式；收到的正文仍执行严格本地校验，非法字段、类型或业务契约继续失败。
- 当前DeepSeek配置已通过最小真实结构化调用和`ORDER-003`统一状态查询，协议拒绝不会被降级或伪装为成功。

---

## 2026-09-07 — `[M7.7-01～08] Java与Tool故障矩阵`

### 核心解决的问题

把Java连接、超时、HTTP业务错误和响应契约损坏从零散测试收口成可重复的全链路矩阵，使Agent失败时可以定位到
`load_order` Tool步骤，并区分瞬时故障、确定性上游错误和响应校验错误。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/fault/DemoFaultInterceptor.java`：默认关闭且仅限GET的404、409、错误JSON等故障模拟。
- `agent-service/tests/e2e/test_order_diagnosis.py`：八类故障的参数化HTTP、错误码、重试次数及Run/Step断言。
- `Makefile`：`test-agent-java-fault-matrix`隔离验收入口。

### 实现的核心功能

- 连接失败与读取超时只进行一次有限重试，403、404、409、500及响应校验错误不盲目重试。
- 每类失败都保存`FAILED` Run和失败TOOL Step，向调用方返回稳定错误码与安全提示，不泄露非法响应正文。
- Java注入测试证明故障开关默认无效且不会作用于写请求，避免异常演练产生错误业务写入。

---

## 2026-09-09 — `[T782] M7.8统一EvalRunner`

### 核心解决的问题

为原本独立运行的Router、RAG及后续领域评测建立统一注册和执行边界，避免各套件自行处理名称、选择顺序与异常，
并防止无效选择在部分评测已经运行后才暴露。

### 实现的核心代码

- `agent-service/app/evaluation/runner.py`：`EvaluationSuite`、`EvalRunner`及配置、执行和报告契约错误。
- `agent-service/tests/evaluation/test_eval_runner.py`：注册、选择、顺序、只读结果、失败安全性和取消语义测试。
- `agent-service/app/evaluation/__init__.py`、`Makefile`：公共导出和独立验收入口。

### 实现的核心功能

- 命名异步Suite在执行前完成格式、非空、唯一和存在性校验，全部运行或显式子集都保持确定顺序。
- Suite必须返回Pydantic报告，Runner使用只读名称映射承接不同领域结果，为后续统一Schema和导出保留强类型边界。
- Suite执行异常只暴露稳定名称并保留异常链，后续Suite不会继续执行；任务取消不被包装，调用方仍可正常停止评测。

---

## 2026-09-09 — `[M7.9-路由指标] 稳定路由质量口径`

### 核心解决的问题

把原有整条实体完全一致率拆解为消息参数提取、页面或会话参数补全、澄清触发和错误业务Skill分发，使路由回归可以
定位到具体能力，而不是只看到单一通过率变化。

### 实现的核心代码

- `agent-service/app/evaluation/router.py`：路由指标分类、字段计数、澄清判定、业务Skill映射和报告字段。
- `agent-service/tests/evaluation/test_router_eval.py`：完整固定集分母及混合成功/失败指标公式测试。
- `Makefile`：`test-eval-metrics`独立验收入口。

### 实现的核心功能

- 参数提取和上下文补全按适用类别中的期望字段分别计算，并同时输出正确数、期望数和比率。
- 澄清触发按是否需要澄清计算，原因差异继续由既有失败样本记录；错误Tool路由按READY预测是否进入非预期Skill计算。
- 保留意图准确率、整条参数完全一致率和混淆矩阵，新增指标不改变历史评测含义，也不把可控Subject结果声明为真实模型质量。

---

## 2026-09-09 — `[M7.9-Tool指标] 非敏感Tool质量聚合`

### 核心解决的问题

为Tool参数门禁、纠错、最终执行、有限重试和重复调用建立彼此独立的稳定指标，避免只用最终成功率掩盖首次参数质量
退化或不必要的重试与重复动作。

### 实现的核心代码

- `agent-service/app/evaluation/tools.py`：`ToolEvaluationOutcome`、`ToolEvaluationReport`和五项指标聚合器。
- `agent-service/tests/evaluation/test_tool_metrics.py`：混合结果、零分母、重复ID和敏感字段拒绝测试。
- `agent-service/app/evaluation/__init__.py`、`Makefile`：公共导出及统一指标验收入口。

### 实现的核心功能

- 每条用例只保存首次校验、最终成功、重试次数和重复调用标记，不保存Tool原始参数或业务响应。
- 首次参数通过率、最终成功率、平均重试和重复调用按全部用例计算，纠错成功率只以首次参数失败用例为分母。
- 空集合、重复用例ID、非法标识、负重试次数和额外敏感字段关闭失败，无适用纠错样本时返回稳定零值。

---

## 2026-09-10 — `[M7.9-RAG指标] 区分检索、版本与引用质量`

### 核心解决的问题

在既有召回和排序指标上补齐版本过滤与引用文档判断，并区分完整链路没有采集观测和已经观测但结果错误，避免零值掩盖
评测覆盖范围。

### 实现的核心代码

- `agent-service/app/evaluation/rag.py`：`RagEvaluationPrediction`可选链路观测、`RagStrategyMetrics`计数与五项指标聚合。
- `agent-service/tests/evaluation/test_rag_eval.py`：混合观测、未采集零分母及既有检索指标回归测试。
- `Makefile`：RAG评测纳入`test-eval-metrics`统一指标验收入口。

### 实现的核心功能

- 保留Hit@5、MRR和Top-5无关片段占比，按策略增加版本过滤正确率和引用文档正确率及可审计分子、分母。
- `None`表示Subject没有执行对应完整链路且不进入分母，明确的`False`才计为失败，无适用观测时比率稳定返回零值。
- 当前仅验证指标契约与公式，实际版本过滤和最终引用观测仍由T786从确定性链路采集，模型不能自报正确性。

---

## 2026-09-10 — `[M7.9-Agent与观测指标] 量化编排质量和故障可诊断性`

### 核心解决的问题

为Agent整体成功、Tool调用效率、诊断耗时、阶段判断以及异常定位建立统一口径，避免只用最终响应成功或测试通过数掩盖
无效动作、重复调用和不可定位故障。

### 实现的核心代码

- `agent-service/app/evaluation/agents.py`：`AgentEvaluationOutcome`、`AgentEvaluationReport`和六项指标聚合器。
- `agent-service/app/evaluation/observability.py`：异常步骤、错误类型和排查中位时长的观测契约与聚合器。
- `agent-service/tests/evaluation/test_agent_metrics.py`、`test_observability_metrics.py`：混合公式、零分母、数据一致性和敏感字段拒绝测试。
- `agent-service/app/evaluation/__init__.py`、`Makefile`：公共导出及M7.9全部指标统一验收入口。

### 实现的核心功能

- Agent指标分别按用例、全部Tool尝试、有计时用例和有预期阶段用例建立稳定分母，并保存所有可审计计数。
- Tool尝试必须完整归类为已执行、参数无效或重复拒绝；异常步骤只有与预期Step一致才算可定位，错误类型按稳定错误码比较。
- 排查耗时采用中位数降低极端慢样本影响；Outcome不保存原始参数、业务响应或异常正文，真实采集仍由后续领域接线负责。

---

## 2026-09-11 — `[M7.7-09～24] 跨层异常矩阵闭环`

### 核心解决的问题

把Tool、RAG、模型、Agent、Approval和SSE的零散保护测试收口为固定编号矩阵，并补齐关键词与向量检索故障被通用错误
吞并的问题，使失败层级、错误码、重试语义和零误写可以从统一入口稳定回归。

### 实现的核心代码

- `agent-service/app/knowledge/retrieval.py`：`KnowledgeRetrievalErrorCode`、`KnowledgeRetrievalError`及双通道安全错误转换。
- `agent-service/app/services/production_agent_skills.py`：RAG Step对Embedding、检索通道和Rerank错误的稳定投影。
- `agent-service/tests/`下Tool、RAG、模型、Agent、Approval与SSE相关测试：`m77_s09`～`m77_s24`固定场景。
- `Makefile`：剩余矩阵及全部24场景的统一验收入口。

### 实现的核心功能

- Tool非法参数与运行内重复调用均在外部业务执行前拒绝；模型超时、非JSON和Schema错误保留稳定LLM Step与重试事实。
- Embedding失败、向量超时、关键词失败和Rerank失败可定位到RAG Step；空召回、全低分与Rerank超时走安全结果而不生成无依据结论。
- Agent重复决策和最大轮数受预算保护；Approval过期不写Java，并发重复确认最多一次写回；SSE断连只释放订阅资源。

---

## 2026-09-13 — `[T783～T793] M7.8统一评测框架闭环`

### 核心解决的问题

把Router、Tool、RAG、诊断、Agent策略、Approval和异常注入纳入同一套执行与报告契约，使各领域结果能够稳定导出、
追溯数据版本并跨次比较，同时避免把可控替身或离线回放成绩误报为真实Provider质量。

### 实现的核心代码

- `agent-service/app/evaluation/suites.py`：七类Suite适配器、固定目录校验和`standard_evaluation_suites`。
- `agent-service/app/evaluation/reporting.py`：`UnifiedEvaluationReport`、Subject元数据、安全导出和报告比较。
- `agent-service/app/evaluation/acceptance.py`：诊断与Approval验收Outcome、失败摘要和成功率聚合。
- `agent-service/app/evaluation/runner.py`、`agent-service/app/cli/evaluation_report.py`：统一报告执行及离线渲染/对比入口。

### 实现的核心功能

- 七类Suite按固定顺序运行并复用既有领域指标；固定数据集Subject和运行观测Provider保持清晰边界。
- 统一报告强制记录Subject类型、名称和每个Suite的数据版本，拒绝敏感Payload，并支持确定性JSON与Markdown输出。
- 两次报告按兼容Suite的数值路径输出原值与差值，显式报告增删Suite、报告类型和版本变化，不擅自判定指标优劣。

---

## 2026-10-18 — `[T423-T430兼容补充] 千问Embedding响应适配`

### 核心解决的问题

千问兼容接口可能返回请求ID且省略输入Token用量，既有严格响应Schema会拒绝这类正常响应。
定向接纳这些已知元数据差异，使模型配置切换能够继续使用既有向量校验和批处理链路。

### 实现的核心代码

- `agent-service/app/knowledge/embeddings.py`：`_EmbeddingUsage`、`_EmbeddingResponse`。

### 实现的核心功能

- 响应允许可选请求ID，输入Token统计缺失时保留缺失，不生成估计用量。
- 保留总Token、未知字段、向量数量、输入顺序、1536维度和有限数值的既有校验。
- 千问模型、20条批次及独立索引版本可通过环境配置，部署时需加载对应代码与环境，生成完整文档向量后方可用于检索。

---

## 2026-10-19 — `[T749-T753/T423-T430补充] 只读真实Provider烟测入口`

### 核心解决的问题

配置查询不能证明远端模型可调用, 临时验证也缺少统一的输入、失败判定和结果格式。
提供显式执行的最小检查命令, 在完整索引或业务流程前确认真实接口和项目响应契约可用。

### 实现的核心代码

- `agent-service/app/cli/provider_smoke.py`: `run_smoke`、`main`, 目标选择、调用预算和脱敏结果。
- `agent-service/app/knowledge/embeddings.py`: `EmbeddingCallResult`、`embed_with_usage`, 复用向量门禁并返回实际用量。
- `Makefile`: `provider-smoke`, 本机命令入口。

### 实现的核心功能

- 选定对话或Embedding检查, 默认显式读取仓库根环境文件, 固定输入且每类最多一次请求, 关闭自动重试。
- Chat检查最小结构化输出并报告模型名称差异; Embedding检查模型匹配、单条1536维有效向量, 缺少输入用量时保留空值。
- 单项失败不掩盖另一项, 终端只输出白名单JSON和稳定退出码; 不连接数据库、不执行业务Tool或Approval, 不持久化Run/Step或向量。

---

## 2026-10-20 — `[T769补充] 生产规范问答重排预算配置`

### 核心解决的问题

真实规范问答中，固定2秒重排预算会提前取消尚未完成的模型调用，导致有相关规范仍只能安全降级。
提供独立且有上限的生产重排预算，并让运行快照记录实际值，便于部署调整和历史排查。

### 实现的核心代码

- `agent-service/app/settings.py`：`Settings.rag_rerank_timeout_seconds`。
- `agent-service/app/main.py`、`app/services/production_agent_skills.py`：从启动配置经生产Skill分发器传入`SpecificationQaWorkflow`。
- `agent-service/app/versioning.py`：`build_run_version_snapshot`冻结实际重排预算。
- `docker-compose.yml`、`.env.example`：`RAG_RERANK_TIMEOUT_SECONDS`部署入口。

### 实现的核心功能

- 生产重排默认预算30秒，可配置为大于0且不超过120秒，覆盖本次重排的模型尝试、退避与有限重试。
- 保留既有超时安全分支：返回`RERANK_UNAVAILABLE`，不继续调用回答模型、不输出规范结论或引用。
- Run的RAG策略快照从实际启动配置取值，保留原有历史记录；该预算不代表整轮问答或页面等待时限。

---

## 2026-10-20 — `[T774-T775补充] 统一消息等待预算与结果未知提示`

### 核心解决的问题

真实规范问答可能因向量或模型有限重试超过页面原20秒等待时间，造成后台完成而页面已超时。
统一消息使用独立的有限预算，并明确客户端等待超时属于结果未知，减少直接重发造成重复Run或草稿的风险。

### 实现的核心代码

- `agent-frontend/src/api/agentClient.ts`：`AGENT_MESSAGE_TIMEOUT_MS`、`requestAgentMessage`。
- `Makefile`：`test-agent-page`纳入真实Axios计时器的受控慢响应回归。

### 实现的核心功能

- 统一消息使用300秒独立HTTP等待预算，其他Agent接口保留20秒，继续校验五类结果及规范引用。
- 客户端超时提示先查运行历史并关闭本轮直接重试入口，不自动重发请求；后端明确失败的Run、步骤和重试语义保持。
- 等待上限适配当前默认后端预算，不取消后台Run，也不提供结果自动恢复；调整后端预算时需同步核对页面等待时间。

---

## 2026-10-22 — `[T774-T777补充] 跨订单诊断确认切换`

### 核心解决的问题

用户在一个订单页面明确诊断另一订单时，路由采用用户目标，但动态图仍校验原页面订单，导致底层参数错误。
分发前转为可操作的切换提示，确认并加载目标后建立独立会话继续，避免混用原订单上下文。

### 实现的核心代码

- `agent-service/app/routing/decision.py`：`require_matching_diagnosis_page`；`app/schemas/routing.py`：切换原因及候选校验。
- `agent-service/app/services/agent_messages.py`：分发前门禁及待切换时保留原Session。
- `agent-frontend/src/stores/orderStore.ts`：`switchOrderForAgent`，目标加载成功后才提交页面切换。
- `agent-frontend/src/components/AgentWorkspaceDrawer.vue`：确认、取消、原问题续接及会话/SSE隔离；`src/App.vue`绑定目标加载。
- `agent-frontend/src/api/agentClient.ts`、`src/types/agent.ts`：切换契约校验；`AgentResultView.vue`：结果订单标识。

### 实现的核心功能

- READY动态诊断目标与页面不同即返回CLARIFICATION/PAGE_ORDER_MISMATCH，提示阶段不执行Skill、Action模型或业务Tool。
- 确认后加载Java快照，再使用原问题、新Session与SSE创建诊断；取消保留原页面会话，加载失败不提交切换或继续诊断。
- 防止重复点击续接，页面变更或卸载使旧续接失效，结果明确标注订单；保留Java事实、权限及动态图初始化防御校验。

---

## 2026-10-22 — `[T768-T769补充] 规范检索查询边界修复`

### 核心解决的问题

规范问答接受的中文查询可能在关键词预处理时因更小的字符或词元限制失败，导致相同业务问题换一种模型措辞就有不同结果。
统一输入边界并限制实际关键词预算，使合法长查询可以继续规范检索，同时提供不含原文的错误定位信息。

### 实现的核心代码

- `agent-service/app/knowledge/search.py`：`preprocess_keyword_query`，统一字符上限并对过多词元作有界选取。
- `agent-service/app/schemas/action.py`：`SpecificationRetrievalArguments`，动态检索动作与规范问答输入上限一致。
- `agent-service/app/knowledge/retrieval.py`：`KnowledgeRetrievalPipeline.retrieve`，安全记录关键词异常类型与长度。

### 实现的核心功能

- 查询最多2000字符，去重词元过多时固定间隔选取最多64个、覆盖首尾，避免合法长查询直接变成检索失败。
- 仅缩减关键词通道输入，完整规范化问题继续用于向量和回答；空查询、无效词元和超长输入仍拒绝。
- 缩减日志记录字符数和词元数，失败日志记录异常类型和查询长度，不输出原文、SQL参数、连接或业务事实。
- 保留权限与现行版本过滤、证据充足性门禁及真实数据库失败的关闭失败策略，不增加自动重发或业务写入。

---

## 2026-10-24 — `[M0.3/M7.6-G补充] 30单业务场景与页面目录`

### 核心解决的问题

原五单不能展示多任务、多问题、不同质检类型、多条交付及已有返工，页面目录也依赖固定ID逐个读取。
增量扩充业务样本，并让页面从Java加载订单目录与返工事实，保留已完成演示的业务及Agent历史。

### 实现的核心代码

- `business-service/src/main/resources/db/migration/V4__expand_demo_scenarios.sql`：新增25个订单及固定关联数据。
- `BusinessQueryService.getOrders/toOverview`、`OrderQueryController.getOrders`：排序列表与任务返工DTO聚合。
- `agent-frontend/src/stores/orderStore.ts`：`initialize`单次读取Java目录，保留详情请求序号隔离。
- `agent-frontend/src/components/OrderSwitcher.vue`、`TaskList.vue`：搜索分类、列表滚动、能力提示及已有返工展示。
- `scripts/reset-demo`：V4和30单基线校验，恢复预置返工。

### 实现的核心功能

- V4只插入ORDER-006～030，保留原五单、已有写入、审计、Agent历史和知识索引；不修改V2/V3或既有写接口。
- 列表接口返回统一信封的data.orders；overview任务包含排序后的reworkTasks，无返工为[]。
- 页面默认ORDER-003，名称和分类独立于Java事实；多任务与非坐标系场景显示既有预算及只读能力边界。
- 全量重置恢复30订单、34任务、38步骤、24问题、23复核、3返工和31交付，清除人工新增写入及历史。
- 动态诊断继续使用6轮决策、8次Tool上限；事实未齐保留信息不足和真实终止原因，不新增返工类型或自动模型调用。

## 2026-10-29 — `[KB-02.1] 知识管理授权契约`

### 核心解决的问题

后续知识管理需要统一的Java角色权限依据，不能由页面或模型自报知识权限、人工确认及当前状态。
本任务提供无写入的知识授权查询，明确Java权限判断与Python知识版本、状态和确认事务的职责。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/KnowledgeAuthorizationController.java`：`authorize`接口。
- `business-service/src/main/java/com/productline/business/application/KnowledgeAuthorizationService.java`：`authorize`演示角色授权。
- `KnowledgeAuthorizationRequest/KnowledgeAuthorizationResponse`：严格请求与授权结果DTO。
- `KnowledgeManagementAction/KnowledgePermissionScope`：动作白名单、人工确认策略及服务端知识范围。

### 实现的核心功能

- `POST /api/knowledge/authorize`接收演示身份及单个动作，返回同一用户/动作、`INTERNAL_REVIEWER`范围及人工确认要求，沿用统一错误与Trace ID信封。
- 支持READ、UPLOAD、PUBLISH、DISABLE和RETRY_INDEX；非READ动作均要求人工确认，未知字段、非法动作和非REVIEWER角色拒绝。
- 授权查询无数据库或模型依赖，不生成执行凭证；Python接线、确认持久化、知识版本状态事务及实际管理操作尚未实现。

## 2026-10-29 — `[KB-02.2] Python知识授权Schema与HTTP Client`

### 核心解决的问题

Java角色权限查询需要由Python按严格契约调用，响应格式正确仍可能属于其他用户、动作或请求，不能直接交给知识写入流程。
本任务增加带请求关联检查、失败阻断和有限重试的Python授权Client，明确无副作用POST查询与业务写POST的边界。

### 实现的核心代码

- `agent-service/app/schemas/knowledge_authorization.py`：`KnowledgeAuthorizationRequest/Response`及`KnowledgeManagementAction`。
- `agent-service/app/clients/business.py`：`BusinessHttpClient.post_readonly`固定路径白名单及既有信封/错误复用。
- `agent-service/app/clients/knowledge_authorization.py`：`KnowledgeAuthorizationClient.authorize`与`_query_with_retry`。
- `agent-service/app/main.py`：应用lifespan装配授权Client，借用既有业务HTTP连接池。

### 实现的核心功能

- 请求仅包含动作，响应严格校验字段、范围和确认策略，并绑定本次用户、动作及Trace；失败抛出分类异常，不缓存成功结果。
- 默认总预算覆盖全部请求和退避，只对明确瞬时错误最多额外重试一次；拒绝、非法响应和不可重试的Java错误直接停止，取消向上传播。
- 固定只读POST白名单不放宽业务写入的幂等要求；应用启动不主动查询Java，不新增数据库、管理接口或实际知识写入。

## 2026-10-31 — `[KB-02.4] 知识管理草稿Schema、ORM与增量迁移`

### 核心解决的问题

知识管理设计需要可验证的数据底座，避免规范版本重复、当前修订悬空或资料指向其他资料的版本。
本任务把内部库、资料、版本及修订落为独立持久化模型，与旧入库和检索表隔离。

### 实现的核心代码

- `agent-service/app/schemas/managed_knowledge.py`：`ManagedKnowledgeLibraryState/DocumentState`、`ManagedKnowledgeDraftVersion`、`ManagedKnowledgeMetadata.metadata_digest`及`ManagedKnowledgeRevisionSnapshot`。
- `agent-service/app/models/managed_knowledge.py`：四表ORM、版本唯一约束、当前版本归属及延迟修订外键。
- `agent-service/migrations/versions/0015_managed_knowledge_drafts.py`：基于0014新增四表和LEGACY单例，提供本版对象的降级。

### 实现的核心功能

- 内部快照校验来源、规范版本、日期、权限范围、MD/TXT原件定位和解析结果，服务端计算元数据哈希，并验证正文哈希且保留首尾空白。
- 数据库约束同资料规范版本唯一、引用身份唯一、原件key唯一，以及资料/版本/修订归属；同事务先写版本再写修订，提交时禁止悬空。
- 四表与旧索引隔离，默认LEGACY且仅接受DRAFT；不创建上传、修订或发布应用，不导入既有语料，不切换问答源。

## 2026-10-31 — `[KB-02.5] 知识操作、任务、候选索引及版本封存模型`

### 核心解决的问题

首批四表不能保存人工操作、构建失败和重试记录，也不能保留多个候选或历史索引并约束发布证据归属。
本任务补齐处理模型，给后续知识管理服务提供确认、幂等、任务和封存关系的数据基础。

### 实现的核心代码

- `agent-service/app/schemas/managed_knowledge_processing.py`：确认、操作、任务、候选批次及分块的严格内部记录。
- `agent-service/app/schemas/managed_knowledge.py`：`ManagedKnowledgeVersionState`封存状态；保留仅接受DRAFT的输入Schema。
- `agent-service/app/models/managed_knowledge_processing.py`：操作、任务、索引批次和Chunk四表，操作幂等、活动任务排他及重试归属约束。
- `agent-service/app/models/managed_knowledge.py`：封存修订/批次外键、发布状态字段及同资料单一发布版本索引。
- `agent-service/migrations/versions/0016_managed_knowledge_state.py`：基于0015补齐八表模型及封存关系，有封存版本时拒绝降级。

### 实现的核心功能

- 确认快照限制固定字段并绑定操作身份，状态、时间和受控错误码组合须一致；不保存Token、正文或供应商原始异常。
- 操作幂等键唯一、同修订同类活动任务排他；任务绑定所属操作/修订/批次，重试引用同修订同类原任务，保留失败历史。
- 分块按批次共存并拥有独立GIN/HNSW索引；版本封存指向本修订的批次，同资料最多一个PUBLISHED版本，历史导入不伪造平台发布时间。
- 保持LEGACY检索源，不增加文件接收、后台执行、发布事务或管理接口；数据模型不代替Java授权、确认事实复查或批次完整性校验。

## 2026-10-31 — `[KB-02.6] 独立原件、草稿修订与解析应用`

### 核心解决的问题

知识管理需要接收真实文件并保存失败/重试事实，只有模型定义无法防止重复上传、过期草稿上下文和迟到解析覆盖新修订。
本任务把Java权限、原件持久化及短事务接成内部上传/解析应用，让原字节、历史修订和处理结果可以回查。

### 实现的核心代码

- `agent-service/app/knowledge/storage.py`：`KnowledgeOriginalStorage.stage/commit/read/discard`原件边界及校验。
- `agent-service/app/knowledge/managed_parsing.py`、`chunking.py`、`loaders.py`：单份规范化、标题校验及稳定分块输入协议。
- `agent-service/app/repositories/managed_knowledge.py`：`accept_upload/claim_parse/finish_parse/recover_interrupted`事务、执行权及修订保护。
- `agent-service/app/services/knowledge_management.py`：`upload/preview/read_original/start`授权、流程与脱敏异常。
- `agent-service/app/schemas/knowledge_management.py`：上传命令、修订预期及安全结果；`settings.py`、`main.py`和`docker-compose.yml`提供惰性装配及独立持久化配置。

### 实现的核心功能

- 原件逐级拒绝符号链接，流式限制大小、UTF-8及非空文本；固定服务端key原子创建，原始字节与规范化正文分别校验，不覆盖仓库资料或已提交原件。
- Java授权后接受新资料、新规范版本或DRAFT修正；事务复查规范版本和预期资料计数/修订，保存幂等操作、任务及快照，旧活动任务失效。
- 文件、HTTP及解析等待不占用数据库事务，提交结果前核对owner、状态、当前修订及只写一次条件；失败或中断记录保留，旧任务不能覆盖新正文。
- 授权预览和原件读取绑定版本及修订，原件缺失不替换既有正文；文件提交而DB失败保留未引用原件，同字节可校验重用，不提供自动永久删除。
- 应用启动只装配服务，管理激活时处理旧owner中断，不调用Embedding、发布或切换问答源，不提供HTTP管理接口。

## 2026-11-04 — `[KB-02.7] 资料、版本和任务只读管理接口`

### 核心解决的问题

上传解析应用已有资料与处理记录，但管理端无法通过HTTP查询，也不能直接把包含正文、原件位置及内部快照的记录返回页面。
本任务接通Java READ授权、范围过滤和公开字段映射，让资料与历史处理状态具有可验证的查询入口。

### 实现的核心代码

- `agent-service/app/api/knowledge_management.py`：资料/版本/任务六个GET入口、身份解析、参数及安全错误响应。
- `agent-service/app/services/knowledge_management_read.py`：`KnowledgeManagementReadService.query`逐次Java授权和固定错误映射。
- `agent-service/app/repositories/knowledge_management_read.py`：`query`权限过滤、稳定分页、同快照计数及版本归属检查。
- `agent-service/app/schemas/knowledge_management_read.py`：查询目标校验、资料/版本/任务白名单和分页Schema；`app/main.py`注册路由。

### 实现的核心功能

- Java授权结束后才查询知识自有管理表，所有集合及计数过滤权限；资源不存在、无权访问及版本归属错误统一404。
- 资料附最新可访问规范版本，版本查询保留草稿、停用及历史状态；任务按所属修订过滤，明确是否当前修订，不提供重试执行。
- 不查询正文列，不返回原件位置、哈希、内部操作者或确认快照；失败仅返回受控错误码及固定文案。
- GET不激活上传服务、不恢复或领取任务，不生成索引或切换LEGACY问答源，既有上传解析应用及Java授权契约保持兼容。

## 2026-11-04 — `[KB-02.8] 上传与草稿修订HTTP接口`

### 核心解决的问题

只读管理入口不能提交真实文件和修正失败草稿，直接使用框架默认表单解析又可能在授权前接收大文件或回显不安全输入。
本任务把已有上传应用接入明确的HTTP文件提交，补齐授权门禁、接收限制和安全失败结果。

### 实现的核心代码

- `agent-service/app/api/knowledge_uploads.py`：三个POST入口、UPLOAD预检、应用授权接线、幂等状态及固定错误映射。
- `agent-service/app/api/knowledge_upload_body.py`：`upload_body`有界multipart、严格命令组装、部分文件清理及分段读取。
- `agent-service/app/schemas/knowledge_upload.py`：元数据/预期快照的HTTP白名单和安全错误结构。
- `agent-service/app/main.py`：注册上传路由；`pyproject.toml`及`uv.lock`新增multipart解析依赖。

### 实现的核心功能

- 新资料、新规范版本和草稿修正分别由路由确定目标，文件名及幂等键来自文件/Header，不接受JSON自报发布状态、原件位置或哈希。
- 首次Java授权后接收一个文件与一个命令，限制实际请求字节、字段数量和命令大小；成功、失败、断流和取消均关闭暂存文件。
- 复用KB-02.6应用再次授权及事务保护，返回首次201/幂等重放200，区分接收成功和解析失败；原字节及历史修订保留，封存版本不可覆盖。
- 未提供预览/原件下载、发布、停用、索引执行或页面，不迁移运行库、不切换LEGACY规范问答源。

## 2026-11-04 — `[KB-02.9] 正文与分块预览HTTP接口`

### 核心解决的问题

上传结果和任务状态无法让用户核对正文及历史修订；内部预览还会调用管理激活，直接接为GET可能意外改变旧任务。
本任务接入指定修订的纯读取预览，保留证据身份并明确区分未就绪、无权限和证据损坏。

### 实现的核心代码

- `agent-service/app/api/knowledge_management.py`：`preview_revision`READ身份、完整目标、禁用缓存及安全错误映射。
- `agent-service/app/services/knowledge_management.py`：`preview`去除管理激活，复用快照校验和线程内确定性分块。
- `agent-service/app/repositories/managed_knowledge.py`：`read_revision`新增可选document_id归属条件，和权限/版本/修订同一SQL核对。

### 实现的核心功能

- 明确资料、版本和修订身份，返回既有预览Schema的元数据、正文及章节分块；历史修订不改查最新正文。
- 每次重新Java授权，范围不符或归属错误统一404；未完成正文409，读取或哈希校验失败503，不返回伪造空正文或替代证据。
- 预览不读原件、不激活恢复或执行任务，不写操作、索引或发布数据；已存正文不因原件缺失而被改写。
- 正文保留规范化后的首尾空白，响应禁止缓存且仅返回JSON，不记录正文或暴露内部路径/快照；默认问答仍使用LEGACY源。

## 2026-11-04 — `[KB-02.10] 原始文件下载HTTP接口`

### 核心解决的问题

规范化预览不能取回原始上传字节，直接按文件路径下载又无法保证权限、资料归属和文件未被篡改。
本任务按指定修订提供经过完整性校验的附件，并明确区分文件缺失、损坏及资源不可见。

### 实现的核心代码

- `agent-service/app/api/knowledge_management.py`：`download_original`附件响应和安全错误，`_attachment_headers`受控文件名编码。
- `agent-service/app/services/knowledge_management.py`：`read_original`去除管理激活、传递资料归属，在读取事务外执行原件完整性校验。
- 复用`ManagedKnowledgeRepository.read_revision`的归属/范围查询及`KnowledgeOriginalStorage.read`的NOFOLLOW、普通文件、大小和SHA-256校验。

### 实现的核心功能

- 每次Java READ授权并核对资料/版本/修订，完整校验原件后返回字节；历史、未解析和解析失败记录均可回查可信原件。
- 附件采用固定MIME、安全UTF-8显示名及ASCII回退名，禁止缓存和内容嗅探，不接收客户端文件key或物理路径。
- 文件缺失、大小/哈希不符或非法路径/显示名返回固定安全错误，不返回部分原件，也不替换为当前正文或仓库资料。
- 下载不恢复或改变任务/操作，不解析或写索引；原件损坏不改写既有正文，既有预览与LEGACY问答源保持。

## 2026-11-06 KB-03.1 发布确认请求、快照与候选版本校验

### 核心解决的问题

历史预览及早先授权不能作为当前发布依据。增加发布专用候选及确认校验，避免草稿变化、换人提交或权限撤销后沿用旧审查内容。

### 实现的核心代码

- `agent-service/app/schemas/knowledge_publication.py`：`KnowledgePublicationTarget`、`KnowledgePublicationCandidate`、`KnowledgePublicationConfirmCommand`。
- `agent-service/app/repositories/managed_knowledge.py`：`PublicationRead`、`ManagedKnowledgeRepository.read_publication_candidate`。
- `agent-service/app/services/knowledge_publication.py`：`KnowledgePublicationService.prepare`、`validate_confirmation`、`publication_digest`。

### 实现的核心功能

- 每次先Java PUBLISH授权，再按资料归属及权限范围读取一个一致的候选快照，校验当前草稿、成功解析、并发计数及数据库UTC有效日期。
- 返回可审查的正文、元数据、分块及绑定实际用户/内容/原发布指针的摘要，明确确认时重新授权及重建事实，拒绝过期输入。
- 仅返回应用层内部确认快照，不新增HTTP或确认记录，不预留执行权或执行发布；后续写事务仍须复核，摘要不能授予权限。

## 2026-11-06 KB-03.2 发布接收事务、幂等操作与候选索引任务预留

### 核心解决的问题

确认校验到保存人工意图之间仍可能出现修订变化或并发请求。通过同一短事务复查知识事实和确认摘要、保护幂等身份并保存索引预留，阻止重复排队或旧确认取得执行权。

### 实现的核心代码

- `agent-service/app/services/knowledge_publication.py`：`KnowledgePublicationService.accept`。
- `agent-service/app/repositories/managed_knowledge.py`：`accept_publication`、`_publication_candidate`、`_publication_result`。
- `agent-service/app/knowledge/publication.py`：`publication_confirmation`及请求/批次/确认摘要函数。
- `agent-service/app/schemas/knowledge_publication.py`：`KnowledgePublicationIndexIdentity.from_settings`、`KnowledgePublicationAcceptance`。

### 实现的核心功能

- 每次Java PUBLISH授权后，按actor/action/key串行化幂等、按资料锁复查当前修订、计数、状态、权限范围和确认摘要，同键返回原处理状态，新键不能绕过未完成操作。
- 原子保存CONFIRMED操作、候选索引身份及必要的QUEUED任务，预留资料row_version，SQL失败完整回滚；旧发布指针、版本封存关系和原件不变。
- 服务端沿用现有索引配置，匹配READY候选则复用且不新建任务，否则创建空BUILDING批次；不执行模型、写Chunk或发布，原任务中断后重放仍返回原失败记录。

## 2026-11-06 KB-03.3 按版本构建候选索引与失败隔离

### 核心解决的问题

已确认资料需要完整索引才能继续发布，但批量模型调用可能超时、返回错误向量，或在草稿更新后才结束。增加执行权校验和完整候选保存，避免半批索引及迟到结果影响当前依据。

### 实现的核心代码

- `agent-service/app/services/knowledge_index_build.py`：`KnowledgeIndexBuildService.process`。
- `agent-service/app/repositories/knowledge_index_build.py`：`IndexBuildClaim`、`claim_index`、`finish_index`、`fail_index`。
- `agent-service/app/knowledge/index_build.py`：`parse_index_input`、`index_chunk_records`、`validate_index_records`。

### 实现的核心功能

- 领取前及完整保存前Java PUBLISH授权，短事务核对实际确认人、owner、当前修订、预留计数、确认快照和索引身份，事务外确定性分块及批量生成向量。
- 验证完整Chunk集合、正文身份和1536维有限非零向量，完整清单同事务写入后才标READY/任务成功；内部tuple在pgvector写入边界转list。
- 超时、异常响应、权限撤销、主动取消、草稿变化、恢复后迟到结果及SQL写入失败均有受控结果，整批回滚并保留旧发布指针；PUBLISH操作不标成功，无自动轮询、索引重试或最终发布。

## 2026-11-06 KB-03.4 最终授权复查与发布切换事务

### 核心解决的问题

候选构建完成后仍可能发生权限撤销、修订或证据变化；分开替代旧版与切换指针也可能造成中间状态。通过完整证据复核和最终短事务完成管理库发布，使重复调用不能重复切换或恢复旧版。

### 实现的核心代码

- `agent-service/app/services/knowledge_publication_finalize.py`：`KnowledgePublicationFinalizeService.finalize`。
- `agent-service/app/repositories/knowledge_publication_finalize.py`：`prepare_finalization`、`commit_finalization`、`reject_finalization`、`finalization_hash`。
- `agent-service/app/schemas/knowledge_publication.py`：`KnowledgePublicationReceipt`。
- `agent-service/app/knowledge/index_build.py`：`IndexEvidenceInput`复用构建与最终发布的完整清单校验。

### 实现的核心功能

- 准备前及最终提交前重新Java PUBLISH授权，仅原确认人可完成操作，事务外复核全部已存分块/向量，最终锁内核对确认、预留计数、日期、READY身份及完整证据摘要。
- 库→资料→任务→操作→批次加锁，原子替代旧版、封存新版、切换指针、增加资料/库发布计数并完成原操作；任何写入失败完整回滚，旧原件与Chunk/向量保留。
- 成功重放返回原发布时间及当前历史状态，不再次发布或恢复旧版；SQL瞬时失败可对原操作显式重试，READY复用路径无需新建任务也须完整复核。
- 仅管理库内部发布，不新增HTTP或切换LEGACY问答源，不调用模型或自动完成停用/纳管。

## 2026-11-07 KB-03.5 停用确认、权限复查与停用事务

### 核心解决的问题

当前依据需要安全退出发布集合，旧确认、重复请求或迟到索引不能误停新版或撤销停用。新增明确停用和事务内版本核对，保留旧引用并失效旧事实上的未完成意图。

### 实现的核心代码

- `agent-service/app/services/knowledge_disable.py`：`KnowledgeDisableService.prepare/disable`。
- `agent-service/app/repositories/knowledge_disable.py`：`prepare_disable`、`disable`、`_invalidate_pending`。
- `agent-service/app/schemas/knowledge_disable.py`：目标、审查、明确确认及停用回执Schema。
- `agent-service/app/knowledge/disable.py`：独立停用确认摘要和请求哈希。

### 实现的核心功能

- 每次审查、提交和重放检查Java DISABLE权限，事务内核对指定当前发布版本、封存身份、元数据、资料计数及绑定实际用户的确认摘要，不用PUBLISH授权代替。
- 同事务置DISABLED、清当前指针、递增资料/库计数、保存实际用户审计并失效同资料未完成的发布/索引意图；失败完整回滚，重放不误停后来发布的新版本。
- 不恢复旧版、不删除原件/向量或新增任务，已完成任务和READY候选保留；审查不加载正文或向量，索引损坏也不妨碍撤回身份明确的当前依据。
- 仅管理库内部应用，不提供停用HTTP、模型调用、索引重试或问答切源。

## 2026-11-07 KB-03.6 索引失败任务的受控重试

### 核心解决的问题

失败任务直接重新排队会覆盖原审计，重复确认可能从同一节点分叉并误用旧发布权限。通过新人工意图和单一失败链保存每次尝试，重试成功也不自动发布。

### 实现的核心代码

- `agent-service/app/services/knowledge_index_retry.py`：`KnowledgeIndexRetryService.prepare/retry`。
- `agent-service/app/repositories/knowledge_index_retry.py`：`prepare_retry`、`accept_retry`、`_source`、`_retry_result`。
- `agent-service/app/repositories/knowledge_index_build.py`及`app/services/knowledge_index_build.py`：固定动作授权、父任务验证及重试READY完成逻辑。
- `agent-service/app/schemas/knowledge_index_retry.py`、`app/knowledge/index_retry.py`：新重试目标/确认/回执及请求摘要。

### 实现的核心功能

- 审查、提交、重放及执行/保存前分别检查RETRY_INDEX权限，仅允许当前草稿修订的FAILED/INTERRUPTED INDEX链尾，不允许解析、成功、过期任务或隐式改变索引身份。
- 按幂等键及资料锁原子创建新操作、批次和任务，尝试号由直接父节点+1，原失败及审计保留，不创建规范版本或修订，同键重放及不同键竞争不重复分叉。
- 复用确定性构建器但按仓库动作隔离PUBLISH和RETRY_INDEX；重试成功仅READY及新重试操作成功，必须经新的PUBLISH确认才能复用候选发布，迟到结果不能撤销停用。
- 任务查询的尝试号与既有BIGINT存储范围一致，HTTP重试仍未接入；不新增迁移、自动调度或问答切源。

## 2026-11-07 KB-03.7 首批演示规范纳管前置校验

### 核心解决的问题

旧索引行数正确不代表原文、引用和向量仍匹配，直接纳管可能复制已经脱节的证据。新增只读源核对，将损坏、配置变化和身份占用在实际复制前明确拒绝。

### 实现的核心代码

- `agent-service/app/services/knowledge_import.py`：`KnowledgeImportPreflightService.check`。
- `agent-service/app/repositories/knowledge_import.py`：`KnowledgeImportPreflightRepository.read_source`。
- `agent-service/app/knowledge/import_preflight.py`：`capture_import_files`、`validate_import_source`、`file_fingerprint`。
- `agent-service/app/schemas/knowledge_import.py`：`KnowledgeImportPreflight`、`KnowledgeImportVersionCheck`。

### 实现的核心功能

- 每次先分别查询Java UPLOAD/PUBLISH权限，再以NOFOLLOW只读捕获固定catalog/原件；复用正文规范化和稳定分块，按明确替代关系核对14逻辑资料/16版本及80块。
- 旧索引和目标库状态在同一可重复读只读事务读取，完整比对目录元数据、正文哈希、分块内容/引用定位、检索文本、向量及配置身份；不隐式调用模型补齐。
- 返回演示标识、实际检查人、清单、catalog哈希及完整源指纹，返回前重读原件；允许无关上传共存，拒绝已纳管标记或引用身份冲突，不分配管理UUID或虚构旧发布时间。
- 仅内部只读应用，无HTTP/CLI纳管入口、原件复制、管理记录写入或问答切源；报告不是实际导入授权或发布回执。

## 2026-11-07 KB-03.8 首批演示规范受确认纳管

### 核心解决的问题

纳管前置检查之后仍缺少人工确认、原件留存和整批版本建立，重复确认与旧CLI并行写入可能产生半批资料或引用脱节。新增整批原子纳管和成功重放，失败时旧库继续服务且不留下部分管理发布集合。

### 实现的核心代码

- `agent-service/app/services/catalog_import.py`：`KnowledgeCatalogImportService.prepare/confirm`。
- `agent-service/app/repositories/catalog_import.py`：`KnowledgeCatalogImportRepository.commit/replay`。
- `agent-service/app/knowledge/catalog_import.py`：`import_digest`、`import_request_hash`、`import_plan`。
- `agent-service/app/schemas/knowledge_import.py`：候选、明确确认、版本结果及整批回执。
- `agent-service/app/services/knowledge_import.py`及`app/repositories/knowledge_import.py`：复用已授权的源读取和锁内源快照检查。

### 实现的核心功能

- 审查、确认和成功重放分别检查Java UPLOAD/PUBLISH，确认摘要绑定实际用户、范围、源指纹、库计数及索引；复制完成后再次授权，拒绝自报状态、原文或管理身份。
- 原件按已验证字节复制到独立目录，确认后的新管理身份和原件key可确定性复用；最终事务锁旧知识表及管理库，完整重查源后原子建立14资料、16版本/修订/READY批次、80块及对应UPLOAD/PUBLISH操作和PARSE/INDEX完成审计。
- 版本来源CATALOG_IMPORT、索引COPIED_LEGACY，14版PUBLISHED、2版HISTORICAL，保留旧引用和替代关系，历史原发布时间未知仍为空；管理库发布计数只递增一次，LEGACY读源不变。
- 同键成功重放不再复制或恢复后来停用的版本，不同键竞争不能覆盖已纳管关系；SQL故障整批回滚，已复制未引用原件保留供受控重试，不自动清理。
- 仅内部应用，不新增表/迁移、HTTP/CLI、启动自动纳管、模型调用或问答切源。

## 2026-11-07 KB-03.9 管理库已发布知识检索读取

### 核心解决的问题

管理库发布后仍缺少与当前指针绑定的检索读取，按READY批次直接取块会召回草稿或旧版本，跨事务双路检索也可能混用不同发布状态。新增发布关系过滤和同一只读快照，将当前证据及实际管理版本一起交付下游。

### 实现的核心代码

- `agent-service/app/services/managed_knowledge_search.py`：`ManagedKnowledgeSearchService.retrieve`、`ManagedKnowledgeRetrievalResult`。
- `agent-service/app/repositories/managed_knowledge_search.py`：`ManagedKnowledgeSearchRepository.search`、双路SQL、`_validate_candidate`及`validate_managed_query`。
- `agent-service/app/schemas/managed_knowledge_search.py`：管理过滤器、数量/阈值、读取上下文及证据定位。

### 实现的核心功能

- 每次Java READ后核对实际身份、只读策略及范围，完整问题先生成查询向量；SQL在模型完成后才开始，事务结束后复用既有RRF融合。
- 沿当前资料指针、PUBLISHED版本、封存修订和READY发布批次查询，权限、日期、产品/卫星/级别、类型/版本及完整索引身份在TopK前过滤，两路和库计数共享可重复读只读快照。
- 校验命中的封存元数据、正文、批次输入及稳定章节分块，保留规范引用ID、版本、原文和全部合并Chunk；附实际管理资料/版本/修订/批次定位，损坏命中及持久化错误明确失败，不回退旧表。
- 内部显式读取管理库与默认configured_source_mode分开，空管理库返回空结果；不变更现有Workflow/HTTP/前端、重排/回答模型、旧Run或默认LEGACY源，不实现全量动态就绪。

## 2026-11-07 KB-03.10 管理库动态就绪检查

### 核心解决的问题

固定catalog数量无法代表上传、发布或停用后的管理集合，TopK命中验证也可能漏掉未召回的坏块。按实际发布声明及当前指针读取完整快照，让零发布、证据不完整、配置不匹配和可用得到不同结果，避免漏统计后误报READY。

### 实现的核心代码

- `agent-service/app/services/managed_knowledge_index.py`：`ManagedKnowledgeIndexCapabilityService.get`、`evaluate_published_index`。
- `agent-service/app/repositories/managed_knowledge_index.py`：`read_published_snapshot`及不可变发布快照。
- `agent-service/app/knowledge/managed_index_evidence.py`：封存身份、单块与完整块集合校验，供管理检索和就绪共用。
- `agent-service/app/schemas/managed_knowledge_index.py`及`agent-frontend/src/types/managedKnowledgeIndex.ts`：动态非负计数及完整身份契约。
- `agent-frontend/src/api/managedKnowledgeIndex.ts`、`src/api/agentClient.ts`：带MANAGED标识的新旧能力分支校验。

### 实现的核心功能

- 每次Java READ后，以同一只读可重复读快照捕获实际发布声明、指针、封存修订/批次和全部块，释放连接后确定性检查；不调用模型、读原件或加载固定catalog。
- 验证发布归属、封存正文/元数据、完整批次输入及完整分块数量/集合/顺序/哈希/检索文本/向量，结构缺陷优先于配置不匹配，异常不回退旧表。
- 零发布明确NOT_INDEXED及“无已发布资料”，非空完整匹配才READY；正常草稿、历史及未发布失败批次不影响发布集合，错误指针不能被内连接漏掉。
- Python与前端同步MANAGED专用非负计数、模式/修订、状态/原因/中文文案和chunking_version身份；既有LEGACY服务和正数预期约束保留，无HTTP装配、默认切源、新迁移或页面。

## 2026-11-08 T801～T805 M8.1 返工领域、契约与SQL存储

### 核心解决的问题

返工创建后只有状态和原因，无法绑定修复成果、检查与多轮处理证据，也没有存储边界防止跨问题复用材料或改写成功回执。
建立Java领域模型、受约束的状态变更提议和增量存储，为后续人工返工闭环提供可追溯基础，存量记录不补造证据。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/domain/model/ReworkArtifact.java`、`ReworkProcessingEvidence.java`、`ReworkProcessingSnapshot.java`：成果版本、不可变材料和资源绑定。
- `business-service/src/main/java/com/productline/business/domain/model/ReworkRound.java`、`ReworkInspectionItem.java`、`ReworkInspection.java`：轮次、人工检查及材料适用性。
- `business-service/src/main/java/com/productline/business/domain/validation/ReworkTransitionPolicy.java`：状态与通过检查约束、不可变变更提议。
- `business-service/src/main/resources/db/migration/V5__add_rework_lifecycle_storage.sql`：五表、复合外键、材料校验、历史及回执不可覆盖约束。
- `docs/api/REWORK_CONTRACT.md`：后续查询/动作、独立确认、新旧兼容和SQL存储边界。

### 实现的核心功能

- 显式区分未登记材料与完整材料，绑定返工/任务/来源问题、轮次和成果版本，不补造历史轮次、检查或人员。
- 开始、异常、恢复、完成及复核先校验Java事实；完成和复核必须有适用的通过检查，输出提议并保持原实体不变。
- SQL持久化成果修订、人工检查、独立M8复核及原始回执，约束同源连续前驱、唯一后继、修订关联和PASSED检查绑定。
- 材料/检查/复核/回执追加后不可改写或删除，生命周期创建身份不可改且开始元数据只登记一次；旧迁移及业务行保持原样。
- 契约冻结与存储不等同于HTTP或业务闭环，未装配新Controller、应用Repository、Python Tool或前端，也不自动执行生产、确认或交付。

## 2026-11-09 T806 M8.2 返工详情查询

### 核心解决的问题

旧订单概览只有返工摘要，无法确认真实轮次、当前成果和有效检查，也不能区分无历史材料与已完成检查。
通过独立只读接口返回同一数据库快照内的归属、共享任务版本和当前材料，避免新失败检查被旧通过结果掩盖或存量被补造轮次。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkQueryController.java`：详情GET及演示身份入口。
- `business-service/src/main/java/com/productline/business/application/ReworkQueryService.java`：`getDetail`授权、参数、父任务和归属校验及可重复读事务，`allowedActions`确定性动作前提。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkReadRepository.java`：`findDetail`按当前修订、检查及有效复核绑定读取V5事实。
- `business-service/src/main/java/com/productline/business/domain/dto/ReworkLifecycleSnapshot.java`、`business-service/src/main/java/com/productline/business/api/dto/ReworkDetailResponse.java`：当前材料快照与新详情响应，不改变旧DTO。

### 实现的核心功能

- 详情读取要求REVIEWER身份，父任务或返工不存在返回404、跨任务归属返回409且不返回材料，旧查询及响应信封保持。
- 在同一只读可重复读快照中返回真实轮次、前驱、任务版本及当前处理/检查/复核；新修订或新检查不沿用失效的旧结论。
- 最新失败检查保留FAILED及检查项，不跳过取旧PASSED；当前无材料显式为null，存量缺少生命周期时允许动作为空。
- 动作列表只表达状态和当前材料前提，不作为写入授权，不改状态、版本、材料或日志，也不执行成果修正、人工确认或业务写入。

## 2026-11-09 T807 M8.2 Java开始返工

### 核心解决的问题

只有返工详情时，无法登记谁开始处理，也无法保证状态、版本与执行结果同步提交。
以重新读取的Java事实裁决开始操作，并保存首次成功回执，避免重复请求二次写入或用后来状态改写原结果。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkStartController.java`、`api/dto/ReworkStartRequest.java`：开始POST、局部严格请求解析。
- `business-service/src/main/java/com/productline/business/application/ReworkStartService.java`：`start`身份/版本/状态重校验、独立事务与原回执重放。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkStartRepository.java`：幂等预留、父任务锁、版本/状态条件更新及开始元数据、审计和回执写入。
- `business-service/src/main/java/com/productline/business/api/dto/ReworkWriteReceipt.java`：固定成功JSON及显式null绑定字段。
- `business-service/src/main/java/com/productline/business/domain/model/ReworkRound.java`：轮次对齐为long及正安全整数范围，不改变SQL或既有非正数校验。

### 实现的核心功能

- 开始仅接收安全整数expectedVersion，拒绝未知字段、自报确认/状态/人员/时间、重复键及尾随内容；旧请求解析行为保持。
- 原生产任务COMPLETED、受控轮次未开始/无后继且返工PENDING/问题OPEN才可开始；Java记录实际请求人和UTC时间，返工改RUNNING、问题改PROCESSING。
- 共享任务版本只递增一次，状态、元数据、幂等完成、审计和原成功回执同事务提交；失败回滚，不补造历史生命周期。
- 同用户/键/operation/目标/完整请求重放返回第一次结果，后来的状态和版本不重建旧回执；不自动换键重试或修改原生产状态。
- 仅完成Java写底座，M8独立Approval、写Tool、页面及自动成果修正均未接入。

## 2026-11-09 T808 M8.2 Java阻塞与失败登记

### 核心解决的问题

返工开始后若无法登记阻塞或失败，就只能保留RUNNING，既不能解释停滞原因，也容易把技术请求失败误当成业务失败。
提供显式异常登记并原样保存原因，状态变化不覆盖创建原因、开始信息或历史材料，为后续受控恢复保留事实。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkInterruptionController.java`、`api/dto/ReworkInterruptionRequest.java`：两个显式POST入口和严格版本/原因解析。
- `business-service/src/main/java/com/productline/business/application/ReworkInterruptionService.java`：`block`、`fail`复用领域约束，在独立事务内完成授权、版本、状态、幂等及原回执校验。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkStartRepository.java`：`lockProcessingIssue`、`markInterrupted`及共用幂等/审计/回执写集。

### 实现的核心功能

- 仅RUNNING/PROCESSING、原生产COMPLETED且受控轮次无后继允许登记；状态改BLOCKED或FAILED，问题仍PROCESSING，任务版本只加一。
- 原因须非空白且符合UTF-16长度及无损UTF-8存储规则，原样写入本次审计，原始创建原因和开始元数据保持。
- 成果修订、检查、复核及当前材料指针保持，不能用旧修订或旧通过复核代替当前事实，不补造存量生命周期。
- 操作、完整请求幂等、审计及原成功回执同事务提交或回滚；同请求重放不再次改状态，不同动作或原因不能借用同一键。
- 仅交付Java异常写底座，技术错误不自动认定业务失败，不实现恢复、模型处理、Python独立确认或页面。

## 2026-11-09 T809 M8.2 Java受控恢复

### 核心解决的问题

人工返工被阻塞或失败后，需要在确认可继续时显式恢复，并能保留原异常原因和已经登记的材料。
恢复不能变成自动重跑；旧恢复请求重放也不能再次改变后来已经失败的事实。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkInterruptionController.java`：`resume`显式HTTP入口，复用严格版本与说明解析。
- `business-service/src/main/java/com/productline/business/application/ReworkInterruptionService.java`：`resume`与`transitionInTransaction`复用领域RESUME约束、事实复查及幂等/审计/原回执事务。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkStartRepository.java`：`markResumed`绑定重新读取的原状态，仅条件恢复RUNNING。

### 实现的核心功能

- 仅受控轮次无后继、原生产COMPLETED及BLOCKED或FAILED/PROCESSING允许恢复；问题仍PROCESSING，共享任务版本递增一次。
- 恢复说明原样写入新RESUME_REWORK审计，旧异常原因、创建原因、原开始信息及全部处理/检查/复核材料保持。
- 状态、版本、完整请求幂等、新审计及原成功JSON同事务保存或回滚；同请求只返回首次结果，后来再次失败不被旧恢复重放改变。
- 不自动重跑生产或修正成果，不新增迁移、独立原因查询、Python确认/写Tool或页面接线。

## 2026-11-09 T811 M8.3 Java成果登记

### 核心解决的问题

人工修正后缺少实际成果版本与处理证据登记，系统无法区分已经处理的材料和等待检查的材料。
将成果、说明及引用按不可变修订保存，使后续检查只能绑定当前材料，登记本身不能产生质量通过或问题已解决的事实。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkResultController.java`、`api/dto/ReworkResultRequest.java`：`register`与`parse`接收成果POST并按冻结契约严格解析原样材料。
- `business-service/src/main/java/com/productline/business/application/ReworkResultService.java`：`registerInTransaction`重新校验身份、归属、轮次、状态及版本，原子追加修订并保存幂等、审计与原始成功回执。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkResultRepository.java`：`lockRunning`、`latestRevision`和`append`在父任务锁保护下核对本轮状态、分配修订并只追加材料。

### 实现的核心功能

- 仅受控轮次无后继、原生产COMPLETED、返工RUNNING且问题PROCESSING可登记；缺轮次的存量保持只读，不补造历史。
- 成果标识、版本、处理说明与证据引用按UTF-16长度及无损UTF-8规则校验并原样保存，登记人来自实际请求身份，时间由Java生成。
- 每次新登记分配连续修订并递增一次共享任务版本，相同成果版本文本也不覆盖旧说明、证据或历史结论。
- 材料、幂等完成、审计及原成功JSON回执同事务保存；失败全部回滚，同请求只重放原回执，不按后来的状态或材料重建。
- 新修订的当前检查和复核为空，旧记录保留；仅登记材料，不访问引用、不检查成果、不完成返工、不关闭问题，Python独立确认与页面尚未接入。

## 2026-11-09 T812 M8.3 Java人工检查登记

### 核心解决的问题

仅保存处理说明与成果版本，无法记录人工检查的实际结论，也无法保证检查针对当前成果。
将逐项结论和证据绑定明确修订，并把通过检查与本轮完成放在同一事务，避免旧材料结论误用或只保存部分成功事实。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkInspectionController.java`、`api/dto/ReworkInspectionRequest.java`：`register`与`parse`接收检查POST，严格校验预期版本、当前修订和逐项材料。
- `business-service/src/main/java/com/productline/business/application/ReworkInspectionService.java`：`registerInTransaction`复查Java事实、构建既有检查领域对象、汇总结果并保存完整原子写集与原始回执。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkInspectionRepository.java`：`latestSequence`、`append`、`complete`和`resolve`分配连续检查序号、追加记录并条件更新本轮与问题状态。

### 实现的核心功能

- 仅受控轮次无后继、原生产COMPLETED、返工RUNNING且问题PROCESSING时可检查明确的当前修订，不接受旧修订或缺失材料。
- 逐项保存检查名、PASSED/FAILED、说明和证据，人员及UTC时间由Java记录，总体结论由检查项汇总，不接收自报总体结论或确认凭证。
- 任一项失败则保留RUNNING/PROCESSING并追加失败历史；全部通过复用既有领域COMPLETE约束，原子保存检查、本轮COMPLETED及问题RESOLVED，原生产不变。
- 为保持冻结契约的原子边界，通过分支的最小写入与检查入口一起接通；不单独提交通过记录，不另设complete接口，不关闭问题或推进订单/交付。
- 检查、共享版本、幂等完成、审计和原成功回执同事务提交或回滚；重放返回首次结果，旧检查、材料及回执均保留，Python独立确认与页面尚未接入。

## 2026-11-09 T814 M8.3 检查通过原子性与有效写入防护

### 核心解决的问题

同一事务不代表每条SQL都实际写入；回执INSERT被静默跳过时，检查通过原先仍可能提交并返回成功，留下无法按原回执重放的业务变化。
明确审计和回执必须实际插入一行，任何零行写入或提交失败均回滚，防止向后续写Tool报告不完整的成功事实。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/domain/repository/ReworkStartRepository.java`：`audit`、`saveReceipt`返回实际INSERT影响行数。
- `business-service/src/main/java/com/productline/business/application/ReworkInspectionService.java`：`registerInTransaction`通过`updated`校验审计和回执写入，纳入检查通过的原子写集。
- `business-service/src/main/java/com/productline/business/application/ReworkStartService.java`、`ReworkInterruptionService.java`、`ReworkResultService.java`：共用仓储的其他调用方同步校验实际写入，不忽略返回值。

### 实现的核心功能

- 审计或原始回执未实际写入一行即返回业务冲突，版本、材料/检查、状态、幂等及已有写入全部回滚。
- 开始、阻塞/失败、恢复、成果及检查登记统一执行共用写入约束，正常成功响应和幂等回执字段保持原契约。
- 检查通过只将本轮置COMPLETED、问题置RESOLVED；事务提交失败不返回成功，事务外读取只看到提交前或提交后的完整事实。
- 失败后没有自动重试或改键，旧成功请求仍只重放原回执；没有新增HTTP、迁移、三端确认或关闭问题能力。

## 2026-11-10 T815 M8.3 成果修订与检查历史查询

### 核心解决的问题

只展示当前材料会隐藏旧修订和失败检查，无法还原人工处理过程；翻页时若把新增记录混入，也容易漏看或重复理解证据。
提供完整、按Java序号排列的历史，在独立只读快照核对归属，并以绑定上下文及首屏上界的签名游标稳定向后读取。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkHistoryController.java`、`api/dto/ReworkHistoryResponse.java`：成果与检查GET及固定分页响应。
- `business-service/src/main/java/com/productline/business/application/ReworkHistoryService.java`、`ReworkHistoryCursor.java`：每页授权/归属复查、只读快照、首屏序号上界和上下文签名。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkHistoryRepository.java`：按修订/检查序号读取完整真实材料，不使用当前有效材料过滤器。

### 实现的核心功能

- 返回完整成果版本、说明、证据和登记人员/时间；检查带真实轮次/修订、序号、结论及完整检查项，旧失败和旧修订保持。
- 空历史返回空数组和null游标，不自动纳管存量或补造证据；读取不改变版本、状态、审计或幂等。
- 页大小1～100，游标签名绑定用户、资源、历史类型、末条序号及首屏上界，后续追加不混入本次翻页；换人/类型/目标或篡改均拒绝。
- 实例重启或跨实例后旧游标失效，须重新读取首页；当前不提供持久密钥或多实例共享能力。历史读取不代替当前有效结论，不执行再次复核、关闭问题或自动成果检查。

## 2026-11-10 T816 M8.4 当前有效复核与完整历史读取

### 核心解决的问题

把全部历史复核混作当前结论，会让旧失败永久阻塞，或让旧通过错误覆盖新轮次、新成果和新检查。
Java按当前材料绑定选择有效复核，并把完整历史和存量缺证据事实单独返回，为后续Tool消费可信结论提供只读入口。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/EffectiveReviewController.java`、`api/dto/EffectiveReviewsResponse.java`、`domain/dto/EffectiveReviewSnapshot.java`：任务级有效复核入口和显式缺失/存量边界。
- `business-service/src/main/java/com/productline/business/application/EffectiveReviewService.java`、`domain/repository/EffectiveReviewRepository.java`：授权、独立只读快照、按问题选择当前轮次/修订/检查及绑定复核。
- `business-service/src/main/java/com/productline/business/api/ReworkHistoryController.java`、`application/ReworkHistoryService.java`、`domain/repository/ReworkHistoryRepository.java`：扩展REVIEWS历史分页，复用已有签名游标及上界。

### 实现的核心功能

- 有效复核仅来自最新受控轮次、当前成果和当前PASSED检查下最大复核序号；最新失败不回退旧通过，新轮/材料/检查不继承旧复核。
- 缺少生命周期时保留旧DTO数组且绑定为null，不伪造轮次或有效结论；受控问题不混入旧表复核，旧接口和诊断规则保持。
- 完整新复核历史按真实序号升序分页，保留旧失败和旧绑定，游标绑定用户、资源、历史类型及首屏上界。
- 每次读取在独立只读可重复读快照内核对父任务/归属和材料，不写状态、版本、审计或幂等，不执行再次复核确认或关闭问题。

## 2026-11-10 T817 M8.4 复核通过与来源问题原子关闭

### 核心解决的问题

读取到当前通过检查不代表之后仍可复核，旧检查或过期版本若被直接用于确认，会错误关闭新成果对应的问题。
写入时重新裁决当前绑定，并把APPROVED复核与来源问题关闭一起提交，避免重复确认或局部失败留下不完整成功。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkReviewController.java`、`api/dto/ReworkReviewRequest.java`：严格五字段复核入口与原样说明校验。
- `business-service/src/main/java/com/productline/business/application/ReworkReviewService.java`：`submitInTransaction`重验版本/状态/当前材料，复用领域REVIEW约束及幂等/审计/原回执写集。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkReviewRepository.java`：完成状态及问题状态锁、连续复核序号、只追加复核和条件关闭。

### 实现的核心功能

- 仅受控轮次无后继、原生产COMPLETED、本轮COMPLETED/问题RESOLVED及当前修订对应的最新PASSED检查可提交APPROVED，旧检查和最新失败不被沿用。
- 复核保存实际请求人、服务端UTC时间、原样说明及真实绑定，关闭来源问题并只递增一次任务版本；本轮完成、开始信息、历史材料及其他问题保持。
- 完整请求幂等、新复核、关闭、版本、审计和原成功回执同事务保存，实际写入数必须一行；异常、零行或提交失败全部回滚，同请求只重放原结果。
- 本轮只提供APPROVED，退回分支仍待后续，不推进订单/交付，不接入Python确认/写Tool、诊断切换或页面，不把Header当确认凭证。

## 2026-11-10 T818 M8.4 未通过复核与来源问题退回

### 核心解决的问题

再次复核发现仍需处理时，原接口只能拒绝未通过结论，无法保存真实退回意见或让问题重新进入待处理状态。
复用当前成果绑定和领域规则保存退回结论，并只重开来源问题，防止误撤销已完成生产、覆盖历史证据或自动产生未经独立确认的下一轮任务。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/application/ReworkReviewService.java`：`submit`接通全部最终结论，`submitInTransaction`复用当前绑定重验、领域REVIEW提议和原子写集，按结论关闭或退回问题。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkReviewRepository.java`：`reopen`在相同任务/问题且原状态RESOLVED时条件更新OPEN，返回实际写入数。

### 实现的核心功能

- REJECTED和REWORK_REQUIRED沿用严格五字段复核请求，仍要求原生产/本轮COMPLETED、来源问题RESOLVED、受控轮次无后继及当前修订的最新PASSED检查。
- 未通过结论、原样说明、实际请求人、UTC时间及连续复核序号与问题OPEN、一次版本递增、幂等完成、审计和原成功回执同事务保存，异常、零行或提交失败全部回滚。
- 本轮完成事实、创建/开始信息、成果、检查及复核历史完整保留，其他问题、订单和交付不变，不重启生产或自动创建后继。
- 有效复核和完整历史可查询真实退回结论，同请求仅重放首次OPEN回执，不重新打开后来已关闭的问题；原通过分支保持，独立Approval/写Tool、下一轮创建和页面仍待后续。

## 2026-11-11 T819 M8.4 受控首轮及下一轮创建

### 核心解决的问题

首轮缺少真实生命周期，退回复核后也没有独立创建下一轮的入口，只能用测试夹具模拟后继，无法保留可追溯的实际轮次链。
新增受控创建并让新旧入口共同核对链路与活动返工，避免绕过前驱、并发分叉或把旧材料和旧通过结论直接沿用到新轮。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkCreationController.java`、`api/dto/ReworkLifecycleCreationRequest.java`：首轮三字段与后继两字段严格入口，版本/原因复用`ReworkInterruptionRequest`。
- `business-service/src/main/java/com/productline/business/application/ReworkCreationService.java`：`createInTransaction`裁决当前事实及完整请求幂等，`requireReturnedRound`重验当前退回绑定，组织新PENDING与原回执原子写入。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkCreationRepository.java`：问题状态锁、活动返工判断、返工及连续生命周期SQL。
- `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java`及原任务/返工Repository：旧创建共用父任务锁并拒绝已有受控链，旧成功重放保持PENDING和原版本。

### 实现的核心功能

- 首轮仅在同属OPEN问题且无受控链/活动返工时生成轮次1；后继要求前轮COMPLETED、无后继且当前成果和最新PASSED检查下存在有效退回复核，Java分配真实连续轮次及前驱。
- 新PENDING、生命周期、一次共享版本递增、幂等完成、审计与固定原回执同事务写入，实际行数必须一行，异常、零行或提交失败整体回滚；同请求只重放首次结果。
- 新轮不继承成果、检查或复核；前轮全部证据和开始信息保持，后继审计关联真实退回结论及原意见，新原因独立原样保存，不自动开始处理或推进订单/交付。
- 新旧创建保留各自请求/响应，旧入口不能绕过受控前驱，旧Python路径保持；Java身份与幂等不等于独立人工确认，Python Approval/Tool及页面仍待接线。

## 2026-11-11 T820 M8.4 订单交付条件查询与关闭并发读取

### 核心解决的问题

关闭一个来源问题不能说明同订单的其他生产、质量或交付条件都已满足；混读不同请求的版本、问题和复核，还会展示根本未同时存在的结果。
在一个独立只读快照汇总已知条件，明确区分当前有效复核与旧审计历史，让受控旧失败不会永久阻塞新通过，同时保留其他真实阻塞。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/DeliveryConditionsController.java`、`api/dto/DeliveryConditionsResponse.java`：订单级只读入口、完整事实与带资源定位的稳定阻塞结构。
- `business-service/src/main/java/com/productline/business/application/DeliveryConditionsService.java`：`conditions`组织独立只读快照，`issueBlockers`分开受控当前绑定与存量规则，复用T816仓储。
- `business-service/src/main/java/com/productline/business/domain/repository/DeliveryConditionsRepository.java`：限定订单/任务归属并稳定排序读取生产、步骤、问题、活动返工和交付记录。

### 实现的核心功能

- 返回订单、全部任务及共享版本、生产步骤、问题和当前复核、活动返工、交付记录及已知阻塞，不把多次独立HTTP读取拼成一个快照。
- 受控问题要求CLOSED及当前绑定APPROVED，新轮/新材料不沿用旧通过，旧受控未通过不永久阻塞新通过；存量显式保留旧规则，不补造轮次或最新结论。
- 同时列出其他生产/问题、活动返工、缺失资料和交付未就绪等条件；没有已知阻塞也不构成交付授权，不改变订单或交付状态，不替换旧Python诊断或旧HTTP响应。

## 2026-11-11 T821 M8.5 独立返工契约与HTTP适配

### 核心解决的问题

Java新增的完整返工状态、当前材料和原成功回执不能直接套用旧PENDING创建响应，自动去空白和字符计数差异还会改变用户审查的内容。
新增独立跨语言契约与类型化HTTP适配，在保留旧调用的同时准确传递新事实和原始请求，防止格式合法但资源、版本或动作不匹配的结果进入编排。

### 实现的核心代码

- `agent-service/app/schemas/rework.py`：`ReworkSchema`、`_text`、详情/历史/有效复核/九类写动作请求与`ReworkWriteReceipt`，保留原值并核对响应材料绑定。
- `agent-service/app/schemas/rework_delivery.py`：`DeliveryConditions`及嵌套事实，校验已有归属字段、阻塞资源关联和hasBlockers自洽，不重新裁决Java条件。
- `agent-service/app/clients/rework.py`：`ReworkHttpClient`借用共享连接池；`_history`核对单页事实，`_write`和`_write_binding`绑定原请求、操作及实际回执副作用。

### 实现的核心功能

- 新Schema严格限制安全整数、业务ID、显式null和枚举；说明、成果版本和证据按Java UTF-16及空白语义原样传递，新完整状态与存量PENDING/null说明分开，旧创建响应不放宽。
- 类型化调用已有六类GET和九类POST，核对Trace、资源、历史序号/分页及写操作、原版本递增和状态/材料副作用，不按后来GET重建原成功回执。
- Client每次只发一次请求，借用外层生命周期的连接池，不注册Tool、不管理人工确认、不切换诊断或直接访问业务表；写入结果不确定时禁止自动重发，未实现的Java查询不伪造空结果。

## 2026-11-11 T822 M8.5 内部只读Tool及统一调用门禁

### 核心解决的问题

新Java事实只有HTTP适配器时，后续编排还缺少统一的参数、权限、超时和重复调用边界，若逐处直接调用也容易叠加重试或把历史当作当前结论。
新增独立只读Tool注册表，复用公共调用门禁并保持新旧Tool隔离，让后续编排按资源和明确分页获取Java事实。

### 实现的核心代码

- `agent-service/app/schemas/rework_tools.py`：`ReworkHistoryInput`、`ReworkTaskInput`、`ReworkOrderInput`及`_safe_cursor`，限定资源/分页并在指纹前拒绝不可无损编码游标。
- `agent-service/app/tools/rework_readonly.py`：`_ReworkReadTool`统一LOW/REWORK_READ与总预算，六个具体Tool调用T821只读方法，`create_rework_read_tool_registry`显式创建独立注册表。

### 实现的核心功能

- 详情、三类历史、有效复核和交付条件六个只读Tool只从服务端上下文取得身份、权限和Trace，Java继续最终校验资源归属与角色；不把允许动作或无阻塞当作写入授权。
- 公共BaseTool统一严格输入、逻辑去重、总预算内至多一次瞬时重试及输出校验，Client不叠加策略；Java明确拒绝及错误事实不重试，取消向上传播。
- 历史只读一页并保留原值、失败/退回记录、存量及显式null，不自动翻页或猜测有效结论；同Run重复不返回旧缓存，显式刷新才重新读取。
- 独立注册表构造不访问Java，不改变原七只读Tool、生产Agent/诊断、角色映射、写操作或人工确认链路。

## 2026-11-12 T823 M8.5 内部写Tool与确认执行快照隔离

### 核心解决的问题

返工HTTP适配器不能直接成为模型的写入口，否则调用者可能替换已审查的目标、版本或材料，也可能把请求超时当作业务失败后重复写入。
新增独立高风险写Tool映射，业务参数只从受信确认执行快照读取，保留Java原回执并将结果保存绑定完整快照。

### 实现的核心代码

- `agent-service/app/schemas/rework_write_tools.py`：`ReworkWriteInput`、`ReworkExecutionSnapshot`和`ReworkWriteOutput`，限定输入并校验操作/版本/轮次/材料绑定。
- `agent-service/app/services/rework_execution.py`：`ReworkExecutionStore`定义读取确认执行快照及完整快照CAS保存原结果的端口，无默认生产实现。
- `agent-service/app/tools/rework_write.py`：`ReworkWriteTool`核对确认身份与执行条件，`_dispatch`固定调用九类Client方法，`_check_receipt`补充轮次/材料校验，`create_rework_write_tool_registry`独立注册。

### 实现的核心功能

- 首轮、开始、阻塞、失败、恢复、成果、检查、复核及下一轮九个HIGH风险Tool，复核要求REVIEW_WRITE，其余要求REWORK_WRITE；身份和Trace来自服务端上下文。
- 输入只含确认单ID和原幂等键，执行前复制并校验完整确认快照，阻止自报确认、替换目标/版本/正文及借用可变材料引用。
- 单次提交Java并核对原回执，失败检查和退回复核保留真实状态；结果交回Store时携带完整预期快照，保存冲突不声称Java回滚，不覆盖首次结果。
- 全部错误禁止自动重试，取消向上传播；不生成确认、不取得执行权，不改变旧Approval或生产装配，实际确认及持久化仍由后续适配完成。

## 2026-11-13 T824 M8.5 原写入回执查询Java前置

### 核心解决的问题

写请求超时后只有当前返工详情，无法区分原操作的首次结果和后来状态，也不能证明查无回执就是没有提交。
补齐按实际用户、父任务及原幂等键读取不可覆盖成功回执的Java接口，为后续Python结果未知核对提供可信事实。

### 实现的核心代码

- `business-service/src/main/java/com/productline/business/api/ReworkOperationQueryController.java`及`api/dto/ReworkOperationQueryRequest.java`：严格解析无副作用查询，限定正文、Content-Type和无URL参数。
- `business-service/src/main/java/com/productline/business/application/ReworkOperationQueryService.java`：`query`校验身份与父任务，在独立只读快照查询；`decode`核对存储绑定并输出原回执。
- `business-service/src/main/java/com/productline/business/domain/repository/ReworkOperationQueryRepository.java`：`find`按实际用户/任务/原键限定回执SQL。
- `agent-service/app/schemas/rework_operation_query.py`：严格查询键和found/receipt存在关系，不引入Python查询调用或自动恢复。

### 实现的核心功能

- 当前REVIEWER查询自己的任务范围成功回执，返回固定found/receipt；他人、其他任务或未见成功回执保持相同显式缺失，不泄露回执存在性。
- 返回首次成功的固定12字段JSON语义，不读取后来状态重建结果，损坏元数据或材料绑定拒绝且错误不含原始内容。
- 使用独立REPEATABLE READ READ ONLY事务，不改业务、幂等、审计或Approval；未见回执保留结果未知，不作为重发授权。
- 旧写入没有M8回执时不伪造成功记录，失败事务不留下可见回执；Python同步Schema，确认服务和生产调用入口保持隔离。

## 2026-11-13 T824 M8.5 Python只读原回执核对与未知结果隔离

### 核心解决的问题

Java已有原回执查询时，Agent侧仍可能把查询失败当作没有写入，或拿别的操作、轮次和材料的回执恢复成功。
增加绑定原确认快照的独立只读核对Tool，区分匹配原回执、结果仍未知和查询错误，保留不自动重发写入的边界。

### 实现的核心代码

- `agent-service/app/clients/business.py`：`post_readonly`仅增加合法任务下固定回执查询路径；`clients/rework.py`的`query_operation`单次查询，`check_write_receipt`与写响应共用可见回执绑定校验。
- `agent-service/app/schemas/rework_operation_query.py`：`ReworkOperationLookupInput`和`ReworkOperationResolution`限定原确认单/原键与MATCHED_RECEIPT/UNKNOWN的回执存在关系。
- `agent-service/app/services/rework_receipts.py`：`validate_rework_receipt_binding`供写Tool及核对Tool共用确认轮次、前驱和材料指针规则。
- `agent-service/app/tools/rework_operation_query.py`：`QueryReworkOperationTool._snapshot/_execute`校验身份/确认并在查询前后比较完整快照，独立注册表不接生产动作。
- `scripts/test-rework-query-e2e.sh`：创建独占环回PostgreSQL及本机Java，负责本次进程/容器/临时目录生命周期，不读取本机.env或继承运行库地址。

### 实现的核心功能

- LOW/REWORK_READ只读核对参数仅为原确认单ID/原键，目标和材料来自受信快照；校验实际用户/Run、曾确认时间和执行记录，过期只允许查询，不恢复写权限。
- 共用原操作/资源/原版本+1/状态副作用及轮次/材料校验；匹配返回原回执，未见成功返回UNKNOWN，HTTP/格式/归属和确认变化保留错误，不伪装成业务失败事实。
- 查询前后复制重验完整快照，拒绝迟到结果；默认总预算与最多一次明确瞬时读重试，未知不轮询，显式刷新仍使用原键。
- 不重发业务写入、不保存核对结果或改变Approval终态；本次查询Trace与首次写Trace明确区分，生产持久化确认及终态恢复保持未装配边界。

## 2026-11-14 T825 M8.5 诊断当前复核与历史隔离

### 核心解决的问题

诊断若把任意历史未通过当成永久阻塞，会忽略后来已通过的新轮成果；反过来，旧成果上的通过也不能放行当前缺复核的成果。
应用级复核读取保留历史，并只把Java当前有效复核投影交给固定和动态诊断，版本或问题集合不一致时停止推断。

### 实现的核心代码

- `agent-service/app/schemas/diagnosis_reviews.py`：`DiagnosisReviewResult`、`project_java_reviews`和`review_snapshot_matches`分离历史/当前视图并验证快照归属。
- `agent-service/app/tools/diagnosis_reviews.py`：`GetDiagnosisReviewResultTool`读取历史和Java有效快照，`create_diagnosis_read_tool_registry`仅替换既有复核动作；`app/main.py`装配该只读注册表。
- `agent-service/app/workflows/diagnosis_rules.py`、`information_gaps.py`：检查任务版本和问题集合，受控问题要求关闭且当前通过，动态复核场景不能跳过问题状态。
- `agent-service/app/workflows/diagnosis_generation.py`：保留旧标量证据路径，当前缺复核可定位有效快照的null字段，并输出当前返工需复核的规则说明。

### 实现的核心功能

- 七个只读动作名称和权限不变，reviews仅投影Java当前受控复核或未纳管记录，history_reviews保留旧接口历史，effective_reviews保留当前完整绑定及原样材料。
- 不按历史时间或序号在Python选通过；有效查询失败不退回旧历史，任务版本/问题集合变化不合并为可放行结论，旧裸Tool工厂及Java契约保持兼容。
- 历史拒绝不再永久阻塞已关闭且当前通过的受控问题，旧通过不能替代当前缺失或退回；未纳管问题沿用旧规则，其他交付阻塞继续保留。
- 固定和动态诊断共用视图/规则，前端保留当前缺复核的null证据；旧Run诊断不按新事实重算，新返工写入确认及页面执行入口保持未接入边界。

## 2026-11-14 T826 M8.6 独立返工审批草稿与审查影响

### 核心解决的问题

旧复核/创建草稿不足以表达开始、检查或再次复核的完整对象和材料，简单复用确认也容易允许更换目标、版本或轮次。
新增九类独立草稿及审查包，把当前目标绑定、可编辑请求和条件性副作用分开，不把格式校验当成已经人工确认。

### 实现的核心代码

- `agent-service/app/schemas/rework_approval.py`：`ReworkApprovalTarget`和九类`ReworkApprovalDraft`绑定目标与明确Java请求，`parse_rework_approval_draft`复制校验材料，`validate_rework_draft_edit`限制编辑范围。
- 同模块`ReworkDraftReview`、`expected_rework_effects`及`review_rework_approval_draft`固定操作与Tool/权限类别映射，生成Java接受请求时的预期状态影响。
- `agent-frontend/src/types/reworkApproval.ts`：独立动作/材料判别联合及审查包类型，不扩容旧确认入口或旧卡片。

### 实现的核心功能

- 九类操作各用明确请求类型，首轮与既有轮次分离，目标绑定任务/问题/版本、轮次/前驱、当前成果标识/版本/修订、检查及复核，缺失字段必须显式null。
- 用户本次材料修改可重新进入审查，但不能替换动作、目标或重置版本/轮次，说明/证据按原值及Java UTF-16规则保留，不借用原材料的可变引用。
- 审查包固定本动作Tool和权限类别，登记不等于检查通过、检查通过不等于最终验收，复核关闭只重查交付条件；元数据不能伪造或隐藏副作用。
- 契约不含确认凭证、不读写业务或审批表、不发放执行权，旧ReviewDraft/ORM及确认接口保持隔离；前端只有类型契约，没有运行时解码、页面或HTTP接线。
