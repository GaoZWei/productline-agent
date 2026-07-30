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
