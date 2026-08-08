# 测试报告

## M0.1 项目基础环境

- 验证时间：2026-07-26
- `make help`：通过，显示 13 个根级开发命令
- `docker compose config`：通过，PostgreSQL、Java、Python、Web 四项服务配置有效
- `make test`：通过
  - 必需目录、文件和环境变量检查：1 组通过
  - Agent Service 健康检查：通过
  - Business Service 健康检查：通过（本机无 JDK，使用 Docker）
  - Web Console 健康检查：通过
- `docker compose up --detach --build`：通过
  - PostgreSQL：`healthy`
  - Java/Python/Web：容器均为 `Up`
  - 三个 HTTP `/health`：均返回 `status=UP`
- 环境切换检查：通过，自定义 PostgreSQL、Java、Python、Web 四个宿主端口均由环境变量正确展开
- 静态语法检查：
  - `python3 -m py_compile agent-service/app/main.py`：通过
  - `node --check web-console/server.mjs`：通过
  - `git diff --check`：通过
- 开发中失败与修复：首次 `make test` 因 macOS `/usr/bin/java` 占位程序被误认为有效 JDK 而失败；改为实际执行 `java -version`/`javac -version` 后回退到 Docker，完整复测通过
- 业务测试：不适用（M0.1 尚无业务逻辑）

## 开发环境维护 ENV-001

- 验证时间：2026-07-26
- `brew list --versions openjdk@21`：通过，版本 `21.0.12`
- OpenJDK `java -version`：通过，版本 `21.0.12`
- OpenJDK `javac -version`：通过，版本 `21.0.12`
- `brew doctor`：通过
- 登录 Shell：通过，`JAVA_HOME`、`java` 和 `javac` 均指向 Homebrew OpenJDK 21
- `make test`：通过，Java 使用本机 JDK 完成冒烟测试，未使用 Docker 回退

## 项目治理 DOC-002

- 验证时间：2026-07-26
- 代码解释规则存在性检查：通过
- 精确行号与绝对路径要求检查：通过
- `AGENTS.md`、`doc/record.md` Markdown 代码围栏检查：通过
- `git diff --check`：通过
- 业务测试：不适用（仅修改开发治理文档）

## M0.2 业务领域模型设计

- 验证时间：2026-07-30
- 运行环境：OpenJDK 21.0.12、Maven 3.9.16、Docker Desktop 29.6.2、PostgreSQL 16
- `mvn --file business-service/pom.xml test`：通过，8/8
  - `BusinessStatusEnumTest`：1/1，五组跨服务状态词汇与计划完全一致
  - `DomainModelValidationTest`：5/5，覆盖 DTO 空 ID、步骤非法序号、聚合子对象重挂及返工跨任务引用的两种调用顺序
  - `DomainRepositoryIntegrationTest`：1/1，在 Testcontainers PostgreSQL 上写入、清空持久化上下文并逐级查询 `ORDER-003 → TASK-003 → ISSUE-001 → REVIEW-003 → DELIVERY-003`
  - `BusinessServiceApplicationIntegrationTest`：1/1，真实启动 Spring Web、执行 Flyway 并验证 `/health`
- `make test`：通过
  - M0.1/M0.2 文件与环境配置检查：通过
  - Docker Compose 配置：通过
  - Agent、Business、Web 三项冒烟：通过
  - 领域测试：7/7；Business 启动测试已在冒烟阶段单独通过 1/1
- `mvn --file business-service/pom.xml --define skipTests package`：通过，生成可执行 Spring Boot JAR
- `docker compose up --detach --build`：通过，四个服务均为 `Up`，PostgreSQL 为 `healthy`
- 容器端点：Agent、Business、Web 三个 `/health` 均通过
- 容器数据库：
  - Flyway `V1__create_business_domain.sql`：版本 `1`，`success=true`
  - 七张领域表：全部存在
- 开发中失败与修复：
  - 首次测试按测试先行预期失败：68 个编译错误，证明实体、枚举和 Repository 尚未实现；实现后消除
  - 首次应用集成测试：3 个测试中 1 个错误，缺少 Web 运行时类；补充 `spring-boot-starter-web` 后通过
  - 首次容器构建：`dependency:go-offline` 解析无关插件和云平台依赖，耗时过长后主动终止；改为直接执行跳过测试的 `package`，镜像成功构建
- 最终失败：0
- 未运行：Java 业务 HTTP 契约测试和固定数据重置测试；M0.2 尚无业务端点，固定数据属于 M0.3

## M0.3 固定业务数据

- 验证时间：2026-07-30
- 运行环境：OpenJDK 21.0.12、Maven 3.9.16、Docker Desktop 29.6.2、PostgreSQL 16
- `mvn --file business-service/pom.xml clean test`：通过，15/15
  - M0.3 数据映射与黄金链路：4/4
  - M0.3 业务状态非法组合：3/3
  - 应用启动、M0.2 枚举、模型约束和 Repository 回归：8/8
- `make test-business-data`：通过，7/7
  - 固定规模：5 个订单、5 个任务、5 个步骤、3 个质检问题、3 个复核记录、0 个返工任务、5 个交付记录
  - `ORDER-002` 失败步骤固定为“影像预处理”
  - `ORDER-003 → TASK-003 → ISSUE-001 → REVIEW-003 → DELIVERY-003` 黄金链路通过
  - 五组数据均通过跨对象业务状态校验
