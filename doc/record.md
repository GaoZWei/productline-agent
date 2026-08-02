# 开发记录（Record）

本文件记录每次开发的核心实现、重要业务决策和真实验证结果，供后续开发追溯。所有代码、配置、接口、数据、测试或重要开发文档变更，都必须在任务结束前追加记录。

记录规则：

- 以追加为主，不覆盖历史条目；需要纠错时新增“更正”条目。
- 核心代码记录到文件路径和类/函数/接口/Schema 级别，必要时附最小关键片段，不复制整个文件。
- 测试结果必须来自实际执行；未运行的项目明确写明原因。
- 不记录密钥、Token、账号、生产数据或其他敏感信息。

---

## 记录模板

### YYYY-MM-DD HH:mm — `[任务编号] 任务名称`

- 里程碑：`M?`
- 任务类型：功能 / 修复 / 重构 / 测试 / 文档 / 配置
- 目标与范围：
  - 本次实现：
  - 明确不实现：
- 需求与关键决策：
  - 业务背景/固定数据映射：
  - 方案选择及原因：
  - 契约、状态或兼容性影响：
- 核心实现：
  - `path/to/file` — `Class/function/API/Schema`：职责与关键逻辑。
  - 必要的最小关键片段：

    ```text
    仅保留理解实现所需的核心片段；没有则写“无”。
    ```

- 代码解释与定位：
  - 整体调用/数据流：
  - 核心类、函数、接口或配置项：
  - 输入、输出、异常和边界：
  - 关键代码位置（文件路径 + 定义起始行号）：
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：
  - 幂等、并发或人工确认：
- 未完成项与已知问题：
  - 未完成项：
  - 已知问题/阻塞：
- 替代方案：
  - 采用的替代方案及原因：
  - 已覆盖/未覆盖的验收要求：
  - 局限、风险和转正/移除条件：
- 后续影响：
  - 对后续任务/里程碑：
  - 对接口/数据/测试/部署：
- 测试与验证：
  - `[通过/失败/未运行] command` — 结果（用例数量或关键输出）。
  - 未运行项及原因：
- 变更文件：
  - `path/to/file`
- 风险与遗留：
  - 已知风险/阻塞：
  - 后续兼容注意事项：
- 下一建议任务：
  - `[任务编号] 任务名称`

---

## 2026-07-26 — `[DOC-001] 建立仓库级开发提示词与记录规范`

- 里程碑：项目治理（M0 开发前）
- 任务类型：文档
- 目标与范围：
  - 本次实现：根据 `doc/plan.md` 和 `doc/detailed-plan.md` 提炼项目目标、架构边界、固定数据、里程碑停止线、单任务流程、测试要求和开发记录规则。
  - 明确不实现：不创建业务子项目，不实现 M0 业务功能，不修改原始需求和细化计划。
- 需求与关键决策：
  - 业务背景/固定数据映射：将 `ORDER-003 → TASK-003 → ISSUE-001 → PENDING review → BLOCKED delivery` 设为不可无理由破坏的黄金回归链路。
  - 方案选择及原因：使用根级 `AGENTS.md` 约束整个仓库；使用已有 `doc/record.md` 作为唯一强制实现记录，避免出现多个含义重叠的 record 文件。
  - 契约、状态或兼容性影响：没有修改代码或 API 契约；未来子目录可添加更具体的 `AGENTS.md`，但必须同时遵守根级约束。
- 核心实现：
  - `AGENTS.md` — 新增仓库级 Agent 开发提示词，覆盖需求来源、职责边界、M0～M7 顺序、质量门禁和完成定义。
  - `doc/record.md` — 新增可复用记录模板，并明确追加、真实性和敏感信息规则。
  - 必要的最小关键片段：无业务代码。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：本次无运行时代码。
  - 幂等、并发或人工确认：提示词明确未来业务写操作必须经人工确认、幂等键和版本校验保护。
- 测试与验证：
  - `[未运行] 业务自动化测试` — 仓库当前仅有规划文档，本次没有可执行的业务代码。
  - 未运行项及原因：M0 工程、Makefile 和测试命令尚未创建。
- 变更文件：
  - `AGENTS.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：`docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md` 尚未创建，后续按 M0 任务建立。
  - 后续兼容注意事项：若未来移动 `doc/` 或拆分模块级提示词，必须同步更新根级路径和记录规则。
- 下一建议任务：
  - `[T001] 创建 Monorepo 目录`

---

## 2026-07-26 — `[T001-T006] M0.1 项目基础环境`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 配置 / 测试 / 文档
- 目标与范围：
  - 本次实现：创建 `agent-service`、`business-service`、`web-console`、`docs` Monorepo 骨架；补齐 Git/编辑器配置、根级 README、环境变量示例、Docker Compose、Makefile 和基础自动检查。
  - 明确不实现：不实现业务领域模型、固定订单、Java 业务 API、FastAPI/LangGraph、Vue 业务页面或任何模型调用。
- 需求与关键决策：
  - 业务背景/固定数据映射：M0.1 不创建业务数据；`ORDER-003` 黄金链路保持文档基线，等待 M0.3 实现。
  - 方案选择及原因：三个服务先采用无外部依赖的 `/health` 启动骨架，确保 M0.1 可以独立构建和运行，同时避免提前开发 M0.2/M1/T050 能力。Java 使用 JDK 21 标准 `HttpServer`，Python 使用标准库 `ThreadingHTTPServer`，Web 使用 Node.js 标准 HTTP 服务；后续分别替换为 Spring Boot、FastAPI 和 Vue/Vite。
  - 契约、状态或兼容性影响：新增的 `/health` 仅作为基础设施探针，不属于订单业务接口。所有端口、数据库连接和模型占位配置均可通过 `.env`/环境变量修改。
- 核心实现：
  - `docker-compose.yml` — 编排 `pgvector/pgvector:pg16`、`business-service`、`agent-service` 和 `web-console`；PostgreSQL 健康后再启动上层服务。
  - `Makefile` — 提供 `help`、`config`、`validate`、`test`、`smoke`、`dev`、三个单服务启动目标、`down`、`logs`、`ps` 和 `reset-demo`。
  - `business-service/src/Main.java` — `Main#main`/`handleHealth`：使用 JDK 21 虚拟线程执行器提供 Java `/health`。
  - `agent-service/app/main.py` — `HealthHandler`/`main`：提供 Python `/health` 和环境变量端口绑定。
  - `web-console/server.mjs` — HTTP 入口：提供 Web `/health` 和 M0.1 静态占位页。
  - `scripts/check-foundation.sh` — 校验 M0.1 必需目录、文件和 `.env.example` 配置项。
  - `scripts/smoke-services.sh` — 独立启动并轮询三个服务；本机 JDK 不可用时使用 Docker 验证 Java 服务，并在退出时清理进程/容器。
  - 必要的最小关键片段：

    ```yaml
    depends_on:
      postgres:
        condition: service_healthy
    ```

- 异常、安全与边界：
  - 参数/权限/超时/上游异常：健康检查只接受预定读路径；冒烟脚本限制健康轮询次数，失败时返回非零状态。
  - 幂等、并发或人工确认：本次没有业务写操作。`.env` 被 Git 忽略，`.env.example` 只含本地占位值；真实模型密钥不得提交。
- 测试与验证：
  - `[通过] make help` — 正确显示 13 个根级命令。
  - `[通过] docker compose config` — 四服务及依赖、环境变量和数据卷配置有效。
  - `[通过] make test` — 基础检查以及 Java、Python、Web 三项独立健康冒烟均通过。
  - `[通过] docker compose up --detach --build` — 四个镜像成功拉取/构建，PostgreSQL 为 `healthy`，其余三个容器均启动。
  - `[通过] curl` 三个 `/health` — Java、Python、Web 均返回 `status=UP`。
  - `[通过] 环境变量端口覆盖检查` — `15432`、`18081`、`18001`、`15174` 四个自定义宿主端口正确展开。
  - `[通过] python3 -m py_compile agent-service/app/main.py` — Python 语法有效。
  - `[通过] node --check web-console/server.mjs` — Node.js 语法有效。
  - `[通过] git diff --check` — 无空白错误。
  - `[失败后修复] 首次 make test` — macOS Java 占位程序通过路径检查但无法运行；改为版本执行检测并回退 Docker 后完整复测通过。
  - 未运行项及原因：未运行 Java/Python/Web 业务测试，M0.1 尚无业务逻辑；未执行 `make reset-demo` 的数据删除动作，仅用 `make -n reset-demo` 验证命令展开。
- 变更文件：
  - `.editorconfig`
  - `.env.example`
  - `.gitignore`
  - `Makefile`
  - `README.md`
  - `docker-compose.yml`
  - `agent-service/`
  - `business-service/`
  - `web-console/`
  - `scripts/`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：本机没有可用 JDK，Java 本地启动需安装 JDK 21；Docker 启动与测试不受影响。本机 Python 为 3.9，生产目标 Python 3.12 由容器保证。
  - 后续兼容注意事项：M0 后续引入 Spring Boot、M1.1 引入 FastAPI、T050 引入 Vue/Vite 时，应保留 `/health` 语义和现有 Compose 服务名/环境变量，或同步更新根级测试与文档。
- 下一建议任务：
  - `[T007] 编写领域对象关系文档`

---

## 2026-07-26 — `[DOC-002] 强制代码解释与精确行号定位`

- 里程碑：项目治理
- 任务类型：文档 / 配置
- 目标与范围：
  - 本次实现：将分层代码解释、调用关系说明和关键文件精确行号链接纳入每次开发的强制交付要求。
  - 明确不实现：不修改 M0.1 服务代码、接口、测试或运行配置。
- 需求与关键决策：
  - 业务背景/固定数据映射：本次只增强开发交付规范，不影响 `ORDER-003` 黄金链路。
  - 方案选择及原因：同时更新根级 `AGENTS.md` 和开发记录模板，使最终用户说明与仓库历史记录都能从整体设计追踪到具体代码定义。
  - 契约、状态或兼容性影响：无运行时契约变化。
- 核心实现：
  - `AGENTS.md` — 新增“代码解释与定位要求”，规定整体目标、模块边界、调用/数据流、文件职责、核心符号、输入输出、异常、替代实现和后续影响的解释顺序。
  - `doc/record.md` — 模板新增“代码解释与定位”，要求记录调用流、核心符号和文件起始行号。
- 代码解释与定位：
  - 整体调用/数据流：用户开发请求 → 按 `AGENTS.md` 实现和验证 → 最终重新读取行号 → 输出分层解释及可点击定位 → 将同类信息追加到 `doc/record.md`。
  - 核心类、函数、接口或配置项：本次没有运行时代码；关键配置为 `AGENTS.md` 的最终交付规则和 `doc/record.md` 的记录模板。
  - 输入、输出、异常和边界：输入是用户要求；输出是仓库级规则。纯问答仍无需修改记录，但凡产生代码或配置变更就必须解释并记录。
  - 关键代码位置（文件路径 + 定义起始行号）：本条记录完成后重新读取并在最终回复中提供准确链接。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：无运行时代码。
  - 幂等、并发或人工确认：未修改历史记录，仅追加新条目；模板属于可持续更新区域。
- 未完成项与已知问题：
  - 未完成项：无。
  - 已知问题/阻塞：无。
- 替代方案：
  - 采用的替代方案及原因：无。
  - 已覆盖/未覆盖的验收要求：已覆盖未来开发的分层解释和行号定位要求；纯只读问答不产生新的仓库记录。
  - 局限、风险和转正/移除条件：行号会随未来文件修改变化，因此每次最终交付必须重新读取，历史 Record 中的行号仅代表当次文件版本。
- 后续影响：
  - 对后续任务/里程碑：所有后续任务都增加代码解释和定位这一完成门禁。
  - 对接口/数据/测试/部署：无运行时影响；会增加少量交付说明与记录维护成本。
- 测试与验证：
  - `[通过] 规则存在性与 Markdown 结构检查` — 必需标题、行号要求和 `DOC-002` 记录均存在；`AGENTS.md` 与 `doc/record.md` 代码围栏成对。
  - `[通过] git diff --check` — 无空白错误。
  - 未运行项及原因：业务测试不适用，本次仅修改文档配置。
- 变更文件：
  - `AGENTS.md`
  - `doc/record.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
- 风险与遗留：
  - 已知风险/阻塞：无。
  - 后续兼容注意事项：文件重构或移动时，最终回复应引用变更后的真实绝对路径。
- 下一建议任务：
  - `[T007] 编写领域对象关系文档`

---

## 2026-07-26 — `[ENV-001] 安装并配置 JDK 21，强化开发完成报告`

- 里程碑：M0 开发环境维护
- 任务类型：配置 / 文档
- 目标与范围：
  - 本次实现：通过 Homebrew 安装 OpenJDK 21，在用户交互与登录 Zsh 环境配置 `JAVA_HOME` 和 `PATH`；强化仓库规则，要求每次开发明确报告未完成项、问题、替代方案和后续影响。
  - 明确不实现：不创建 Spring Boot 工程，不修改 M0.1 Java 健康服务逻辑，不进行系统级 `/Library/Java/JavaVirtualMachines` 链接。
- 需求与关键决策：
  - 业务背景/固定数据映射：本次仅调整开发环境与开发治理，不影响 `ORDER-003` 固定业务基线。
  - 方案选择及原因：安装与 Dockerfile 一致的 Homebrew `openjdk@21`，避免本机和容器 Java 主版本不一致；使用用户级 `~/.zprofile` 和 `~/.zshrc` 配置，覆盖登录/自动化与交互终端，同时避免需要管理员权限的系统目录写入。
  - 契约、状态或兼容性影响：没有业务接口或数据变化。后续 Java 构建默认使用 JDK 21。
- 核心实现：
  - `~/.zprofile`、`~/.zshrc` — 新增 `JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`，并将 OpenJDK 21 `bin` 置于 `PATH` 前部，分别覆盖登录/自动化和交互 Shell。
  - `AGENTS.md` — 强制最终报告分别列出未完成项、已知问题、替代方案及后续影响；无内容时也必须明确写“无”。
  - `doc/record.md` — 扩展记录模板，加入替代方案覆盖范围、局限、移除条件和后续影响。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：首次安装被 `/opt/homebrew/opt/freetype` 阻塞，第二次被 `/opt/homebrew/opt/fontconfig` 阻塞；检查发现这些路径是包含旧动态库的普通目录，而 Homebrew 需要创建符号链接。
  - 幂等、并发或人工确认：安装前确认 `openjdk@21` 未安装；Shell 配置仅追加一次并通过搜索避免重复。
- 未完成项与已知问题：
  - 未完成项：尚未建立 Spring Boot 构建系统，该内容属于后续 M0 Java 工程任务。
  - 已知问题/阻塞：无 JDK 使用阻塞。保留了三个旧目录备份：`/opt/homebrew/opt/freetype.pre-jdk21-install-20260726`、`fontconfig.pre-jdk21-install-20260726`、`little-cms2.pre-jdk21-install-20260726`。
- 替代方案：
  - 采用的替代方案及原因：没有使用需要管理员权限的系统 JDK 符号链接；改为在用户 Zsh 启动文件中配置 Homebrew JDK。对冲突的旧动态库目录使用重命名备份，而非直接删除。
  - 已覆盖/未覆盖的验收要求：覆盖新 Zsh 终端直接运行 `java`/`javac`、设置 `JAVA_HOME` 和本项目本地 Java 构建；未向 macOS 系统级 Java 注册表创建 JDK 链接。
  - 局限、风险和转正/移除条件：不读取 `~/.zshrc` 的进程需显式使用 `$JAVA_HOME/bin` 或配置 IDE JDK。确认旧备份没有外部消费者后可手动删除；当前保留以便恢复。
- 后续影响：
  - 对后续任务/里程碑：M0 Java 领域模型和接口任务可以在本机使用 JDK 21；未来构建工具应明确 Java Toolchain 21。
  - 对接口/数据/测试/部署：无接口或数据影响；本机 Java 冒烟测试将从 Docker 回退路径切换为本机 JDK 路径，容器部署仍使用 Temurin 21。
- 测试与验证：
  - `[通过] brew list --versions openjdk@21` — 安装版本为 `21.0.12`。
  - `[通过] /opt/homebrew/opt/openjdk@21/bin/java -version` — OpenJDK Runtime `21.0.12`。
  - `[通过] /opt/homebrew/opt/openjdk@21/bin/javac -version` — `javac 21.0.12`。
  - `[通过] brew doctor` — 输出 `Your system is ready to brew.`。
  - `[通过] 登录 Shell 环境验证` — `JAVA_HOME` 指向 Homebrew OpenJDK 21，`java`/`javac` 均解析到 `/opt/homebrew/opt/openjdk@21/bin`。
  - `[通过] make test` — M0.1 基础检查、Compose 校验及三个服务冒烟全部通过；Java 明确使用本机 JDK，未使用 Docker 回退。
  - 未运行项及原因：未创建系统级 JDK 链接，因此没有执行 `/usr/libexec/java_home` 注册验证；项目与用户 Shell 不依赖该链接。
- 变更文件：
  - `~/.zshrc`
  - `~/.zprofile`
  - `AGENTS.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：系统目录没有创建 JDK 链接，依赖 `/usr/bin/java` 且不读取用户环境的图形化工具可能仍需单独配置 JDK 路径。
  - 后续兼容注意事项：Homebrew 升级 `openjdk@21` 时 `/opt/homebrew/opt/openjdk@21` 稳定链接会自动指向新补丁版本。
