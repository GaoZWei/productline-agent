# 遥感数据产线 Agent 系统开发计划

## 一、项目开发目标

围绕遥感数据产线中的订单、生产任务、生产进度、质检问题、复核结果和成果交付，建设嵌入业务系统的智能协同 Agent。

系统以订单和生产任务为主线，通过页面业务上下文、领域知识库和标准化业务 Tool，实现：

```text
业务查询
→ 状态聚合
→ 异常诊断
→ 规范检索
→ 处理建议生成
→ 操作草稿预览
→ 人工确认
→ 业务结果回写
```

第一阶段不追求建设通用 Agent 平台，而是优先完成一条真实、稳定、可测试的垂直业务链路。

核心演示问题固定为：

```text
这个订单为什么还没有交付？
```

完整执行过程为：

```text
读取当前订单页面上下文
→ 识别订单异常诊断意图
→ 查询订单和关联任务
→ 查询生产进度
→ 查询质检问题和复核状态
→ 查询交付状态
→ 检索相关生产或质检规范
→ 输出阻塞环节、问题根因、数据依据和处理建议
→ 生成复核意见草稿
→ 用户修改并确认
→ 调用 Java 接口完成业务回写
```

---

# 二、总体开发原则

## 1. 固定业务数据优先

先建立固定订单、任务、质检、复核和交付数据，不使用随机数据。

所有功能开发都基于固定业务对象和确定的预期结果进行测试。

## 2. 业务接口优先于 Agent

开发顺序必须是：

```text
Java 接口可以调用
→ Python Tool 可以调用
→ Workflow 可以运行
→ Agent 可以动态决策
```

不能直接让大模型调用尚未经过验证的接口。

## 3. 先完成确定性 Workflow，再增加动态 Agent

状态查询、规范问答等流程明确的场景使用固定 Workflow。

订单延期、任务阻塞等需要根据业务结果动态选择后续路径的场景，再使用 Agent 决策。

## 4. 先读后写

第一阶段优先完成查询和诊断。

复核意见提交、返工任务创建等写操作，必须在查询与诊断链路稳定后开发，并进入人工确认节点。

## 5. 每个迭代必须可测试、可演示

每个迭代都必须包含：

```text
固定输入
预期输出
自动化测试
验收命令
可演示结果
```

没有通过当前迭代验收，不进入下一阶段。

## 6. 从第一条链路开始记录运行过程

不需要在前期建设完整观测平台，但从第一个 Workflow 开始，就要保存最小 Run、Step、错误和耗时信息。

后期再扩展为完整观测系统。

---

# 三、系统范围

## 1. 第一阶段必须完成的业务场景

### 场景一：订单全链路状态查询

用户在订单详情页输入：

```text
这个订单现在进行到哪一步了？
```

系统自动读取当前 `order_id`，汇总订单、生产任务、质检、复核和交付状态。

### 场景二：订单异常诊断

用户输入：

```text
这个订单为什么还没有交付？
```

系统通过多个业务 Tool 查询跨系统数据，输出：

* 当前业务状态；
* 阻塞环节；
* 问题根因；
* 数据依据；
* 规范引用；
* 处理建议。

### 场景三：规范问答

用户输入：

```text
这个产品的坐标系统要求是什么？
```

系统根据当前产品类型、卫星类型和规范版本检索知识库，并返回带引用的回答。

### 场景四：复核意见生成与回写

用户输入：

```text
根据这些问题生成复核意见。
```

系统生成结构化复核草稿，用户修改并确认后，再调用 Java 写接口。

---

## 2. 第一阶段暂不开发

暂不投入大量时间开发：

* 多 Agent 协作；
* 多主 Agent 调度；
* 长期用户记忆；
* MCP 全量接入；
* 可视化 Workflow 拖拽平台；
* 完整业务 CRUD 后台；
* 复杂组织与权限中心；
* 多级审批流引擎；
* 多模态遥感影像识别；
* Kubernetes；
* RabbitMQ；
* Celery；
* Prometheus 和 Grafana；
* 完整报告设计器。

业务系统只实现支撑 Agent 闭环所需要的查询接口、关键写接口和最小展示页面。

---

# 四、系统架构与职责边界

## 1. 前端系统

技术栈：

```text
Vue 3
TypeScript
Vite
Pinia
Element Plus
Axios
SSE
Vitest
Playwright
```

