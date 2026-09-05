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

- `web-console/src/types/agent.ts`：与后端Approval、ReviewDraft和状态枚举对齐的前端契约。
- `web-console/src/components/ReviewApprovalCard.vue`：草稿展示、编辑、引用、二次确认和事件边界。
- `web-console/src/components/ReviewApprovalCard.spec.ts`：内容展示、编辑归一化、结论联动和防重复交互测试。

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
- `web-console/src/api/agentClient.ts`：确认请求、写入结果校验及Approval错误映射。

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
- `agent-service/app/api/approvals.py`、`web-console/src/api/agentClient.ts`：按Approval读取日志及前端运行时校验。

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

- `web-console/src/api/runEventClient.ts`、`src/types/runEvents.ts`：带身份的流连接、严格事件解析、有限重连和错误契约。
- `web-console/src/observability/runEventTimeline.ts`、`src/components/AgentRunTimeline.vue`：纯事件归并、步骤状态、失败定位和耗时展示。
- `web-console/src/components/AgentDiagnosisDrawer.vue`、`src/api/agentClient.ts`：先连接再诊断的流标识绑定及生命周期清理。
- `web-console/server.mjs`：生产同源代理的SSE专用上游不可用响应。

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
- `web-console/src/api/runHistoryClient.ts`、`src/components/RunHistoryPage.vue`：运行时响应校验、列表/详情隔离加载和完整历史视图。

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
- `agent-service/app/schemas/run_history.py`、`web-console/src/components/RunHistoryPage.vue`：LLM Step指标的受控历史投影与展示。

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
