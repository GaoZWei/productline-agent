# 遥感数据产线 Agent 细化开发计划

## 一、任务拆分标准

每个开发任务尽量满足以下条件：

1. 单个任务预计耗时 1～4 小时；
2. 只修改一个明确模块；
3. 有固定输入和预期输出；
4. 至少包含一个自动化测试；
5. 有独立测试命令；
6. 完成后可以提交一次 Git Commit；
7. 不依赖尚未实现的大量后续能力。

单个任务的完成流程统一为：

```text
阅读接口或业务定义
→ 编写测试
→ 实现功能
→ 运行局部测试
→ 运行代码质量检查
→ 检查并同步当前 Mx.y 的“解决的问题”
→ 更新 STATUS.md
→ 提交代码
```

---

# 二、里程碑总览

| 里程碑 | 核心目标                | 最终产物                   |
| --- | ------------------- | ---------------------- |
| M0  | 固定业务数据和 Java 接口基线   | 可查询、可重置的业务系统           |
| M1  | Python Tool 调用 Java | 可独立测试的标准化 Tool 层       |
| M2  | 确定性订单诊断链路           | ORDER-003 端到端诊断        |
| M3  | 上下文、路由和澄清           | 能理解“这个订单”等自然语言         |
| M4  | RAG 规范检索            | 带版本过滤和引用的规范回答          |
| M5  | 动态诊断 Agent          | 根据业务状态选择不同 Tool        |
| M6  | 人工确认和安全回写           | 复核草稿确认后写入 Java         |
| M7  | 运行观测和统一评测           | Run/Step、SSE、异常定位、指标报告 |

---

# 三、M0：业务数据与 Java 接口基线

## 目标

建立稳定、可重复、可自动测试的业务数据环境。

本阶段不开发 Agent，只保证业务数据和接口本身正确。

---

## M0.1 项目基础环境

### 解决的问题

本阶段搭建Java业务服务、Python Agent服务和Web控制台的统一工程骨架，并提供可复用的启动、
配置和验证入口，为后续业务与Agent能力开发建立稳定基础。

| ID   | 任务                | 主要产物                                                    | 验证方式                    |   工时 |
| ---- | ----------------- | ------------------------------------------------------- | ----------------------- | ---: |
| T001 | 创建 Monorepo 目录    | `agent-service`、`business-service`、`web-console`、`docs` | 目录检查                    |   1h |
| T002 | 初始化 Git 和基础忽略配置   | `.gitignore`、`.editorconfig`                            | Git 状态正常                | 0.5h |
| T003 | 创建根目录 README      | 启动方式、项目结构、业务背景                                          | 文档检查                    |   1h |
| T004 | 创建 `.env.example` | Java、Python、数据库、模型配置项                                   | 环境变量检查                  |   1h |
| T005 | 创建 Docker Compose | PostgreSQL、Java、Python、前端                               | `docker compose config` |   2h |
| T006 | 创建根目录 Makefile    | `make dev`、`make test`、`make reset-demo`                | 命令可执行                   |   2h |

### M0.1 验收

```bash
docker compose config
make help
```

完成标准：

* 三个子项目均可以单独启动；
* 根目录有统一开发命令；
* 不需要手动修改源码才能切换环境。

---

## M0.2 业务领域模型设计

### 解决的问题

本阶段统一订单、生产任务、质检、复核和交付的Java领域对象及状态契约，为业务接口、Tool Schema和
确定性诊断提供不可随意补造的事实边界。

### 核心枚举

先定义统一业务状态，避免 Java、Python、前端各自使用不同字符串。

#### 订单状态

```text
CREATED
PRODUCING
QUALITY_CHECKING
REVIEWING
READY_FOR_DELIVERY
DELIVERING
DELIVERED
BLOCKED
```

#### 生产任务状态

```text
PENDING
RUNNING
COMPLETED
FAILED
BLOCKED
```

#### 质检问题状态

```text
OPEN
PROCESSING
RESOLVED
CLOSED
```

#### 复核状态

```text
PENDING
APPROVED
REJECTED
REWORK_REQUIRED
```

#### 交付状态

```text
NOT_READY
READY
DELIVERING
DELIVERED
FAILED
BLOCKED
```

### 具体任务

| ID   | 任务                   | 主要产物                   | 验证方式          | 工时 |
| ---- | -------------------- | ---------------------- | ------------- | -: |
| T007 | 编写领域对象关系文档           | `docs/DOMAIN_MODEL.md` | 人工检查          | 2h |
| T008 | 定义统一业务枚举             | Java Enum、接口文档         | 单元测试          | 2h |
| T009 | 定义 Order 模型          | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T010 | 定义 ProductionTask 模型 | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T011 | 定义 ProductionStep 模型 | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T012 | 定义 QualityIssue 模型   | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T013 | 定义 ReviewRecord 模型   | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T014 | 定义 ReworkTask 模型     | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T015 | 定义 DeliveryRecord 模型 | 实体、DTO、数据库表            | Repository 测试 | 2h |
| T016 | 定义对象关联关系             | 外键、一对多关系               | 集成测试          | 2h |

### M0.2 验收

至少能够通过 Repository 查询：

```text
ORDER-003
→ TASK-003
→ ISSUE-001
→ REVIEW 状态
→ DELIVERY 状态
```

---

## M0.3 固定业务数据

### 解决的问题

本阶段建立ORDER-001～005五个可重复、可重置的固定业务场景，并固化ORDER-003黄金链路，为接口、
Tool和后续Agent诊断提供确定性输入与预期结论。

### 固定订单

#### ORDER-001：正常生产

```text
订单状态：PRODUCING
任务状态：RUNNING
质检问题：无
交付状态：NOT_READY
```

#### ORDER-002：生产阻塞

```text
订单状态：BLOCKED
任务状态：FAILED
失败环节：影像预处理
质检问题：无
交付状态：NOT_READY
```

#### ORDER-003：质检问题阻塞

```text
订单状态：QUALITY_CHECKING
任务状态：COMPLETED
质检问题：坐标系问题，OPEN
复核状态：PENDING
交付状态：BLOCKED
```

#### ORDER-004：等待复核

```text
订单状态：REVIEWING
任务状态：COMPLETED
质检问题：RESOLVED
复核状态：PENDING
交付状态：BLOCKED
```

#### ORDER-005：满足交付条件

```text
订单状态：READY_FOR_DELIVERY
任务状态：COMPLETED
质检问题：CLOSED
复核状态：APPROVED
交付状态：READY
```

### 具体任务

| ID   | 任务                 | 主要产物                 | 验证方式     | 工时 |
| ---- | ------------------ | -------------------- | -------- | -: |
| T017 | 编写 ORDER-001 初始化数据 | SQL 或 Java Seed      | 查询验证     | 1h |
| T018 | 编写 ORDER-002 初始化数据 | SQL 或 Java Seed      | 查询验证     | 1h |
| T019 | 编写 ORDER-003 初始化数据 | SQL 或 Java Seed      | 黄金场景测试   | 2h |
| T020 | 编写 ORDER-004 初始化数据 | SQL 或 Java Seed      | 查询验证     | 1h |
| T021 | 编写 ORDER-005 初始化数据 | SQL 或 Java Seed      | 查询验证     | 1h |
| T022 | 创建数据重置脚本           | `scripts/reset-demo` | 多次执行结果一致 | 2h |
| T023 | 创建数据完整性测试          | 映射关系测试               | 自动测试     | 2h |
| T024 | 创建业务状态一致性测试        | 状态组合约束               | 自动测试     | 2h |

### 状态一致性示例

以下数据应被判定为错误：

```text
任务未完成，但订单已经 DELIVERED
存在 OPEN 质检问题，但交付状态为 READY
复核状态为 PENDING，但订单状态为 DELIVERED
```

---

## M0.4 Java 查询接口

### 解决的问题

本阶段通过Java只读接口对外提供订单、任务、进度、质检、复核和交付事实，使Python Tool只能通过
经过业务校验的API获取数据，而不是直接访问业务数据库。

| ID   | 接口任务     | 接口                                     | 测试重点           | 工时 |
| ---- | -------- | -------------------------------------- | -------------- | -: |
| T025 | 查询订单详情   | `GET /api/orders/{id}`                 | 正常、404         | 2h |
| T026 | 查询订单任务   | `GET /api/orders/{id}/tasks`           | 空列表、404        | 2h |
| T027 | 查询任务详情   | `GET /api/tasks/{id}`                  | 正常、404         | 2h |
| T028 | 查询生产进度   | `GET /api/tasks/{id}/progress`         | 多步骤排序          | 2h |
| T029 | 查询质检问题   | `GET /api/tasks/{id}/quality-issues`   | OPEN/CLOSED 过滤 | 2h |
| T030 | 查询复核结果   | `GET /api/tasks/{id}/review`           | 无复核记录          | 2h |
| T031 | 查询交付状态   | `GET /api/orders/{id}/delivery-status` | READY/BLOCKED  | 2h |
| T032 | 查询订单聚合状态 | `GET /api/orders/{id}/overview`        | 跨表聚合           | 3h |