主要负责：

* 订单列表和订单详情展示；
* 任务和质检问题展示；
* 页面上下文采集；
* Agent 对话侧边栏；
* Tool 执行状态展示；
* RAG 引用展示；
* 诊断结果卡片；
* 复核草稿编辑；
* 人工确认；
* Run/Step 运行详情展示。

前端传递的业务对象只能作为上下文提示，Python 和 Java 服务仍需要重新校验对象和权限。

---

## 2. Python Agent 服务

技术栈：

```text
Python 3.12
FastAPI
LangGraph
Pydantic v2
SQLAlchemy 2.x
Alembic
httpx
PostgreSQL
pgvector
Redis（后期可选）
pytest
Ruff
mypy
uv
```

主要负责：

* 页面、会话和执行三级上下文；
* 意图识别；
* 参数提取与澄清；
* Java API Tool 化封装；
* Workflow 执行；
* Agent 动态决策；
* RAG 检索；
* 结构化诊断；
* 操作草稿生成；
* Approval 状态管理；
* Run/Step 持久化；
* SSE 运行事件推送；
* 路由、Tool、RAG 和 Agent 评测。

Python Agent 服务不直接读取或修改 Java 业务数据库。

---

## 3. Java 业务服务

技术栈可以使用：

```text
Spring Boot
Spring Validation
MyBatis-Plus 或 Spring Data JPA
PostgreSQL
OpenAPI / Swagger
统一异常处理
简化 JWT 或 Token 鉴权
```

主要负责：

* 订单数据；
* 生产任务数据；
* 生产进度；
* 质检问题；
* 复核记录；
* 返工任务；
* 交付记录；
* 业务权限；
* 业务状态校验；
* 数据一致性；
* 最终写入。

如果没有完整 Java 服务，可以先使用 WireMock 或最小 Spring Boot Mock 服务，但接口契约需要按照真实业务接口设计。

---

# 五、核心业务模型

## 1. 业务对象关系

```text
Order
├── ProductionTask
│   ├── ProductionStep
│   ├── QualityTask
│   │   ├── QualityIssue
│   │   └── ReviewRecord
│   └── ReworkTask
└── DeliveryBatch
    └── DeliveryRecord
```

核心约束：

* 一个订单包含多个生产任务；
* 一个生产任务包含多个生产环节；
* 一个任务可以产生多条质检问题；
* 一条质检问题可以包含多次处理或复核记录；
* 复核结果可以触发返工任务；
* 所有任务、质检和复核满足要求后，订单才允许交付。

---

## 2. Agent 数据模型

Agent 服务至少包含以下表：

```text
agent_sessions
agent_messages
agent_runs
agent_steps
approval_records
operation_logs
knowledge_documents
knowledge_chunks
evaluation_cases
evaluation_results
```

---

# 六、固定测试数据

## 1. 第一批固定订单

| 订单        | 业务状态   | 关键数据        | 预期结论         |
| --------- | ------ | ----------- | ------------ |
| ORDER-001 | 正常生产中  | 生产任务执行中     | 当前无异常，等待生产完成 |
| ORDER-002 | 生产任务阻塞 | 某生产步骤执行失败   | 阻塞在生产环节      |
| ORDER-003 | 质检未通过  | 坐标系问题未关闭    | 质检问题阻断交付     |
| ORDER-004 | 等待复核   | 问题已处理但未复核   | 阻塞在复核环节      |
| ORDER-005 | 满足交付条件 | 生产、质检、复核均完成 | 可以发起交付       |

## 2. 黄金测试订单

第一条完整链路只围绕 `ORDER-003` 开发。

```text
ORDER-003
├── TASK-003
│   ├── production_status: COMPLETED
│   ├── QUALITY-TASK-003
│   │   ├── ISSUE-001
│   │   │   ├── type: COORDINATE_SYSTEM
│   │   │   └── status: OPEN
│   │   └── review_status: PENDING
│   └── delivery_status: BLOCKED
└── product_type: DOM
```

预期诊断结果：