- `make test-business-domain`：通过，7/7，M0.2 领域模型没有回归
- `make reset-demo`：连续两次通过
  - 两次均恢复 `orders=5`
  - 两次数据快照均为 `d57e54c32e4ef26eb01c76a8ed97a0ce`
- `make validate`：通过，基础文件与 Docker Compose 配置有效
- `make smoke`：通过，Agent、Business、Web 三项健康检查均通过
- `make test`：通过，基础检查、三服务冒烟、M0.2 回归 7/7 和 M0.3 数据测试 7/7 全部通过
- `sh -n scripts/reset-demo`、`git diff --check`：通过，Shell 语法和变更空白检查无错误
- 开发中失败与修复：
  - 测试先行首次运行固定数据测试：3 个测试中 1 个失败、2 个错误；原因是数据库尚无 V2 数据，加入迁移后 3/3 通过
  - 状态校验测试首次编译：7 个缺失类型错误；实现校验器后 3/3 通过
  - 首次 Maven 全量测试：15 个测试中 1 个失败、4 个错误；旧 Repository 测试修改固定 ID，且增至多个 DataJpa 测试后 Spring 复用了已停止容器的数据源
  - 修复方式：Repository 测试改用独立 `*-MODEL-TEST` ID；Testcontainers 支持改为 JVM 共享 PostgreSQL 容器；最终 15/15 通过
- 最终失败：0
- 未运行：M0.4 Java 业务 HTTP 契约测试；查询端点尚未实现
- 已知非阻塞问题：Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告；当前测试结果不受影响
- 下一建议任务：`T025` 实现订单详情查询及 404 契约

## Agent 面试关注点治理 DOC-003

- 验证时间：2026-07-30
- `needCare.md` 结构与范围检查：通过
  - 历史内容只保留 M0.1 服务边界、M0.2 事实契约、M0.3 确定性评测基线
  - 三个条目均包含面试价值、Agent 关联、可能问题和禁止过度声称的能力
  - 未包含环境安装或历史治理任务条目
- `AGENTS.md` 门禁检查：通过
  - 已包含“先评估、有价值才记录”
  - 已禁止制造空条目和把规划描述为已实现
  - 已要求最终回复说明本次是否产生新的 Agent 面试关注点
- Markdown 代码围栏检查：通过，`AGENTS.md`、`doc/needCare.md` 与 `doc/record.md` 围栏数量均为偶数
- 开发中检查脚本修正：首次扩展到 `doc/record.md` 时只匹配行首围栏，未识别模板内的缩进围栏而返回非零；改为允许前导空白后完整检查通过，文档内容无需修复
- `make validate`：通过，基础文件和 Docker Compose 配置有效
- `git diff --check`：通过，无空白错误
- 业务测试：未运行；本次只修改治理和面试准备文档，不改变运行时代码、接口或数据

## M0.4 Java 查询接口

- 验证时间：2026-07-30
- 运行环境：OpenJDK 21.0.12、Maven 3.9.16、Docker Desktop 29.6.2、PostgreSQL 16
- `mvn --file business-service/pom.xml clean test`：通过，28/28
  - M0.4 Java HTTP 查询契约：13/13
  - M0.3 固定数据与状态校验：7/7
  - 应用启动、M0.2 枚举、模型约束和 Repository 回归：8/8
- `make test`：通过
  - 基础文件和 Docker Compose 配置检查：通过
  - Agent、Business、Web 三服务冒烟：通过
  - M0.2 领域测试：7/7
  - M0.3 数据测试：7/7
  - M0.4 查询契约测试：13/13
- M0.4 契约覆盖：
  - 订单详情、关联任务、任务详情、生产进度、质检问题、复核记录、交付状态和订单总览 8 个端点
  - 未知订单/任务 `404`，非法质检状态过滤 `400`
  - 父资源存在但关联数据为空时返回 `200` 与空数组
  - 多生产步骤按 `sequenceNumber` 升序
  - `OPEN`/`CLOSED` 质检问题过滤
  - `ORDER-003` 聚合链路和 `ORDER-005` 可交付状态
- 开发中失败与修复：
  - 测试先行首次运行：13 个测试中 9 个失败、4 个通过；失败原因均为查询端点尚未实现，4 个未知资源用例因路径不存在而返回 `404`
  - 完成 Controller、只读查询服务、响应 Schema 和 Repository 查询后：13/13 通过
- 最终失败：0
- 未运行：M0.5 写接口、权限、幂等和并发测试；对应运行时代码尚未实现
- 已知非阻塞问题：
  - Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告，当前结果不受影响
  - M0.4 只稳定 HTTP 状态码，统一错误体、业务错误码和 Trace ID 留到 M0.6

## M0.5 Java 写接口

- 验证时间：2026-07-31
- 运行环境：OpenJDK 21.0.12、Maven 3.9.16、Docker Desktop 29.6.2、PostgreSQL 16
- `mvn --file business-service/pom.xml clean test`：通过，40/40
  - M0.5 写接口：12/12
  - M0.4 查询契约：13/13
  - M0.3 固定数据与状态校验：7/7
  - 应用启动、M0.2 枚举、模型约束和 Repository 回归：8/8
- `make test`：通过
  - 基础文件、Docker Compose 配置和三个服务冒烟：通过
  - M0.2 领域测试：7/7
  - M0.3 数据测试：7/7
  - M0.4 查询契约：13/13
  - M0.5 权限、状态、幂等、并发和审计：12/12