- 下一建议任务：
  - `[T007] 编写领域对象关系文档`

---

## 2026-07-30 — `[T007-T016] M0.2 业务领域模型设计`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 数据模型 / 配置 / 测试 / 文档
- 目标与范围：
  - 本次实现：完成领域关系文档、五组状态枚举、`Order`、`ProductionTask`、`ProductionStep`、`QualityIssue`、`ReviewRecord`、`ReworkTask`、`DeliveryRecord` 的实体/DTO/表/Repository，以及对象关联和 PostgreSQL 集成验收。
  - 明确不实现：不创建 M0.3 固定演示数据，不提供 M0.4 查询 API，不实现状态流转服务、权限、写回或 Python Tool。
- 需求与关键决策：
  - 业务背景/固定数据映射：保持 `ORDER-003 → TASK-003(COMPLETED) → ISSUE-001(COORDINATE_SYSTEM, OPEN) → REVIEW-003(PENDING) → DELIVERY-003(BLOCKED)` 基线；集成测试临时创建并回滚该链路，生产迁移只建表。
  - 方案选择及原因：采用 Spring Boot 3.5.16、Java 21、Spring Data JPA、Flyway 和 PostgreSQL；所有 ID 使用稳定业务字符串，枚举以字符串持久化，数据库再用 `CHECK` 约束防止跨服务状态漂移。
  - 契约、状态或兼容性影响：新增七张业务表和五组公共状态字符串。`V1` 一旦应用不得改写，后续数据库变化只能新增迁移。
- 核心实现：
  - 本机开发环境 — 执行 `brew install maven` 安装 Maven 3.9.16；Homebrew 同时安装 OpenJDK 26.0.2 依赖，但现有 `JAVA_HOME` 和 Maven 运行时继续使用项目规定的 OpenJDK 21.0.12。
  - `business-service/pom.xml` — 建立 Maven/Spring Boot 工程，接入 Web、Actuator、JPA、Validation、Flyway、PostgreSQL 与 Testcontainers。
  - `BusinessServiceApplication` — 替换 M0.1 标准库占位服务，作为 Spring Boot 组件扫描和应用入口。
  - `domain/enums/*` — 固定订单、生产、质检、复核和交付状态词汇。
  - `domain/model/*` — `Order` 为聚合根；聚合方法设置双向归属并防止子对象跨聚合重挂；只暴露不可修改集合。
  - `domain/dto/*` — 七个 Java Record DTO，使用 Jakarta Validation 约束业务 ID、必填字段、状态和步骤序号。
  - `domain/repository/*` — 七个 `JpaRepository`，支持按稳定业务 ID 独立查询。
  - `V1__create_business_domain.sql` — 创建七张表、外键、索引、唯一约束、序号约束和状态 `CHECK`。
  - `application.yml` — 数据源通过环境变量注入；Flyway 管理结构；Hibernate 使用 `ddl-auto=validate` 且关闭 Open Session in View。
  - `DomainRepositoryIntegrationTest` — 在真实 PostgreSQL 中级联保存后清空 JPA 上下文，再通过各 Repository 验证黄金链路。
- 代码解释与定位：
  - 整体调用/数据流：聚合方法组装 `Order` 业务链路 → `OrderRepository.saveAndFlush` 级联写入 → Flyway 约束数据库结构 → 清空持久化上下文 → 各 Repository 独立查询并验证状态。
  - 核心类、函数、接口或配置项：`Order#addTask`/`addDeliveryRecord` 管理聚合根关系；`ProductionTask#addStep`/`addQualityIssue`/`addReworkTask` 管理任务子对象；`ReworkTask#assignTo`/`setSourceIssue` 双向检查同任务约束。
  - 输入、输出、异常和边界：输入是非空业务 ID、必填文本和枚举；输出是可持久化聚合及 DTO。构造器拒绝空值和非法序号，关系方法拒绝重挂，返工拒绝跨生产任务引用。
  - 关键代码位置（文件路径 + 定义起始行号）：最终回复在全部修改完成后重新读取并提供准确绝对路径链接。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：M0.2 无业务 HTTP 参数或上游调用；DTO 与实体先执行本地输入约束，数据库继续执行非空、外键、唯一和状态检查。
  - 幂等、并发或人工确认：本阶段无业务写接口。稳定主键可作为后续幂等基础，但版本字段与写入幂等键仍属于 M0.5/M0.6。
- 未完成项与已知问题：
  - 未完成项：M0.3 的 `ORDER-001`～`ORDER-005` 固定数据、重置机制和固定数据测试尚未实现。
  - 已知问题/阻塞：测试运行会出现 Mockito 动态加载 Java Agent 的未来兼容警告；当前 JDK 21 测试不受影响。仓库尚未提供 Maven Wrapper，本机构建需要 Maven 3.9+。
- 替代方案：
  - 采用的替代方案及原因：概念模型中的 `QualityTask` 和 `DeliveryBatch` 未列入 T009～T015，本阶段分别用 `ProductionTask → QualityIssue` 和 `Order → DeliveryRecord` 直接关系覆盖验收链路；容器构建移除 `dependency:go-offline`，因为它会下载大量与运行 JAR 无关的 Maven 插件/云平台依赖。
  - 已覆盖/未覆盖的验收要求：已覆盖 M0.2 七个指定实体和 `ORDER-003` Repository 查询链；未覆盖质检批次、交付批次的独立生命周期，因为当前计划没有对应字段、表或验收。
  - 局限、风险和转正/移除条件：若确认一批质检包含多个问题或一个订单存在多个交付批次，应新增容器实体、DTO 和 Flyway 迁移并迁移外键；不能修改已执行的 V1。直接 Maven 镜像构建依赖网络，但成功后由 Docker 层缓存。
- 后续影响：
  - 对后续任务/里程碑：M0.3 可直接复用实体与外键写入固定数据；M0.4 查询接口应基于 DTO 映射，不直接序列化懒加载实体。
  - 对接口/数据/测试/部署：状态值成为跨服务契约；数据库首次启动自动应用 V1。现有本地 PostgreSQL 卷已升级到 V1、但未写入固定业务数据。删除或改名枚举值需要新迁移和跨服务兼容测试。
- 测试与验证：
  - `[通过] mvn --version` — Maven 3.9.16，运行时 Java 21.0.12。
  - `[通过] brew list --versions maven openjdk openjdk@21` — 分别为 3.9.16、26.0.2、21.0.12；项目仍固定 JDK 21。
  - `[通过] mvn --file business-service/pom.xml test` — 8/8，失败 0、错误 0、跳过 0。
  - `[通过] make test` — 基础检查、Compose、三个服务冒烟和领域测试全部通过。
  - `[通过] mvn --file business-service/pom.xml --define skipTests package` — 可执行 JAR 构建成功。
  - `[通过] docker compose up --detach --build` — 四服务成功构建并启动。
  - `[通过] 三个容器 /health` — Agent、Business、Web 均返回 UP。
  - `[通过] 容器 PostgreSQL` — Flyway V1 `success=true`，七张领域表全部存在。
  - `[失败后修复] 首次 Maven 测试` — 测试先行产生 68 个缺失类型编译错误；完成领域实现后通过。
  - `[失败后修复] 首次 Spring 应用集成测试` — 3 个测试中 1 个因缺少 Web 类报错；补充 Web Starter 后通过。
  - `[中止后优化] 首次 Java 镜像构建` — `dependency:go-offline` 下载无关构建插件和云依赖，主动终止并改为直接打包，随后构建通过。
  - 未运行项及原因：未运行 Java 业务 API 契约测试和固定数据重置测试；相应能力属于 M0.3/M0.4。
- 变更文件：
  - `.env.example`
  - `Makefile`
  - `README.md`
  - `docker-compose.yml`
  - `business-service/`
  - `scripts/check-foundation.sh`
  - `scripts/smoke-services.sh`
  - `docs/API_CONTRACT.md`
  - `docs/DOMAIN_MODEL.md`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无当前阻塞；Mockito 警告和 Maven Wrapper 缺失是非阻塞维护项。
  - 后续兼容注意事项：M0.3 种子数据必须与 V1 外键顺序一致；M0.4 避免直接暴露 JPA 实体；未来状态变化必须同步数据库、Java、Python 和前端。
- 下一建议任务：
  - `[T019] 创建 ORDER-003 黄金数据并实现可重置验证`

---

## 2026-07-30 — `[T017-T024] M0.3 固定业务数据`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 数据 / 测试 / 配置 / 文档 / 修复
- 目标与范围：
  - 本次实现：通过 Flyway 固定初始化 `ORDER-001`～`ORDER-005`；提供本地演示数据重置命令、数据完整性测试、黄金链路测试和跨对象业务状态一致性校验。
  - 明确不实现：不实现 M0.4 Java 查询接口、HTTP DTO 映射、统一错误响应、Python Tool 或任何写操作。
- 需求与关键决策：
  - 业务背景/固定数据映射：严格保持 `ORDER-003 → TASK-003(COMPLETED) → ISSUE-001(COORDINATE_SYSTEM, OPEN) → REVIEW-003(PENDING) → DELIVERY-003(BLOCKED)`；不预置返工任务，使后续“创建返工任务”建议与事实一致。
  - 方案选择及原因：采用版本化 Flyway V2 作为唯一种子数据源，首次启动和删除数据卷后的重建都走相同迁移；固定数据不用随机值、当前时间或执行顺序。
  - 契约、状态或兼容性影响：新增 `ORDER-001`～`005`、`TASK-001`～`005`、固定步骤、`ISSUE-001`～`003`、`REVIEW-003`～`005` 和 `DELIVERY-001`～`005`。这些 ID 和状态将成为 M0.4 Java API 与 M1 Python Tool 的契约夹具。
- 核心实现：
  - `business-service/src/main/resources/db/migration/V2__seed_fixed_demo_data.sql` — 六组 `INSERT`（第 3、11、19、27、51、57 行）：按外键顺序写入订单、任务、步骤、质检问题、复核和交付。
  - `business-service/src/main/java/com/productline/business/domain/validation/BusinessStateConsistencyValidator.java` — `BusinessStateConsistencyValidator`（第 22 行）、`Violation`（第 24 行）、`validate`（第 30 行）：返回稳定违规代码，不修改实体或数据库。
  - `scripts/reset-demo` — `run_sql`（第 12 行）和 V2 等待/校验/快照流程（第 18 行起）：删除本项目 Compose 数据卷，重建 PostgreSQL 与 Java 服务，确认 5 个订单和黄金链路后输出确定性快照。
  - `Makefile` — `test-business-data`（第 28 行）、`reset-demo`（第 54 行）：提供独立验收入口。
  - `DemoDataIntegrityIntegrationTest` — 固定数据映射（第 43 行）、生产失败环节（第 103 行）、黄金链路（第 116 行）和五场景一致性（第 134 行）。
  - `BusinessStateConsistencyValidatorTest` — 三个非法组合测试（第 25、36、55 行）。
  - 必要的最小关键片段：

    ```text
    ORDER-003 / TASK-003 / ISSUE-001 / REVIEW-003 / DELIVERY-003
    QUALITY_CHECKING / COMPLETED / OPEN / PENDING / BLOCKED
    ```

- 代码解释与定位：
  - 整体调用/数据流：Spring Boot 启动 → Flyway 先执行 V1 建表、再执行 V2 写入固定事实 → Repository 读取聚合 → 数据测试检查 ID、外键、状态和数量 → 状态校验器检查跨对象非法组合。重置命令通过删除本项目数据卷重新触发同一条链路。
  - 核心类、函数、接口或配置项：V2 是固定数据唯一来源；`validate(Order)` 输入一个已加载的订单聚合，输出去重且顺序稳定的 `List<Violation>`；`scripts/reset-demo` 等待 Flyway V2、验证黄金链路并计算全表排序后的 MD5。
  - 输入、输出、异常和边界：固定输入是五个订单 ID；输出是可重复数据库状态和违规代码。重置等待上限 60 秒，迁移、数量或黄金链路不满足时返回非零并在超时时输出 Java 日志。校验器拒绝 `null` 订单，但不负责懒加载事务边界或 HTTP 错误映射。
  - 关键代码位置（文件路径 + 定义起始行号）：`V2__seed_fixed_demo_data.sql:3`、`BusinessStateConsistencyValidator.java:22`、`scripts/reset-demo:12`、`DemoDataIntegrityIntegrationTest.java:43`、`BusinessStateConsistencyValidatorTest.java:25`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：本阶段无业务 HTTP 参数或上游调用。重置脚本只解析本项目 Compose 服务与容器内数据库环境变量，不输出密码；失败时立即停止。
  - 幂等、并发或人工确认：没有业务写接口。重置操作通过重建专属数据卷实现重复执行结果一致，不在已有数据上做易漂移的追加；命令具有破坏性，只用于本地演示数据。
- 未完成项与已知问题：
  - 未完成项：M0.4 Java 查询接口尚未实现，因此 Python Tool 当前不能通过 HTTP 获得固定数据；状态校验器尚未接入写事务，接入点属于 M0.5。
  - 已知问题/阻塞：无当前阻塞。Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告；`make reset-demo` 会停止当前项目的其他 Compose 服务并只重启 PostgreSQL 与 Java；Maven Wrapper 仍未提供。
- 替代方案：
  - 采用的替代方案及原因：计划未规定 `ORDER-001`、`002`、`004`、`005` 的产品类型，当前统一使用 `DOM`，避免引入未经确认的产品分支；重置采用删除项目数据卷，而非在原库逐表清理，以保证表结构、迁移历史和数据完全可重复。
  - 已覆盖/未覆盖的验收要求：覆盖 T017～T024 的五场景、黄金链路、重复重置、映射完整性和三类非法状态判定；未覆盖多产品类型差异、保留本地手工数据的原位重置、生产环境种子隔离和 HTTP 契约。
  - 局限、风险和转正/移除条件：当前 V2 会随默认应用迁移写入演示数据，适合演示阶段但不应无评审进入真实生产库。生产部署前必须确定独立 Flyway location/profile 或在全新生产基线中排除演示迁移；已应用 V2 的库只能通过新增迁移清理，不能改写 V2。若确认其他产品类型，使用新增迁移和同步契约测试替换相应值。
