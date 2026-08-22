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
- `web-console/src/components/KnowledgeCitationCard.vue`：引用身份、分数和原文展开卡片。

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