- M0.5 契约覆盖：
  - `POST /api/tasks/{id}/review` 成功写入、角色拒绝、任务/问题状态冲突和资源不存在
  - `POST /api/tasks/{id}/rework` 成功写入、关闭/跨任务问题拒绝和活动返工防重
  - 缺失幂等键 `400`，相同键相同请求只写一次，相同键不同请求 `409`
  - 过期版本 `409`；两个并发请求使用同一版本时恰好一个 `200`、一个 `409`
  - 成功操作记录前后版本、业务字段和操作者；幂等重放不重复记录
  - 测试结束恢复固定数据，写测试与查询测试联合运行 25/25，顺序无关
- 开发中失败与修复：
  - 测试先行首次运行：11 个测试全部报错，首个证据是 `operation_logs` 表不存在；随后实现 V3、接口和事务逻辑
  - V3 首次使用 `CHAR(64)` 与 Hibernate `VARCHAR(64)` 映射不一致，应用启动失败；迁移改为 `VARCHAR(64)` 后通过结构校验
  - 首次级联写入同时显式 `save` 子实体触发同一 ID 的重复托管异常；移除显式保存，由聚合级联持久化
  - JPA `OPTIMISTIC_FORCE_INCREMENT` 将版本递增推迟到事务提交，造成响应版本仍为 `0` 且并发失败返回 `500`；改为带期望版本条件的原子更新后，12/12 通过
  - 写/查询契约联合运行首次为 25 个测试中 1 个失败，原因是写测试残留任务版本；增加测试后清理后 25/25 通过
- 最终失败：0
- 未运行：M0.6 统一错误体/Trace ID、Python Tool、Approval 和 Agent E2E；对应运行时代码尚未实现
- 已知非阻塞问题：
  - `X-User-Id`/`X-User-Role` 尚未连接真实认证来源，不能作为生产级鉴权方案
  - 幂等记录尚无 TTL/归档清理策略；当前适合固定演示规模
  - Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告，当前结果不受影响

## M0.6 Java 统一异常

- 验证时间：2026-07-31
- 运行环境：OpenJDK 21.0.12、Maven 3.9.16、Docker Desktop 29.6.2、PostgreSQL 16
- 测试先行基线：`mvn --file business-service/pom.xml -Dtest=ApiExceptionHandlingIntegrationTest,BusinessQueryApiIntegrationTest,BusinessWriteApiIntegrationTest test` 共 31 个用例，16 个失败、15 个通过；失败证明成功信封、统一错误体、Trace ID 及缺失身份的 401 语义尚未实现
- 实现后定向回归：同一命令扩充为 33 个用例，33/33 通过
  - M0.6 统一响应、错误与 Trace ID：8/8
  - M0.4 查询契约：13/13
  - M0.5 写入契约：12/12
- `mvn --file business-service/pom.xml clean test`：通过，48/48，失败 0、错误 0、跳过 0
- `make test`：通过
  - 基础文件和 Docker Compose 配置检查：通过
  - Agent、Business、Web 三服务冒烟：通过
  - M0.2 领域测试：7/7
  - M0.3 数据测试：7/7
  - M0.4 查询契约：13/13
  - M0.5 写入契约：12/12
  - M0.6 异常契约：8/8
- M0.6 契约覆盖：
  - 成功响应包装，以及来访 Trace ID 的 Header/响应体一致透传
  - 非法枚举、Bean Validation 和畸形 JSON 映射为 `400/PARAM_VALIDATION_ERROR`
  - 缺少用户身份映射为 `401/PERMISSION_DENIED`，角色不足映射为 `403/PERMISSION_DENIED`
  - 未知业务资源映射为 `404/RESOURCE_NOT_FOUND`
  - 版本冲突映射为 `409/BUSINESS_CONFLICT`
  - 未预期异常映射为 `500/INTERNAL_SERVER_ERROR`，不泄露内部异常详情且不建议自动重试
  - 缺失或非法 Trace ID 自动替换为安全的 `trace-<uuid>`
- 开发中发现并修复：API 契约文档的总览 JSON 示例存在尾逗号，已移除，不影响运行时代码
- 最终失败：0
- 未运行：M0.7 延迟/500/畸形响应故障模拟、Python Tool、Approval 和 Agent E2E；对应运行时代码尚未实现
- 已知非阻塞问题：
  - 500 用例会在测试日志中输出预期堆栈，用于验证服务端保留诊断证据；客户端响应不包含敏感详情
  - `X-User-Id`/`X-User-Role` 尚未连接真实认证来源，401/403 只验证 Java 接口语义，不等同生产级认证授权
  - Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告，当前结果不受影响

## M0.7 故障模拟

- 验证时间：2026-07-31
- 运行环境：OpenJDK 21.0.12、Maven 3.9.16、Docker Desktop 29.6.2、PostgreSQL 16
- 测试先行基线：`mvn --file business-service/pom.xml -Dtest=DemoFaultSimulationIntegrationTest,DemoFaultDisabledIntegrationTest test` 共 7 个用例，6 个失败、1 个通过；仅默认关闭保护通过，其余请求均返回正常 200，证明故障能力尚未实现
- M0.7 独立验收：同一命令扩充为 8 个用例，8/8 通过
- M0.4～M0.7 联合回归：41/41 通过
- `mvn --file business-service/pom.xml clean test`：通过，56/56，失败 0、错误 0、跳过 0
- `make test`：通过
  - 基础检查、Docker Compose 配置和三服务冒烟：通过
  - M0.2 领域测试：7/7
  - M0.3 数据测试：7/7
  - M0.4 查询契约：13/13
  - M0.5 写入契约：12/12
  - M0.6 异常契约：8/8
  - M0.7 故障模拟：8/8