建议保留聚合接口，但 Agent 第一版仍通过多个 Tool 查询，以体现跨系统诊断过程。

---

## M0.5 Java 写接口

### 解决的问题

本阶段实现复核提交和返工创建等Java写能力，并通过权限、状态版本、幂等键和操作日志保护最终业务回写，
为后续Approval确认后的安全写Tool提供接口基础。

| ID   | 接口任务      | 接口                            | 测试重点      | 工时 |
| ---- | --------- | ----------------------------- | --------- | -: |
| T033 | 提交复核结果    | `POST /api/tasks/{id}/review` | 权限、状态冲突   | 3h |
| T034 | 创建返工任务    | `POST /api/tasks/{id}/rework` | 重复创建      | 3h |
| T035 | 增加幂等键支持   | `Idempotency-Key`             | 相同请求只执行一次 | 3h |
| T036 | 增加业务状态版本号 | `version` 字段                  | 并发修改冲突    | 2h |
| T037 | 增加操作日志    | `operation_log`               | 操作前后记录    | 2h |

写接口此时只需要完成 Java 侧实现，暂时不接 Agent。

---

## M0.6 Java 统一异常

### 解决的问题

本阶段统一Java接口的成功与失败响应、错误码、可重试标识和Trace ID，使Python Client能够稳定区分
参数、权限、资源、冲突和系统异常。

统一响应：

```json
{
  "success": false,
  "code": "BUSINESS_CONFLICT",
  "message": "当前任务状态不允许提交复核",
  "data": null,
  "trace_id": "trace-001",
  "retryable": false
}
```

| ID   | 任务                 | 主要产物             | 工时 |
| ---- | ------------------ | ---------------- | -: |
| T038 | 定义统一响应结构           | `ApiResponse<T>` | 1h |
| T039 | 实现参数异常处理           | 400 映射           | 1h |
| T040 | 实现未认证和无权限处理        | 401、403          | 2h |
| T041 | 实现资源不存在处理          | 404              | 1h |
| T042 | 实现业务冲突处理           | 409              | 2h |
| T043 | 实现系统异常处理           | 500              | 1h |
| T044 | 增加 Trace ID Filter | 请求链路追踪           | 2h |

---

## M0.7 故障模拟

### 解决的问题

本阶段提供仅用于开发测试的延迟、超时、服务异常、响应缺失和权限失败模拟，使Python Tool的错误
映射、重试与降级行为可以稳定复现和自动验证。

| ID   | 任务          | 故障类型        | 工时 |
| ---- | ----------- | ----------- | -: |
| T045 | 增加延迟模拟参数    | 响应延迟        | 1h |
| T046 | 增加超时模拟接口    | Java 长时间无响应 | 1h |
| T047 | 增加 500 模拟接口 | 服务异常        | 1h |
| T048 | 增加字段缺失模拟    | 错误响应结构      | 1h |
| T049 | 增加权限失败模拟    | 403         | 1h |

开发环境可以通过请求头控制：

```text
X-Demo-Fault: timeout
X-Demo-Fault: server-error
X-Demo-Fault: invalid-response
```

---

## M0.8 最小前端业务页面

### 解决的问题

本阶段提供五个固定订单的最小业务展示和切换页面，验证Java查询接口与前端状态映射，并为后续嵌入
Agent对话、步骤和诊断结果预留业务上下文载体。

| ID   | 任务              | 页面或组件         | 工时 |
| ---- | --------------- | ------------- | -: |
| T050 | 初始化 Vue3 项目     | Vite、TS、Pinia | 2h |
| T051 | 封装 Axios Client | Base URL、错误拦截 | 2h |
| T052 | 实现订单列表页         | 5 个固定订单       | 3h |
| T053 | 实现订单详情页         | 订单基础信息        | 3h |
| T054 | 实现任务列表组件        | 任务状态展示        | 2h |
| T055 | 实现质检问题组件        | 问题和状态         | 2h |
| T056 | 实现交付状态组件        | 交付状态展示        | 1h |
| T057 | 实现固定订单快速切换      | ORDER-001～005 | 1h |

---

## M0 完整验收

```bash
make reset-demo
make test-java-contract
make test-business-data
```

必须满足：

* ORDER-001～005 数据稳定；
* ORDER-003 映射完整；
* 查询和写接口均有接口测试；
* 故障模拟可以使用；
* 前端能够查看 5 个订单；
* 暂时不包含任何大模型调用。

---

# 四、M1：Python Tool 层

## 目标

Python Agent 服务能够稳定调用 Java 接口。

本阶段仍然不让大模型自主选择 Tool。

---

## M1.1 Python 工程初始化

### 解决的问题

本阶段搭建FastAPI、配置、数据库、迁移、日志和测试质量工具组成的Python Agent服务骨架，为Client、
Tool、Workflow和运行记录提供统一工程基础。

| ID   | 任务                  | 主要产物             | 工时 |
| ---- | ------------------- | ---------------- | -: |
| T101 | 使用 uv 初始化 Python 项目 | `pyproject.toml` | 1h |
| T102 | 配置 FastAPI          | 应用入口、健康检查        | 1h |
| T103 | 配置 Ruff             | lint 规则          | 1h |
| T104 | 配置 mypy             | 类型检查             | 1h |
| T105 | 配置 pytest           | 单元、集成标记          | 1h |
| T106 | 配置 SQLAlchemy       | Agent 数据库连接      | 2h |
| T107 | 配置 Alembic          | 数据库迁移            | 2h |
| T108 | 配置结构化日志             | JSON 日志、Trace ID | 2h |

---

## M1.2 Java HTTP Client

### 解决的问题

本阶段封装Python访问Java业务接口的异步HTTP Client，统一管理连接生命周期、超时、身份与Trace ID
透传、响应解析和Schema校验，为所有Tool提供稳定调用通道。

| ID   | 任务                  | 主要内容               | 测试      | 工时 |
| ---- | ------------------- | ------------------ | ------- | -: |
| T109 | 定义 Client 配置模型      | Base URL、Timeout   | 配置测试    | 1h |
| T110 | 创建 AsyncClient 生命周期 | 启动和关闭              | 生命周期测试  | 2h |
| T111 | 实现身份头透传             | User ID、Role、Token | 请求头断言   | 2h |
| T112 | 实现 Trace ID 透传      | Trace ID           | 链路测试    | 1h |
| T113 | 实现查询请求方法            | GET 封装             | Mock 测试 | 2h |
| T114 | 实现写请求方法             | POST 封装            | Mock 测试 | 2h |
| T115 | 实现超时配置              | connect/read/write | 超时测试    | 2h |
| T116 | 实现响应 JSON 解析        | 正常结构               | 解析测试    | 2h |
| T117 | 实现响应 Schema 校验      | 字段缺失拦截             | 异常测试    | 2h |

---

## M1.3 标准错误模型

### 解决的问题

本阶段把Java业务错误、HTTP异常、超时和响应校验失败转换为统一Tool错误类型，使Workflow能够根据
稳定错误码和retryable属性决定失败处理与重试策略。

Python 错误类型：

```text
PARAM_VALIDATION_ERROR
RESOURCE_NOT_FOUND
PERMISSION_DENIED
BUSINESS_CONFLICT
TOOL_TIMEOUT
UPSTREAM_UNAVAILABLE
RESPONSE_VALIDATION_ERROR
DUPLICATE_CALL
UNKNOWN_TOOL_ERROR
```

| ID   | 任务                  | 主要内容                      | 工时 |
| ---- | ------------------- | ------------------------- | -: |
| T118 | 定义 ToolException 基类 | code、message、retryable    | 1h |
| T119 | 映射 400 参数错误         | Java → Python             | 1h |
| T120 | 映射 403 权限错误         | Java → Python             | 1h |
| T121 | 映射 404 资源不存在        | Java → Python             | 1h |
| T122 | 映射 409 业务冲突         | Java → Python             | 1h |
| T123 | 映射 500 上游异常         | Java → Python             | 1h |
| T124 | 映射 httpx Timeout    | TOOL_TIMEOUT              | 1h |
| T125 | 映射响应字段错误            | RESPONSE_VALIDATION_ERROR | 1h |
| T126 | 编写错误映射参数化测试         | 全错误类型                     | 2h |