```json
{
  "order_id": "ORDER-003",
  "blocking_stage": "QUALITY_REVIEW",
  "root_causes": [
    "关联任务存在未关闭的坐标系质量问题",
    "质检复核尚未完成"
  ],
  "evidence": [
    "TASK-003 的生产状态为 COMPLETED",
    "ISSUE-001 的问题状态为 OPEN",
    "ORDER-003 的交付状态为 BLOCKED"
  ],
  "suggestions": [
    "创建坐标系处理返工任务",
    "问题处理完成后重新提交复核"
  ]
}
```

每次开发都必须保证 ORDER-003 的预期结果不发生无理由变化。

---

# 七、业务 Skill 设计

单主 Agent 下第一阶段只实现四个业务 Skill。

## 1. OrderStatusSkill

负责：

* 订单基本信息查询；
* 任务列表查询；
* 生产进度汇总；
* 质检和复核状态汇总；
* 交付状态查询。

执行模式：确定性 Workflow。

## 2. DiagnosisSkill

负责：

* 订单延期诊断；
* 任务阻塞诊断；
* 多业务数据聚合；
* 根因分析；
* 处理建议生成。

执行模式：Agent 动态决策。

## 3. SpecificationSkill

负责：

* 生产规范问答；
* 质检规范问答；
* 交付规范问答；
* 规范版本过滤；
* 引用溯源。

执行模式：RAG Workflow。

## 4. ReviewSkill

负责：

* 复核草稿生成；
* 操作预览；
* 人工修改；
* 二次确认；
* 复核结果回写；
* 返工任务创建。

执行模式：Approval Workflow。

---

# 八、迭代开发计划

## M0：业务数据与 Java 接口基线

### 目标

建立可重复、可重置、可自动测试的业务数据环境。

### 开发任务

1. 初始化前端、Python、Java Mock 和 PostgreSQL 项目；
2. 定义 Java OpenAPI 接口契约；
3. 创建 ORDER-001～ORDER-005 固定数据；
4. 编写一键初始化和重置脚本；
5. 实现 Java Mock 或最小 Spring Boot 服务；
6. 创建订单列表和订单详情最小页面；
7. 建立最小 Trace ID 和接口日志。

第一批接口：

```text
GET  /api/orders/{orderId}
GET  /api/orders/{orderId}/tasks
GET  /api/tasks/{taskId}/progress
GET  /api/tasks/{taskId}/quality-issues
GET  /api/tasks/{taskId}/review
GET  /api/orders/{orderId}/delivery-status
POST /api/tasks/{taskId}/review
POST /api/tasks/{taskId}/rework
```

### 验收标准

* 5 个固定订单均可查询；
* 订单、任务、质检、复核和交付映射正确；
* 数据可一键恢复；
* Java Mock 可以模拟 403、404、409、500 和超时；
* 前端能够展示 ORDER-003；
* Java 接口契约测试通过。

### 测试命令

```bash
make dev
make reset-demo
make test-java-contract
```

---

## M1：Python Tool 层

### 目标

不经过大模型，验证 Python 能稳定调用 Java 接口。

### 开发任务

1. 基于 `httpx.AsyncClient` 实现统一 Java Client；
2. 实现连接池、超时和身份透传；
3. 定义 Tool 输入、输出 Pydantic 模型；
4. 定义风险等级、权限和重试策略；
5. 实现标准错误映射；
6. 实现 Tool 调用日志；
7. 编写 Tool 集成测试。

第一批只读 Tool：

```text
get_order_detail
get_related_tasks
get_production_progress
get_quality_issues
get_review_result
get_delivery_status
```

统一错误类型：

```text
PARAM_VALIDATION_ERROR
RESOURCE_NOT_FOUND
PERMISSION_DENIED
BUSINESS_CONFLICT
TOOL_TIMEOUT
UPSTREAM_UNAVAILABLE
RESPONSE_VALIDATION_ERROR
DUPLICATE_CALL
```

重试原则：

* 查询 Tool 遇到短暂网络异常可以有限重试；
* 业务错误不重试；
* 写 Tool 默认不自动重试；
* 写 Tool 必须携带幂等键。

### 验收标准

* 6 个只读 Tool 均能独立调用；
* Java 返回值能转换为 Pydantic 模型；
* 超时和错误能映射为标准异常；
* Python 不访问业务数据库；
* Tool 正常和异常测试全部通过。

### 测试命令

```bash
make test-tools
pytest tests/integration/tools -q
```

---

## M2：第一条确定性诊断链路

### 目标

