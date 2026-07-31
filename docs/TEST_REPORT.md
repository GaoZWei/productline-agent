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