---

## M1.4 Tool 基础协议

### 解决的问题

本阶段定义Tool输入输出、调用上下文、风险和权限等统一协议，并通过Registry集中注册与查找Tool，
为后续Workflow和Agent安全、可测试地调用业务能力建立边界。

每个 Tool 统一包含：

```python
name
description
input_model
output_model
risk_level
required_permissions
timeout
max_retries
```

| ID   | 任务              | 主要内容               | 工时 |
| ---- | --------------- | ------------------ | -: |
| T127 | 定义 Tool 基类      | execute 接口         | 2h |
| T128 | 定义 ToolContext  | 用户、Trace、Run       | 2h |
| T129 | 定义 ToolResult   | success、data、error | 2h |
| T130 | 定义 ToolRegistry | 名称注册和获取            | 2h |
| T131 | 实现重复 Tool 注册检测  | 防名称冲突              | 1h |
| T132 | 编写 Tool 基类测试    | 正常和异常              | 2h |

---

## M1.5 只读 Tool

### 解决的问题

本阶段把七个Java查询接口封装为具有明确Pydantic输入输出Schema的只读Tool，使订单诊断所需业务
事实可以脱离Agent独立调用和验证。

每个 Tool 单独开发和提交。

| ID   | Tool                      | 输入         | 输出               | 工时 |
| ---- | ------------------------- | ---------- | ---------------- | -: |
| T133 | `get_order_detail`        | `order_id` | OrderDetail      | 3h |
| T134 | `get_related_tasks`       | `order_id` | TaskList         | 3h |
| T135 | `get_task_detail`         | `task_id`  | TaskDetail       | 2h |
| T136 | `get_production_progress` | `task_id`  | ProgressResult   | 3h |
| T137 | `get_quality_issues`      | `task_id`  | QualityIssueList | 3h |
| T138 | `get_review_result`       | `task_id`  | ReviewResult     | 3h |
| T139 | `get_delivery_status`     | `order_id` | DeliveryStatus   | 3h |

每个 Tool 的测试必须覆盖：

1. 正常返回；
2. 参数为空；
3. 参数格式错误；
4. 资源不存在；
5. 无权限；
6. Java 500；
7. Java 超时；
8. Java 返回字段缺失。

---

## M1.6 Tool 重试

### 解决的问题

本阶段为明确可重试的只读Tool失败增加次数受限的退避重试，同时拦截参数、权限、资源和业务冲突
等不可重试错误，避免无效放大上游请求。

建议规则：

```text
连接失败：重试
读取超时：重试一次
Java 500：根据 retryable 决定
Java 400/403/404/409：不重试
响应 Schema 错误：不重试
```

| ID   | 任务             | 工时 |
| ---- | -------------- | -: |
| T140 | 定义 RetryPolicy | 2h |
| T141 | 实现指数退避         | 2h |
| T142 | 实现最大重试次数       | 1h |
| T143 | 实现不可重试错误拦截     | 1h |
| T144 | 编写重试次数测试       | 2h |

---

## M1.7 重复调用检测

### 解决的问题

本阶段通过Tool名称和规范化参数生成调用指纹，在单次Run内阻止无意义的相同调用，并保留显式
刷新入口，使Agent循环更可控且仍能按需获取最新业务事实。

| ID   | 任务                       | 主要内容            | 工时 |
| ---- | ------------------------ | --------------- | -: |
| T145 | 生成 Tool Call Fingerprint | Tool 名称和参数 Hash | 2h |
| T146 | 在单次 Run 中保存调用记录          | 内存状态            | 2h |
| T147 | 拦截相同 Tool 和参数            | DUPLICATE_CALL  | 2h |
| T148 | 允许显式强制刷新                 | `force_refresh` | 1h |
| T149 | 编写重复调用测试                 | 相同和不同参数         | 2h |

---

## M1.8 Tool 调试接口

### 解决的问题

本阶段提供仅开发环境启用的内部Tool调用接口，使七个只读Tool可以在尚无Workflow或动态Agent时通过
HTTP和Swagger独立调试，并继续返回标准ToolResult。

内部调试接口：

```text
POST /internal/tools/{tool_name}/invoke
```

| ID | 任务 | 工时 |
|---|---:|
| T150 | 实现 Tool 调试 API | 2h |
| T151 | 限制只在开发环境启用 | 1h |
| T152 | 返回标准 ToolResult | 1h |
| T153 | 添加 Swagger 示例 | 1h |

---

## M1 完整验收

```bash
make test-tools
pytest tests/integration/tools -q
make quality
```

必须满足：

* 所有只读 Tool 可以脱离 Agent 调用；
* Python 不直接访问业务数据库；
* Tool 输入输出全部使用 Pydantic；
* 所有错误有统一错误码；
* 重试和重复调用规则可测试。

---

# 五、M2：确定性订单诊断 Workflow

## 目标

跑通第一条完整业务链路：

```text
ORDER-003 为什么没有交付？
```

本阶段先不使用动态 Agent，由固定 Workflow 保证结果正确。

---

## M2.1 Agent 基础数据表

### 解决的问题

本阶段搭建Agent Session、Message、Run和Step的持久化架构，用于保存会话归属和执行历史，为后续
Workflow可观测性、失败定位与结果追踪提供数据基础。

| ID   | 任务                  | 数据表          | 工时 |
| ---- | ------------------- | ------------ | -: |
| T201 | 创建 `agent_sessions` | 会话信息         | 2h |
| T202 | 创建 `agent_messages` | 用户和助手消息      | 2h |
| T203 | 创建 `agent_runs`     | 单次请求         | 2h |
| T204 | 创建 `agent_steps`    | 执行步骤         | 3h |
| T205 | 创建 Alembic 迁移       | 数据库迁移        | 1h |
| T206 | 创建 Repository       | Run、Step 增删查 | 3h |

---

## M2.2 最小 Run 生命周期

### 解决的问题

本阶段建立整次Agent请求的最小Run状态流转，保存成功结果快照或失败错误位置，并通过数据库条件更新
保护并发终态一致性。

Run 状态：

```text
PENDING
RUNNING
SUCCEEDED
FAILED
WAITING_APPROVAL
CANCELLED
```

| ID | 任务 | 工时 |
|---|---:|
| T207 | 创建 Run | 1h |
| T208 | 将 Run 标记为 RUNNING | 1h |
| T209 | 将 Run 标记为 SUCCEEDED | 1h |
| T210 | 将 Run 标记为 FAILED | 1h |
| T211 | 保存最终结果 | 1h |
| T212 | 保存错误码和错误步骤 | 2h |
| T213 | 编写 Run 状态流转测试 | 2h |

---

## M2.3 最小 Step 记录

### 解决的问题

本阶段记录Run内部各Step的开始、成功和失败状态，以及受控输入输出摘要、错误码与执行耗时，为后续
Workflow节点接线、步骤展示和故障定位提供基础。

Step 类型：

```text
CONTEXT
TOOL
RULE
LLM
```

| ID | 任务 | 工时 |
|---|---:|
| T214 | 实现 Step 开始记录 | 1h |
| T215 | 实现 Step 成功记录 | 1h |
| T216 | 实现 Step 失败记录 | 1h |
| T217 | 保存输入输出摘要 | 2h |
| T218 | 保存执行耗时 | 1h |
| T219 | 自动关联 Run | 1h |
| T220 | 编写 Step 记录测试 | 2h |

注意：不要在日志中保存完整 Token、敏感用户数据或完整业务接口密钥。

---

## M2.4 Workflow 状态模型

### 解决的问题

本阶段定义固定订单诊断节点共享的TypedDict状态通道，并以严格Pydantic Schema表达根因、Tool字段
证据、建议、步骤错误和最终诊断结果，为后续Workflow节点与确定性规则提供稳定数据契约。

```python
class OrderDiagnosisState(TypedDict):
    run_id: str
    order_id: str
    order: OrderDetail | None
    tasks: list[TaskDetail]
    progress: dict[str, ProgressResult]
    quality_issues: dict[str, list[QualityIssue]]
    reviews: dict[str, ReviewResult | None]
    delivery: DeliveryStatus | None
    diagnosis: DiagnosisResult | None
    errors: list[StepError]
```