尽快跑通第一个端到端场景，避免先开发大量 Agent 框架。

这一阶段暂时不依赖复杂自然语言路由，可以通过固定诊断入口或简单规则进入订单诊断 Workflow。

### 执行流程

```text
读取 ORDER-003 页面上下文
→ 查询订单
→ 查询关联任务
→ 查询生产进度
→ 查询质检问题
→ 查询复核状态
→ 查询交付状态
→ 按确定性规则生成诊断
```

### 诊断输出 Schema

```python
class DiagnosisResult(BaseModel):
    order_id: str
    blocking_stage: str
    root_causes: list[str]
    evidence: list[str]
    suggestions: list[str]
    confidence: float
```

### 数据约束

* 业务状态必须来自 Tool；
* 数值必须来自 Tool；
* `evidence` 必须能够追溯到 Tool 字段；
* 信息不足时必须明确输出信息不足；
* 不允许模型自行构造业务状态。

### 最小 Run/Step

从这一阶段开始记录：

```text
run_id
step_name
step_type
status
duration
error_code
```

暂时不建设完整观测页面。

### 验收标准

* ORDER-003 能得到固定预期结果；
* ORDER-001～ORDER-005 能得到正确阻塞阶段；
* 输出符合 Pydantic Schema；
* 任何 Tool 失败时能够定位到对应 Step；
* 前端可以展示诊断卡片；
* 系统已经具备第一条可演示链路。

### 测试命令

```bash
make test-agent-e2e
pytest tests/e2e/test_order_diagnosis.py -q
```

---

## M3：页面上下文、会话上下文与意图路由

### 目标

让用户能够通过自然语言引用当前业务对象。

### 页面上下文

```json
{
  "current_system": "production-system",
  "current_page": "order-detail",
  "order_id": "ORDER-003",
  "task_id": null,
  "batch_id": null,
  "product_type": "DOM",
  "satellite_type": "GF",
  "user_role": "REVIEWER"
}
```

### 会话上下文

保存：

* 当前订单或任务；
* 上一轮意图；
* 已确认参数；
* 候选业务对象；
* 最近一次诊断结果；
* 待确认操作。

### 执行上下文

保存：

* Tool 调用结果；
* 已执行 Tool；
* RAG 结果；
* 错误信息；
* 当前执行状态；
* 待确认参数。

### 第一批意图

```text
ORDER_QUERY
ORDER_DIAGNOSIS
TASK_TRACKING
SPEC_QA
REVIEW_GENERATION
UNKNOWN
```

### 路由结构

```json
{
  "intent": "ORDER_DIAGNOSIS",
  "confidence": 0.93,
  "entities": {
    "order_id": "ORDER-003"
  },
  "missing_fields": [],
  "need_clarification": false
}
```

### 置信度策略

* 高置信度且参数完整：直接执行；
* 中置信度：展示候选意图或对象；
* 低置信度：进入澄清；
* 缺少必填参数：禁止调用业务 Tool；
* 多个候选任务：要求用户选择，不能自行猜测。

### 路由评测集

至少准备 50 条：

* 明确业务意图；
* 同义表达；
* 模糊指代；
* 页面上下文继承；
* 会话上下文继承；
* 参数缺失；
* 多候选对象；
* 无关问题。

### 验收标准

* 能识别“这个订单”为 ORDER-003；
* 能理解“刚才那个任务”；
* 参数缺失时不会猜测；
* 用户补充参数后可以继续原任务；
* 路由评测结果可以重复运行；
* 失败样本能够保存。

### 测试命令

```bash
make eval-router
pytest tests/evaluation/test_router_eval.py -q
```

---

## M4：RAG 规范检索

### 目标

为规范问答和异常诊断提供可追溯的领域依据。

### 第一批知识文档

准备 10～20 份：

* DOM 产品生产规范；
* 坐标系统要求；
* 云量检查规范；
* 质检问题处理规范；
* 复核操作规范；
* 成果交付条件；
* 新旧版本规范各一份。

### 文档元数据

```text
document_type
satellite_type
product_type
processing_level
specification_version
effective_date
expiry_date
permission_scope
```

### 检索流程

```text
Query Rewrite
→ 元数据过滤
→ 关键词召回
→ 向量召回
→ 分数融合
→ 重复片段合并
→ Rerank
→ 低相关片段拦截
→ 上下文组装
→ 带引用生成
```