- M0.7 覆盖：
  - 指定延迟达到下限，超过配置上限返回统一 400
  - Java `HttpClient` 80 毫秒请求超时可由 300 毫秒服务端延迟稳定触发
  - 模拟 500 和 403 沿用统一信封及调用方 Trace ID
  - 模拟非法响应保持 HTTP 200/合法 JSON，但故意缺失 `data`
  - 未知故障类型返回统一 400
  - 功能关闭时即使收到模拟 Header 也正常响应
  - 功能开启时 POST 写请求仍忽略模拟 Header，并继续执行原有身份门禁
- 最终失败：0
- 未运行：M0.8 前端、Python HTTP Client/Tool、Tool 超时重试和 Agent E2E；对应运行时代码尚未实现
- 已知非阻塞问题：
  - 500 模拟会按 M0.6 设计输出预期服务端堆栈；客户端仍只得到安全错误体
  - 延迟通过阻塞 Servlet 线程实现，仅适合小规模受控故障测试，不代表生产超时实现
  - Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告，当前结果不受影响

## M0.8 最小前端业务页面

- 验证时间：2026-07-31
- 运行环境：Node.js 22.22.2、npm 10.9.7、Vue 3.5.40、Vite 8.2.0、TypeScript 6.0.3、Docker Desktop 29.6.2
- 测试先行基线：首次 `npm test` 的 3 个测试套件均失败，原因是 API Client、Store、页面组件尚未实现；生产服务测试新增后因 `createWebServer` 不存在而 1/1 失败
- `make test-web`：通过
  - Vitest：4 个测试文件、7/7 用例通过
  - API Client：成功信封解包、统一错误转换、缺少 `data` 的响应校验
  - Pinia Store：固定五单加载、默认 `ORDER-003`、快速切换只接受最后请求
  - 页面：五个订单、黄金链路质检/复核/交付信息及 `ORDER-005` 切换
  - 生产服务：`/health`、SPA 回退和 `/business-api` Java 代理
  - `vue-tsc --noEmit` 与 Vite 构建：通过
- 生产构建产物：CSS 49.57 kB（gzip 8.34 kB），JavaScript 185.03 kB（gzip 69.95 kB），无大包告警
- `npm audit` 与 `npm audit --omit=dev`：均通过，0 个已知漏洞
- `docker compose config --quiet && docker compose build web-console`：通过；多阶段镜像执行 `npm ci`、类型检查和生产构建成功
- 真实容器验收：Web `/health` 通过；同源代理可查询 `ORDER-001`～`ORDER-005`；`ORDER-003` 总览包含 `TASK-003`、`ISSUE-001`、`COORDINATE_SYSTEM`、`PENDING` 和 `BLOCKED`
- `make test`：通过
  - 基础检查、Docker Compose 配置和三服务冒烟：通过
  - M0.2 领域测试：7/7
  - M0.3 数据测试：7/7
  - M0.4 查询契约：13/13
  - M0.5 写入契约：12/12
  - M0.6 异常契约：8/8
  - M0.7 故障模拟：8/8
  - M0.8 前端：7/7，生产构建通过
- 开发中发现并修复：TypeScript 7 已移除 `vue-tsc` 使用的内部导出，类型检查失败；将 TypeScript 固定为 6.0.3 后恢复。最初的测试工具依赖链报告 6 个开发期高危漏洞，改用 Vue 原生挂载测试并移除该依赖后审计为 0
- 最终失败：0
- 未运行：`make reset-demo` 会删除本地持久卷，未在未获单独授权时执行；当前环境没有可用浏览器实例，未运行截图与人工视觉回归；M1 Python Tool 和 Agent E2E 尚未实现
- 已知非阻塞问题：页面当前没有端到端浏览器测试，视觉和移动端布局只有 CSS 响应式规则与 jsdom 组件测试支撑；页面不含 Agent 对话、SSE、RAG、Approval 或写操作，这是 M0.8 的有意范围边界

## M0.8 云端蓝灰视觉改版

- 验证时间：2026-07-31
- 测试先行基线：`npm test -- --run src/App.spec.ts` 为 1 个测试、1 个失败；旧页面缺少“固定演示订单”“订单概览”“生产执行”“质量控制”“成果交付”中文区块标识
- 定向复测：同一命令 1/1 通过
- `make test-web`：通过
  - Vitest：4 个测试文件、7/7 用例通过
  - `vue-tsc --noEmit` 与 Vite 生产构建：通过
  - 生产构建产物：CSS 51.77 kB（gzip 8.61 kB），JavaScript 185.04 kB（gzip 69.92 kB）
- `npm --prefix web-console audit --omit=dev`：通过，0 个已知漏洞
- `node --check web-console/server.mjs`：通过
- 静态视觉规则检查：旧英文眉题、旧墨绿色值和 8～10px 字号均无匹配；1000px、720px 响应式断点保留
- 最终失败：0
- 未运行：Java 测试未重复运行，因为本次未修改 Java、API、DTO、Store 或业务状态映射；应用内浏览器列表重试后仍为空，未完成真实桌面/移动端截图和像素视觉验收
- 已知非阻塞问题：真实浏览器视觉验收仍是证据缺口；当前以 jsdom 组件回归、CSS 静态检查、TypeScript 检查和生产构建作为阶段性替代，不把这些证据表述为像素级视觉通过