| ID | 任务 | 工时 |
|---|---:|
| T221 | 定义 Workflow State | 2h |
| T222 | 定义 DiagnosisResult Schema | 2h |
| T223 | 定义 RootCause Schema | 2h |
| T224 | 定义 Evidence Schema | 2h |
| T225 | 定义 Suggestion Schema | 1h |
| T226 | 编写 Schema 校验测试 | 2h |

建议不要只使用字符串数组，而是使用结构化证据：

```json
{
  "source_type": "TOOL",
  "tool_name": "get_quality_issues",
  "field_path": "data[0].status",
  "value": "OPEN",
  "description": "ISSUE-001 尚未关闭"
}
```

---

## M2.5 固定 Workflow 节点

### 解决的问题

本阶段使用LangGraph固定串联上下文和六类业务事实加载节点，将各只读Tool结果按订单、任务归属
合并到共享状态，并在首个标准错误处中断后续调用、记录可定位Step，为M2.6规则判断提供可靠输入。

固定执行流程：

```text
load_context
→ load_order
→ load_tasks
→ load_progress
→ load_quality
→ load_review
→ load_delivery
→ diagnose_by_rules
→ format_result
```

| ID   | 节点任务               | 工时 |
| ---- | ------------------ | -: |
| T227 | 实现 `load_context`  | 2h |
| T228 | 实现 `load_order`    | 2h |
| T229 | 实现 `load_tasks`    | 2h |
| T230 | 实现 `load_progress` | 3h |
| T231 | 实现 `load_quality`  | 3h |
| T232 | 实现 `load_review`   | 3h |
| T233 | 实现 `load_delivery` | 2h |
| T234 | 实现节点间状态合并          | 3h |
| T235 | 实现节点失败中断           | 2h |

---

## M2.6 确定性诊断规则

### 解决的问题

Java接口已经返回订单、任务、生产进度、质检、复核和交付事实后，Python应该如何稳定判断“订单卡在哪个阶段”。

### 示例规则

```text
存在 FAILED/BLOCKED 生产任务
→ PRODUCTION_BLOCKED

生产完成，但存在 OPEN 质检问题
→ QUALITY_REVIEW

质检问题已解决，但复核 PENDING
→ REVIEW

生产、质检、复核完成，但交付失败
→ DELIVERY

所有条件满足
→ NONE
```

| ID | 任务 | 工时 |
|---|---:|
| T236 | 定义阻塞阶段枚举 | 1h |
| T237 | 实现生产阻塞规则 | 2h |
| T238 | 实现质检阻塞规则 | 2h |
| T239 | 实现复核阻塞规则 | 2h |
| T240 | 实现交付阻塞规则 | 2h |
| T241 | 实现无阻塞规则 | 1h |
| T242 | 实现信息不足结果 | 2h |
| T243 | 编写规则参数化测试 | 3h |

---

## M2.7 诊断文案生成

这一阶段可以采用两种方式：

1. 规则直接生成文案；
2. 规则确定业务事实，大模型只负责整理表达。

建议先完成规则文案，再接入模型。

| ID | 任务 | 工时 |
|---|---:|
| T244 | 生成阻塞环节说明 | 2h |
| T245 | 生成根因列表 | 2h |
| T246 | 生成证据列表 | 2h |
| T247 | 生成建议列表 | 2h |
| T248 | 接入结构化模型输出 | 3h |
| T249 | 模型输出 Schema 校验 | 2h |
| T250 | 模型失败回退规则结果 | 2h |

模型不得修改：

* 订单状态；
* 任务状态；
* 问题状态；
* 阻塞阶段；
* 业务 ID；
* 时间和数值。

---

## M2.8 诊断 API

```text
POST /api/agent/order-diagnosis
```

请求：

```json
{
  "order_id": "ORDER-003",
  "user_message": "这个订单为什么还没有交付？"
}
```

| ID | 任务 | 工时 |
|---|---:|
| T251 | 定义请求 Schema | 1h |
| T252 | 定义响应 Schema | 1h |
| T253 | 创建 Run | 1h |
| T254 | 调用固定 Workflow | 2h |
| T255 | 返回诊断结果 | 1h |
| T256 | 处理 Workflow 异常 | 2h |
| T257 | 编写接口集成测试 | 3h |

---

## M2.9 前端 Agent 侧边栏

| ID | 任务 | 工时 |
|---|---:|
| T258 | 创建 Agent 抽屉组件 | 2h |
| T259 | 创建消息输入框 | 2h |
| T260 | 显示当前订单上下文 | 2h |
| T261 | 调用诊断接口 | 2h |
| T262 | 显示加载状态 | 1h |
| T263 | 显示阻塞环节卡片 | 2h |
| T264 | 显示根因列表 | 1h |
| T265 | 显示证据列表 | 2h |
| T266 | 显示处理建议 | 1h |
| T267 | 显示错误结果 | 2h |

---

## M2.10 E2E 测试

| ID   | 场景        | 预期                        |
| ---- | --------- | ------------------------- |
| T268 | ORDER-001 | PRODUCTION                |
| T269 | ORDER-002 | PRODUCTION_BLOCKED        |
| T270 | ORDER-003 | QUALITY_REVIEW            |
| T271 | ORDER-004 | REVIEW                    |
| T272 | ORDER-005 | NONE                      |
| T273 | 订单不存在     | RESOURCE_NOT_FOUND        |
| T274 | Java 超时   | 失败定位到 Tool Step           |
| T275 | Java 字段错误 | RESPONSE_VALIDATION_ERROR |

---

## M2 完整验收

```bash
make test-agent-e2e
pytest tests/e2e/test_order_diagnosis.py -q
```

必须满足：

* ORDER-003 可以完整诊断；
* 业务事实全部来自 Tool；
* 结果符合 Schema；
* 每个 Tool 调用都有 Step；
* 失败能够定位到具体节点；
* 前端已有可演示结果。

---

# 六、M3：页面上下文、会话上下文与路由

## 目标

让用户不必手动输入订单号，并能够完成多轮参数补全。

---

## M3.1 页面上下文

| ID | 任务 | 工时 |
|---|---:|
| T301 | 定义 PageContext Schema | 2h |
| T302 | 定义页面类型枚举 | 1h |
| T303 | 实现订单详情 Context Adapter | 2h |
| T304 | 实现任务详情 Context Adapter | 2h |
| T305 | 实现质检页面 Context Adapter | 2h |
| T306 | 请求时携带页面上下文 | 2h |
| T307 | 服务端重新校验 order_id | 2h |
| T308 | 服务端重新校验用户权限 | 2h |
| T309 | 编写上下文伪造测试 | 2h |

---

## M3.2 会话上下文

会话只保存业务必要信息：

```text
当前订单
当前任务
上一轮意图
已确认实体
候选实体
最近一次诊断 Run
待确认操作
```

| ID | 任务 | 工时 |
|---|---:|
| T310 | 定义 SessionContext | 2h |
| T311 | 创建会话 API | 2h |
| T312 | 保存当前业务对象 | 2h |
| T313 | 保存上一轮意图 | 1h |
| T314 | 保存已确认参数 | 2h |
| T315 | 保存候选对象 | 2h |
| T316 | 会话过期策略 | 2h |
| T317 | 清除会话接口 | 1h |
| T318 | 编写会话继承测试 | 3h |

---

## M3.3 意图定义

第一批意图：

```text
ORDER_QUERY
ORDER_DIAGNOSIS
TASK_TRACKING
SPEC_QA
REVIEW_GENERATION
UNKNOWN
```

| ID | 任务 | 工时 |
|---|---:|
| T319 | 定义 Intent 枚举 | 1h |
| T320 | 定义 RouterResult Schema | 2h |
| T321 | 定义每个意图必填参数 | 2h |
| T322 | 定义意图到 Skill 映射 | 2h |
| T323 | 定义 UNKNOWN 处理方式 | 1h |

---

## M3.4 路由 Prompt

| ID | 任务 | 工时 |
|---|---:|
| T324 | 编写路由 System Prompt | 3h |
| T325 | 注入页面上下文 | 2h |
| T326 | 注入会话上下文 | 2h |
| T327 | 定义 JSON Schema 输出 | 2h |
| T328 | 实现结构化解析 | 2h |
| T329 | 实现 Schema 失败重试一次 | 2h |
| T330 | 实现重试失败回退 UNKNOWN | 1h |

---

## M3.5 参数合并优先级

建议优先级：

```text
用户本轮明确参数
> 用户之前确认的参数
> 当前页面上下文
> 上一轮临时参数
```

模型不能覆盖用户本轮明确输入。