### 引用结构

返回：

```text
document_name
document_version
section
chunk_id
content
relevance_score
```

### RAG 评测

准备 50 条问题，每条包含：

```text
question
metadata_filter
expected_document
expected_section
expected_keywords
```

对比：

* 纯向量检索；
* 纯关键词检索；
* 混合检索；
* 混合检索加重排；
* 混合检索加元数据过滤和重排。

### 验收标准

* ORDER-003 能引用坐标系统规范；
* DOM 问题不会引用其他产品规范；
* 已失效规范默认不召回；
* 无有效结果时不输出确定性规范结论；
* RAG 指标能够重复运行和比较。

### 测试命令

```bash
make eval-rag
pytest tests/integration/rag -q
```

---

## M5：动态异常诊断 Agent

### 目标

将固定诊断 Workflow 升级为根据业务状态动态选择 Tool 的 Agent。

### Agent 动作

```text
QUERY_ORDER
QUERY_TASKS
QUERY_PROGRESS
QUERY_QUALITY
QUERY_REVIEW
QUERY_DELIVERY
RETRIEVE_SPEC
FINISH
```

### LangGraph 流程

```text
读取目标和上下文
→ 选择下一 Action
→ 执行 Tool
→ 保存 Observation
→ 判断信息是否充分
→ 继续查询或生成结果
```

### 执行限制

* 最大决策轮数：6；
* 最大 Tool 调用数：8；
* 相同 Tool 和相同参数禁止重复；
* 连续两轮没有新增信息则结束；
* Tool 错误达到限制后停止；
* 写操作禁止在动态 Agent 中自动执行。

### 不同订单期望路径

```text
ORDER-001：
get_order_detail
→ get_related_tasks
→ get_production_progress

ORDER-002：
get_order_detail
→ get_related_tasks
→ get_production_progress

ORDER-003：
get_order_detail
→ get_related_tasks
→ get_quality_issues
→ get_review_result
→ get_delivery_status
→ retrieve_spec

ORDER-004：
get_order_detail
→ get_related_tasks
→ get_review_result

ORDER-005：
get_order_detail
→ get_related_tasks
→ get_delivery_status
```

### 验收标准

* 5 个订单可以走不同 Tool 路径；
* 不出现重复 Tool 调用和无限循环；
* 不需要的 Tool 不调用；
* 动态诊断结果与固定 Workflow 基线一致；
* Agent 不能调用写 Tool；
* Prompt、模型、Tool 描述和策略版本被记录。

### 测试命令

```bash
make test-agent-policy
pytest tests/e2e/test_dynamic_agent.py -q
```

---

## M6：复核草稿与人工确认回写

### 目标

完成一个安全、可追溯的写操作闭环。

### 第一阶段：生成操作草稿

输入：

* 任务信息；
* 质检问题；
* 诊断结果；
* 规范依据。

输出：

```json
{
  "operation_type": "SUBMIT_REVIEW",
  "target_id": "TASK-003",
  "draft": {
    "task_id": "TASK-003",
    "issue_id": "ISSUE-001",
    "conclusion": "REWORK_REQUIRED",
    "problem_summary": "存在未关闭的坐标系质量问题",
    "review_comment": "建议完成坐标系统处理后重新提交复核",
    "specification_references": []
  }
}
```

生成草稿时不得调用 Java 写接口。

### 第二阶段：用户确认

前端支持：

* 预览草稿；
* 修改内容；
* 确认；
* 取消；
* 展示影响对象；
* 展示规范依据。

### 第三阶段：执行回写

确认后执行：

```text
重新校验用户权限
→ 重新查询目标业务对象
→ 校验业务状态是否变化
→ 校验 Approval 是否过期
→ 检查重复提交
→ 调用 Java 写接口
→ 保存执行结果和操作日志
```

### 写 Tool

```text
write_review_result
create_rework_task
```

写 Tool 必须：

* 携带 approval_id；
* 携带用户身份；
* 携带幂等键；
* 重新执行权限校验；
* 不允许大模型直接构造确认状态。

### 验收标准

* 未确认时 Java 写接口调用次数为 0；
* 用户修改后的内容可以正确提交；
* 重复点击只执行一次；
* 取消后业务数据不变；
* Java 409 能正确展示；
* 原始草稿、修改内容和最终结果均可追踪。