## M1.1 Python 工程初始化

- 验证时间：2026-07-31
- 运行环境：uv 0.12.0、uv 管理的 CPython 3.12.13、FastAPI 0.141.1、Pydantic 2.13.4、SQLAlchemy 2.0.51、Alembic 1.18.5、pytest 9.1.1、Ruff 0.16.1、mypy 1.20.2
- 测试先行基线：`uv lock && uv run --frozen pytest -q` 在收集阶段产生 3 个导入错误，目标 `app.database`、`app.observability` 和 FastAPI 应用工厂尚不存在
- 首轮实现：pytest 6 个测试中 5 个通过、1 个失败；Alembic 会把 `%(here)s` 自动展开为绝对路径，测试仍比较未展开文本。修正后 6/6
- `make test-agent-foundation`：通过，pytest 6/6
  - FastAPI 健康检查保留安全 Trace ID、替换非法 Trace ID：2/2
  - PostgreSQL URL 转 asyncpg、异步 Session Factory：2/2
  - JSON 日志字段和 Trace 上下文：1/1
  - Alembic 路径与模板：1/1
- `make quality`：通过
  - Ruff：全部通过
  - mypy strict：9 个源/测试文件无问题
- `uv lock --check`：通过，共解析 42 个直接及传递依赖；`uv run --frozen python --version` 为 Python 3.12.13
- `docker compose build agent-service && docker compose up --detach agent-service`：通过；生产镜像使用锁文件安装 26 个非开发依赖并成功启动
- 容器 HTTP 验收：`GET /health` 返回 `200` 和 `{"service":"agent-service","status":"UP"}`，响应 `X-Trace-Id=trace-m11-container`
- 容器日志验收：同一请求输出 JSON，包含 `trace_id`、`method=GET`、`path=/health`、`status_code=200` 和 `duration_ms`
- `docker compose exec -T agent-service /service/.venv/bin/alembic current`：通过；当前尚无 Agent 表迁移，因此没有 revision 输出或数据变更
- `make agent-migrate`：通过；在 Compose 网络内执行 `upgrade head`，创建独立空版本表 `agent_alembic_version`，未创建或修改业务表
- 迁移后 `make test-business-data`：通过，Java 固定数据与状态一致性 7/7，无业务数据回归
- `make smoke`：Agent、Business、Web 三项健康检查通过
- `make test`：通过；基础/Compose、三服务冒烟、Python M1.1 6/6、Java M0 56/56、Web 7/7 和生产构建全部通过
- 最终失败：0
- 未运行：没有运行 Python Tool/Java Client 测试，因为 T109 以后尚未实现；M1.1 尚无 Run/Step 等 Agent 业务表 revision
- 已知非阻塞问题：宿主机 `127.0.0.1:5432` 同时存在本机 PostgreSQL，直接运行 Alembic 会连到错误实例并报角色不存在；根级迁移命令改为在 Compose 容器内执行。开发 Compose 尚未为 Agent 数据配置独立数据库角色；健康检查当前只验证进程存活

## M1.2 Java HTTP Client

- 验证时间：2026-08-01
- 测试先行基线：`uv run --frozen pytest -q tests/test_business_client.py` 在收集阶段因
  `app.clients` 尚不存在产生 1 个导入错误
- 首轮实现：10 个测试中 8 个通过、2 个失败；失败原因是宿主机 SOCKS 代理被 httpx 默认
  继承，而生产依赖未安装 SOCKS 扩展。内部服务 Client 改为 `trust_env=False` 后 10/10
- `make test-agent-foundation`：M1.1 回归 6/6
- `make test-agent-client`：M1.2 10/10
  - Base URL 和 connect/read/write/pool 超时校验：通过
  - FastAPI 生命周期创建/关闭共享 Client：通过
  - GET/POST、身份/Token/Trace/幂等键 Header：通过
  - 正常 JSON、缺少 data、业务 data 缺字段、非法 JSON、Trace 不一致：通过
  - `httpx.ReadTimeout` 保留给 M1.3 映射：通过
- `make quality`：Ruff 全部通过；mypy strict 检查 14 个源/测试文件无问题
- `uv lock --check`：通过，共解析 42 个直接及传递依赖；httpx 已从开发依赖转为生产依赖
- `docker compose up --detach --build business-service agent-service`：两个生产镜像构建并启动成功；Agent 镜像安装 29 个非开发依赖
- 真实容器 Client 验收：通过；Python Client 调用 Java `GET /api/orders/ORDER-003`，返回
  `ORDER-003 QUALITY_CHECKING trace-m12-real`，响应信封、data Schema 和 Trace 一致性均通过
- `make smoke`：Agent、Business、Web 健康检查通过
- `make test`：通过；Python 16/16、Java M0 56/56、Web 7/7 和生产构建全部通过
- 最终失败：0
- 未运行：未运行 M1.3 Tool 错误映射、M1.5 具体 Tool 或 M1.6 自动重试测试，对应功能尚未实现
- 已知非阻塞问题：HTTP 状态、超时和 Client 响应校验异常仍是底层异常；当前仅验证成功
  `ORDER-003` 真实链路，故障路径由 MockTransport 覆盖；Java 测试仍输出 Mockito 动态 Agent
  的未来 JDK 兼容警告