| ID | 任务 | 工时 |
|---|---:|
| T331 | 实现实体提取结果模型 | 2h |
| T332 | 实现参数合并器 | 3h |
| T333 | 实现参数来源标记 | 2h |
| T334 | 实现冲突检测 | 2h |
| T335 | 用户输入覆盖页面上下文 | 2h |
| T336 | 编写参数优先级测试 | 3h |

参数来源示例：

```json
{
  "order_id": {
    "value": "ORDER-003",
    "source": "PAGE_CONTEXT"
  }
}
```

---

## M3.6 置信度和澄清

建议初始规则：

```text
confidence >= 0.85 且参数完整
→ 直接执行

0.60 <= confidence < 0.85
→ 展示候选意图或请求确认

confidence < 0.60
→ 重新澄清

必填参数缺失
→ 请求参数

存在多个候选对象
→ 请求选择
```

| ID | 任务 | 工时 |
|---|---:|
| T337 | 实现置信度分级 | 2h |
| T338 | 实现缺失参数检测 | 2h |
| T339 | 实现澄清问题生成 | 2h |
| T340 | 实现候选任务列表 | 2h |
| T341 | 实现用户选择处理 | 2h |
| T342 | 实现澄清后恢复 Run | 3h |
| T343 | 编写澄清状态测试 | 3h |

---

## M3.7 路由评测数据

至少 60 条，更方便覆盖细分场景。

| 类型     | 数量 |
| ------ | -: |
| 明确意图   | 15 |
| 同义表达   | 10 |
| 页面模糊指代 | 10 |
| 会话模糊指代 |  5 |
| 参数缺失   |  8 |
| 多候选对象  |  5 |
| 意图混淆   |  4 |
| 无关问题   |  3 |

| ID | 任务 | 工时 |
|---|---:|
| T344 | 创建评测数据格式 | 2h |
| T345 | 编写明确意图样本 | 2h |
| T346 | 编写模糊指代样本 | 2h |
| T347 | 编写参数缺失样本 | 2h |
| T348 | 编写多候选样本 | 2h |
| T349 | 编写无关问题样本 | 1h |
| T350 | 实现评测执行器 | 3h |
| T351 | 计算意图准确率 | 2h |
| T352 | 计算参数完整率 | 2h |
| T353 | 输出混淆矩阵 | 2h |
| T354 | 输出失败样本文件 | 2h |

---

## M3 完整验收

```bash
make eval-router
pytest tests/evaluation/test_router_eval.py -q
```

关键用例：

```text
在 ORDER-003 页面：
“这个订单为什么没有交付？”
→ ORDER_DIAGNOSIS + ORDER-003

离开订单页面：
“查一下 ORDER-002”
→ ORDER_QUERY + ORDER-002

“看看这个任务”
当前订单存在多个任务
→ 返回任务候选项

“看看刚才那个”
上一轮已经确认 TASK-003
→ 继承 TASK-003
```

---

# 七、M4：RAG 规范检索

## 目标

实现规范问答和异常诊断中的知识依据引用。

---

## M4.1 文档准备

第一版不追求文档数量，重点是版本和元数据差异。

建议准备：

| 文档类型     | 数量 |
| -------- | -: |
| DOM 产品规范 |  3 |
| 质检规范     |  4 |
| 坐标系统规范   |  2 |
| 复核操作规范   |  2 |
| 交付规范     |  3 |
| 历史失效规范   |  2 |

| ID | 任务 | 工时 |
|---|---:|
| T401 | 建立文档目录规范 | 1h |
| T402 | 准备 DOM 规范 | 2h |
| T403 | 准备坐标系统规范 | 2h |
| T404 | 准备质检规范 | 2h |
| T405 | 准备复核规范 | 2h |
| T406 | 准备交付规范 | 2h |
| T407 | 准备历史失效版本 | 2h |

---

## M4.2 知识库数据模型

| ID | 任务 | 工时 |
|---|---:|
| T408 | 创建 `knowledge_documents` 表 | 2h |
| T409 | 创建 `knowledge_chunks` 表 | 2h |
| T410 | 启用 pgvector | 1h |
| T411 | 增加全文检索字段 | 2h |
| T412 | 定义 DocumentMetadata Schema | 2h |
| T413 | 创建数据库迁移 | 1h |

元数据字段：

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

---

## M4.3 文档解析和分块

| ID | 任务 | 工时 |
|---|---:|
| T414 | 定义统一 DocumentLoader | 2h |
| T415 | 实现 Markdown Loader | 2h |
| T416 | 实现纯文本 Loader | 1h |
| T417 | 实现按标题分块 | 3h |
| T418 | 实现超长章节二次分块 | 2h |
| T419 | 保存章节路径 | 2h |
| T420 | 生成稳定 Chunk ID | 2h |
| T421 | 实现重复文档检测 | 2h |
| T422 | 编写分块测试 | 3h |

第一版不建议急于支持复杂 PDF 解析，优先将演示规范整理为结构化 Markdown。

---

## M4.4 Embedding 入库

| ID | 任务 | 工时 |
|---|---:|
| T423 | 定义 Embedding Provider 接口 | 2h |
| T424 | 实现统一 Provider 配置 | 2h |
| T425 | 实现批量 Embedding | 3h |
| T426 | 实现失败重试 | 2h |
| T427 | 将向量写入 pgvector | 2h |
| T428 | 实现文档重新索引 | 2h |
| T429 | 实现索引版本记录 | 2h |
| T430 | 编写入库测试 | 3h |

---

## M4.5 关键词检索

| ID | 任务 | 工时 |
|---|---:|
| T431 | 构建 PostgreSQL 全文索引 | 2h |
| T432 | 实现关键词检索 Repository | 3h |
| T433 | 实现中文查询预处理 | 2h |
| T434 | 返回关键词分数 | 1h |
| T435 | 编写关键词检索测试 | 2h |

---

## M4.6 向量检索

| ID | 任务 | 工时 |
|---|---:|
| T436 | 实现 Query Embedding | 2h |
| T437 | 实现 pgvector 相似度查询 | 3h |
| T438 | 支持 TopK | 1h |
| T439 | 支持相似度阈值 | 2h |
| T440 | 返回向量分数 | 1h |
| T441 | 编写向量检索测试 | 2h |

---

## M4.7 元数据过滤

| ID | 任务 | 工时 |
|---|---:|
| T442 | 产品类型过滤 | 2h |
| T443 | 卫星类型过滤 | 2h |
| T444 | 文档类型过滤 | 1h |
| T445 | 规范版本过滤 | 2h |
| T446 | 生效时间过滤 | 3h |
| T447 | 权限范围过滤 | 2h |
| T448 | 编写跨产品误召回测试 | 3h |
| T449 | 编写历史规范过滤测试 | 3h |

---

## M4.8 混合检索

建议第一版使用加权融合或 RRF。

| ID | 任务 | 工时 |
|---|---:|
| T450 | 定义 RetrievalResult | 2h |
| T451 | 合并关键词和向量结果 | 3h |
| T452 | 实现结果去重 | 2h |
| T453 | 实现 RRF 或加权融合 | 3h |
| T454 | 实现重复片段合并 | 2h |
| T455 | 支持混合 TopK | 1h |
| T456 | 编写融合排序测试 | 3h |

---

## M4.9 Rerank

| ID | 任务 | 工时 |
|---|---:|
| T457 | 定义 Reranker 接口 | 2h |
| T458 | 实现简单模型重排 | 3h |
| T459 | 实现重排超时降级 | 2h |
| T460 | 实现低相关片段拦截 | 2h |
| T461 | 编写重排前后对比测试 | 3h |

---

## M4.10 引用结构

| ID | 任务 | 工时 |
|---|---:|
| T462 | 定义 Citation Schema | 2h |
| T463 | 返回文档名和版本 | 1h |
| T464 | 返回章节路径 | 1h |
| T465 | 返回 Chunk ID | 1h |
| T466 | 返回相关性分数 | 1h |
| T467 | 前端引用卡片 | 3h |
| T468 | 点击查看引用原文 | 2h |

---

## M4.11 规范问答 Workflow

```text
识别 SPEC_QA
→ 构造检索 Query
→ 合并页面元数据
→ 执行混合检索
→ 重排
→ 判断结果是否充足
→ 生成带引用回答
```

| ID | 任务 | 工时 |
|---|---:|
| T469 | 实现 Query Rewrite | 3h |
| T470 | 实现 Metadata Builder | 2h |
| T471 | 实现 Retrieval 节点 | 3h |
| T472 | 实现相关性检查 | 2h |
| T473 | 实现带引用生成 | 3h |
| T474 | 无结果时安全回答 | 2h |
| T475 | 接入路由 Skill | 2h |
| T476 | 编写规范问答 E2E 测试 | 3h |