### 测试命令

```bash
make test-approval
pytest tests/e2e/test_review_approval.py -q
```

---

## M7：运行观测、生产闭环集成与统一评测

### 目标

先把前面已经独立实现的路由、动态诊断、RAG和Approval接入真实模型、统一HTTP入口和Web交互，再将日志、
测试和评测统一为完整观测与回归体系。M7完成后，用户应能从同一个Agent入口实际使用四个业务Skill，而不只是
在内部测试中分别验证组件。

### Run 数据

保存：

```text
run_id
session_id
user_id
page_context
intent
status
started_at
finished_at
model
prompt_version
tool_schema_version
rag_strategy_version
total_tool_calls
total_tokens
error_code
```

### Step 数据

保存：

```text
step_id
run_id
step_type
step_name
input_summary
output_summary
status
duration
retry_count
error_code
trace_id
```

Step 类型：

```text
CONTEXT
ROUTER
WORKFLOW
AGENT
TOOL
RAG
LLM
APPROVAL
WRITEBACK
```

### SSE 事件

```text
run_started
context_loaded
intent_detected
clarification_required
tool_started
tool_completed
retrieval_completed
diagnosis_generated
approval_required
writeback_completed
run_completed
run_failed
```

### 生产闭环集成

M7.5完成后必须先补齐生产集成，不能直接用内部组件测试代替真实用户链路。计划增加统一Agent入口：

```text
统一Agent抽屉
→ POST /api/agent/messages
→ SessionContext与页面提示合并
→ 真实模型Intent Router
→ 确定性参数、权限和置信度门禁
→ OrderStatus / DynamicDiagnosis / Specification / Review Skill
→ Java Tool事实或带引用RAG
→ Run、Step与SSE
→ Review草稿
→ 用户修改和二次确认
→ Java重新校验并唯一写入
```

本阶段计划补齐：

* OpenAI兼容结构化模型Client及Router、Action、规范回答、Rerank和Review草稿适配器；
* 可重复执行的知识库全量入库命令，以及模型和知识索引能力查询；
* 统一Agent请求、澄清、Skill分发和判别联合响应；
* 状态查询、动态诊断、规范问答和Review人工确认四条生产链路；
* 统一Agent抽屉、规范引用、澄清结果和Approval确认卡片；
* 新类型结果的Run/Step、Token、SSE和历史页面兼容。

M7.6按以下七个批次执行，每个批次验收后再进入下一批次：

```text
M7.6-A 模型调用底座（配置、HTTP、结构化输出、错误和用量）
→ M7.6-B 现有模型协议适配（Router、Action、回答、Rerank、Review）
→ M7.6-C 知识库可运行入库（应用服务、CLI、就绪检查）
→ M7.6-D 统一Agent入口与路由闭环（Schema、Run、澄清、HTTP）
→ M7.6-E 三个只读Skill生产接线（状态、诊断、规范问答）
→ M7.6-F Review与Approval生产闭环（草稿、确认、取消、返工）
→ M7.6-G 统一页面与端到端验收（五类结果、SSE、Docker E2E）
```

`POST /api/agent/order-diagnosis`继续作为固定诊断兼容入口。模型未配置或不可用时，统一Agent入口必须明确返回
稳定错误，不得静默调用固定Workflow并把结果冒充为模型驱动Agent。

模型只负责意图选择、下一步只读动作、规范归纳和可审查草稿。订单状态和阻塞事实仍来自Java Tool，规范结论
必须来自带版本引用的RAG，权限、参数、引用白名单、执行限制和最终写入继续由确定性代码与Java业务服务裁决。

Review草稿中的返工建议不等于执行授权。提交复核结果和创建返工任务必须分别生成Approval，并分别经过用户确认。

M7后续顺序固定为：

```text
M7.1～M7.5 Run/Step、SSE、实时展示和历史页面（已完成）
→ M7.6 生产闭环集成
→ M7.7 异常注入测试
→ M7.8 统一评测框架
→ M7.9 指标计算
```

### 异常注入测试

至少覆盖：

* Java 超时；
* Java 500；
* 业务对象不存在；
* Tool 参数错误；
* Java 返回字段缺失；
* RAG 无结果；
* Embedding 失败；
* 模型结构化输出失败；
* Agent 重复 Tool 调用；
* Agent 超过最大轮数；
* 用户无权限；
* Approval 过期；
* 重复回写；
* 用户取消；
* SSE 中断。

