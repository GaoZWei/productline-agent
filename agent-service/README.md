# Agent Service

M2.6 Python 3.12/FastAPI 服务。当前包含工程基础、Agent 自有数据库连接、结构化日志、
调用 Java 的共享异步 HTTP Client、标准 Tool 错误映射、Tool 基础协议和七个只读业务 Tool；
只读 Tool 已具备显式有限退避重试、Run 内重复调用检测和仅开发环境启用的调试 API。当前还
包含 Session/Message/Run/Step 模型、Alembic迁移、Repository、最小Run/Step生命周期和
Workflow状态/诊断Schema、固定LangGraph数据加载节点和确定性阻塞阶段规则，尚未包含诊断文案、
RAG或模型调用。

## 本地开发

uv 会按照 `.python-version` 安装/选择 Python 3.12，并根据 `uv.lock` 创建 `.venv`：

```bash
cd agent-service
uv sync --frozen
uv run python -m app.main
```

默认健康检查为 <http://localhost:8000/health>。可使用 `PORT`、`ENVIRONMENT`、
`LOG_LEVEL`、`DATABASE_URL`、`BUSINESS_SERVICE_URL` 和四项
`BUSINESS_*_TIMEOUT_SECONDS` 覆盖配置。

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
持久化基础，但当前 Tool 调试链尚未写入这些表，也没有 Approval。

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
    └── agent_runs      一次请求、状态、最终结果与错误定位
            └── agent_steps  CONTEXT/TOOL/RULE/LLM 步骤、摘要和耗时
```

`AgentRunRepository` 和 `AgentStepRepository` 提供异步增、删、查。Repository 会 `flush` 以便
尽早发现外键、唯一序号等数据库约束，但不会隐式 `commit`；事务边界由 Run 生命周期调用方
统一控制。删除 Session 会级联其 Message、Run 和 Step，删除 Run 会级联 Step；删除请求消息
只把 Run 的 `request_message_id` 置空，保留已发生的运行记录。

Run 状态和 Step 类型已按 M2 计划固化为字符串 Check Constraint。Step 输入/输出只预留受控
摘要字段，不能写入完整 Token、密钥或未经脱敏的业务载荷。

`RunLifecycleService`实现以下最小状态机：

```text
create_run       → PENDING
mark_running     → PENDING → RUNNING
mark_succeeded   → RUNNING → SUCCEEDED，并保存标准JSON结果快照
mark_failed      → RUNNING → FAILED，并保存error_code和error_step
```

状态更新使用`WHERE run_id=? AND status=?`的原子条件更新。并发成功/失败请求只有一个能修改
`RUNNING` Run，另一个得到`InvalidRunTransitionError`，避免最后写入者覆盖先完成的终态。
Repository和Service仍不隐式commit，事务由调用方统一提交。M2.5 Workflow已通过
`DatabaseWorkflowStepRecorder`复用Step生命周期；`WAITING_APPROVAL`和`CANCELLED`操作未提前实现。

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

`DiagnosisResult`使用严格、不可变且禁止额外字段的Pydantic模型，包含订单ID、阻塞阶段、结构化
`RootCause`、`Evidence`、`Suggestion`和0～1置信度。`Evidence`当前只接受七个已注册只读Tool、
可定位字段路径和标量值，禁止把模型判断或整段业务响应冒充事实证据；`StepError`只保留稳定
错误码、安全文案、retryable和可选Trace ID，不接收原始响应或异常堆栈。

`blocking_stage`由`BlockingStage`限制为`PRODUCTION/PRODUCTION_BLOCKED/QUALITY_REVIEW/REVIEW/
DELIVERY/NONE/INSUFFICIENT_INFORMATION`。`NONE`不得同时携带根因，其他阶段至少需要一个根因。
M2.6只把规则决策保存到`RuleDecision`，最终`DiagnosisResult`仍留给M2.7生成。

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
→ diagnose_by_rules
```

`load_context`校验`order_id`和Run一致性并初始化全部状态通道；其余节点只通过现有只读Tool读取
Java事实。任务列表按`task_id`稳定排序，进度、质检和复核以`task_id`为键一次性合并，避免多任务
结果失去归属。节点返回增量字典，由LangGraph合并到共享`OrderDiagnosisState`。

Tool标准失败转换为`StepError`后，条件边直接进入`END`，因此失败节点后的Tool不会继续执行。
每次Workflow实例绑定一个`ToolContext`且只能运行一次，确保Run内重复调用账本不会被跨Run误用。
`WorkflowStepRecorder`用于测试替换，生产适配`DatabaseWorkflowStepRecorder`会在动作前后分别开启
短事务记录Step，Java HTTP等待期间不持有数据库锁。

`diagnose_by_rules`只消费前序Tool事实，不再发HTTP请求。规则先检查订单、任务、进度、质检、复核
和交付事实是否完整，再按“生产失败 → 生产中 → 未关闭质检 → 未通过复核 → 交付阻塞 → 无阻塞”
返回最早阶段；缺失或归属矛盾时返回`INSUFFICIENT_INFORMATION`。规则执行以`RULE`类型Step记录，
但当前没有诊断HTTP API，也不会生成根因、字段证据、建议或用户文案。

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
```

`unit` 标记不使用外部服务；`integration` 标记覆盖 FastAPI 生命周期、中间件和 HTTP
边界及 PostgreSQL 持久化。`make test-agent-persistence` 使用随机宿主端口和临时数据目录启动
隔离 PostgreSQL，完成后自动删除，避免误用本机或开发数据库。

## 数据边界

`app.database.Base` 当前只映射 Agent Session、Message、Run、Step，并可继续承载 Approval 和
RAG 元数据。Python 服务
不得为 Java 的订单、生产、质检、复核或交付表建立 ORM 映射，也不得绕过 Java API
读取或修改业务事实。

## Docker 启动

```bash
docker compose up --build agent-service
```