## M1.3 标准错误模型

- 验证时间：2026-08-03
- 测试先行基线：`uv run --frozen pytest -q tests/test_tool_errors.py tests/test_business_client.py`
  在收集阶段产生 2 个导入错误，目标 `app.errors` 尚不存在
- `make test-agent-errors`：18/18
  - 9 个 `ToolErrorCode` 词汇及 `ToolException` 结构：通过
  - Java 400/401/403/404/409/500 参数化映射：6/6
  - connect/read/write/pool 四类 timeout → `TOOL_TIMEOUT`：4/4，且没有提前实现重试
  - 网络不可达 → `UPSTREAM_UNAVAILABLE`，固定安全文案且保留异常因果链：通过
  - 非法 JSON、缺少 data、端点 data 缺字段、HTTP/code 不匹配和 Trace 不匹配 →
    `RESPONSE_VALIDATION_ERROR`：5/5
- `make test-agent-client`：M1.2 回归 10/10；原始 timeout/响应校验断言已更新为标准错误契约
- `make test-agent-foundation`：M1.1 回归 6/6
- Python 汇总：34/34
- `make quality`：Ruff 全部通过；mypy strict 检查 16 个源/测试文件无问题
- `uv lock --check`：通过，共解析 42 个直接及传递依赖
- 真实 Java 故障链路：6/6
  - 400 → `PARAM_VALIDATION_ERROR`
  - 403 → `PERMISSION_DENIED`
  - 404 → `RESOURCE_NOT_FOUND`
  - 500 → `UPSTREAM_UNAVAILABLE`
  - Java 延迟超过 Python read timeout → `TOOL_TIMEOUT`
  - HTTP 200 缺少 data → `RESPONSE_VALIDATION_ERROR`
- `make test`：通过；foundation/Compose、三服务 smoke、Python 34/34、Java M0 56/56、
  Web 7/7 和生产构建全部通过
- `docker compose up --detach --build agent-service && make smoke`：Agent 与依赖的 Java 生产
  镜像构建成功、容器重建成功，三服务 smoke 通过
- 生产容器导入验收：`ToolErrorCode.TOOL_TIMEOUT` 输出 `TOOL_TIMEOUT`
- `make validate`、Markdown code fence 结构检查和 `git diff --check`：通过
- 最终失败：0
- 开发中发现并修复：一次 Python 汇总命令误在仓库根目录执行，uv 找不到 pytest；切换到
  `agent-service` 后通过。首次 Ruff 检查发现既有中文注释标点和新类型别名写法不符合规则，
  改为 ASCII 标点和 Python 3.12 `type` 语法后通过
- 未运行：`make reset-demo` 会删除本地持久卷，本次没有修改固定数据且未获删除授权；没有运行
  M1.4 Tool 协议、M1.6 自动重试或 Agent E2E 测试，对应功能尚未实现
- 已知非阻塞问题：错误已完成分类但尚无 ToolResult/Run/Step 持久化；网络错误的
  `retryable=true` 不代表写请求可以自动重放；Java 测试仍输出 Mockito 动态 Agent 的未来
  JDK 兼容警告

## Python 文档字符串中文化维护

- 验证时间：2026-08-03
- 范围：Agent Python/Alembic 中 33 处说明性三双引号文档字符串，以及 Alembic revision
  模板中的版本标识、前置版本和创建时间标签
- 边界：Java Repository 中两处三双引号内容是可执行 SQL/JPQL 文本块，不是说明文档；为避免
  改变查询语义而保持原样
- 首轮功能回归：M1.1 6/6、M1.2 10/10、M1.3 18/18
- 首轮 `make quality`：失败，Ruff 报告翻译引入的全角逗号，以及目标文件既有学习注释中的
  全角标点和超长行；保留原意并改用句号、连接词和分行后修复
- 最终 `make quality`：Ruff 通过；mypy strict 检查 16 个源/测试文件无问题
- Python 汇总测试：34/34
- `uv lock --check`：通过，共解析 42 个直接及传递依赖
- 未运行：Java和Web测试未运行，因为未修改Java SQL/JPQL、接口、业务数据、前端或运行配置
- 最终失败：0

## Python 中文说明规则固化

- 验证时间：2026-08-03
- 范围：在根级 `AGENTS.md` 增加后续Python开发的中文文档字符串和解释性注释规则
- 边界：技术标识保持原文；日志事件名、错误码、API文案、SQL/JPQL、Prompt和第三方协议等
  运行时字符串不得因说明语言规则被擅自修改
- 验证：`make validate`、Markdown code fence结构检查和`git diff --check`
- 业务测试未运行：本次只修改开发治理文档、状态和开发记录，不修改运行时代码

## M1.4 Tool 基础协议

- 验证时间：2026-08-04
- 测试先行基线：`uv run --frozen pytest -q tests/test_tool_protocol.py` 在收集阶段产生 1 个
  `ModuleNotFoundError`，目标 `app.tools` 尚不存在