### 统一评测报告

统一输出：

```text
路由准确率
参数提取与澄清补全率
Tool 参数首次通过率
Tool 最终成功率
RAG Hit@5
Top-5 无关片段占比
Agent E2E 通过率
Agent 平均 Tool 调用次数
异常步骤可定位率
诊断平均耗时
复核内容平均整理时间
```

### 验收标准

* 每次执行均有 Run 和 Step；
* 失败可以定位到具体 Step；
* SSE 能实时展示执行过程；
* 统一Agent入口可以实际分发并展示四个业务Skill；
* 模型不可用时不会伪装为动态Agent成功；
* 规范问答在知识入库后返回现行版本引用；
* Review草稿未经确认不写入，确认和返工使用独立Approval；
* 所有评测可以统一执行；
* 测试结果能够导出；
* 简历中的量化指标只使用真实测试结果。

### 测试命令

```bash
make test
make quality
make eval-all
```

---

# 九、时间安排

## 第一阶段：可运行 MVP

| 迭代             |    时间 | 可演示结果             |
| -------------- | ----: | ----------------- |
| M0 业务数据与接口     | 3～4 天 | 固定订单数据可查询         |
| M1 Python Tool | 4～5 天 | Python 可稳定调用 Java |
| M2 确定性诊断       | 4～5 天 | ORDER-003 可完成诊断   |
| M3 上下文与路由      | 4～5 天 | 能理解“这个订单”并澄清      |

完成 M0～M3 后，系统已经具备可演示的 Agent 雏形。

## 第二阶段：核心 Agent 能力

| 迭代          |    时间 | 可演示结果           |
| ----------- | ----: | --------------- |
| M4 RAG      | 5～7 天 | 诊断结果带规范引用       |
| M5 动态 Agent | 5～7 天 | 不同订单走不同 Tool 路径 |
| M6 人工确认回写   | 4～6 天 | 复核意见确认后写回       |

## 第三阶段：工程化与数据指标

| 迭代       |    时间 | 可演示结果        |
| -------- | ----: | ------------ |
| M7 观测、生产集成与评测 | 8～12 天 | 四个Skill可从页面使用并运行统一评测 |

整体建议周期约为 7～9 周。

如果从零开始且时间有限，优先完成M0～M4，再补M6；M5的动态Agent可以在固定Workflow稳定后逐步增强。
当前M0～M7.5已经完成，下一步不得跳过M7.6而直接用内部组件执行异常评测，否则评测结果不能代表真实页面链路。

---

# 十、统一测试命令

```bash
make dev
make reset-demo
make test-java-contract
make test-tools
make test-agent-e2e
make eval-router
make eval-rag
make test-agent-policy
make test-approval
make eval-all
make quality
```

---

# 十一、项目目录建议

```text
remote-sensing-agent/
├── agent-service/
│   ├── app/
│   │   ├── api/
│   │   ├── agents/
│   │   ├── skills/
│   │   ├── workflows/
│   │   ├── tools/
│   │   ├── contexts/
│   │   ├── rag/
│   │   ├── approvals/
│   │   ├── observability/
│   │   ├── providers/
│   │   ├── models/
│   │   └── repositories/
│   ├── tests/
│   └── alembic/
├── business-service/
├── web-console/
├── knowledge-base/
├── evals/
│   ├── router/
│   ├── tools/
│   ├── rag/
│   ├── agent/
│   └── fault-injection/
├── scripts/
├── docs/
│   ├── REQUIREMENTS.md
│   ├── ARCHITECTURE.md
│   ├── DOMAIN_MODEL.md
│   ├── API_CONTRACT.md
│   ├── ROADMAP.md
│   └── STATUS.md
└── docker-compose.yml
```

---

# 十二、Codex 开发规则

每次只让 Codex 完成一个有确定输入、输出和测试标准的任务。

任务模板：