---

## M4.12 RAG 评测

准备 50 条标注问题。

| ID | 任务 | 工时 |
|---|---:|
| T477 | 定义 RAG EvalCase | 2h |
| T478 | 标注预期文档 | 3h |
| T479 | 标注预期章节 | 3h |
| T480 | 实现 Hit@5 | 2h |
| T481 | 实现 MRR | 2h |
| T482 | 实现无关片段占比 | 2h |
| T483 | 对比纯向量检索 | 2h |
| T484 | 对比关键词检索 | 2h |
| T485 | 对比混合检索 | 2h |
| T486 | 对比混合检索加重排 | 2h |
| T487 | 输出失败样本 | 2h |

---

## M4 完整验收

```bash
make eval-rag
pytest tests/integration/rag -q
```

关键用例：

* DOM 问题只能优先返回 DOM 规范；
* 当前日期下不返回失效版本；
* 坐标系统问题能够返回对应章节；
* 检索为空时不伪造规范答案；
* 回答中所有引用都能追溯到 Chunk。

---

# 八、M5：动态异常诊断 Agent

## 目标

让 Agent 根据已有信息决定是否继续查询，而不是每次固定调用全部 Tool。

---

## M5.1 Agent State 扩展

| ID | 任务 | 工时 |
|---|---:|
| T501 | 定义 AgentAction 枚举 | 1h |
| T502 | 定义 AgentObservation | 2h |
| T503 | 增加 Tool History | 2h |
| T504 | 增加 Information Gaps | 2h |
| T505 | 增加 Iteration Count | 1h |
| T506 | 增加 Termination Reason | 1h |
| T507 | 编写状态序列化测试 | 2h |

---

## M5.2 动作模型

动作：

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

动作输出：

```json
{
  "action": "QUERY_QUALITY",
  "reason": "生产已完成，需要检查是否存在未关闭质检问题",
  "tool_name": "get_quality_issues",
  "tool_arguments": {
    "task_id": "TASK-003"
  }
}
```

| ID | 任务 | 工时 |
|---|---:|
| T508 | 定义 ActionDecision Schema | 2h |
| T509 | 编写决策 Prompt | 3h |
| T510 | 注入已知事实 | 2h |
| T511 | 注入 Tool 描述 | 2h |
| T512 | 解析结构化动作 | 2h |
| T513 | 非法动作回退 | 2h |
| T514 | 编写动作决策测试 | 3h |

---

## M5.3 LangGraph 动态图

```text
initialize
→ plan_next_action
→ validate_action
→ execute_action
→ save_observation
→ check_completion
→ plan_next_action / finish
```

| ID | 任务 | 工时 |
|---|---:|
| T515 | 创建 LangGraph StateGraph | 2h |
| T516 | 实现初始化节点 | 2h |
| T517 | 实现决策节点 | 3h |
| T518 | 实现动作校验节点 | 2h |
| T519 | 实现 Tool 执行节点 | 3h |
| T520 | 实现 Observation 节点 | 2h |
| T521 | 实现完成判断节点 | 3h |
| T522 | 实现结果生成节点 | 3h |
| T523 | 实现异常结束节点 | 2h |

---

## M5.4 Agent 执行限制

| ID | 任务 | 工时 |
|---|---:|
| T524 | 最大决策轮数 6 | 1h |
| T525 | 最大 Tool 调用数 8 | 1h |
| T526 | 重复 Tool 调用拦截 | 2h |
| T527 | 连续无新增信息终止 | 3h |
| T528 | 写 Tool 黑名单 | 2h |
| T529 | 未知 Tool 拦截 | 1h |
| T530 | Tool 参数权限校验 | 2h |
| T531 | 编写无限循环测试 | 3h |

---

## M5.5 信息充分度判断

不能完全依赖模型主观判断。

需要定义最低信息要求：

### 订单诊断至少需要

```text
订单状态
至少一个关联任务
任务关键状态
交付状态
```

根据状态再要求：

```text
生产异常 → 生产进度
质检异常 → 质检问题
复核异常 → 复核结果
规范判断 → RAG 结果
```

| ID | 任务 | 工时 |
|---|---:|
| T532 | 定义基础必需信息 | 2h |
| T533 | 定义生产场景信息规则 | 2h |
| T534 | 定义质检场景信息规则 | 2h |
| T535 | 定义复核场景信息规则 | 2h |
| T536 | 定义交付场景信息规则 | 2h |
| T537 | 实现 InformationGapDetector | 3h |
| T538 | 编写信息充分度测试 | 3h |

---

## M5.6 动态路径测试

| ID   | 测试订单      | 期望路径              |
| ---- | --------- | ----------------- |
| T539 | ORDER-001 | 订单→任务→进度          |
| T540 | ORDER-002 | 订单→任务→进度          |
| T541 | ORDER-003 | 订单→任务→质检→复核→交付→规范 |
| T542 | ORDER-004 | 订单→任务→复核          |
| T543 | ORDER-005 | 订单→任务→交付          |

额外测试：

| ID   | 场景                    |
| ---- | --------------------- |
| T544 | 相同 Tool 不重复调用         |
| T545 | Tool 超时后有限重试          |
| T546 | 达到最大轮数后结束             |
| T547 | 无新增信息后结束              |
| T548 | Agent 尝试调用写 Tool 被拦截  |
| T549 | 动态结果与固定 Workflow 基线一致 |

---

## M5.7 版本记录

| ID | 任务 | 工时 |
|---|---:|
| T550 | 记录 Router Prompt 版本 | 1h |
| T551 | 记录 Agent Prompt 版本 | 1h |
| T552 | 记录模型名称和参数 | 1h |
| T553 | 记录 Tool Schema 版本 | 1h |
| T554 | 记录 RAG 策略版本 | 1h |
| T555 | Run 关联全部版本 | 2h |

---

## M5 完整验收

```bash
make test-agent-policy
pytest tests/e2e/test_dynamic_agent.py -q
```

必须满足：

* 5 个订单走不同 Tool 路径；
* 不出现无限循环；
* 不重复调用相同 Tool；
* 动态结果与 M2 固定 Workflow 结果一致；
* Agent 永远不会直接执行写操作。

---

# 九、M6：人工确认和业务回写

## 目标

跑通复核意见生成、修改、确认和回写闭环。

---

## M6.1 Approval 数据模型

Approval 状态：

```text
DRAFT
WAITING_CONFIRMATION
CONFIRMED
EXECUTING
SUCCEEDED
FAILED
CANCELLED
EXPIRED
STALE
```

| ID | 任务 | 工时 |
|---|---:|
| T601 | 创建 `approval_records` 表 | 3h |
| T602 | 定义 ApprovalStatus | 1h |
| T603 | 定义 OperationType | 1h |
| T604 | 保存原始草稿 | 2h |
| T605 | 保存用户修改内容 | 2h |
| T606 | 保存待调用 Tool | 2h |
| T607 | 保存目标对象版本 | 2h |
| T608 | 保存确认人和确认时间 | 2h |
| T609 | 编写状态流转测试 | 3h |

---

## M6.2 复核草稿 Schema

```json
{
  "task_id": "TASK-003",
  "conclusion": "REWORK_REQUIRED",
  "problem_summary": "存在未关闭的坐标系质量问题",
  "review_comment": "建议完成坐标系统处理后重新提交复核",
  "specification_references": [],
  "suggested_rework": {
    "required": true,
    "type": "COORDINATE_SYSTEM_FIX"
  }
}
```

| ID | 任务 | 工时 |
|---|---:|
| T610 | 定义 ReviewDraft Schema | 2h |
| T611 | 定义 Conclusion 枚举 | 1h |
| T612 | 定义 ReworkSuggestion | 2h |
| T613 | 校验复核内容长度 | 1h |
| T614 | 校验引用有效性 | 2h |
| T615 | 编写 Schema 测试 | 2h |

---

## M6.3 草稿生成 Workflow

```text
读取最近诊断
→ 查询最新任务和质检问题
→ 检索相关规范
→ 生成结构化草稿
→ 保存 Approval
→ 返回 WAITING_CONFIRMATION
```

| ID | 任务 | 工时 |
|---|---:|
| T616 | 获取最近诊断结果 | 2h |
| T617 | 重新读取业务数据 | 2h |
| T618 | 检索规范依据 | 2h |
| T619 | 生成结构化草稿 | 3h |
| T620 | 草稿 Schema 校验 | 2h |
| T621 | 保存 Approval | 2h |
| T622 | Run 进入 WAITING_APPROVAL | 2h |
| T623 | 编写草稿生成测试 | 3h |