- `make test-agent-tool-protocol`：16/16
  - `ToolContext` 身份、权限、Trace、Run、严格不可变和 Token 脱敏：通过
  - `ToolResult` 成功/失败互斥约束：通过
  - Tool 八项元数据及非法名称、说明、权限、超时、重试次数：通过
  - 权限门禁、输入/输出 Pydantic 校验、整体 timeout：通过
  - `ToolException`、未知异常到标准失败结果：通过
  - 未知异常固定安全文案及 `tool_name/run_id/error_code` 排障日志：通过
  - 注册、查找、稳定名称列表、重复注册和未知名称：通过
  - `max_retries` 不会在 M1.4 提前触发自动重试：通过，timeout 场景只调用 1 次
- Python 分项回归：M1.1 7/7、M1.2 10/10、M1.3 18/18；Python 汇总 51/51
- `make quality`：Ruff 全部通过；mypy strict 检查 21 个源/测试文件无问题
- `uv lock --check`：通过，共解析 42 个直接及传递依赖
- `make validate`：通过，基础结构和 Compose 配置有效
- `make test`：通过；三服务 smoke、Python 分项、Java M0 56/56、Web 7/7 和生产构建全部通过
- `git diff --check`：通过
- 开发中发现并修复：
  - 首轮实现后 11/16；5 个元数据测试错误地尝试实例化抽象 `BaseTool`，改为具体测试 Tool 后
    16/16。这是测试夹具问题，不是放宽生产校验。
  - 首次 Ruff 报告两个旧式 `Generic` 声明；改用 Python 3.12 类型参数语法后又提示 import
    分组，完成排序后 Ruff 和 mypy 均通过。
- 最终失败：0
- 未运行：`make reset-demo` 未运行，因为本次没有修改固定数据且该命令会删除本地持久卷
- 已知非阻塞问题：没有具体业务 Tool；`max_retries` 仍是元数据；没有 Run/Step 持久化、
  重复调用检测、Workflow、模型调用或 Approval；Java 测试仍输出 Mockito 动态 Agent 的未来
  JDK 兼容警告

## M1.5 七个只读 Tool

- 验证时间：2026-08-07
- 测试先行基线：`uv run --frozen pytest -q tests/integration/tools/test_read_tools.py` 在收集
  阶段产生 1 个 `ImportError`，目标 `READ_TOOL_NAMES` 和只读 Tool 尚不存在
- `make test-tools`：M1.4 协议 16/16，M1.5 只读 Tool 69/69
  - 七个名称、Java GET 路径、身份和 Trace ID 透传及成功输出：通过
  - 空 ID、非法 ID、缺少权限均在 HTTP 前拒绝：通过
  - Java 404、500 和 timeout 到稳定 `ToolResult.error`，且当前只调用一次：通过
  - Java 缺少字段、非法状态和资源 ID 不一致的响应拒绝：通过
  - tasks、steps、issues、reviews 和 records 空数组保留为成功：通过
  - Registry 精确包含七个 Tool，FastAPI lifespan 装配并共享 Client：通过
- 真实 Java 固定数据验收：七个 Tool 针对 `ORDER-003` / `TASK-003` 依次调用，7/7 成功
- Python 全量：120/120
- `make quality`：Ruff 全部通过；mypy strict 检查 24 个源/测试文件无问题
- `make test`：通过；基础与 Compose、三服务 smoke、Python 分项、Java M0 56/56、Web 7/7
  及生产构建全部通过
- `docker compose up --detach --build agent-service` 后三服务 smoke：通过；新 Agent 镜像已包含
  M1.5 Schema、Tool 和启动装配
- `uv lock --check`、`make validate`、Markdown code fence 检查和 `git diff --check`：通过
- 开发中发现并修复：首次 Ruff 报告 21 项导出排序、既有中文教学注释格式和固定业务中文标点
  问题；保留注释含义并调整排版，对不可改的业务响应原文仅做定点 `noqa`，最终通过
- 验收命令首次误在 `agent-service` 子目录调用根级 Make 目标，第二次又因 shell 的持续 `cd`
  和未启用 `set -e` 掩盖前置失败；改为子 shell 并启用 `set -e` 后整组检查真实通过
- 最终失败：0
- 未运行：`make reset-demo` 未运行；本次不修改固定数据，该命令会删除本地持久卷
- 已知非阻塞问题：`max_retries=1` 目前只是元数据，M1.5 的 500/timeout 都只调用一次；尚无
  M1.7 重复调用检测、M1.8 调试 API、Run/Step、Workflow、模型调用或 Approval；Java 测试仍
  输出 Mockito 动态 Agent 的未来 JDK 兼容警告

## M1.6 Tool 重试

- 验证时间：2026-08-08
- 测试先行基线：首次收集先暴露既有 `app/schemas/tools.py` 标识符拼写回归并产生
  `NameError`；恢复 `OrderIdentifier`、`TaskIdentifier` 和 `BusinessIdentifier` 后，测试按预期
  因 `RetryPolicy` 尚不存在产生 1 个 `ImportError`
- `make test-tools`：M1.4 Tool 协议 16/16，RetryPolicy 与七个只读 Tool 92/92
  - 严格策略配置、不可变性、封顶指数退避和非法参数：通过
  - `max_retries` 的 retry/attempt 边界与次数耗尽：通过
  - 仅 `TOOL_TIMEOUT`/`UPSTREAM_UNAVAILABLE`、`retryable=true` 且有剩余次数时重试：通过
  - 首次连接失败、第二次成功：七个 Tool 7/7
  - timeout 持续失败时每个 Tool 最多调用两次并返回稳定错误：七个 Tool 7/7
  - Java 404/保守 500、缺字段和资源 ID 串线只调用一次：通过
  - 首次请求、退避、重试和输出校验共享 Tool 整体 timeout：通过
  - `tool_retry_scheduled` 日志包含 Tool、Run、Trace、错误码、序号和退避毫秒：通过