- 后续影响：
  - 对后续任务/里程碑：M0.4 应从这些固定事实构造响应 DTO，并优先实现 `ORDER-003` 完整可查询；M1 Tool 测试直接复用 `docs/DEMO_DATA.md` 的 ID 和状态断言。M0.5 写接口在提交前调用状态校验器。
  - 对接口/数据/测试/部署：V2 已成为不可改写迁移；固定字符串是跨 Java/Python/前端契约。测试支持改为 JVM 生命周期共享一个 PostgreSQL Testcontainer，避免多个 Spring 测试上下文复用已停止数据源。重置命令会删除本项目数据库卷，不能用于需要保留数据的环境。
- 测试与验证：
  - `[预期失败] mvn --file business-service/pom.xml -Dtest=DemoDataIntegrityIntegrationTest test` — 3 个测试中 1 失败、2 错误，证明 V2 前数据库为空；实现迁移后 3/3 通过，加入一致性断言后为 4/4。
  - `[预期失败] mvn --file business-service/pom.xml -Dtest=BusinessStateConsistencyValidatorTest test` — 7 个缺失类型编译错误；实现校验器后 3/3 通过。
  - `[失败后修复] mvn --file business-service/pom.xml test` — 首次 15 个测试中 1 失败、4 错误；修复固定 ID 污染和 Testcontainer 生命周期后通过。
  - `[通过] mvn --file business-service/pom.xml clean test` — 15/15，失败 0、错误 0、跳过 0。
  - `[通过] make test-business-data` — 7/7。
  - `[通过] make test-business-domain` — 7/7，M0.2 回归通过。
  - `[通过] make reset-demo` 连续两次 — 两次均为 `orders=5`，快照均为 `d57e54c32e4ef26eb01c76a8ed97a0ce`。
  - `[通过] make validate` — 基础文件与 Compose 配置检查通过。
  - `[通过] make smoke` — Agent、Business、Web 三项健康检查通过。
  - `[通过] make test` — 基础检查、三服务冒烟、M0.2 回归 7/7 和 M0.3 数据测试 7/7 全部通过。
  - `[通过] sh -n scripts/reset-demo`、`git diff --check` — Shell 语法和变更空白检查无错误。
  - 未运行项及原因：未运行 Java 业务 HTTP 契约测试；M0.4 端点尚未实现。
- 变更文件：
  - `business-service/src/main/resources/db/migration/V2__seed_fixed_demo_data.sql`
  - `business-service/src/main/java/com/productline/business/domain/validation/BusinessStateConsistencyValidator.java`
  - `business-service/src/test/java/com/productline/business/demo/DemoDataIntegrityIntegrationTest.java`
  - `business-service/src/test/java/com/productline/business/domain/BusinessStateConsistencyValidatorTest.java`
  - `business-service/src/test/java/com/productline/business/domain/DomainRepositoryIntegrationTest.java`
  - `business-service/src/test/java/com/productline/business/support/PostgresIntegrationTestSupport.java`
  - `scripts/reset-demo`
  - `Makefile`
  - `README.md`
  - `docs/API_CONTRACT.md`
  - `docs/DEMO_DATA.md`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；生产种子隔离、Mockito Agent 警告、Maven Wrapper 缺失是后续非阻塞维护项。
  - 后续兼容注意事项：不得改写 V2 或固定 ID；接口字段和 Python Schema 必须直接复用状态词汇。改变固定场景时同步新增迁移、Java/Python/前端契约测试、评测预期和本文件。
- 下一建议任务：
  - `[T025] 实现 GET /api/orders/{id} 订单详情查询及 404 契约`

---

## 2026-07-30 — `[DOC-003] 建立 Agent 面试价值评估与记录机制`

- 里程碑：项目治理
- 任务类型：文档 / 配置
- 目标与范围：
  - 本次实现：建立 `doc/needCare.md` 的价值门禁，回填 M0.1～M0.3 中对 Agent 面试确有价值的内容，并把“先评估、有价值才记录”加入仓库级开发规则。
  - 明确不实现：不修改业务代码、接口、数据库、测试逻辑或里程碑进度；不把环境安装、治理任务和普通样板代码包装成面试亮点。
- 需求与关键决策：
  - 业务背景/固定数据映射：历史关注点保留 Java 事实层与 Python Agent 的边界、M0.2 结构化状态契约、M0.3 五组固定场景和 `ORDER-003` 黄金链路；未改变任何固定数据。
  - 方案选择及原因：`needCare.md` 采用价值筛选而非按任务流水记录。每次开发仍必须评估，但只有内容影响 Agent 架构、Tool、可靠性、安全或评测时才落盘。
  - 契约、状态或兼容性影响：没有运行时契约变化；新增开发完成门禁和最终汇报项。
- 核心实现：
  - `doc/needCare.md` — “记录门禁”（第 6 行）定义准入标准；M0.1（第 29 行）、M0.2（第 83 行）、M0.3（第 137 行）回填已验证的面试知识、问题回答、简历边界和未实现能力。
  - `AGENTS.md` — “Agent 面试价值评估”（第 241 行）规定每次开发先评估、有价值才记录，并禁止空条目和过度声称。
  - `README.md` — 开发约束（第 80 行）提示开发者执行面试价值评估。
  - 必要的最小关键片段：

    ```text
    每次开发先评估 Agent 面试价值
    → 有价值：更新 doc/needCare.md
    → 无价值：不制造空条目，只在最终回复说明判断
    ```

- 代码解释与定位：
  - 整体调用/数据流：开发任务完成并验证 → 根据五项价值标准评估 → 有价值时沉淀原理、取舍、问答和能力边界 → 无价值时不修改关注点文件 → 最终回复说明判断。
  - 核心类、函数、接口或配置项：本次没有运行时代码；核心配置是 `AGENTS.md` 的准入门禁，核心知识载体是 `doc/needCare.md`。
  - 输入、输出、异常和边界：输入是已真实完成的开发事实；输出是筛选后的面试知识。尚未实现的规划只能写入“不能过度声称”，不得作为成果表述。
  - 关键代码位置（文件路径 + 定义起始行号）：`doc/needCare.md:6`、`doc/needCare.md:29`、`doc/needCare.md:83`、`doc/needCare.md:137`、`AGENTS.md:241`、`README.md:80`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：无运行时代码，不涉及参数、权限、超时或上游调用。
  - 幂等、并发或人工确认：不修改 `doc/record.md` 的历史事实；`needCare.md` 只增加有价值内容，不作为完整开发记录。
- 未完成项与已知问题：
  - 未完成项：无。
  - 已知问题/阻塞：面试价值判断包含一定主观性，已通过明确准入标准和“禁止过度声称”降低偏差；无当前阻塞。
- 替代方案：
  - 采用的替代方案及原因：没有采用“每个任务强制生成一条关注点”的流水账方案，因为它会放大普通配置和样板代码、降低 Agent 面试准备的信噪比。
  - 已覆盖/未覆盖的验收要求：覆盖历史筛选、未来门禁、最终汇报和能力边界；不记录环境安装与纯治理任务的面试条目。
  - 局限、风险和转正/移除条件：若目标岗位从 Agent 开发转为纯 Java/运维，当前价值标准需要重新评审；在 Agent 岗位目标不变时持续使用。
- 后续影响：
  - 对后续任务/里程碑：从 T025 开始，每次开发结束必须先判断其对 Tool 契约、Agent 可靠性、评测或安全是否有面试价值。
  - 对接口/数据/测试/部署：无运行时影响；增加一项轻量文档完成检查。
- 测试与验证：
  - `[通过] needCare/AGENTS 结构脚本` — 三个历史条目及四类必需小节存在；排除内容不存在；价值门禁、空条目禁令和最终汇报要求存在；Markdown 围栏成对。
  - `[检查脚本修正] Markdown 围栏检查` — 首次扩展检查 `doc/record.md` 时只匹配行首围栏，未识别模板中的缩进围栏而返回非零；允许前导空白后复测通过，文档内容无需修改。
  - `[通过] make validate` — M0.1 基础文件检查和 Docker Compose 配置校验通过。
  - `[通过] git diff --check` — 无空白错误。
  - 未运行项及原因：未运行业务自动化测试，本次没有修改运行时代码、接口、数据库或业务测试。