草稿生成阶段，Java 写接口调用次数必须为 0。

---

## M6.4 前端确认卡片

| ID | 任务 | 工时 |
|---|---:|
| T624 | 创建复核草稿卡片 | 3h |
| T625 | 显示影响对象 | 1h |
| T626 | 显示问题摘要 | 1h |
| T627 | 编辑复核意见 | 2h |
| T628 | 编辑复核结论 | 2h |
| T629 | 显示规范引用 | 2h |
| T630 | 确认按钮 | 1h |
| T631 | 取消按钮 | 1h |
| T632 | 二次确认弹窗 | 2h |
| T633 | 防重复点击 | 2h |

---

## M6.5 写 Tool

### `write_review_result`

| ID | 任务 | 工时 |
|---|---:|
| T634 | 定义输入 Schema | 2h |
| T635 | 定义输出 Schema | 2h |
| T636 | 校验 approval_id | 2h |
| T637 | 校验确认用户 | 2h |
| T638 | 透传幂等键 | 2h |
| T639 | 调用 Java 复核接口 | 3h |
| T640 | 保存执行结果 | 2h |
| T641 | 编写正常回写测试 | 3h |

### `create_rework_task`

| ID | 任务 | 工时 |
|---|---:|
| T642 | 定义返工输入 Schema | 2h |
| T643 | 校验返工类型 | 2h |
| T644 | 调用 Java 返工接口 | 3h |
| T645 | 保存新任务 ID | 2h |
| T646 | 编写返工创建测试 | 3h |

---

## M6.6 确认前重新校验

确认时不能直接使用旧数据。

```text
读取 Approval
→ 判断是否过期
→ 检查确认人
→ 重新查询任务
→ 比较业务对象版本
→ 判断状态是否变化
→ 执行写 Tool
```

| ID | 任务 | 工时 |
|---|---:|
| T647 | Approval 有效期检查 | 2h |
| T648 | 目标对象重新查询 | 2h |
| T649 | 版本号比较 | 2h |
| T650 | 状态变化标记 STALE | 2h |
| T651 | 用户权限重新校验 | 2h |
| T652 | 重复提交检查 | 2h |
| T653 | 确认执行状态锁 | 3h |
| T654 | 编写并发确认测试 | 3h |

---

## M6.7 操作日志

| ID | 任务 | 工时 |
|---|---:|
| T655 | 创建 `operation_logs` 表 | 2h |
| T656 | 保存操作前摘要 | 2h |
| T657 | 保存操作后摘要 | 2h |
| T658 | 保存用户修改差异 | 2h |
| T659 | 保存 Java Trace ID | 1h |
| T660 | 创建操作详情接口 | 2h |

---

## M6.8 安全测试

| ID   | 测试场景        | 预期                 |
| ---- | ----------- | ------------------ |
| T661 | 未确认         | Java 写接口调用 0 次     |
| T662 | 正常确认        | 写入成功               |
| T663 | 用户修改后确认     | 提交修改后内容            |
| T664 | 重复点击        | 只执行一次              |
| T665 | 用户取消        | 数据不变               |
| T666 | Approval 过期 | 不执行                |
| T667 | 业务状态已变化     | 标记 STALE           |
| T668 | 用户无权限       | PERMISSION_DENIED  |
| T669 | Java 返回 409 | 显示业务冲突             |
| T670 | Java 返回 500 | Approval 标记 FAILED |

---

## M6 完整验收

```bash
make test-approval
pytest tests/e2e/test_review_approval.py -q
```

必须满足：

* 写操作必须经过真实用户确认；
* 用户可以修改草稿；
* 重复提交不会产生重复数据；
* 业务状态变化后旧草稿不能直接执行；
* 原始草稿、修改内容和执行结果全部可追溯。

---

# 十、M7：Run/Step、SSE、异常注入和统一评测

## 目标

完成项目工程化闭环，让每次执行都可查看、可定位、可复现。

---

## M7.1 Run 完整字段

| ID | 任务 | 工时 |
|---|---:|
| T701 | 增加页面上下文快照 | 2h |
| T702 | 增加 Router 结果 | 2h |
| T703 | 增加模型信息 | 1h |
| T704 | 增加 Prompt 版本 | 1h |
| T705 | 增加 Tool Schema 版本 | 1h |
| T706 | 增加 RAG 策略版本 | 1h |
| T707 | 增加 Token 统计 | 2h |
| T708 | 增加 Tool 调用次数 | 1h |
| T709 | 增加总耗时 | 1h |
| T710 | 增加终止原因 | 1h |

---

## M7.2 Step 完整类型

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

| ID | 任务 | 工时 |
|---|---:|
| T711 | Context Step 记录 | 2h |
| T712 | Router Step 记录 | 2h |
| T713 | Agent 决策 Step 记录 | 2h |
| T714 | Tool Step 记录 | 2h |
| T715 | RAG Step 记录 | 2h |
| T716 | LLM Step 记录 | 2h |
| T717 | Approval Step 记录 | 2h |
| T718 | WriteBack Step 记录 | 2h |
| T719 | 输入输出脱敏 | 3h |
| T720 | 超长内容截断 | 2h |

---

## M7.3 SSE 事件服务

事件：

```text
run_started
context_loaded
intent_detected
clarification_required
agent_action_selected
tool_started
tool_completed
retrieval_started
retrieval_completed
diagnosis_generated
approval_required
writeback_started
writeback_completed
run_completed
run_failed
```

| ID | 任务 | 工时 |
|---|---:|
| T721 | 定义 SSE Event Schema | 2h |
| T722 | 创建 SSE 连接接口 | 3h |
| T723 | 实现 Run 事件发布器 | 3h |
| T724 | 发布 Tool 事件 | 2h |
| T725 | 发布 RAG 事件 | 2h |
| T726 | 发布 Approval 事件 | 2h |
| T727 | 发布完成和失败事件 | 2h |
| T728 | 实现心跳 | 2h |
| T729 | 实现断线清理 | 2h |
| T730 | 编写 SSE 集成测试 | 3h |

---

## M7.4 前端实时步骤展示

| ID | 任务 | 工时 |
|---|---:|
| T731 | 封装 SSE Client | 3h |
| T732 | 实现自动重连 | 2h |
| T733 | 实现步骤时间线 | 3h |
| T734 | 显示 Tool 执行状态 | 2h |
| T735 | 显示 RAG 检索状态 | 2h |
| T736 | 显示人工确认状态 | 2h |
| T737 | 显示失败步骤 | 2h |
| T738 | 显示步骤耗时 | 2h |

---

## M7.5 Run 历史页面

| ID | 任务 | 工时 |
|---|---:|
| T739 | Run 列表 API | 2h |
| T740 | Run 详情 API | 2h |
| T741 | Step 列表 API | 2h |
| T742 | Run 列表页面 | 3h |
| T743 | Run 详情页面 | 3h |
| T744 | Step 时间线 | 3h |
| T745 | Tool 输入输出摘要 | 2h |
| T746 | RAG 引用展示 | 2h |
| T747 | Approval 修改记录展示 | 2h |
| T748 | 错误详情展示 | 2h |

---

## M7.6 异常注入测试

建议准备 24 个固定异常场景，对应简历中的异常定位指标。

### Java 与 Tool 异常

| 编号 | 场景             |
| -- | -------------- |
| 1  | Java 连接失败      |
| 2  | Java 读取超时      |
| 3  | Java 返回 500    |
| 4  | Java 返回 403    |
| 5  | Java 返回 404    |
| 6  | Java 返回 409    |
| 7  | Java 返回错误 JSON |
| 8  | Java 返回字段缺失    |
| 9  | Tool 输入参数错误    |
| 10 | Tool 重复调用      |

### RAG 异常

| 编号 | 场景           |
| -- | ------------ |
| 11 | Embedding 失败 |
| 12 | 向量检索超时       |
| 13 | 关键词检索失败      |
| 14 | Rerank 失败    |
| 15 | 检索结果为空       |
| 16 | 所有片段低于阈值     |

### 模型与 Agent 异常

| 编号 | 场景             |
| -- | -------------- |
| 17 | 模型调用超时         |
| 18 | 模型返回非 JSON     |
| 19 | 模型返回 Schema 错误 |
| 20 | Agent 重复决策     |
| 21 | Agent 达到最大轮数   |

### Approval 与 SSE 异常

| 编号 | 场景          |
| -- | ----------- |
| 22 | Approval 过期 |
| 23 | 写回重复提交      |
| 24 | SSE 客户端中断   |

每个异常测试验证：