- `make test-agent-foundation`：8/8，包含结构化重试日志字段回归
- Python 全量：144/144
- `make quality`：Ruff 全部通过；mypy strict 检查 26 个源/测试文件无问题
- `uv lock --check`：通过，共解析 42 个直接及传递依赖
- `make validate`、Markdown code fence 检查和 `git diff --check`：通过，基础结构、Compose、
  文档围栏和差异空白有效
- 执行环境替代：默认 uv 缓存 `/Users/gao/.cache/uv` 在受限环境中不可写，改用
  `UV_CACHE_DIR=/tmp/productline-agent-m16-uv-cache`；只改变依赖缓存位置，不改变锁文件、依赖
  或测试行为
- 真实 Java 重试验收：未完成。受限环境拒绝访问 `127.0.0.1:8080`；直接调用确实先记录一次
  `tool_retry_scheduled`，第二次连接仍被拒绝后返回 `UPSTREAM_UNAVAILABLE`，不能作为 Java
  成功链路证据
- 完整 `make test`：未通过环境阶段。基础结构与 Compose 配置检查通过，随后三服务 smoke 因
  无法访问 `127.0.0.1:18000/health` 停止；Java 和 Web 测试目标未执行。本次 M1.6 不修改 Java
  或 Web 运行代码，Python 全量和边界测试作为阶段性验证，但不冒充完整跨服务回归
- 开发中发现并修复：
  - 既有 Tool Schema 的三个类型别名被误写为 `typeOrderIdentifier` 等名称，导致任意 Tool 导入
    失败；恢复原名称并由 Python 全量测试验证，无接口字段变化
  - 首次 Ruff 报告 42 项，主要是既有中文教学注释的全角标点，以及本次导出排序、文档字符串和
    测试行格式；保留注释语义、调整排版后 Ruff 与 mypy 均通过
- 未运行：`make reset-demo` 未运行；本次不修改固定数据且该命令会删除本地持久卷
- 最终代码测试失败：0；完整环境回归仍受本地网络权限阻塞
- 已知非阻塞问题：当前无 jitter、熔断或跨实例重试预算；Java 通用 500 保持
  `retryable=false`；尚无重复调用检测、Run/Step、Workflow、模型调用或 Agent E2E 恢复指标

## M1.7 重复调用检测

- 验证时间：2026-08-08
- 测试先行基线：`uv run --frozen pytest -q tests/test_tool_call_deduplication.py` 在收集阶段产生
  1 个预期 `ImportError`，目标 `build_tool_call_fingerprint` 尚不存在
- M1.7 专项测试：9/9
  - Tool 名和已校验参数生成 64 字符 SHA-256 指纹，不保存参数原文：通过
  - JSON key 顺序不同但语义等价的参数指纹相同：通过
  - Tool 名或参数不同会生成不同指纹：通过
  - ToolContext 私有账本绑定 Run ID、初始为空且不参与序列化：通过
  - 同一上下文内相同调用返回不可重试 `DUPLICATE_CALL`，具体 Tool 只执行一次：通过
  - 同 Run 不同参数、不同 Run 相同参数：通过
  - `force_refresh=True` 放行一次，随后普通重复调用仍拦截：通过
  - 两个并发相同调用只有一个执行：通过
  - `force_refresh` 拒绝非 bool 控制值：通过
- `make test-tools`：M1.4 协议 16/16，M1.5～M1.7 只读 Tool、RetryPolicy 和重复检测 115/115
  - 七个真实只读 Tool 同参第二次调用均在 HTTP 前拦截：7/7
  - 七个真实只读 Tool 显式强制刷新均发出第二次请求并成功：7/7
  - M1.6 内部 retry 回归保持通过，不被调用账本误判：通过
- Python 全量：167/167
- `make quality`：Ruff 全部通过；mypy strict 检查 28 个源/测试文件无问题
- `uv lock --check`：通过，共解析 42 个直接及传递依赖
- 真实 Java `ORDER-003` 只读验收：首次 `get_order_detail` 成功，同 Run 同参第二次返回
  `DUPLICATE_CALL`，`force_refresh=True` 后再次成功
- `make test`：通过；基础与 Compose、三服务 smoke、Python M1 分项、Java 56/56、Web 7/7 和
  Vue 生产构建全部通过
- `docker compose up --detach --build agent-service` 后 `make smoke`：通过；最终 Agent 镜像以及
  Java、Web 三服务健康检查全部通过
- `make validate`、Markdown code fence 检查和 `git diff --check`：通过
- 开发中发现并修复：首次 Ruff 报告 8 个既有中文教学注释的全角标点和行长问题；其中
  `readonly.py` 注释写“200ms”而实际 `initial_backoff_seconds=0.1`，已更正为 100ms。只修改
  说明文字，不改变 M1.6 运行配置
- 最终失败：0
- 未运行：`make reset-demo` 未运行；本次不修改固定数据且该命令会删除本地持久卷
- 已知非阻塞问题：调用账本只属于当前 `ToolContext`，不持久化、不跨进程/实例；相同
  `run_id` 的独立上下文不会自动共享；当前不是结果缓存，也没有 TTL 或业务版本新鲜度策略