```markdown
## 任务名称

实现 get_quality_issues Tool。

## 业务场景

查询 TASK-003 对应的质检问题。

## 业务映射

ORDER-003 → TASK-003 → ISSUE-001。

## 输入

task_id = TASK-003

## 预期输出

返回 ISSUE-001：

- type = COORDINATE_SYSTEM
- status = OPEN

## 异常场景

1. TASK-999 返回 RESOURCE_NOT_FOUND；
2. Java 超时返回 TOOL_TIMEOUT；
3. Java 响应字段缺失返回 RESPONSE_VALIDATION_ERROR。

## 测试命令

pytest tests/integration/tools/test_get_quality_issues.py -q

## 完成标准

1. 正常和异常测试全部通过；
2. Ruff 通过；
3. mypy 通过；
4. 不修改其他 Tool；
5. 更新 docs/STATUS.md。
```

Codex 每次任务必须遵守：

1. 不跨里程碑提前开发；
2. 不一次实现多个业务模块；
3. 先编写或确认测试；
4. 修改后运行对应测试；
5. 更新 STATUS；
6. 不擅自修改接口契约；
7. 不直接访问 Java 业务数据库；
8. 不让模型生成业务事实；
9. 不绕过人工确认；
10. 不虚构测试指标。

---

# 十三、进度管理

## ROADMAP.md

```text
[x] M0 业务数据与 Java 接口
[ ] M1 Python Tool
[ ] M2 确定性订单诊断
[ ] M3 页面上下文与路由
[ ] M4 RAG
[ ] M5 动态 Agent
[ ] M6 人工确认回写
[ ] M7 Run/Step 与评测
```

## STATUS.md

```text
当前里程碑：M2
当前场景：ORDER-003 未交付诊断
已完成任务：T201-T205
通过测试：35
失败测试：2
当前阻塞：质检问题证据映射失败
下一任务：修复 DiagnosisResult evidence 映射
```

## 测试与评测结果

```text
每次开发：
在 STATUS.md 记录当前执行命令、通过/失败摘要和阻塞。

需要指标时运行可重复评测命令，例如：

路由评测：
样本数：50
正确数：46
准确率：92%

Tool 评测：
参数首次校验通过率：89%
最终有效调用成功率：97%

RAG 评测：
样本数：50
Hit@5：86%

Agent E2E：
总场景：5
通过：4
失败：1
```

仓库不维护累计测试报告；历史明细由 Git/CI 日志保留。评测数字必须能够通过固定数据和命令重新生成。

---

# 十四、简历成果与开发阶段对应关系

| 简历成果                    | 数据来源                |
| ----------------------- | ------------------- |
| 异常诊断时间由约 3 分钟缩短至 30 秒   | M2、M5、M7 的端到端耗时测试   |
| 意图识别准确率 90%+            | M3 路由评测集            |
| 参数补全率 95%+              | M3 参数缺失与澄清评测        |
| Tool 首次通过率 88%+         | M1 Tool 参数评测        |
| Tool 最终成功率 97%+         | M1 重试和错误修正评测        |
| RAG Hit@5 从 76% 提升至 88% | M4 多策略对比评测          |
| 无关片段占比降至 18%            | M4 Top-5 片段标注结果     |
| 复核整理时间降低约 50%           | M6 人工基线与 Agent 草稿对比 |
| 23/24 次异常可定位            | M7 异常注入测试           |

在可重复自动化评测未达到这些数据之前，简历指标应标记为目标值，不能当作已经完成的真实结果。

---

# 十五、最终开发顺序

```text
1. 固定业务对象和映射关系
2. 定义 Java 接口契约
3. 准备可重置测试数据
4. 完成 Java Mock
5. 完成 Python HTTP Client
6. 完成只读 Tool
7. 完成 ORDER-003 固定诊断 Workflow
8. 接入最小 Run/Step
9. 完成页面上下文
10. 完成意图路由和澄清
11. 完成 RAG 规范检索
12. 升级为动态诊断 Agent
13. 生成复核草稿
14. 完成人工确认和安全回写
15. 完整实现 Run/Step、SSE 和历史页面
16. 接入真实模型、知识入库和统一Agent入口
17. 从页面接通四个Skill与Approval闭环
18. 完成异常注入和统一评测
19. 根据真实测试结果更新简历指标
```

核心原则是：

> 先保证业务接口能够闭环，再保证 Tool 能够闭环；先用固定 Workflow 得到正确结果，再让 Agent 动态选择路径；先完成读操作，再开发需要人工确认的写操作；每完成一个功能，立即通过固定数据和自动测试验证。