```text
是否生成失败 Step
是否记录正确错误码
是否标记可重试
是否返回安全用户提示
是否没有产生错误业务写入
```

---

## M7.7 统一评测框架

评测目录：

```text
evals/
├── router/
├── tools/
├── rag/
├── diagnosis/
├── agent_policy/
├── approval/
└── fault_injection/
```

| ID | 任务 | 工时 |
|---|---:|
| T749 | 创建统一 EvalRunner | 3h |
| T750 | 统一评测结果 Schema | 2h |
| T751 | 运行路由评测 | 2h |
| T752 | 运行 Tool 评测 | 2h |
| T753 | 运行 RAG 评测 | 2h |
| T754 | 运行诊断 E2E | 2h |
| T755 | 运行 Agent 路径评测 | 2h |
| T756 | 运行 Approval 测试 | 2h |
| T757 | 运行异常注入测试 | 3h |
| T758 | 生成 JSON 报告 | 2h |
| T759 | 生成 Markdown 报告 | 3h |
| T760 | 对比两次评测结果 | 3h |

---

## M7.8 指标计算

### 路由指标

```text
意图准确率
参数提取率
参数补全率
澄清触发准确率
错误 Tool 路由率
```

### Tool 指标

```text
参数首次校验通过率
错误修正后成功率
最终有效调用成功率
平均重试次数
重复调用率
```

### RAG 指标

```text
Hit@5
MRR
Top-5 无关片段占比
版本过滤正确率
引用文档正确率
```

### Agent 指标

```text
E2E 成功率
平均 Tool 调用数
无效 Tool 调用率
重复 Tool 调用率
平均诊断耗时
阻塞阶段判断正确率
```

### 观测指标

```text
异常步骤可定位率
错误类型识别准确率
问题排查中位时长
```

---

## M7 完整验收

```bash
make test
make quality
make eval-all
```

必须满足：

* 所有 Run 均有完整步骤记录；
* 失败能定位到具体 Step；
* 前端可以实时展示执行过程；
* 24 个异常场景可以重复运行；
* 评测报告可以对比版本差异；
* 简历数据可以从测试报告追溯。

---

# 十一、开发过程中的公共任务

以下任务不属于某一个里程碑，但应该持续执行。

## 1. 测试数据管理

每新增业务场景时：

1. 增加固定业务数据；
2. 增加数据映射说明；
3. 增加预期诊断结果；
4. 增加数据重置逻辑；
5. 增加 E2E 测试。

## 2. 文档更新

每完成一个任务，更新：

```text
docs/ROADMAP.md
docs/STATUS.md
docs/TEST_REPORT.md
```

## 3. 提交规范

建议 Commit 格式：

```text
feat(tool): implement get_quality_issues
test(router): add ambiguous reference cases
fix(rag): filter expired specifications
docs(status): update M3 progress
```

## 4. 分支规范

```text
main
develop
feature/m0-order-api
feature/m1-tool-quality-issues
feature/m2-order-diagnosis
feature/m4-rag-hybrid-search
```

个人开发也建议保留功能分支，避免 Codex 大范围修改后难以回退。

---

# 十二、建议的前 20 个实际开发任务

不要一开始把整个计划交给 Codex。建议按照下面顺序逐个执行。

```text
1. T001 创建 Monorepo 目录
2. T004 创建 .env.example
3. T005 创建 Docker Compose
4. T007 编写领域模型文档
5. T008 定义业务状态枚举
6. T009 定义 Order 模型
7. T010 定义 ProductionTask 模型
8. T012 定义 QualityIssue 模型
9. T013 定义 ReviewRecord 模型
10. T015 定义 DeliveryRecord 模型
11. T016 建立对象映射
12. T019 创建 ORDER-003 黄金数据
13. T017 创建 ORDER-001 数据
14. T018 创建 ORDER-002 数据
15. T020 创建 ORDER-004 数据
16. T021 创建 ORDER-005 数据
17. T022 创建数据重置脚本
18. T023 创建数据完整性测试
19. T025 实现订单详情接口
20. T026 实现订单任务接口
```

第一批任务完成后，先暂停继续开发并验证：

```bash
make reset-demo
make test-business-data
make test-java-contract
```

---

# 十三、每个任务交给 Codex 的固定模板

````markdown
## 当前里程碑

M1：Python Tool 层

## 任务编号

T137

## 任务名称

实现 get_quality_issues Tool

## 业务背景

订单 ORDER-003 关联 TASK-003，TASK-003 存在一条未关闭的坐标系质量问题 ISSUE-001。

## 本次只实现

1. GetQualityIssuesInput；
2. QualityIssueItem；
3. GetQualityIssuesOutput；
4. get_quality_issues Tool；
5. 对应单元测试和集成测试。

## 不实现

1. 不修改其他 Tool；
2. 不实现 Agent；
3. 不实现 RAG；
4. 不修改 Java 接口契约；
5. 不修改前端页面。

## 输入

```json
{
  "task_id": "TASK-003"
}
````

## 预期输出

```json
{
  "task_id": "TASK-003",
  "issues": [
    {
      "issue_id": "ISSUE-001",
      "type": "COORDINATE_SYSTEM",
      "status": "OPEN"
    }
  ]
}
```

## 异常场景

1. task_id 为空：PARAM_VALIDATION_ERROR；
2. TASK-999：RESOURCE_NOT_FOUND；
3. Java 超时：TOOL_TIMEOUT；
4. Java 返回字段缺失：RESPONSE_VALIDATION_ERROR；
5. 用户无权限：PERMISSION_DENIED。

## 测试命令

```bash
pytest tests/unit/tools/test_get_quality_issues.py -q
pytest tests/integration/tools/test_get_quality_issues.py -q
ruff check .
mypy app
```

## 完成标准

1. 所有测试通过；
2. Ruff 通过；
3. mypy 通过；
4. 不修改任务范围外代码；
5. 更新 docs/STATUS.md；
6. 输出修改文件清单和测试结果。

````

---

# 十四、阶段停止线

每个阶段达到停止线后，先演示和测试，不要立即继续扩展。

## M0 停止线

```text
ORDER-003 可以通过 Java 接口查询完整数据。
````

## M1 停止线

```text
所有只读 Tool 可以通过 pytest 独立调用。
```

## M2 停止线

```text
ORDER-003 可以在前端完成一次完整诊断。
```

## M3 停止线

```text
用户输入“这个订单为什么没交付”能够自动使用页面 order_id。
```

## M4 停止线

```text
诊断结果能够引用正确版本的坐标系统规范。
```

## M5 停止线

```text
ORDER-001～005 可以走不同 Tool 路径且结果正确。
```

## M6 停止线

```text
复核草稿未经确认绝不写入，确认后只写入一次。
```

## M7 停止线

```text
24 个异常场景均有 Run/Step 记录，至少 23 个可直接定位失败步骤。
```

---

# 十五、时间不足时的裁剪顺序

## 必须保留

```text
M0 业务数据和 Java 接口
M1 Python Tool
M2 确定性诊断
M3 页面上下文和路由
M4 基础 RAG
M6 人工确认回写
M7 最小 Run/Step
```

## 可以弱化

```text
M5 动态 Agent：
只对 ORDER-002、ORDER-003 实现动态路径

M4 Rerank：
先使用简单分数融合

M7 SSE：
只展示核心事件

M7 运行详情页面：
先展示 Step 时间线，不做复杂筛选
```

## 可以暂不开发

```text
Redis 分布式锁
复杂模型 Provider 管理页面
多 Agent
复杂 RBAC 后台
多级审批流
Kubernetes
Prometheus
Grafana
消息队列
多模态影像分析
```

---

# 十六、最终开发顺序

```text
第一步：固定业务数据
第二步：Java 查询和写接口
第三步：Python HTTP Client
第四步：只读 Tool
第五步：ORDER-003 固定诊断 Workflow
第六步：最小 Run/Step
第七步：Agent 前端侧边栏
第八步：页面上下文
第九步：意图识别和澄清
第十步：RAG 文档入库
第十一步：混合检索和引用
第十二步：动态诊断 Agent
第十三步：复核草稿生成
第十四步：人工确认
第十五步：安全业务回写
第十六步：完整 Run/Step 和 SSE
第十七步：异常注入
第十八步：统一评测
第十九步：根据真实测试结果更新简历数据
```

核心开发原则：

> 每次只完成一个可以测试的小任务；每个里程碑先形成一条可运行链路，再扩展更多能力；任何业务事实必须来自 Java Tool，任何规范结论必须来自 RAG，任何写操作必须经过人工确认。
