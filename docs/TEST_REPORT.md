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