- 变更文件：
  - `doc/needCare.md`
  - `AGENTS.md`
  - `README.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无。
  - 后续兼容注意事项：不得把规划中的 Java API、Python Tool、Workflow、RAG 或动态 Agent 写成已完成能力；实现后才能升级相应关注点表述。
- Agent 面试价值评估：
  - 本次治理任务本身不构成新的 Agent 技术亮点，因此未在 `needCare.md` 新增 DOC-003 条目；文件中只回填既有 M0.1～M0.3 的有效内容。
- 下一建议任务：
  - `[T025] 实现 GET /api/orders/{id} 订单详情查询及 404 契约`

---

## 2026-07-30 21:34 — `[T025-T032] M0.4 Java 查询接口`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 接口 / 测试 / 文档 / 配置
- 目标与范围：
  - 本次实现：实现订单详情、关联任务、任务详情、生产进度、质检问题、复核记录、交付状态和订单总览 8 个只读 HTTP 端点，使 `ORDER-003` 固定事实可通过 Java API 完整查询。
  - 明确不实现：不实现 M0.5 写接口、权限认证、幂等/版本控制、M0.6 统一响应与 Trace ID、故障模拟、Python HTTP Client 或 Tool。
- 需求与关键决策：
  - 业务背景/固定数据映射：HTTP 总览必须保持 `ORDER-003 → TASK-003(COMPLETED) → ISSUE-001(COORDINATE_SYSTEM, OPEN) → REVIEW-003(PENDING) → DELIVERY-003(BLOCKED)`，不得由 Controller 或模型补造事实。
  - 方案选择及原因：使用 Controller → `BusinessQueryService` 只读事务 → Repository → DTO/响应 record 的分层；禁止直接序列化 JPA Entity。集合端点带父资源 ID，并稳定返回数组。
  - 契约、状态或兼容性影响：父资源不存在返回 `404`，父资源存在但关联记录为空返回 `200 + []`；非法质检状态过滤返回 `400`；步骤按业务序号排序，其余集合按业务 ID 排序。M0.6 可能为当前成功响应增加统一包装，Python Client 应以届时最终契约为准。
- 核心实现：
  - `business-service/src/main/java/com/productline/business/api/OrderQueryController.java` — `OrderQueryController`（第 15 行）暴露订单详情、任务、交付状态和总览 4 个 GET 端点（第 24、29、34、39 行）。
  - `business-service/src/main/java/com/productline/business/api/TaskQueryController.java` — `TaskQueryController`（第 17 行）暴露任务详情、进度、质检过滤和复核 4 个 GET 端点（第 26、31、36、43 行）。
  - `business-service/src/main/java/com/productline/business/application/BusinessQueryService.java` — `BusinessQueryService`（第 39 行）在只读事务中校验父资源、执行有序查询并映射 DTO；总览聚合从第 119 行开始，任务内步骤/问题/复核组合从第 132 行开始。
  - `business-service/src/main/java/com/productline/business/api/dto/OrderOverviewResponse.java` — `OrderOverviewResponse`（第 7 行）定义订单、任务总览和交付记录的嵌套 Schema；其余集合响应 record 使用 `List.copyOf` 固化返回集合。
  - `business-service/src/main/java/com/productline/business/api/error/ResourceNotFoundException.java` — `ResourceNotFoundException`（第 7 行）提供 M0.4 阶段的 404 状态映射。
  - `business-service/src/main/java/com/productline/business/domain/repository/ProductionStepRepository.java` — 有序步骤查询（第 9 行）；任务、问题、复核和交付 Repository 同步增加父 ID 查询及排序/过滤。
  - `business-service/src/test/java/com/productline/business/api/BusinessQueryApiIntegrationTest.java` — `BusinessQueryApiIntegrationTest`（第 17 行）通过真实 Spring Web 与 Testcontainers PostgreSQL 验证 13 个正常、空结果、过滤、排序、404/400 和黄金链路场景。
  - `Makefile` — `test-java-contract`（第 33 行）提供 M0.4 独立验收入口，并纳入根级 `make test`（第 18 行）。
  - 必要的最小关键片段：

    ```text
    页面/Python Tool（后续）
    → GET Java API
    → Controller
    → @Transactional(readOnly = true) BusinessQueryService
    → 有序 Repository 查询
    → DTO/响应 Schema
    → 可追溯业务事实 JSON
    ```

- 代码解释与定位：
  - 整体调用/数据流：HTTP 路径参数和可选 `QualityIssueStatus` 进入 Controller；服务先确认订单/任务存在，再从对应 Repository 查询；Entity 只在事务内使用并映射为 DTO；Jackson 序列化 record 返回 JSON。总览按订单加载任务，再为每个任务组合步骤、质检问题和按问题分组的复核，最后附加交付记录。
  - 核心类、函数、接口或配置项：`getQualityIssues`（`BusinessQueryService.java:89`）根据可选枚举选择全量或状态过滤查询；`getOrderOverview`（第 119 行）与 `toOverview`（第 132 行）构造跨表结果；`requireOrder`（第 156 行）及对应任务方法区分 404 与空集合。
  - 输入、输出、异常和边界：输入为稳定订单/任务 ID 和可选 `OPEN|PROCESSING|RESOLVED|CLOSED`；输出为 DTO 或含父 ID 的数组响应。不存在的父资源为 404，非法枚举由 Spring 参数转换映射 400；没有关联数据不是错误。当前无分页，适用于固定演示规模。
  - 关键代码位置（文件路径 + 定义起始行号）：`OrderQueryController.java:15`、`TaskQueryController.java:17`、`BusinessQueryService.java:39`、`OrderOverviewResponse.java:7`、`ResourceNotFoundException.java:7`、`BusinessQueryApiIntegrationTest.java:17`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：已覆盖非法状态 400 和未知资源 404；当前接口没有认证/授权，也没有统一业务错误码、错误体、Trace ID、超时或故障注入，这些不能被后续 Tool 当作已稳定能力。
  - 幂等、并发或人工确认：全部为只读接口，不涉及写幂等、版本冲突或人工确认。Controller 不接受写请求。
- 未完成项与已知问题：
  - 未完成项：M0.5 写接口和 M0.6 统一异常均未实现；Python Tool 尚不能直接复用本次代码，仍需实现 HTTP Client 和 Pydantic 响应 Schema。
  - 已知问题/阻塞：无当前阻塞。总览按任务执行步骤、问题和复核查询，固定数据下可控，但任务数量增长时可能增加 SQL 次数；当前缺少生产规模和耗时数据。Mockito 动态 Java Agent 有未来 JDK 兼容警告。
- 替代方案：
  - 采用的替代方案及原因：在 M0.6 前使用 `@ResponseStatus` 只保证 404 HTTP 状态，不提前复制统一错误模型；总览使用清晰的分组查询而非复杂多表 Join，避免笛卡尔积和重复去重逻辑；复核和交付返回记录数组，因为当前模型没有“唯一当前记录”约束或时间字段，不能安全猜测最新记录。
  - 已覆盖/未覆盖的验收要求：已覆盖 T025～T032 正常路径、404、空数组、步骤排序、状态过滤、READY/BLOCKED 和跨表聚合；未覆盖统一错误 JSON、权限、分页、生产规模性能和 Python Tool 消费。
  - 局限、风险和转正/移除条件：M0.6 实现后由 `ApiResponse<T>`、统一异常处理和 Trace ID 替换临时状态映射；出现真实多任务性能证据时，将总览内部改为批量查询/投影并保持外部 Schema；业务明确当前复核/交付唯一性后，再通过新迁移增加约束或时间/版本字段并评审是否收敛数组。
- 后续影响：
  - 对后续任务/里程碑：M0.5 可复用 `ResourceNotFoundException` 的状态语义但不能把它视为最终错误契约；M1 Python Client 应分别映射 8 个响应，Agent 第一版优先使用细粒度 Tool，聚合端点保留给页面和排障。
  - 对接口/数据/测试/部署：未修改数据库迁移和固定数据；新增 HTTP 路径会随 Java 服务部署生效。后续若增加统一成功包装，必须同步 API 文档、Java 契约测试和 Python Schema。接口尚未鉴权，不应直接暴露到不受控网络。
- 测试与验证：
  - `[预期失败] mvn --file business-service/pom.xml -Dtest=BusinessQueryApiIntegrationTest test` — 13 个测试中 9 个失败、4 个通过；失败均为待实现端点返回 404。
  - `[通过] mvn --file business-service/pom.xml -Dtest=BusinessQueryApiIntegrationTest test` — 实现后 13/13，失败 0、错误 0、跳过 0。
  - `[通过] mvn --file business-service/pom.xml clean test` — 全量 28/28，失败 0、错误 0、跳过 0。
  - `[通过] make test` — 基础检查、Compose 校验、三服务冒烟、M0.2 领域 7/7、M0.3 数据 7/7、M0.4 契约 13/13 全部通过。
  - `[通过] git diff --check` — 无空白错误。
  - 未运行项及原因：未运行 M0.5 写接口、权限、幂等、并发和人工确认测试，相关实现不在本次范围。
- 变更文件：
  - `business-service/src/main/java/com/productline/business/api/`
  - `business-service/src/main/java/com/productline/business/application/BusinessQueryService.java`
  - `business-service/src/main/java/com/productline/business/domain/repository/`
  - `business-service/src/test/java/com/productline/business/api/BusinessQueryApiIntegrationTest.java`
  - `Makefile`
  - `README.md`
  - `docs/API_CONTRACT.md`
  - `docs/DOMAIN_MODEL.md`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/needCare.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；未鉴权、临时错误体、总览查询次数和 Mockito 警告是已知非阻塞问题。
  - 后续兼容注意事项：Python 端不得依赖 Spring 默认错误 JSON；必须区分 200 空数组与 404；不得将总览端点存在描述为动态 Tool 路由已完成。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次建立了 Agent Tool 的 Java 事实接口，明确空结果/404、确定性排序、细粒度 Tool 与聚合接口的取舍，并通过黄金链路契约测试提供可举证内容。
- 下一建议任务：
  - `[T033] 实现 POST /api/tasks/{id}/review 的请求、权限与状态冲突校验`

---

## 2026-07-31 21:36 — `[T033-T037] M0.5 Java 写接口`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 接口 / 数据库 / 测试 / 配置 / 文档 / 修复
- 目标与范围：
  - 本次实现：实现提交复核结果和创建返工任务两个 Java POST 接口；增加最小角色/状态校验、请求幂等、任务业务版本、并发冲突和操作前后日志；将写契约加入根级回归。
  - 明确不实现：不实现 M0.6 统一响应、错误码和 Trace ID，不实现真实认证、Python 写 Tool、Agent Approval、前端确认或自动推进问题/订单/交付状态。
- 需求与关键决策：
  - 业务背景/固定数据映射：以 `TASK-003 + ISSUE-001(OPEN)` 验证 `REWORK_REQUIRED` 复核和 `PENDING` 返工写入；测试后删除新增记录并恢复任务版本，保持 `ORDER-003` 固定黄金事实和无预置返工基线。
  - 方案选择及原因：计划只给出路径和测试重点，当前明确最小契约为 `X-User-Id`、`X-User-Role: REVIEWER`、`Idempotency-Key`，请求体携带业务字段与 `expectedVersion`。复核只追加历史，不推断未定义的状态迁移；返工初始状态固定为 `PENDING`。
  - 契约、状态或兼容性影响：`ProductionTaskDto` 新增 `version`；两个 POST 成功响应返回新资源和 `taskVersion`。400/403/404/409 当前只稳定 HTTP 状态，M0.6 可能增加统一响应包装，后续 Python Schema 必须以届时最终契约为准。
- 核心实现：
  - `business-service/src/main/java/com/productline/business/api/TaskWriteController.java` — `TaskWriteController`（第 18 行）、`submitReview`（第 27 行）、`createRework`（第 38 行）：接收路径、身份/幂等 Header 和校验后的请求 Schema。
  - `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java` — `BusinessWriteService`（第 42 行）、`submitReview`（第 82 行）、`createRework`（第 155 行）：在单事务内执行身份、幂等、资源、状态、版本、写入和审计流程。
  - `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java` — `reserveOrLoad`（第 233 行）区分首次预占、同请求重放、同键异请求和进行中冲突；`incrementVersion`（第 346 行）把条件更新结果映射为并发 409。
  - `business-service/src/main/resources/db/migration/V3__add_write_safety_support.sql` — 从第 1、4、21 行增加任务版本、`idempotency_records` 和 `operation_logs`，并以约束保证幂等完成字段成对为空或成对有值。
  - `business-service/src/main/java/com/productline/business/domain/model/ProductionTask.java` — `@Version`（第 37 行）把版本纳入领域/查询契约。
  - `business-service/src/main/java/com/productline/business/domain/model/IdempotencyRecord.java` — `isCompleted`/`complete`（第 62、66 行）记录首次成功资源及写后版本。
  - `business-service/src/main/java/com/productline/business/domain/model/OperationLog.java` — 构造器（第 45 行）强制操作类型、目标、操作者、幂等键哈希和前后状态非空。
  - `business-service/src/test/java/com/productline/business/api/BusinessWriteApiIntegrationTest.java` — 12 个真实 HTTP/PostgreSQL 用例（类第 28 行）；幂等（第 135 行）、并发竞争（第 191 行）、返工防重（第 264 行）和审计均有数据库副作用断言。
  - `Makefile` — `test-java-write`（第 38 行）提供独立验收入口，并在第 18 行纳入 `make test`。
  - 必要的最小关键片段：

    ```sql
    UPDATE production_tasks
       SET version = version + 1
     WHERE task_id = :taskId
       AND version = :expectedVersion
    ```

- 代码解释与定位：
  - 整体调用/数据流：HTTP POST → Controller 校验请求形状 → `BusinessWriteService` 校验身份和幂等键 → 预占幂等记录 → 重查任务/问题并校验状态 → 通过聚合关系级联写复核/返工 → 原子递增版本 → 完成幂等结果并保存操作日志 → 事务提交后返回资源与新版本。同键同请求在状态校验前直接读取首次资源并重放。
  - 核心类、函数、接口或配置项：`submitReview` 拒绝未完成任务、跨任务/关闭问题、`PENDING` 结论和对非 `RESOLVED` 问题的 `APPROVED`；`createRework` 拒绝关闭/跨任务问题及已有活动返工；`incrementVersionIfMatches` 用数据库更新行数作为并发判定，而不是依赖提交时异常。
  - 输入、输出、异常和边界：输入为任务 ID、用户/角色、幂等键和带 `expectedVersion` 的复核/返工 Schema；输出为新记录 DTO 和递增版本。缺失/非法参数 400、非 `REVIEWER` 403、未知资源 404、状态/幂等/版本冲突 409。单事务失败会回滚业务子记录、幂等预占、版本和日志。
  - 关键代码位置（文件路径 + 定义起始行号）：`TaskWriteController.java:18`、`BusinessWriteService.java:82`、`BusinessWriteService.java:155`、`BusinessWriteService.java:233`、`BusinessWriteService.java:346`、`V3__add_write_safety_support.sql:1`、`BusinessWriteApiIntegrationTest.java:28`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：Bean Validation 约束必填、非负版本和 1000 字符文本；业务层限制身份/幂等键长度并校验角色、资源归属和状态。当前没有上游 HTTP 调用或超时；Header 身份尚不能证明来源真实性。
  - 幂等、并发或人工确认：同键同用户同请求只写一次并重放首次结果，同键变更内容/操作/用户为 409；不同键但重复活动返工由业务规则阻止；不同写动作使用同一旧版本时原子条件更新保证只有一个成功。人工确认不在 M0.5，当前直接调用 Java 接口会尝试写入。
- 未完成项与已知问题：
  - 未完成项：M0.6 统一错误模型/Trace ID、真实认证、幂等记录 TTL/归档、操作日志查询、Python 写 Tool、Approval 和前端确认尚未实现；复核成功不会自动迁移问题、订单或交付状态。
  - 已知问题/阻塞：无阻塞。Mockito 在 JDK 21 输出动态 Java Agent 的未来兼容警告；幂等表会持续增长；当前操作日志是关键字段快照而非完整事件溯源。
- 替代方案：
  - 采用的替代方案及原因：M0.5 尚无认证系统，暂用 `X-User-Id`/`X-User-Role` 传入最小身份上下文以验证 Java 侧权限门禁；M0.6 前用三个 `@ResponseStatus` 异常提供临时 400/403/409；本机没有 Maven Wrapper，验收使用已固定到 JDK 21 的系统 Maven。
  - 已覆盖/未覆盖的验收要求：覆盖 T033～T037 的正常写入、权限、状态冲突、重复创建、同请求只写一次、并发冲突和前后日志；不覆盖身份防伪、统一错误 JSON、Trace 链路、跨服务幂等治理、人工确认或 Agent 调用次数策略。
  - 局限、风险和转正/移除条件：接入网关/JWT 后必须从可信 Principal 获取身份并删除可伪造角色 Header；M0.6 用全局异常处理和统一错误码替换临时异常映射；生产化前根据保留周期增加幂等/日志归档；若补充 Maven Wrapper，再把本地与 CI 验收统一到 `./mvnw`。
- 后续影响：
  - 对后续任务/里程碑：M0.6 应为 400/403/404/409 建立稳定业务错误码并加入 Trace ID；M1 只读 Tool 不消费写端点；M6 写 Tool 必须透传 Approval 派生的可信用户、幂等键和查询所得版本，并正确处理 409 为 STALE/冲突，而不是盲目重试。
  - 对接口/数据/测试/部署：V3 是不可改写迁移；已有数据库部署会新增非空默认版本和两张表。查询 DTO 的 `version` 是新增字段，宽松 JSON 客户端兼容，严格客户端需同步 Schema。写成功会改变固定数据库，演示重置仍通过删除项目数据卷恢复；测试自身已做后清理。
- 测试与验证：
  - `[预期失败] mvn --file business-service/pom.xml -Dtest=BusinessWriteApiIntegrationTest test` — 首次 11/11 错误，首个证据为 `operation_logs` 不存在，证明写安全结构和接口尚未实现。
  - `[失败后修复] 同一目标测试` — V3 首次 `CHAR(64)` 与 Hibernate `VARCHAR(64)` 不一致导致应用启动失败；改为 `VARCHAR(64)`。
  - `[失败后修复] 同一目标测试` — 聚合级联后又显式保存子实体触发重复托管异常；移除显式 `save`，统一由聚合级联持久化。
  - `[失败后修复] 同一目标测试` — 11 个测试中 3 个失败：成功响应版本仍为 0，并发结果为 200/500；将提交阶段 `OPTIMISTIC_FORCE_INCREMENT` 改为条件更新后通过。
  - `[通过] mvn --file business-service/pom.xml -Dtest=BusinessWriteApiIntegrationTest test` — 扩充后 12/12，失败 0、错误 0、跳过 0。
  - `[失败后修复] mvn --file business-service/pom.xml -Dtest=BusinessWriteApiIntegrationTest,BusinessQueryApiIntegrationTest test` — 首次 25 个测试中 1 个失败，写测试残留版本污染查询测试；增加 `@AfterEach` 恢复后 25/25。
  - `[通过] mvn --file business-service/pom.xml clean test` — 全量 40/40，失败 0、错误 0、跳过 0。
  - `[通过] make test` — 基础检查、Compose 校验、三服务冒烟、M0.2 7/7、M0.3 7/7、M0.4 13/13、M0.5 12/12 全部通过。
  - `[失败后使用既有替代命令] ./mvnw -Dtest=BusinessWriteApiIntegrationTest test` — 退出 127，仓库无 Maven Wrapper；随后使用 `mvn --file business-service/pom.xml ...` 完成全部验证。
  - 未运行项及原因：未运行 M0.6、Python Tool、Approval 和 Agent E2E 测试，对应实现不在本次范围。
- 变更文件：
  - `business-service/src/main/java/com/productline/business/api/TaskWriteController.java`
  - `business-service/src/main/java/com/productline/business/api/dto/ReviewSubmissionRequest.java`
  - `business-service/src/main/java/com/productline/business/api/dto/ReviewWriteResponse.java`
  - `business-service/src/main/java/com/productline/business/api/dto/ReworkCreationRequest.java`
  - `business-service/src/main/java/com/productline/business/api/dto/ReworkWriteResponse.java`
  - `business-service/src/main/java/com/productline/business/api/error/BusinessConflictException.java`
  - `business-service/src/main/java/com/productline/business/api/error/InvalidRequestException.java`
  - `business-service/src/main/java/com/productline/business/api/error/PermissionDeniedException.java`
  - `business-service/src/main/java/com/productline/business/application/BusinessQueryService.java`
  - `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java`
  - `business-service/src/main/java/com/productline/business/domain/dto/ProductionTaskDto.java`
  - `business-service/src/main/java/com/productline/business/domain/model/ProductionTask.java`
  - `business-service/src/main/java/com/productline/business/domain/model/IdempotencyRecord.java`
  - `business-service/src/main/java/com/productline/business/domain/model/OperationLog.java`
  - `business-service/src/main/java/com/productline/business/domain/repository/ProductionTaskRepository.java`
  - `business-service/src/main/java/com/productline/business/domain/repository/ReworkTaskRepository.java`
  - `business-service/src/main/java/com/productline/business/domain/repository/IdempotencyRecordRepository.java`
  - `business-service/src/main/java/com/productline/business/domain/repository/OperationLogRepository.java`
  - `business-service/src/main/resources/db/migration/V3__add_write_safety_support.sql`
  - `business-service/src/test/java/com/productline/business/api/BusinessQueryApiIntegrationTest.java`
  - `business-service/src/test/java/com/productline/business/api/BusinessWriteApiIntegrationTest.java`
  - `business-service/README.md`
  - `Makefile`
  - `docs/API_CONTRACT.md`
  - `docs/DEMO_DATA.md`
  - `docs/DOMAIN_MODEL.md`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/needCare.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；临时身份 Header、默认错误体、无 Trace、幂等/日志无归档和 Mockito 警告是已知风险。
  - 后续兼容注意事项：不得改写 V3；Python/前端必须从任务查询读取最新版本并把 409 当业务冲突，写请求不能自动无条件重试；接入 Approval 前不得声称“未确认绝不写入”已完成。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次真实实现并测试了 Agent 写回所需的 Java 权威校验、请求幂等、乐观并发和同事务审计，并记录了 JPA 提交阶段版本冲突为何改为条件更新的工程取舍。
- 下一建议任务：
  - `[T038] 定义统一 ApiResponse<T> 响应结构`

## 2026-07-31 22:11 — `[T038-T044] M0.6 Java 统一异常`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 接口 / 测试 / 文档 / 配置
- 目标与范围：
  - 本次实现：为全部 `/api` 业务端点增加统一成功/失败信封，完成参数、未认证、无权限、资源不存在、业务冲突和系统异常的 400/401/403/404/409/500 映射，并增加 Trace ID 入口过滤与响应透传。
  - 明确不实现：不实现 M0.7 故障模拟、真实 JWT/网关认证、Python HTTP Client/Tool、跨服务重试、Agent Run/Step、Approval 或 SSE。
- 需求与关键决策：
  - 业务背景/固定数据映射：统一包装不改变 `ORDER-003 → TASK-003(COMPLETED) → ISSUE-001(OPEN) → REVIEW-003(PENDING) → DELIVERY-003(BLOCKED)` 事实，只把原 DTO 移入 `data`。
  - 方案选择及原因：使用 `ResponseBodyAdvice` 集中包装成功结果，使用 `@RestControllerAdvice` 集中映射异常，避免 10 个既有 Controller 方法重复构造信封；用最高优先级 `OncePerRequestFilter` 在 Controller 前建立 Trace ID。
  - 契约、状态或兼容性影响：成功响应从根 DTO 变为 `ApiResponse<DTO>`，现有 Java 查询/写契约测试已同步改为读取 `data`。调用方必须先校验 `success/code/retryable`，再解析 `data`；错误分支不得匹配 `message` 文案。
  - 错误分类：400=`PARAM_VALIDATION_ERROR`，401/403=`PERMISSION_DENIED`，404=`RESOURCE_NOT_FOUND`，409=`BUSINESS_CONFLICT`，500=`INTERNAL_SERVER_ERROR`；HTTP 状态保留 401/403 的认证与授权差异。
  - 重试决策：通用 500 最终设为 `retryable=false`。写请求出现 500 时执行结果可能未知，不能诱导 Tool 使用新幂等键重复写；M0.7/M1 以后只对明确、安全的只读暂态异常增加白名单重试。
- 核心实现：
  - `business-service/src/main/java/com/productline/business/api/response/ApiResponse.java` — `ApiResponse<T>`（第 6 行）固定 `success/code/message/data/trace_id/retryable` 六字段，成功工厂在第 20 行，失败工厂在第 30 行并禁止失败响应使用 `SUCCESS`。
  - `business-service/src/main/java/com/productline/business/api/response/ApiResponseCode.java` — `ApiResponseCode`（第 3 行）定义可被后续 Tool Schema 枚举校验的稳定代码。
  - `business-service/src/main/java/com/productline/business/api/response/ApiSuccessResponseAdvice.java` — `ApiSuccessResponseAdvice`（第 15 行）只作用于业务 API Controller 包，第 26 行统一包装返回体，第 33 行跳过已包装的错误响应以避免二次信封。
  - `business-service/src/main/java/com/productline/business/api/error/GlobalApiExceptionHandler.java` — `GlobalApiExceptionHandler`（第 23 行）完成异常到状态/错误码的集中映射；401/403 分别从第 117、129 行开始，404/409 从第 141、153 行开始；第 165 行隐藏未知异常详情并按 Trace ID 记录服务端堆栈。
  - `business-service/src/main/java/com/productline/business/api/error/AuthenticationRequiredException.java` — `AuthenticationRequiredException`（第 3 行）将缺失身份与角色不足分离，使二者分别返回 401 和 403。
  - `business-service/src/main/java/com/productline/business/api/trace/TraceIdFilter.java` — `TraceIdFilter`（第 16 行）在第 30～37 行完成安全透传/生成、请求属性、响应 Header、MDC 写入与清理；第 22 行限制允许字符和 128 位长度。
  - `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java` — `validateActor`（第 276 行）将缺失用户映射为未认证，将非法长度保留为参数错误，将非 `REVIEWER` 映射为无权限。
  - `business-service/src/test/java/com/productline/business/api/ApiExceptionHandlingIntegrationTest.java` — 测试类（第 23 行）通过真实 HTTP/PostgreSQL 验证 8 组成功、400、401/403、404、409、500 和 Trace 边界；第 161 行的测试专用 500 验证响应不泄露内部详情。
  - `Makefile` — `test-java-errors`（第 43 行）提供 M0.6 独立验收，并在第 18 行纳入根级 `make test`。
  - 必要的最小关键流程：

    ```text
    HTTP 请求
    → TraceIdFilter 校验/生成 trace_id，并写 Header + request attribute + MDC
    → Controller / BusinessService
    → 成功：ResponseBodyAdvice 包装 ApiResponse.success(data)
    → 失败：GlobalApiExceptionHandler 映射 HTTP + code + retryable
    → 响应 Header X-Trace-Id 与响应体 trace_id 一致
    ```

- 代码解释与定位：
  - 整体调用/数据流：Filter 最先建立请求链路标识；Controller 继续返回原业务 DTO，成功 Advice 在序列化前将 DTO 放入 `data`；参数转换、Bean Validation、领域异常或未知异常进入全局 Handler，构造同一信封。Filter 在请求结束后清理 MDC，防止线程复用串号。
  - 核心类、函数、接口或配置项：`ApiResponse.success/failure` 保证信封基本不变量；`handleTypeMismatch`、`handleUnreadableBody` 和 `handleMethodArgumentNotValid` 覆盖主要 400 来源；`handleUnexpectedException` 只回固定文案但保留带 Trace 的服务端堆栈；`resolveTraceId` 拒绝空格、换行、超长等不安全来访值。
  - 输入、输出、异常和边界：Trace Header 允许以字母或数字开头，后续为字母、数字、点、下划线、冒号或短横线，总长 1～128；缺失/非法时生成 `trace-<uuid>`。统一信封只覆盖 `/api` 业务端点，Actuator `/health` 为兼容探针保持原结构，但响应 Header 仍含 Trace ID。
  - 关键代码位置：`ApiResponse.java:6`、`ApiSuccessResponseAdvice.java:15`、`GlobalApiExceptionHandler.java:23`、`TraceIdFilter.java:16`、`ApiExceptionHandlingIntegrationTest.java:23`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：已覆盖非法枚举、空字段、畸形 JSON、缺失身份、角色不足、资源不存在、版本冲突和未知异常。500 不回传原异常信息。当前 Java 服务没有上游 HTTP 调用，超时和畸形上游响应留到 M0.7/M1。
  - 幂等、并发或人工确认：409 继续表达版本、状态和幂等冲突，`retryable=false` 防止调用方把业务冲突当网络错误盲重试。统一异常不改变 M0.5 事务、幂等和版本逻辑；人工确认仍未实现。
- 未完成项与已知问题：
  - 未完成项：M0.7 故障模拟、真实认证、Python 错误 Schema/Tool 分支、Run/Step Trace 关联、结构化日志平台和按异常类型区分的安全重试尚未实现。
  - 已知问题/阻塞：无阻塞。测试专用 500 会按生产策略在测试日志打印预期堆栈；Mockito 动态 Java Agent 仍有未来 JDK 兼容警告。`ResponseBodyAdvice` 在运行时完成包装，未来若引入 OpenAPI 生成，需要显式补充参数化信封 Schema。
- 替代方案：
  - 采用的替代方案及原因：使用 `ResponseBodyAdvice` 兼容既有 Controller 返回类型，而未逐个把方法签名改成 `ApiResponse<DTO>`；当前身份仍使用 M0.5 Header，因为真实认证不在当前里程碑；通用 500 采用保守不可重试，而未对未知异常猜测可恢复性。
  - 已覆盖/未覆盖的验收要求：覆盖 T038～T044 的信封、400/401/403/404/409/500 和 Trace ID，并覆盖成功与既有查询/写接口回归；不覆盖未定义路由的框架错误定制、JWT 身份真实性、故障注入、跨服务 Trace 或自动重试执行。
  - 局限、风险和转正/移除条件：接入 Spring Security/网关后从可信 Principal 生成身份并移除可伪造角色 Header；引入 OpenAPI 时为信封增加明确组件 Schema；M0.7/M1 有真实故障类型和只读幂等证据后，才为特定错误设置 `retryable=true` 和有限退避。
- 后续影响：
  - 对后续任务/里程碑：M0.7 的故障响应必须继续遵守信封和 Trace 契约；M1 Python Client 必须先解析 `ApiResponse` 再解析 `data`，将 400/404/权限错误转为不可重试 Tool 错误，将 409 转为刷新事实/STALE 分支，而不是把所有非 200 当同一异常。
  - 对接口/数据/测试/部署：无数据库迁移和固定数据变化。所有现有 `/api` 客户端都需适配新增信封，这是有意的契约变更；Actuator 探针无需适配。Java 测试已更新并证明 M0.4/M0.5 业务语义未回归。
- 测试与验证：
  - `[预期失败] mvn --file business-service/pom.xml -Dtest=ApiExceptionHandlingIntegrationTest,BusinessQueryApiIntegrationTest,BusinessWriteApiIntegrationTest test` — 初始 31 个测试中 16 个失败、15 个通过；失败集中在统一包装/错误体/Trace ID 缺失及缺失身份仍为 400。
  - `[通过] 同一目标测试` — 首轮实现后 31/31 通过；补充畸形 JSON、Bean Validation 和非法 Trace 边界后，最终 33/33 通过。
  - `[通过] mvn --file business-service/pom.xml -Dtest=ApiExceptionHandlingIntegrationTest test` — 8/8，失败 0、错误 0、跳过 0。
  - `[通过] mvn --file business-service/pom.xml clean test` — 全量 48/48，失败 0、错误 0、跳过 0。
  - `[通过] make test` — 基础/Compose 检查、三服务冒烟、M0.2 7/7、M0.3 7/7、M0.4 13/13、M0.5 12/12、M0.6 8/8 全部通过。
  - 未运行项及原因：未运行 M0.7 故障模拟、Python Tool、Approval 和 Agent E2E，相关实现不在本次范围。
- 变更文件：
  - `business-service/src/main/java/com/productline/business/api/response/ApiResponse.java`
  - `business-service/src/main/java/com/productline/business/api/response/ApiResponseCode.java`
  - `business-service/src/main/java/com/productline/business/api/response/ApiSuccessResponseAdvice.java`
  - `business-service/src/main/java/com/productline/business/api/error/AuthenticationRequiredException.java`
  - `business-service/src/main/java/com/productline/business/api/error/GlobalApiExceptionHandler.java`
  - `business-service/src/main/java/com/productline/business/api/error/BusinessConflictException.java`
  - `business-service/src/main/java/com/productline/business/api/error/InvalidRequestException.java`
  - `business-service/src/main/java/com/productline/business/api/error/PermissionDeniedException.java`
  - `business-service/src/main/java/com/productline/business/api/error/ResourceNotFoundException.java`
  - `business-service/src/main/java/com/productline/business/api/trace/TraceIdFilter.java`
  - `business-service/src/main/java/com/productline/business/api/TaskWriteController.java`
  - `business-service/src/main/java/com/productline/business/application/BusinessWriteService.java`
  - `business-service/src/test/java/com/productline/business/api/ApiExceptionHandlingIntegrationTest.java`
  - `business-service/src/test/java/com/productline/business/api/BusinessQueryApiIntegrationTest.java`
  - `business-service/src/test/java/com/productline/business/api/BusinessWriteApiIntegrationTest.java`
  - `business-service/README.md`
  - `Makefile`
  - `docs/API_CONTRACT.md`
  - `docs/DOMAIN_MODEL.md`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/needCare.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；身份 Header、跨服务 Trace 未完成、OpenAPI 参数化信封待补和通用 500 保守不可重试是已知边界。
  - 后续兼容注意事项：Python/前端必须读取 `data`；写请求的 500 和 409 都不得用新幂等键盲重试；后续新增业务端点需返回可由 Jackson 包装的 DTO，或直接返回 `ApiResponse` 避免二次包装。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次稳定了 Tool 可机器判定的错误控制流、写操作保守重试边界和 Trace ID 安全透传，直接影响后续 Workflow 分支、Tool Schema 与结果可观测性。
- 下一建议任务：
  - `[T045] 增加延迟模拟参数`

## 2026-07-31 22:42 — `[T045-T049] M0.7 故障模拟`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 接口测试夹具 / 配置 / 测试 / 文档
- 目标与范围：
  - 本次实现：为 Java 只读业务 API 增加可配置、可重复的延迟、客户端超时、服务端 500、缺失字段响应和权限 403 模拟，供后续 Python Client/Tool 错误映射验收。
  - 明确不实现：不实现 M0.8 前端、Python HTTP Client/Tool、httpx 重试、熔断/降级、生产混沌平台、网络分区、连接池故障或写接口故障注入。
- 需求与关键决策：
  - 业务背景/固定数据映射：所有模拟都通过 `GET /api/orders/ORDER-003` 等既有只读端点触发；不修改固定数据，也不改变 `ORDER-003` 黄金事实。
  - Header 契约：`X-Demo-Delay-Ms` 提供 T045 的可控普通延迟；`X-Demo-Fault` 支持计划中的 `timeout`、`server-error`、`invalid-response`，并为 T049 补充 `permission-denied`。
  - 安全门禁：应用默认 `demo.faults.enabled=false`；Docker Compose 本地开发显式开启。仅 GET `/api/**` 读取模拟 Header，POST 写接口无条件忽略，防止测试设施改变业务写入或绕过幂等/版本门禁。
  - 方案选择及原因：使用 Spring MVC `HandlerInterceptor`，使 Trace Filter 已先建立 Trace ID，同时模拟 500/403 仍可进入 M0.6 `@RestControllerAdvice`；`invalid-response` 刻意直接写响应并停止 Controller 链，生成 HTTP 200 但缺少 `data` 的协议漂移样本。
  - 参数与资源保护：请求延迟受可配置上限约束，延迟和超时配置另有 60000ms 启动硬上限；非法数字、负数、越界值和未知故障类型统一返回 400。
- 核心实现：
  - `business-service/src/main/java/com/productline/business/api/fault/DemoFaultInterceptor.java` — `DemoFaultInterceptor`（第 19 行）在 `preHandle`（第 40 行）先执行可选延迟，再分派 4 类故障；`shouldSimulate`（第 66 行）强制开关、GET 和 `/api/` 三重条件；`writeInvalidResponse`（第 94 行）故意省略 `data`；`sleep`（第 110 行）恢复中断标记。
  - `business-service/src/main/java/com/productline/business/api/fault/DemoFaultProperties.java` — `DemoFaultProperties`（第 5 行）绑定开关和两个延迟值，并在第 11 行拒绝超过 60 秒的启动配置。
  - `business-service/src/main/java/com/productline/business/api/fault/DemoFaultWebConfiguration.java` — 配置类（第 8 行）注册属性和 `/api/**` 拦截器（第 18 行）。
  - `business-service/src/main/resources/application.yml` — `demo.faults`（第 22 行）默认关闭，普通延迟默认最大 2000ms，超时模拟默认 5000ms。
  - `docker-compose.yml` / `.env.example` — 本地 Compose 显式启用并暴露三个非敏感配置项；裸机启动仍需主动设置环境变量。
  - `business-service/src/test/java/com/productline/business/api/DemoFaultSimulationIntegrationTest.java` — 测试类（第 26 行）启用 300ms 测试配置；真实延迟第 41 行，Java Client 超时第 56 行，500/缺字段/403 第 75、88、102 行，参数拒绝第 114 行，写接口隔离第 128 行。
  - `business-service/src/test/java/com/productline/business/api/DemoFaultDisabledIntegrationTest.java` — 第 18 行用独立 Spring 上下文证明功能关闭时所有模拟 Header 均被忽略。
  - `Makefile` — `test-java-faults`（第 48 行）提供独立验收，并在第 18 行进入根级 `make test`。
  - 关键流程：

    ```text
    GET /api/** + 模拟 Header
    → TraceIdFilter 建立 trace_id
    → DemoFaultInterceptor 检查 enabled / GET / path
    → 可选 X-Demo-Delay-Ms
    ├─ timeout：等待后继续正常 Controller
    ├─ server-error：抛异常 → 统一 500
    ├─ permission-denied：抛权限异常 → 统一 403
    └─ invalid-response：直接返回缺少 data 的 200 JSON
    ```

- 代码解释与定位：
  - 整体调用/数据流：普通延迟只增加请求耗时，之后仍查询真实固定数据；timeout 以更长服务端等待让短超时客户端主动失败，等待结束后服务端仍完成只读请求；500/403 复用统一错误码和 Trace；缺字段响应用于验证客户端 Schema，而不是验证 JSON 解析器。
  - 输入、输出、异常和边界：`X-Demo-Delay-Ms` 允许 0 到配置上限；未知/越界为 `400/PARAM_VALIDATION_ERROR`。500 为 `INTERNAL_SERVER_ERROR`、403 为 `PERMISSION_DENIED` 且均不可重试。非法响应为合法 JSON、HTTP 200、`success=true`，但无 `data`。
  - 调用顺序原因：选择 MVC Interceptor 而非 Servlet Filter，是因为拦截器抛出的异常可由现有全局 Handler 转为统一信封；Filter 抛出的异常发生在 DispatcherServlet 外，可能退回容器默认错误体。
  - 关键代码位置：`DemoFaultInterceptor.java:19`、`DemoFaultProperties.java:5`、`DemoFaultWebConfiguration.java:8`、`application.yml:22`、`DemoFaultSimulationIntegrationTest.java:26`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：五类要求均已覆盖；模拟请求记录故障类型和路径，不记录身份或业务正文。来自 M0.6 的 Trace Header/响应体一致性在 500、403 和缺字段响应中继续验证。
  - 幂等、并发或人工确认：模拟器不作用于写方法。测试携带 `server-error` 调用复核 POST，结果仍为原有缺少身份的 401，证明模拟器没有在写业务前短路；不产生数据库副作用。
- 未完成项与已知问题：
  - 未完成项：Python `httpx` 超时、Pydantic 响应校验、Tool 错误映射、有限重试/退避、Run/Step 耗时与错误记录、前端故障展示和 Agent 降级尚未实现。
  - 已知问题/阻塞：无阻塞。阻塞式 `Thread.sleep` 会占用 Servlet 工作线程，只适合小规模开发测试；500 模拟按统一异常策略打印预期堆栈；Mockito 仍有未来 JDK 动态 Agent 警告。
- 替代方案：
  - 采用的替代方案及原因：采用应用内 MVC 拦截器模拟慢响应，而未引入 Toxiproxy、网关故障注入或容器网络控制，原因是 M0.7 只需为 M1 提供最小、确定、可独立运行的 HTTP 失败夹具，且当前仓库没有相应基础设施。
  - 已覆盖/未覆盖的验收要求：覆盖 T045～T049 的响应延迟、真实客户端超时、500、字段缺失和 403，以及默认关闭、参数限幅、Trace 和写接口隔离；不覆盖连接拒绝、连接重置、DNS、TLS、网络分区、随机抖动、并发容量或生产混沌演练。
  - 局限、风险和转正/移除条件：当需要连接层故障或并发压测时，应在隔离环境引入代理/网络级工具并保留相同测试语义；生产部署必须保持 `DEMO_FAULTS_ENABLED=false`。应用内夹具可继续服务契约测试，但不能作为生产故障平台。
- 后续影响：
  - 对后续任务/里程碑：M1 T123～T126 可直接使用这些 Header 验证 500、`httpx.Timeout`、响应字段错误和权限映射；重试测试只应对只读调用开放，并验证次数与总预算。
  - 对接口/数据/测试/部署：无数据库迁移和业务响应正常路径变化。Docker Compose 新增开发环境变量；部署配置若误设开关会开放故障 Header，因此生产清单必须显式关闭或不设置。客户端正常不发送 Header 时不受影响。
- 测试与验证：
  - `[预期失败] mvn --file business-service/pom.xml -Dtest=DemoFaultSimulationIntegrationTest,DemoFaultDisabledIntegrationTest test` — 7 个测试中 6 个失败、1 个通过；只有默认关闭保护通过，其余模拟 Header 均被忽略并正常返回 200。
  - `[通过] 同一命令` — 首轮实现 7/7；补充写接口隔离后最终 8/8，失败 0、错误 0、跳过 0。
  - `[通过] mvn --file business-service/pom.xml -Dtest=BusinessQueryApiIntegrationTest,BusinessWriteApiIntegrationTest,ApiExceptionHandlingIntegrationTest,DemoFaultSimulationIntegrationTest,DemoFaultDisabledIntegrationTest test` — M0.4～M0.7 联合 41/41。
  - `[通过] mvn --file business-service/pom.xml clean test` — 全量 56/56，失败 0、错误 0、跳过 0。
  - `[通过] make test` — 基础/Compose 检查、三服务冒烟及 M0.2～M0.7 全部分阶段验收通过。
  - `[通过] make validate` — 基础文件与 Compose 配置有效。
  - `[通过] git diff --check` — 无空白错误。
  - `[通过] API JSON/Markdown 结构检查` — 5 个 JSON 示例可解析，Markdown 围栏成对。
  - 未运行项及原因：未运行 M0.8、Python Tool、Approval 或 Agent E2E，对应实现不在本次范围。
- 变更文件：
  - `business-service/src/main/java/com/productline/business/api/fault/DemoFaultInterceptor.java`
  - `business-service/src/main/java/com/productline/business/api/fault/DemoFaultProperties.java`
  - `business-service/src/main/java/com/productline/business/api/fault/DemoFaultWebConfiguration.java`
  - `business-service/src/main/resources/application.yml`
  - `business-service/src/test/java/com/productline/business/api/DemoFaultSimulationIntegrationTest.java`
  - `business-service/src/test/java/com/productline/business/api/DemoFaultDisabledIntegrationTest.java`
  - `.env.example`
  - `docker-compose.yml`
  - `Makefile`
  - `business-service/README.md`
  - `docs/API_CONTRACT.md`
  - `docs/ROADMAP.md`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/needCare.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；生产误开故障开关和阻塞线程只适合小规模测试是主要风险。
  - 后续兼容注意事项：M1 不得把 `invalid-response` 当空数据，必须进行严格 Schema 校验；超时是否重试必须同时考虑只读幂等性、次数和总预算；不得把 Java 测试成功表述为 Python Tool 已实现。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次提供了真实 HTTP 的确定性失败夹具，并把默认关闭、只读隔离、限幅、Trace 和 HTTP 200/Schema 失败的差异落实为可执行测试，直接支撑后续 Tool 可靠性评测。
- 下一建议任务：
  - `[T050] 初始化 Vue 3 项目`

## 2026-07-31 23:11 — `[T050-T057] M0.8 最小前端业务页面`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：功能 / 前端 / 测试 / 配置 / 文档
- 目标与范围：
  - 本次实现：初始化 Vue 3、TypeScript、Vite、Pinia、Axios、Element Plus 工程；展示固定五单、订单详情、生产任务/步骤、质检/复核和交付状态；提供快速切单、统一错误展示、Trace ID、生产静态服务和 Java 同源代理。
  - 明确不实现：不实现 Agent 对话、页面上下文提交、SSE、Python Tool、Workflow、RAG、Approval、写操作或大模型调用。
- 需求与关键决策：
  - 业务背景/固定数据映射：页面默认选择黄金场景 `ORDER-003`，并从 Java `/api/orders/{id}/overview` 展示 `TASK-003(COMPLETED) → ISSUE-001(COORDINATE_SYSTEM/OPEN) → REVIEW-003(PENDING) → DELIVERY-003(BLOCKED)`；另外四单用于快速切换业务场景。
  - 方案选择及原因：浏览器统一请求同源 `/business-api`，Vite 开发代理与 Node 生产代理都移除前缀后转发 Java。这样不要求 Java 开放 CORS，生产镜像也不把容器内域名编译进浏览器资源。
  - 契约、状态或兼容性影响：前端严格读取 M0.6 六字段信封，缺少 `data` 即报 `RESPONSE_VALIDATION_ERROR`，不把 M0.7 非法响应当空业务数据；错误保留稳定 `code/traceId/retryable/status`。无 Java API、数据库和固定数据变更。
  - 并发决策：快速切单为每次详情请求分配递增序号，只有最新请求可更新 `overview/error/loading`，防止慢旧请求覆盖用户最后选择。
- 核心实现：
  - `web-console/src/api/businessClient.ts` — `BusinessApiError`（第 7 行）、Axios 实例/响应拦截器（第 29、35 行）、`requestBusinessData`（第 51 行）和信封校验（第 59 行）：统一正常、业务错误、协议错误、超时与网络错误。
  - `web-console/src/api/businessApi.ts` — `fetchOrder/fetchOrderOverview`（第 4、8 行）：封装页面实际使用的两个 Java 查询端点并编码路径参数。
  - `web-console/src/stores/orderStore.ts` — `DEMO_ORDER_IDS`（第 8 行）、`useOrderStore`（第 26 行）、`initialize`（第 41 行）、`selectOrder`（第 57 行）：管理固定五单、黄金场景、加载/错误/Trace 和最新请求门禁。
  - `web-console/src/App.vue` — 根页面（模板第 28 行）组织订单切换、错误重试、订单概览、任务、质检/复核和交付组件。
  - `web-console/src/components/OrderSwitcher.vue`、`TaskList.vue`、`QualityIssuesPanel.vue`、`DeliveryStatusPanel.vue` — 模板分别从第 21、13、18、12 行开始，对应 T052、T054、T055、T056/T057。
  - `web-console/server.mjs` — `createWebServer`（第 10 行）提供健康检查、静态资源和 SPA 回退；`proxyBusinessRequest`（第 67 行）转发运行时 Java 请求。
  - `web-console/Dockerfile` — 第 1 行开始的多阶段镜像先执行 `npm ci` 和生产构建，再只复制 `dist` 与 Node 服务。
  - 必要的最小关键片段：

    ```text
    用户选择订单 → selectedOrderId 立即更新 → requestSequence + 1
    → GET /business-api/api/orders/{id}/overview
    → 仅当 requestSequence 仍等于最新序号时写入页面状态
    ```

- 代码解释与定位：
  - 整体调用/数据流：`App.onMounted` 调用 Store → 并行查询五个固定订单 → 默认查询 `ORDER-003` 总览 → Vite/Node 代理转发 Java → Axios 拦截器校验统一信封 → Store 保存业务 DTO 和 Trace ID → 展示组件按任务层级渲染步骤、问题/复核和交付记录。
  - 核心类、函数、接口或配置项：`requestBusinessData<T>` 只在信封完整且 `success=true` 时返回 `data`；`selectOrder` 通过请求序号实现 latest-wins；`ORDER_SCENES` 仅提供演示说明，真实状态始终来自 Java。
  - 输入、输出、异常和边界：输入限定为五个演示订单 ID；输出为 Java `OrderOverview`。404/500 等统一错误保留错误码与 Trace；超时/网络失败标为可重试并提供手动重载；HTTP 200 但缺 `data` 被拒绝。页面不推断根因，不生成建议。
  - 关键代码位置：`businessClient.ts:7`、`businessClient.ts:29`、`businessClient.ts:51`、`orderStore.ts:26`、`orderStore.ts:41`、`orderStore.ts:57`、`App.vue:28`、`server.mjs:10`、`server.mjs:67`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：路径 ID 经过 URL 编码；统一错误响应和非法响应结构均有测试；生产代理上游不可用时返回 `502/UPSTREAM_UNAVAILABLE`。当前只调用公开演示查询端点，没有身份输入或权限提升。
  - 幂等、并发或人工确认：页面无写操作，因此不涉及写幂等或人工确认；详情请求竞态已用 latest-wins 测试。后续写页面不得复用“手动重试读取”的策略绕过 Approval。
- 未完成项与已知问题：
  - 未完成项：M1 Python Tool、Agent 页面上下文、对话/SSE、RAG 引用、Run/Step 与 Approval 均未实现；当前环境无可用浏览器实例，未完成截图和人工视觉回归。
  - 已知问题/阻塞：无功能阻塞。移动端布局和真实浏览器视觉仅由响应式 CSS 设计支撑，尚无 Playwright 视觉证据；Java 测试仍输出 Mockito 动态 Agent 的未来兼容警告。
- 替代方案：
  - 采用的替代方案及原因：浏览器实例不可用时，以 jsdom 页面组件测试、生产构建、生产服务测试和真实容器 HTTP 链路替代本次视觉验收；`make reset-demo` 因会删除本地持久卷未执行，改用 Testcontainers 固定数据回归及运行容器五单查询。
  - 已覆盖/未覆盖的验收要求：已覆盖五单可读取、黄金链路字段、切换交互、错误契约、生产资源和代理；未覆盖像素布局、真实浏览器 CSS/可访问性行为和持久卷重建后的 UI 复验。
  - 局限、风险和转正/移除条件：可用浏览器恢复后应增加一次桌面/移动端人工或 Playwright 验收；需要确认可删除本地演示数据时再执行 `make reset-demo`。两项均不阻塞 T050～T057 的代码与自动契约验收。
- 后续影响：
  - 对后续任务/里程碑：M1 Python Tool 可沿用 Java 信封分类，但应在 Python 用 Pydantic 独立实现服务端响应 Schema，不应依赖前端 TypeScript 类型；M3 可在此页面增加上下文采集，但必须由 Python/Java 重校验订单 ID。
  - 对接口/数据/测试/部署：新增 Node/npm 构建步骤和生产镜像；Compose Web 运行时依赖 `business-service:8080`，不再依赖 Agent 服务启动。Java 接口或信封字段变化时需同步前端类型与 7 个契约/组件测试。
- 测试与验证：
  - `[预期失败] npm test` — 初始 3 个套件因目标 API Client、Store、页面不存在而失败；生产服务测试新增后因 `createWebServer` 不存在而 1/1 失败。
  - `[失败后修复] npm run typecheck` — TypeScript 7 与 `vue-tsc` 内部导出不兼容；固定 TypeScript 6.0.3 后通过。严格数组索引检查另发现测试夹具可能为 `undefined`，增加显式非空约束后通过。
  - `[通过] make test-web` — Vitest 4 文件、7/7；Vue TypeScript 检查和 Vite 生产构建通过。
  - `[通过] npm audit && npm audit --omit=dev` — 0 个已知漏洞；移除带 6 个开发期高危传递依赖的测试工具后复测。
  - `[通过] docker compose config --quiet && docker compose build web-console` — 生产镜像构建成功，镜像内 `npm ci` 审计 0 漏洞。
  - `[通过] 真实容器 HTTP 验收` — Web 健康检查、五单查询和 `ORDER-003` 黄金链路关键字段全部通过。
  - `[通过] make test` — 基础/Compose、三服务冒烟、Java M0 回归 56/56、Web 7/7 与生产构建全部通过。
  - `[未运行] make reset-demo` — 命令会删除本地持久卷，未获单独删除授权；使用非破坏性固定数据测试替代。
  - `[未运行] 浏览器视觉验收` — 浏览器本地测试能力报告当前无可用浏览器实例。
- 变更文件：
  - `web-console/package.json`、`web-console/package-lock.json`、`web-console/tsconfig.json`、`web-console/vite.config.ts`、`web-console/index.html`
  - `web-console/src/env.d.ts`、`web-console/src/main.ts`、`web-console/src/styles.css`、`web-console/src/types/business.ts`
  - `web-console/src/api/businessClient.ts`、`web-console/src/api/businessApi.ts`
  - `web-console/src/stores/orderStore.ts`
  - `web-console/src/App.vue`、`web-console/src/components/OrderSwitcher.vue`、`web-console/src/components/OrderSummary.vue`、`web-console/src/components/TaskList.vue`、`web-console/src/components/QualityIssuesPanel.vue`、`web-console/src/components/DeliveryStatusPanel.vue`
  - `web-console/src/api/businessClient.spec.ts`、`web-console/src/stores/orderStore.spec.ts`、`web-console/src/App.spec.ts`、`web-console/src/server.spec.mjs`、`web-console/src/test/setup.ts`、`web-console/src/test/fixtures.ts`
  - `web-console/server.mjs`、`web-console/Dockerfile`、`web-console/README.md`、`docker-compose.yml`、`Makefile`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`、`doc/record.md`
  - 删除旧占位页 `web-console/src/index.html`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；视觉回归缺口和未运行破坏性重置是透明遗留。
  - 后续兼容注意事项：不得把当前页面描述为 Agent UI；前端的 `retryable` 只控制是否适合提示用户重试，不等于未来 Python Tool 自动重试策略。运行时生产代理依赖 `BUSINESS_API_URL`，部署清单必须指向可达 Java 服务。
- Agent 面试价值评估：
  - 无新增条目，未修改 `doc/needCare.md`。M0.8 是必要的业务事实展示与常规前端可靠性实现，但尚未承载 Agent 上下文、Tool 调用、步骤/引用、SSE 或 Approval；快速切单和错误展示更适合前端工程讨论，不足以单独形成 Agent 岗位面试证据。
- 下一建议任务：
  - `[T101] 使用 uv 初始化 Python 项目`

## 2026-07-31 23:38 — `[UI-001] M0.8 云端蓝灰视觉改版`

- 里程碑：M0 业务数据与 Java 接口
- 任务类型：前端视觉 / 测试 / 文档
- 目标与范围：
  - 本次实现：只调整既有 M0.8 页面的色板、层次、卡片、状态标签、字号、中文区块眉题和响应式视觉，形成清爽克制的云端蓝灰企业平台风格。
  - 明确不实现：不新增 M1、Agent 对话、图表、导航、业务接口、数据字段、状态映射、Store 行为或运行时依赖。
- 需求与关键决策：
  - 色板契约：页面背景 `#F5F7FA`、顶部导航 `#17243B`、主蓝 `#2F6BFF`、正文 `#1F2937`、次级文字 `#667085`、边框 `#E4E7EC`，成功/警告/失败分别为 `#12B76A`、`#F79009`、`#D92D20`。
  - 信息层次：仅顶部导航保留深色；侧栏改为浅蓝灰，选中订单使用淡蓝底、蓝边和左侧强调条；订单概览改为白色卡片和蓝色顶部线；普通面板统一白底、细边框、轻阴影与约 10px 圆角。
  - 语义边界：状态颜色继续表达成功、等待和失败；质检问题改为白底红色左边线，避免用大面积红底制造过度告警。页面只展示 Java 事实，不增加诊断或建议。
  - 兼容决策：保留桌面双栏、移动端横向订单切换、1000px/720px 断点，以及 `data-order-id`、`data-current-order` 和现有业务文本；只替换装饰性英文眉题。
- 核心实现：
  - `web-console/src/styles.css` — 根级 CSS 变量定义统一色板；顶部栏、浅色订单侧栏、白色概览卡、普通面板、语义标签和两个响应式断点共用同一组视觉令牌。使用系统字体，不新增图片、字体、图标库或运行时依赖。
  - `web-console/src/App.vue` — 顶栏与业务区装饰文案改为中文，明确页面是 M0 业务视图和 Java 事实源。
  - `web-console/src/components/OrderSwitcher.vue`、`OrderSummary.vue`、`TaskList.vue`、`QualityIssuesPanel.vue`、`DeliveryStatusPanel.vue` — 将英文眉题替换为“固定演示订单”“订单概览”“生产执行”“质量控制”“成果交付”；组件输入、事件和业务字段不变。
  - `web-console/src/App.spec.ts` — 增加五个中文区块标识断言，防止视觉文案回退，同时保留五单、黄金链路和快速切单断言。
- 代码解释与定位：
  - 整体渲染流不变：Store 读取 Java 总览 → `App.vue` 组合订单切换和业务面板 → 组件渲染固定事实 → `styles.css` 仅决定视觉呈现。此次没有进入 API Client、Pinia Store 或 DTO 层。
  - 色板通过根变量集中管理，再由导航、侧栏、概览、面板和状态类消费；后续更换品牌色时无需逐组件修改硬编码颜色。
  - 1000px 以下由双栏收敛为单列并把订单列表变为横向滚动；720px 以下进一步调整顶部栏、内容间距和概览字段网格，业务 DOM 与选择行为保持一致。
  - 测试只对稳定的中文业务区块做文本断言，不绑定阴影、像素或 class 细节，避免合理视觉微调造成脆弱测试。
- 异常、安全与边界：
  - 错误卡片、重试按钮、Trace ID 和状态语义仍由原组件/Store 驱动；没有改变错误是否可重试、Trace 解析或 Java 事实来源。
  - `ORDER-003` 黄金事实和 `ORDER-005` 切换路径仍由既有组件测试覆盖；本次不涉及写操作、权限、幂等或 Approval。
- 未完成项与已知问题：
  - 未完成项：真实浏览器桌面与移动端截图/人工视觉验收未完成。
  - 已知问题/阻塞：无功能阻塞；应用内浏览器能力在读取故障排查说明并重试后仍返回空列表，因此当前没有像素级、字体渲染或真实滚动行为证据。
- 替代方案：
  - 采用原因：浏览器实例不可用时，使用 jsdom 组件测试、CSS 规则检查、TypeScript 检查和 Vite 生产构建作为阶段性证据，避免引入计划外浏览器依赖或绕过指定测试能力。
  - 已覆盖/未覆盖：覆盖 DOM 文案、五单与黄金链路功能回归、响应式规则存在、类型和生产打包；不覆盖真实浏览器像素布局、系统字体差异、横向滚动手感和视觉主观验收。
  - 局限与移除条件：可用浏览器恢复后，应分别在桌面、1000px 附近和 720px 以下检查 `ORDER-003`、`ORDER-005` 与错误态；完成后可关闭该视觉证据缺口，无需改变运行时代码。
- 后续影响：
  - 对后续任务/里程碑：无 M1 功能影响；未来增加 Agent 面板时应复用本次色板与轻量面板层次，但不能把当前业务页面称为 Agent UI。
  - 对接口/数据/测试/部署：Java API、Axios Client、Pinia Store、DTO、固定数据、Docker 代理和数据库均不变；CSS 构建产物从 49.57 kB 增至 51.77 kB（gzip 从 8.34 kB 增至 8.61 kB），无部署配置变化。
- 测试与验证：
  - `[预期失败] npm test -- --run src/App.spec.ts` — 1 个测试、1 个失败；旧模板尚无五个中文区块标识。
  - `[通过] 同一命令` — 1/1。
  - `[通过] make test-web` — Vitest 4 文件、7/7；Vue TypeScript 检查与 Vite 生产构建通过。
  - `[通过] npm --prefix web-console audit --omit=dev` — 0 个已知漏洞。
  - `[通过] node --check web-console/server.mjs` — Node 生产服务脚本语法有效。
  - `[通过] 静态视觉规则检查` — 旧英文眉题、旧墨绿色值和 8～10px 字号均无匹配。
  - `[未运行] Java 测试` — 本次未修改 Java、接口契约或业务逻辑，按计划不重复运行。
  - `[未运行] 浏览器视觉验收` — 应用内浏览器列表两次均为空。
- 变更文件：
  - `web-console/src/styles.css`
  - `web-console/src/App.vue`
  - `web-console/src/components/OrderSwitcher.vue`
  - `web-console/src/components/OrderSummary.vue`
  - `web-console/src/components/TaskList.vue`
  - `web-console/src/components/QualityIssuesPanel.vue`
  - `web-console/src/components/DeliveryStatusPanel.vue`
  - `web-console/src/App.spec.ts`
  - `docs/STATUS.md`
  - `docs/TEST_REPORT.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无功能阻塞；真实浏览器视觉验收是唯一遗留证据缺口。
  - 后续兼容注意事项：后续业务/Agent UI 应复用 CSS 变量，不要重新引入大面积深色或硬编码语义色；组件测试依赖的业务文本与 `data-*` 属性应继续保留。
- Agent 面试价值评估：
  - 无新增条目，未修改 `doc/needCare.md`。本次是纯视觉与展示文案调整，没有新增 Agent、Tool、Workflow、RAG、上下文、Approval、评测或模型/业务边界实现，不满足 Agent 岗位面试价值门禁。
- 下一建议任务：
  - 浏览器能力恢复后补一次桌面与移动端视觉验收；用户恢复功能开发时再进入 `[T101] 使用 uv 初始化 Python 项目`。

## 2026-07-31 23:54 — `[T101-T108] M1.1 Python 工程初始化`

- 里程碑：M1 Python Tool 层
- 任务类型：工程基础 / FastAPI / 数据库 / 可观测性 / 测试 / 配置 / 文档
- 目标与范围：
  - 本次实现：使用 uv 管理 Python 3.12 和锁文件；将无依赖 HTTP 占位替换为 FastAPI；配置 pytest、Ruff、mypy；建立异步 SQLAlchemy、Alembic、JSON 日志和请求 Trace ID 基础。
  - 明确不实现：不实现 T109 之后的 Java HTTP Client、错误映射、Tool 协议、重试、Workflow、模型调用、Run/Step 实体、RAG 或 Approval。
- 需求与关键决策：
  - 版本和依赖：`.python-version` 固定 3.12，`requires-python` 限定 `>=3.12,<3.13`；`pyproject.toml` 声明运行时/开发依赖，`uv.lock` 保存 42 个解析结果，Docker 使用 `--frozen --no-dev` 安装。
  - 应用工厂：`create_app(settings)` 支持测试注入；FastAPI lifespan 创建惰性异步 Engine 并在停止时 `dispose`，健康检查保持既有 `service/status` 契约。
  - 数据边界：`Base` 只面向后续 Agent Run/Step/Approval/RAG 元数据，不映射 Java 业务表；Alembic 使用独立 `agent_alembic_version`，避免与 Java Flyway 历史表混淆。
  - Trace 与日志：请求头 `X-Trace-Id` 仅接受 1～128 位安全字符，否则生成 `trace-UUID`；JSON 日志固定保存 Trace、方法、路径、状态和耗时，不记录数据库 URL、Token 或请求正文。
  - 探针语义：`/health` 是 liveness，不主动连接数据库。这样数据库短暂不可用时不会把“依赖未就绪”误判为“进程已死”；readiness 留给后续独立任务。
- 核心实现：
  - `agent-service/pyproject.toml` / `.python-version` / `uv.lock` — Python 3.12、运行/开发依赖、pytest 标记、Ruff 规则、mypy strict 和可重复锁定环境。
  - `agent-service/app/main.py` — `create_app` 组织 lifespan、数据库资源、Trace 中间件和 `/health`；`main` 读取设置并启动 Uvicorn。
  - `agent-service/app/settings.py` — `Settings` 校验环境、端口、日志级别和数据库 URL，并将 Compose 的 `postgresql://` 转为 `postgresql+asyncpg://`。
  - `agent-service/app/database.py` — `Base`、惰性 `AsyncEngine`、`async_sessionmaker`、Session 上下文和关闭释放。
  - `agent-service/app/observability.py` — `ContextVar` 保存请求 Trace，`JsonFormatter` 输出白名单字段，`TraceIdMiddleware` 绑定响应 Header 和请求日志。
  - `agent-service/alembic.ini` / `migrations/env.py` / `script.py.mako` — 异步 Alembic 环境、Agent 独立版本表和迁移模板；M1.1 无数据表 revision。
  - `agent-service/tests` — 6 个测试覆盖健康检查/Trace、数据库 URL/Session、JSON 日志和 Alembic 结构。
  - `agent-service/Dockerfile` — 从官方 uv 镜像复制 0.12.0 二进制，在 Python 3.12 slim 中按锁文件安装非开发依赖，并直接使用 `.venv` 启动。
  - `Makefile` / `scripts/smoke-services.sh` — 新增 `test-agent-foundation`、`quality`、容器内 `agent-migrate`，根级 `make test` 纳入 Python 6 个测试，冒烟改为 uv/Python 3.12。
- 代码解释与定位：
  - 启动流：`python -m app.main` → `get_settings` → Uvicorn → FastAPI lifespan → 创建不立即联网的 `Database` → 请求进入 Trace 中间件 → `/health` → 响应写回同一 Trace → 结构化请求日志 → 应用停止释放 Engine。
  - 数据流：`DATABASE_URL` 由 Pydantic Settings 读取并验证 → 转换 asyncpg dialect → SQLAlchemy 生成 Engine/Session Factory；只有未来代码显式进入 Session 并执行语句才会连接。当前没有任何业务表查询。
  - 迁移流：根级 `make agent-migrate` 在 Compose 网络内运行 Alembic → `migrations/env.py` 读取同一设置 → 使用 `Base.metadata` 与独立版本表执行 revision。当前无业务 revision，首次执行只创建空的 `agent_alembic_version`，不触碰 Java 业务表。
  - Trace 流：优先复用安全来访值，非法/缺失则生成 → `ContextVar` 让同一异步请求日志读取 → 响应 Header 回传 → finally 重置，防止请求间串值。
- 异常、安全与边界：
  - 配置错误：非法端口/环境/日志级别由 Pydantic 拒绝；非 PostgreSQL URL 在创建数据库时失败，不带错误 URL 输出启动日志。
  - 数据安全：Python 没有 Java 业务 Entity/Repository；当前共享开发数据库角色仍是权限隔离缺口，生产前需独立数据库或 Schema/角色。
  - Trace 安全：拒绝空格、换行、超长和非白名单字符；日志只复制白名单附加字段。
- 未完成项与已知问题：
  - 未完成项：Java HTTP Client、Pydantic Java 响应 Schema、Tool/错误/重试、readiness、Run/Step 表和端到端 Trace 尚未实现。
  - 已知问题/阻塞：无功能阻塞。本机 PostgreSQL 与 Docker 都监听 5432，宿主机 `127.0.0.1:5432` 优先连接本机实例，直接运行 Alembic 会得到“role agent does not exist”；本地 Compose 仍共用 Java 数据库角色；Java 测试仍有 Mockito 动态 Agent 警告。
- 替代方案：
  - 采用原因：将根级 `agent-migrate` 放到 Compose 容器内执行，避免宿主端口冲突、`postgres` 容器主机名不可解析和凭据漂移；M1.1 暂不创建独立数据库/角色，以免扩大 M0 数据初始化范围。
  - 已覆盖/未覆盖：覆盖 Alembic 在与应用一致的 Python 3.12、锁定依赖、Compose 网络和环境变量下运行；不提供宿主机直连，也没有权限层阻止 Python 查询已有 Java 表。
  - 局限与移除条件：生产部署或开始持久化 Run/Step 前，应建立独立 Agent 数据库/Schema 与最小权限角色，再调整 `DATABASE_URL`；若宿主机开发需要直连，应使用未冲突端口和本地专用凭据。
- 后续影响：
  - 对后续任务/里程碑：T109～T117 可直接复用 Settings、lifespan、Trace 上下文、pytest/httpx 和结构化日志；Java Client 应把当前 Trace 透传到 `X-Trace-Id`，并在未来 Step 中同时保存 Run/Step/Trace。
  - 对接口/数据/测试/部署：`/health` 响应体保持兼容并新增/稳定 Trace Header；未修改 Java API、固定数据或前端。Agent 镜像现在依赖 `pyproject.toml`/`uv.lock`，依赖变更必须重新 lock；数据库只新增空的 Agent Alembic 版本表，尚无 Run/Step 等业务表。
- 测试与验证：
  - `[预期失败] uv lock && uv run --frozen pytest -q` — 收集阶段 3 个导入错误，目标数据库、可观测性和应用工厂尚未实现。
  - `[失败后修复] pytest` — 首轮 5/6，Alembic `%(here)s` 已展开而测试比较原文本；改为绝对路径后 6/6。
  - `[失败后修复] mypy app tests` — 测试中的 `get_main_option` 为 `str | None`；增加显式非空断言后通过。
  - `[通过] make test-agent-foundation` — pytest 6/6。
  - `[通过] make quality` — Ruff 全部通过；mypy strict 检查 9 个文件无问题。
  - `[通过] uv lock --check` — 锁文件有效；Python 3.12.13。
  - `[通过] docker compose build agent-service && docker compose up --detach agent-service` — 镜像构建和容器启动成功。
  - `[通过] 容器 HTTP/JSON 日志验收` — 健康检查 200、Trace Header 一致，请求日志含 Trace/方法/路径/状态/耗时。
  - `[通过] docker compose exec -T agent-service /service/.venv/bin/alembic current` — 异步连接成功，无 revision/数据变更。
  - `[通过] make agent-migrate` — 容器内 `upgrade head` 成功，创建独立 `agent_alembic_version`，无 Agent 业务 revision。
  - `[通过] make test-business-data` — 迁移后 Java 固定数据与状态一致性 7/7，证明空 Agent 版本表未影响业务基线。
  - `[通过] make smoke` — Agent、Business、Web 健康检查通过。
  - `[通过] make test` — Python 6/6、Java M0 56/56、Web 7/7 和生产构建全部通过。
- 变更文件：
  - `agent-service/.python-version`、`pyproject.toml`、`uv.lock`
  - `agent-service/app/main.py`、`settings.py`、`database.py`、`observability.py`
  - `agent-service/alembic.ini`、`migrations/env.py`、`migrations/script.py.mako`、`migrations/versions/.gitkeep`
  - `agent-service/tests/test_health.py`、`test_database.py`、`test_observability.py`、`test_alembic.py`
  - `agent-service/Dockerfile`、`.dockerignore`、`README.md`
  - `Makefile`、`scripts/smoke-services.sh`、`docker-compose.yml`、`.env.example`、`README.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`、`doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；数据库权限隔离、readiness 和跨服务 Trace 尚未完成。
  - 后续兼容注意事项：不得在 Python 添加 Java 业务表 ORM；T109 应复用 Settings 而不是散落环境读取；T112 应透传当前 Trace；后续迁移必须使用 `agent_alembic_version` 并先解决生产数据库权限边界。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。价值不在 FastAPI/uv 样板，而在已落地的 Agent 自有状态与 Java 业务事实边界、Trace 安全传播和结构化日志基础，同时明确记录了尚未完成的数据库权限隔离与 Run/Step 追踪。
- 下一建议任务：
  - `[T109] 定义 Java Client 配置模型`。

## 2026-08-01 18:31 — `[DOC-004] 整理 Python 工程学习手册`

- 里程碑：M1 Python Tool 层（配套知识文档）
- 任务类型：文档 / 重构 / 校验
- 目标与范围：
  - 本次实现：以当前 `agent-service` 真实实现为唯一事实来源，重构
    `doc/pythonKnowledge.md`；合并原文与 M1.1 代码讲解，去除重复内容，并持续使用
    Java Spring Boot、Node.js 类比帮助第一次接触 Python 项目的开发者理解。
  - 明确不实现：不修改 Python/Java/Web 运行代码、接口、配置、依赖、数据库、固定数据、
    `doc/needCare.md`、项目状态或测试报告。
- 需求与关键决策：
  - 业务背景/固定数据映射：手册明确 Python 只能保存 Agent 自有状态，不能映射 Java 的订单、
    任务、质检、复核和交付表；本次不变更 `ORDER-003` 黄金链路。
  - 方案选择及原因：按照“工程对应关系 → 目录与依赖 → 核心模块 → 生命周期 → 迁移/测试/
    容器 → Python 语法 → 能力边界”组织知识，通用概念直接放入对应项目文件章节，不保留
    脱离仓库的重复教程。
  - 事实更正：删除旧项目的目录、数据库、镜像、迁移、健康接口和 Make 命令；改为当前
    `agent-service/`、根级 Compose、`pgvector/pgvector:pg16`、`remote_sensing_agent`、
    `/health` liveness、空 Agent Alembic 版本表及当前根级命令。
  - 契约、状态或兼容性影响：无运行时契约变化；文档明确 Compose 中 Java URL/模型变量尚未被
    `Settings` 消费，Run/Step、Client、Schema、Tool、Workflow 和 RAG 均未实现。
- 核心实现：
  - `doc/pythonKnowledge.md` — 当前项目 Python 入门手册：说明 Python/Java/Node 工程对应、
    Uvicorn/FastAPI/Pydantic/SQLAlchemy/asyncpg/Alembic 协作、启动/请求/关闭顺序、迁移测试与
    初学者语法重点。
  - 必要的最小关键片段：无运行时代码；核心调用链统一为：

    ```text
    uv/Python 3.12 → Uvicorn → FastAPI lifespan → TraceIdMiddleware
    → /health + Pydantic 响应 → JSON 日志 → lifespan 释放 Engine
    ```

- 代码解释与定位：
  - 整体调用/数据流：手册先说明三服务边界，再沿当前 Python 进程的配置、应用、数据库、
    可观测性和生命周期解释代码，最后收束到尚未实现的 T109+ 目录。
  - 核心类、函数、接口或配置项：解释 `HealthResponse`、`create_app`、lifespan、`Settings`、
    `Base`、`Database`、`JsonFormatter`、`TraceIdMiddleware` 和 `/health` 的实际职责与类比。
  - 输入、输出、异常和边界：说明环境变量经 Pydantic 校验、数据库 URL 转换、Trace 白名单、
    Session 生命周期及 liveness 不检查数据库；避免把占位环境变量或 pgvector 镜像描述为能力。
  - 关键文档位置：`doc/pythonKnowledge.md:1`（定位与范围）、`:15`（工程类比）、`:230`
    （应用入口）、`:356`（配置）、`:401`（数据库）、`:593`（执行顺序）、`:883`（Python
    语法）、`:984`（能力边界）。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：本次没有运行时输入；文档如实标注共享开发数据库角色尚未做到
    权限级隔离，未来 Java Client 的超时、错误映射和重试尚未实现。
  - 幂等、并发或人工确认：本次无写接口；手册仅解释 `ContextVar` 的异步并发隔离，不把未来
    Approval 或写入幂等描述为已完成。
- 未完成项与已知问题：
  - 未完成项：本次文档整理范围内无；T109 之后的 Client、Schema 和 Tool 仍按计划待开发。
  - 已知问题/阻塞：无。
- 替代方案：
  - 采用的替代方案及原因：无。
  - 已覆盖/未覆盖的验收要求：已覆盖当前仓库文件、符号、命令、结构和错误事实清理；不运行
    业务测试，因为没有修改运行时代码。
  - 局限、风险和转正/移除条件：无阶段性替代方案；后续实现变化时需同步维护手册。
- 后续影响：
  - 对后续任务/里程碑：为 T109 Java Client 和后续 Tool 开发提供当前工程基线，预计目录明确
    标为计划而不是已实现能力。
  - 对接口/数据/测试/部署：无影响；没有修改接口、数据、依赖或部署配置。
- 测试与验证：
  - `[通过] 旧项目标识搜索` — 指定的 10 类旧路径、数据库、镜像、接口、迁移和 Make 命令
    均为 0 处匹配。
  - `[通过] 文档结构检查` — 154 个代码围栏成对、标题层级连续、无重复标题。
  - `[通过] 仓库事实检查` — 文档链接的 20 个文件均存在；9 个核心类/函数和 6 个 Make 目标
    均可在当前仓库定位。
  - `[通过] make validate` — M0.1 基础文件检查通过，Compose 配置有效。
  - `[通过] git diff --check` — 追加记录前检查无空白错误；追加后再次复验。
  - `[未运行] Java/Python/Web 业务测试` — 本次只整理知识文档，不修改运行时代码或配置。
- 变更文件：
  - `doc/pythonKnowledge.md`
  - `doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无。
  - 后续兼容注意事项：实现 T109+ 后应更新 `Settings`、Client、Schema、Tool 和执行链章节；
    不得继续把预计目录当成已存在文件。
- Agent 面试价值评估：
  - 无新增条目，未修改 `doc/needCare.md`。本次只是整理由 M1.1 已实现内容产生的学习材料，
    没有新增 Agent、Tool、Workflow、RAG、Approval、评测或可靠性实现证据。
- 下一建议任务：
  - `[T109] 定义 Java Client 配置模型`。

## 2026-08-01 18:54 — `[T109-T117] M1.2 Java HTTP Client`

- 里程碑：M1 Python Tool 层
- 任务类型：功能 / Schema / 测试 / 配置 / 文档
- 目标与范围：
  - 本次实现：建立 Python 到 Java 的共享异步 HTTP Client，完成 Base URL、分项超时、
    生命周期、身份/Token/Trace 透传、GET/POST、幂等键以及成功响应双层 Schema 校验。
  - 明确不实现：不实现 M1.3 标准 Tool 错误映射、M1.4 Tool 协议、M1.5 端点 Tool、M1.6
    自动重试、Workflow、模型调用、RAG、Run/Step 或 Approval。
- 需求与关键决策：
  - 业务背景/固定数据映射：Python 只通过 Java `/api/**` 获取事实；真实容器验收读取
    `ORDER-003=QUALITY_CHECKING`，没有为 Java 订单表增加 Python ORM。
  - 方案选择及原因：统一成功信封与具体 data 分两层校验。第一层固定六字段，第二层由调用方
    传入 Pydantic Model；避免 HTTP 200 或统一信封正常时把缺字段业务数据交给 Tool/模型。
  - 生命周期：FastAPI lifespan 创建一个共享 `httpx.AsyncClient` 并在关闭时释放连接池，避免
    每次 Tool 调用新建连接；数据库和 HTTP Client 的关闭使用嵌套 `finally`，保证一方关闭失败
    时仍尝试释放另一方。
  - 网络边界：只接受 `/api/` 相对路径，内部 Client 设置 `trust_env=False`。首轮测试实际发现
    宿主机 SOCKS 代理会导致无 Mock Client 初始化失败，内部服务流量改为只服从受控 Base URL。
  - 写安全：POST 要求身份和安全格式幂等键，但不自动重试。超时/500 下服务端写入结果可能
    未知，M1.2 不绕过 Java 幂等、版本和操作日志边界。
  - 契约、状态或兼容性影响：httpx 从开发依赖转为生产依赖；新增四个可配置超时环境变量。
    未修改 Java API、固定数据或 Web 契约。
- 核心实现：
  - `agent-service/app/clients/business.py` — `BusinessHttpClient`：共享连接池、GET/POST、相对
    路径限制、身份/Trace/幂等 Header、HTTP 状态检查和成功响应校验；
    `BusinessResponseValidationError` 不包含原始响应 Body，避免错误信息泄露上游数据。
  - `agent-service/app/schemas/business.py` — `BusinessIdentity` 使用 `SecretStr` 隐藏 Token；
    `BusinessSuccessEnvelope` 严格校验 Java 六字段；`BusinessResponse[DataT]` 返回强类型 data。
  - `agent-service/app/settings.py` — `AnyHttpUrl` Base URL，以及 connect/read/write/pool 四项
    `>0` 且 `<=60s` 配置。
  - `agent-service/app/main.py` — lifespan 创建 `BusinessHttpClient`、保存到
    `application.state.business_client`，停止时先关闭 HTTP 连接池再释放数据库 Engine。
  - 必要的最小关键片段：

    ```text
    HTTP status
    → BusinessSuccessEnvelope
    → TypeAdapter(endpoint data model)
    → Header/Body Trace equality
    → BusinessResponse[DataT]
    ```

- 代码解释与定位：
  - 整体调用/数据流：未来 Tool 取得应用级 Client → Client 构造身份和 Trace Header → httpx
    使用连接池与分项超时请求 Java → 先校验 HTTP，再校验信封和 data → 返回可供 Tool 使用的
    强类型事实。当前还没有具体 Tool。
  - 核心类、函数、接口或配置项：`BusinessHttpClient`（第 33 行）、`get`（第 66 行）、`post`
    （第 82 行）、`_build_headers`（第 112 行）、`_validate_success_response`（第 132 行）；
    `BusinessIdentity`（Schema 第 13 行）、`BusinessSuccessEnvelope`（第 33 行）、
    `BusinessResponse`（第 50 行）；Settings HTTP 配置第 27 行；lifespan 集成第 35 行。
  - 输入、输出、异常和边界：GET 输入相对路径、可选身份/Trace/查询参数；POST 额外要求 JSON、
    身份和幂等键；输出为 `BusinessResponse[DataT]`。4xx/5xx 保留 `HTTPStatusError`，超时保留
    httpx 异常，非法 JSON/Schema/Trace 转为 Client 校验异常，等待 M1.3 映射。
  - 关键代码位置：`agent-service/app/clients/business.py:33`、`:66`、`:82`、`:112`、`:132`；
    `agent-service/app/schemas/business.py:13`、`:33`、`:50`；`agent-service/app/settings.py:27`；
    `agent-service/app/main.py:35`；`agent-service/tests/test_business_client.py:36`。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：身份 Header 禁止空值、换行和超长；Token 不进入 repr；Trace 使用
    既有安全生成规则；超时分四类；Client 不打印原始响应。Java 仍是最终权限校验者。
  - 幂等、并发或人工确认：共享 AsyncClient 支持并发连接池；POST 强制幂等键但没有自动重试；
    Approval 未实现，不能将 POST Client 描述为 Agent 已可写回。
- 未完成项与已知问题：
  - 未完成项：T118～T126 标准错误映射、端点业务 DTO、具体 Tool、只读重试与真实故障到标准
    错误的端到端测试尚未实现。
  - 已知问题/阻塞：无功能阻塞；Java 测试仍输出 Mockito 动态 Agent 的未来 JDK 兼容警告。
- 替代方案：
  - 采用的替代方案及原因：无临时替代方案。MockTransport 用于确定性覆盖请求和异常分支，
    同时使用 Compose 真实 Java 请求补充跨服务成功链路证据，两者是不同层级测试。
  - 已覆盖/未覆盖的验收要求：已覆盖 T109～T117 和真实 `ORDER-003` 成功调用；未覆盖 M1.3
    错误码映射和真实故障恢复，因为属于下一子阶段。
  - 局限、风险和转正/移除条件：MockTransport 不证明真实网络故障分类；M1.3 应接入 Java
    故障夹具验证 403/404/500/超时/非法响应，并保留当前单元测试。
- 后续影响：
  - 对后续任务/里程碑：T118 可直接基于 `HTTPStatusError`、`TimeoutException` 和
    `BusinessResponseValidationError` 建立标准错误；T127+ Tool 应复用应用级 Client，禁止
    直接新建 httpx 或信任原始 JSON。
  - 对接口/数据/测试/部署：Agent 生产镜像新增 httpx 运行依赖；Compose 新增四项超时配置；
    Java API、数据库和前端不变。部署需要保证 `BUSINESS_SERVICE_URL` 在服务网络内可达。
- 测试与验证：
  - `[预期失败] uv run --frozen pytest -q tests/test_business_client.py` — 收集阶段 1 个导入错误，
    `app.clients` 尚不存在。
  - `[失败后修复] 同一测试` — 首轮 8/10；宿主机 SOCKS 代理导致 2 个 Client 初始化失败；
    设置 `trust_env=False` 后 10/10。
  - `[通过] make test-agent-foundation` — M1.1 6/6。
  - `[通过] make test-agent-client` — M1.2 10/10。
  - `[通过] make quality` — Ruff 全部通过；mypy strict 检查 14 个文件无问题。
  - `[通过] uv lock --check && pytest -q` — 锁文件解析 42 个包；Python 16/16。
  - `[通过] docker compose up --detach --build business-service agent-service` — 两镜像构建、
    容器启动成功，Agent 生产环境安装 29 个非开发依赖。
  - `[通过] 真实容器 Client 验收` — `ORDER-003 QUALITY_CHECKING trace-m12-real`。
  - `[通过] make smoke` — 三服务通过。
  - `[通过] make test` — Python 16/16、Java M0 56/56、Web 7/7 与生产构建全部通过。
  - `[通过] git diff --check` — 无空白错误。
  - `[未运行] make reset-demo` — 本次没有修改固定数据，且该命令会删除本地数据卷；完整
    Testcontainers 数据回归和运行容器 `ORDER-003` 查询已覆盖非破坏性验证。
- 变更文件：
  - `agent-service/app/clients/__init__.py`、`business.py`
  - `agent-service/app/schemas/__init__.py`、`business.py`
  - `agent-service/app/settings.py`、`main.py`、`database.py`、`observability.py`
  - `agent-service/tests/test_business_client.py`、`test_health.py`
  - `agent-service/pyproject.toml`、`uv.lock`、`README.md`
  - `.env.example`、`docker-compose.yml`、`Makefile`、`README.md`
  - `doc/pythonKnowledge.md`、`doc/needCare.md`、`doc/record.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；标准错误、重试和 Tool 尚未完成是明确停止线，不是隐藏能力。
  - 后续兼容注意事项：Java 信封或 Trace 契约变化时必须同步 `BusinessSuccessEnvelope` 和测试；
    写 Tool 必须保持幂等键、版本校验、Approval 和禁止盲重试；内部调用如确需代理，应增加
    显式受控代理配置，不能重新启用环境隐式代理。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次把业务事实进入 Agent 前的 Schema 门禁、身份/Trace
    边界、写请求幂等与重试停止线以及代理环境故障定位落实为真实实现和测试。
- 下一建议任务：
  - `[T118] 定义 ToolException 基类`。
