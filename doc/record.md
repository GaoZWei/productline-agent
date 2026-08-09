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

## 2026-08-03 21:16 — `[T118-T126] M1.3 标准错误模型`

- 里程碑：M1 Python Tool 层
- 任务类型：功能 / Schema / 测试 / 文档
- 目标与范围：
  - 本次实现：定义 9 类 `ToolErrorCode` 和结构化 `ToolException`；把 Java
    400/401/403/404/409/500、httpx 四类 timeout、其他网络异常以及非法响应映射为稳定错误。
  - 明确不实现：不实现 M1.4 Tool 协议、M1.5 业务 Tool/DTO、M1.6 自动重试、M1.7 重复调用
    检测、Workflow、Run/Step、模型调用或 Approval。
- 需求与关键决策：
  - 业务背景/固定数据映射：错误层不修改 `ORDER-003` 或 Java 业务事实；它保证未知资源、权限、
    上游故障或不完整 data 不会作为正常业务事实进入未来 Tool/Agent。
  - 方案选择及原因：`ToolException` 保存 `code/message/retryable/trace_id/status_code`。Workflow
    后续按 code 分支，message 只给人阅读；status_code 保留 401/403 的协议差异。
  - 双向契约校验：失败响应先由 `BusinessErrorEnvelope` 严格校验，再核对 HTTP 状态、Java
    code 及 Header/Body Trace；不一致统一归为 `RESPONSE_VALIDATION_ERROR`，避免错误分类漂移。
  - 安全异常：网络错误只暴露固定文案，原始 httpx 异常通过 Python 异常因果链保留，不把
    内部 URL、代理或连接细节交给 Workflow/模型。
  - 重试边界：timeout 和网络错误标记 `retryable=true` 只描述技术可恢复性，Client 本次仍只
    调用一次。500 继承 Java `retryable=false`；写操作是否允许重放必须由后续 Tool 风险策略、
    幂等和版本共同决定。
  - 契约、状态或兼容性影响：`BusinessHttpClient.get/post` 不再向上泄露 `HTTPStatusError`、
    `TimeoutException` 或响应校验异常，而是统一抛 `ToolException`；Java API、固定数据、前端和
    数据库不变。
- 核心实现：
  - `agent-service/app/errors.py` — `ToolErrorCode` 定义 9 类机器错误；`ToolException` 提供安全
    文案、可重试性、Trace 与 HTTP 状态。
  - `agent-service/app/schemas/business.py` — `BusinessErrorEnvelope` 严格限定 Java 失败信封、
    允许错误码、`data=null`、安全 Trace 和当前 `retryable=false` 契约。
  - `agent-service/app/clients/business.py` — `_raise_request_error` 映射网络/超时；
    `_validate_response` 分流成功与失败；`_raise_java_error` 完成状态/code/Trace 门禁；
    `_raise_response_validation_error` 统一隐藏原始响应内容。
  - `agent-service/tests/test_tool_errors.py` — 参数化覆盖 Java 六类 HTTP 映射、四类 timeout、
    网络故障和五类响应契约错误，并断言 Client 不提前重试。
  - 必要的最小关键片段：

    ```text
    Java/网络失败
    → 识别传输错误或校验 BusinessErrorEnvelope
    → 核对 HTTP status + Java code + Header/Body Trace
    → ToolException(code, retryable, trace_id, status_code)
    → 后续 Tool/Workflow 按 code 分支
    ```

- 代码解释与定位：
  - 整体调用/数据流：未来 Tool 调用共享 Client；正常响应继续走成功信封和 data 双层校验；
    非正常响应先区分传输异常和 Java HTTP 错误，校验后只向上暴露标准异常。
  - 输入、输出、异常和边界：输入仍是 M1.2 的路径、身份、Trace、params/json；成功输出仍是
    `BusinessResponse[DataT]`，失败输出变为 `ToolException`。本地非法路径/幂等键仍是调用方
    编程错误，端点输入 Schema 的 `PARAM_VALIDATION_ERROR` 留给具体 Tool。
  - `DUPLICATE_CALL` 和 `UNKNOWN_TOOL_ERROR` 只定义词汇；没有在 Client 层制造不属于它的触发
    逻辑，分别等待 M1.7 重复调用检测和 M1.4 Tool 执行边界。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：400、401/403、404、409 均不可重试；Java 500 映射上游不可用
    但保留不可重试；网络和 timeout 标记技术上可恢复；Schema/Trace 漂移不可重试。
  - 幂等、并发或人工确认：没有自动重试；尤其 POST timeout 仍可能服务端已经提交，未来写
    Tool 必须继续依赖稳定幂等键、版本校验、状态重查和 Approval。
- 未完成项与已知问题：
  - 未完成项：Tool 协议、端点 DTO、具体只读 Tool、有限重试、重复调用检测、Run/Step 和 Agent
    E2E 尚未实现。
  - 已知问题/阻塞：无功能阻塞；Java 测试仍输出 Mockito 动态 Agent 的未来 JDK 兼容警告。
- 替代方案：
  - 采用的替代方案及原因：参数化测试使用 `httpx.MockTransport` 精确覆盖所有分支；同时对
    已运行的真实 Java 容器执行 6 条故障验收。Mock 用于确定性和边界组合，真实请求用于证明
    两服务契约能实际对接，两者不是功能降级。
  - 已覆盖/未覆盖的验收要求：覆盖 T118～T126、真实 400/403/404/500/超时/非法响应和完整
    M0 回归；未覆盖自动恢复成功率或 Tool/Workflow 错误展示，因为对应能力尚未实现。
  - 局限、风险和转正/移除条件：真实故障验收使用开发环境故障 Header 和一次性传输适配器，
    不进入生产代码；未来正式跨服务集成测试可复用 Java 测试容器并自动管理服务生命周期。
- 后续影响：
  - 对后续任务/里程碑：T127+ Tool 应只消费 `ToolException.code`，不得解析 message；M1.6 只能
    对明确只读、`retryable=true` 的错误设置有限重试，并设置次数、退避和总预算。
  - 对接口/数据/测试/部署：无数据库、Java、Web 或部署配置变化；Python 调用方若曾捕获原始
    httpx 异常需改为捕获 `ToolException`，当前仓库只有测试调用方且已同步。
- 测试与验证：
  - `[预期失败] uv run --frozen pytest -q tests/test_tool_errors.py tests/test_business_client.py` —
    收集阶段 2 个导入错误，目标 `app.errors` 尚不存在。
  - `[通过] make test-agent-errors` — M1.3 18/18。
  - `[通过] make test-agent-client` — M1.2 回归 10/10。
  - `[通过] make test-agent-foundation` — M1.1 回归 6/6。
  - `[通过] agent-service 内 uv run --frozen pytest -q` — Python 汇总 34/34。
  - `[通过] make quality` — Ruff 全部通过；mypy strict 检查 16 个文件无问题。
  - `[通过] uv lock --check` — 解析 42 个包。
  - `[通过] 真实 Java 故障验收` — 400/403/404/500/timeout/invalid-response 共 6/6，Trace 均
    保持对应 `trace-m13-*`。
  - `[通过] make test` — foundation/Compose、三服务 smoke、Python 34/34、Java M0 56/56、
    Web 7/7 与生产构建全部通过。
  - `[通过] docker compose up --detach --build agent-service && make smoke` — Agent 与依赖的
    Java 生产镜像构建、容器重建和三服务 smoke 通过。
  - `[通过] 生产容器 Python 导入验收` — `ToolErrorCode.TOOL_TIMEOUT` 输出 `TOOL_TIMEOUT`。
  - `[通过] make validate + Markdown code fence 检查 + git diff --check` — 基础结构、Compose、
    文档代码围栏和空白检查通过。
  - `[失败后修复] 根目录 uv run pytest` — 根目录不是 Python 项目导致找不到 pytest；切换到
    `agent-service` 后 34/34。首次 Ruff 因既有中文注释标点和新类型别名写法失败，修正后通过。
  - `[未运行] make reset-demo` — 本次没有修改固定数据，且该命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/errors.py`、`app/clients/business.py`、`app/schemas/business.py`
  - `agent-service/tests/test_tool_errors.py`、`tests/test_business_client.py`
  - `Makefile`、`README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；标准错误还没有 ToolResult、Run/Step 或前端展示消费者。
  - 后续兼容注意事项：如果 Java 将特定 5xx 改为 `retryable=true` 或新增错误码，必须同步
    `BusinessErrorEnvelope`、状态/code 映射、读写重试策略和契约测试，不能只放宽 Pydantic。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次形成了模型/Workflow 可消费的稳定错误语义、失败
    信封一致性门禁、安全异常链和“可恢复性不等于重试授权”的真实实现证据。
- 下一建议任务：
  - `[T127] 定义 Tool 基类`。

## 2026-08-03 22:05 — `[MAINT-PY-DOCSTRING] Python 文档字符串中文化`

- 里程碑：M1 Python Tool 层维护
- 任务类型：代码说明 / 迁移模板 / 文档
- 目标与范围：
  - 本次实现：将 `agent-service/app`、`agent-service/migrations/env.py` 中 33 处说明性
    `"""..."""` 文档字符串翻译为中文；将 Alembic revision 模板的 `Revision ID`、
    `Revises`、`Create Date` 标签翻译为中文。
  - 明确不实现：不修改 Java Repository 的两个三双引号 SQL/JPQL 文本块，不修改业务逻辑、
    API、Schema字段、错误码、数据库迁移行为、固定数据、前端或 Agent 能力。
- 需求与关键决策：
  - 方案选择及原因：只翻译供开发者阅读的说明内容，保留 FastAPI、Pydantic、SQLAlchemy、
    Tool、Workflow、Trace ID 等技术标识，避免把可搜索的真实类库和契约名称强行意译。
  - 运行语义边界：Java 的 `"""` 是 Java text block，内容分别为 JPQL 查询和 PostgreSQL
    幂等预留 SQL；`select`、`insert`、`on conflict` 等是可执行语法，翻译会直接破坏查询，
    因此不属于本次“说明文字中文化”。
  - Alembic影响：后续自动生成 revision 时，文件头的人类可读标签变为中文；`${message}`、
    revision变量和 upgrade/downgrade 模板保持不变。
- 核心修改：
  - `agent-service/app/main.py`、`database.py`、`observability.py`、`settings.py`：应用入口、
    数据库、日志和配置文档字符串中文化。
  - `agent-service/app/errors.py`、`clients/business.py`、`schemas/business.py`：M1.2/M1.3 Client、
    错误和传输Schema文档字符串中文化。
  - `agent-service/app/**/__init__.py`：包级职责说明中文化。
  - `agent-service/migrations/env.py`、`script.py.mako`：迁移环境说明和新revision模板标签中文化。
- 异常、安全与边界：
  - 参数、权限、超时、上游异常：无行为变化；所有运行时错误分类和安全文案保持不变。
  - 幂等、并发或人工确认：无变化。
- 开发中发现并修复：
  - 首轮Ruff发现中文全角逗号触发 `RUF002`，目标文件已有学习注释还触发 `RUF003/E501/I001`；
    保留中文含义并使用句号、连接词、分行和必要空行修复，最终Ruff通过。
- 替代方案：
  - 采用的替代方案及原因：无临时替代方案。保留Java SQL/JPQL不是降级，而是保护可执行文本
    语义的必要边界。
  - 已覆盖/未覆盖：全部说明性Python文档字符串和Alembic模板标签已中文化；可执行SQL/JPQL
    明确不翻译。
  - 局限、风险和移除条件：无临时方案需要移除；若未来新增英文说明性文档字符串，应继续按
    本次规则翻译，运行时文本则按语义判断。
- 后续影响：
  - 对接口/数据/测试/部署：无。后续Alembic revision文件头使用中文标签，不影响迁移执行。
  - 对后续开发：T127仍为下一任务；新增Python类、函数或模块时应使用中文文档字符串，并保留
    技术专有名词原名。
- 测试与验证：
  - `[通过] make test-agent-foundation` — M1.1 6/6。
  - `[通过] make test-agent-client` — M1.2 10/10。
  - `[通过] make test-agent-errors` — M1.3 18/18。
  - `[首次失败后修复] make quality` — 首轮Ruff 17项标点、格式和行长问题；修复后Ruff通过，
    mypy strict检查16个文件无问题。
  - `[通过] agent-service内 uv run --frozen pytest -q` — Python汇总34/34。
  - `[通过] uv lock --check` — 解析42个包。
  - `[未运行] Java/Web测试` — 没有修改Java可执行文本、Java/前端代码或跨服务契约。
- 变更文件：
  - `agent-service/app/__init__.py`
  - `agent-service/app/clients/__init__.py`、`business.py`
  - `agent-service/app/schemas/__init__.py`、`business.py`
  - `agent-service/app/main.py`、`database.py`、`observability.py`、`settings.py`、`errors.py`
  - `agent-service/migrations/env.py`、`script.py.mako`
  - `docs/STATUS.md`、`docs/TEST_REPORT.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无。
  - 后续兼容注意事项：不要把Java text block一律当成注释；必须先判断内容是否参与运行。
- Agent 面试价值评估：
  - 无新增价值，未修改 `doc/needCare.md`。本次仅改善代码说明语言，没有新增 Agent、Tool、
    Workflow、RAG、Approval、评测或可靠性实现证据。
- 下一建议任务：
  - `[T127] 定义 Tool 基类`。

## 2026-08-03 22:10 — `[GOV-PY-CN] 固化 Python 中文说明规则`

- 里程碑：M1 Python Tool 层维护
- 任务类型：开发治理 / 文档
- 目标与范围：
  - 本次实现：在根级 `AGENTS.md` 增加持续生效的Python说明语言规则，要求后续模块、类、函数、
    方法的文档字符串及解释业务原因、设计约束、关键流程的注释默认使用中文。
  - 明确不实现：不修改运行时代码、Java/Web、业务接口、Schema、固定数据或Agent能力。
- 需求与关键决策：
  - 技术标识边界：FastAPI、Pydantic、SQLAlchemy、Tool、Workflow、Trace ID、字段名、类名和
    函数名保留原文，避免意译造成检索和技术表达失真。
  - 运行语义边界：中文说明规则不自动作用于日志事件名、错误码、API文案、SQL/JPQL、Prompt、
    第三方协议或其他运行时字符串；这些内容只有在业务契约和具体任务明确要求时才能修改。
  - 规则生效方式：根级 `AGENTS.md` 适用于整个仓库，后续每次Python开发均需遵守；若子目录
    新增更具体规则，应同时遵守并按就近原则处理。
- 核心修改：
  - `AGENTS.md` — 在“每次开发的执行规则/实现要求”后增加Python中文说明规则与运行时边界。
  - `docs/STATUS.md`、`docs/TEST_REPORT.md`、`doc/record.md` — 同步状态、验证范围和历史记录。
- 测试与验证：
  - `[通过] make validate` — 基础结构和Compose配置有效。
  - `[通过] Markdown code fence结构检查` — 修改文档代码围栏成对。
  - `[通过] git diff --check` — 无空白错误。
  - `[未运行] 业务测试` — 本次没有修改运行时代码。
- 未完成项与已知问题：
  - 未完成项：无。
  - 已知问题/阻塞：无。
- 替代方案：
  - 采用的替代方案及原因：无。
  - 局限、风险和移除条件：无临时方案；运行时文本仍需逐项依据契约判断，不能机械翻译。
- 后续影响：
  - 对后续开发：从T127开始，新增或修改的Python说明性文档字符串和关键解释注释默认使用中文。
  - 对接口/数据/测试/部署：无。
- Agent 面试价值评估：
  - 无新增价值，未修改 `doc/needCare.md`。本次属于开发治理，不构成Agent岗位面试实现证据。
- 下一建议任务：
  - `[T127] 定义 Tool 基类`。

## 2026-08-04 21:51 — `[T127-T132] M1.4 Tool 基础协议`

- 里程碑：M1 Python Tool 层
- 任务类型：功能 / Schema / 测试 / 文档 / 配置
- 目标与范围：
  - 本次实现：建立 Tool 八项统一元数据、`ToolContext`、互斥 `ToolResult`、`BaseTool.execute`
    公共执行门禁和 `ToolRegistry`，完成 T127～T132。
  - 明确不实现：不实现订单等具体业务 Tool、自动重试、单次 Run 重复调用检测、调试 API、
    Workflow、模型调用、Run/Step 持久化或 Approval。
- 需求与关键决策：
  - 业务背景/固定数据映射：本阶段不读取或修改 Java 业务事实，不改变 `ORDER-003`。M1.5 具体
    Tool 将通过当前协议调用已有 `BusinessHttpClient`，Python 仍禁止直接访问业务数据库。
  - 方案选择及原因：公共 `execute` 使用 Template Method 固定权限、输入 Schema、整体超时、
    具体调用、输出 Schema 和异常收敛顺序；子类只实现 `_execute`，避免不同 Tool 策略漂移。
  - 结果契约：`ToolResult` 由 Pydantic 保证成功时只有 `data`、失败时只有 `error`；Workflow
    后续根据稳定 `ToolError.code` 分支，不解析文案或 Python 异常类型。
  - 权限边界：Python 根据 `required_permissions` 提前拒绝明显越权调用，但 Java 仍负责最终
    用户权限、对象归属、业务状态和写入一致性校验。
  - 重试边界：`max_retries` 只作为 M1.6 策略元数据。本阶段即使 timeout 返回
    `retryable=true` 也只执行一次，防止提前产生写请求重放风险。
  - 重名边界：注册表重复名称属于装配错误，使用 `DuplicateToolRegistrationError`；不复用
    M1.7 的 `DUPLICATE_CALL`，后者表示单次 Run 中相同 Tool 和参数的重复业务调用。
  - 兼容性影响：新增 Python 内部协议和根级测试命令；不修改 Java API、前端、数据库、Compose
    或现有 Client 的成功/异常契约。
- 核心实现：
  - `agent-service/app/tools/models.py` — `ToolContext` 保存脱敏身份、权限、Trace 和 Run；
    `ToolError` 映射标准异常；泛型 `ToolResult` 校验成功/失败互斥。
  - `agent-service/app/tools/base.py` — `ToolRiskLevel` 定义 LOW/MEDIUM/HIGH；`BaseTool` 暴露八项
    只读元数据；`execute` 统一权限、双向 Schema、整体 timeout 和错误处理。
  - `agent-service/app/tools/registry.py` — `ToolRegistry.register/get/names` 提供确定性注册与查找，
    独立异常阻止重名静默覆盖并报告未知名称。
  - `agent-service/app/observability.py` — JSON 日志增加 `tool_name/run_id/error_code` 白名单字段；
    未知异常对结果隐藏内部详情，但通过 `logging.exception` 保留堆栈用于排障。
  - `agent-service/tests/test_tool_protocol.py` — 测试用 Echo Tool 覆盖协议正常和异常路径，不代表
    已实现业务 Tool。
  - 必要的最小关键片段：

    ```text
    raw_input + ToolContext
    → 权限门禁
    → input_model
    → timeout 内执行 _execute
    → output_model
    → ToolResult(success, data, error)
    ```

- 代码解释与定位：
  - 整体调用/数据流：未来 Workflow 或调试 API 从注册表获取 Tool，构造上下文并调用公共
    `execute`；具体 Tool 通过 `_execute` 调 Java Client；上层只收到标准结果。
  - 核心类、函数、接口或配置项：`ToolContext`、`ToolError`、`ToolResult`、`ToolRiskLevel`、
    `BaseTool.execute/_execute`、`ToolRegistry.register/get/names`、Make 的
    `test-agent-tool-protocol`。
  - 输入、输出、异常和边界：输入是 Pydantic Model 或字段映射加严格上下文；成功输出是经过
    `output_model` 校验的 Model；参数、权限、超时、输出漂移、标准异常和未知异常分别映射稳定
    错误。未知异常只向结果暴露固定文案，日志保留堆栈和调用标识。
  - 关键代码位置：`models.py` 第22、33、62行；`base.py` 第23、31、97行；`registry.py`
    第8、16、24、30、37行；`Makefile` 第32行。行号代表本次记录时版本。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：输入错误为 `PARAM_VALIDATION_ERROR`；缺权限为
    `PERMISSION_DENIED`；整体 timeout 为可恢复的 `TOOL_TIMEOUT`；Client 的 `ToolException`
    保留 code/retryable/Trace/HTTP 状态；非法输出为 `RESPONSE_VALIDATION_ERROR`；其他异常为
    `UNKNOWN_TOOL_ERROR`。
  - 幂等、并发或人工确认：无业务写入；没有自动重试。`ToolContext` 冻结且 Token 由
    `SecretStr` 脱敏；Approval 尚未实现。
- 未完成项与已知问题：
  - 未完成项：T133～T139 具体只读 Tool、T140～T144 RetryPolicy、T145～T149 重复调用检测、
    T150～T153 调试 API 及 M2+ 能力。
  - 已知问题/阻塞：无阻塞。`run_id` 当前只用于上下文和未知异常日志，没有 Run/Step 持久化；
    风险等级已经建模但尚无写 Tool/Approval 消费者；Java 回归仍输出 Mockito 动态 Agent 的
    未来 JDK 兼容警告。
- 替代方案：
  - 采用的替代方案及原因：无临时替代方案。测试使用本地 Echo Tool 是协议单元夹具，不冒充
    业务实现；M1.5 将在相同协议上接入真实 Java 端点。
  - 已覆盖/未覆盖的验收要求：完整覆盖 T127～T132 的基类、上下文、结果、注册、重复名称和
    正常/异常自动化测试；不覆盖下一阶段业务 Tool 和跨服务 Tool 调用。
  - 局限、风险和转正/移除条件：测试 Echo Tool 只存在于测试文件，无生产替换任务；具体业务
    能力必须由 T133+ 的端点 DTO 和 Tool 测试举证。
- 后续影响：
  - 对后续任务/里程碑：M1.5 Tool 必须继承 `BaseTool`、使用明确 Pydantic 输入输出、声明权限
    与风险并注册到 `ToolRegistry`；M1.6 不得把 `max_retries` 当成无条件重放次数。
  - 对接口/数据/测试/部署：无 Java/API/数据迁移/前端/部署影响；Python 测试总数增加，根级
    `make test` 新增 M1.4 协议目标。
- 测试与验证：
  - `[预期失败] agent-service 内 uv run --frozen pytest -q tests/test_tool_protocol.py` — 收集
    阶段 1 个 `ModuleNotFoundError`，`app.tools` 尚不存在。
  - `[首次失败后修复] 同一测试` — 首轮 11/16；5 个元数据用例错误实例化抽象基类，改用具体
    测试 Tool 后 16/16，没有放宽生产校验。
  - `[通过] make test-agent-tool-protocol` — M1.4 16/16。
  - `[通过] make test-agent-foundation` — M1.1 7/7，包含 Tool 日志字段格式化回归。
  - `[通过] make test-agent-client` — M1.2 10/10。
  - `[通过] make test-agent-errors` — M1.3 18/18。
  - `[通过] agent-service 内 uv run --frozen pytest -q` — Python 汇总 51/51。
  - `[首次失败后修复] Ruff` — 先报告两个旧式 Generic 声明，改用 Python 3.12 类型参数语法后
    报告 import 分组；排序后通过。mypy strict 检查21个源/测试文件无问题。
  - `[通过] uv lock --check` — 解析42个包。
  - `[通过] make validate` — 基础结构和 Compose 配置有效。
  - `[通过] make test` — 三服务 smoke、Python分项、Java M0 56/56、Web 7/7和生产构建通过。
  - `[通过] git diff --check` — 无空白错误。
  - `[未运行] make reset-demo` — 本次没有修改固定数据，且该命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/tools/__init__.py`、`base.py`、`models.py`、`registry.py`
  - `agent-service/app/observability.py`
  - `agent-service/tests/test_tool_protocol.py`、`test_observability.py`
  - `Makefile`、`README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；M1 停止线尚未达到，因为只读业务 Tool 尚未实现。
  - 后续兼容注意事项：不要绕过公共 `execute` 直接调用 `_execute`；风险等级、权限名和 Tool 名
    将成为 Registry、Workflow、评测及未来模型 Tool Schema 的稳定契约，变更时需同步测试。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次形成了 Tool Schema 双向门禁、模型/Workflow 与业务
    异常隔离、两层权限、整体超时、重试停止线、稳定注册和安全可观测性的真实实现证据。
- 下一建议任务：
  - `[T133] 实现 get_order_detail Tool`。

## 2026-08-07 21:40 — `[T133-T139] M1.5 七个只读 Tool`

- 里程碑：M1 Python Tool 层
- 任务类型：功能 / Schema / HTTP 集成 / 测试 / 文档 / 配置
- 目标与范围：
  - 本次实现：完成 `get_order_detail`、`get_related_tasks`、`get_task_detail`、
    `get_production_progress`、`get_quality_issues`、`get_review_result` 和
    `get_delivery_status` 七个只读 Tool；装配进 FastAPI lifespan；完成 T133～T139。
  - 明确不实现：不实现 T140～T144 自动重试、T145～T149 单次 Run 重复调用检测、
    T150～T153 Tool 调试 API、Workflow、LLM Tool Calling、Run/Step、RAG 或 Approval。
- 需求与关键决策：
  - 业务事实边界：Python 只通过 Java API 获取订单、任务、进度、质检、复核和交付数据，不建立
    Java 业务表 ORM，也不根据模型输出补造事实。
  - Tool 粒度：保留七个独立 Tool，而不是提前聚合成订单总览。后续 Workflow/Agent 能按问题
    选择证据路径，Run/Step 和评测也能定位具体查询；聚合与调用预算留给后续里程碑。
  - Schema 契约：`OrderIdInput` / `TaskIdInput` 限制路径 ID；输出模型以 Java DTO 的 camelCase
    alias、Literal 状态、必填字段、不可变对象和 `extra=forbid` 建立严格边界。
  - 资源绑定：除结构校验外，具体 Tool 核对请求 ID、响应顶层父 ID 与嵌套 task/step/issue/
    delivery 的父 ID。形状合法但属于其他订单或任务的响应映射为非重试
    `RESPONSE_VALIDATION_ERROR`，避免跨订单事实污染后续 Agent 结论。
  - 空集合语义：tasks、steps、issues、reviews、records 的 `[]` 是成功结果；404 才表示父资源
    不存在，二者不合并。
  - 权限与链路：五类 Python 权限做前置快速拒绝，`BusinessIdentity` 和 Trace ID 原样传给 Java；
    Java 仍是最终权限和业务事实边界。
  - 重试停止线：七个 Tool 声明 LOW 风险与 `max_retries=1` 元数据，但没有执行重试；timeout 和
    Java 500 测试均确认只调用一次，真正策略留给 M1.6。
- 核心实现：
  - `agent-service/app/schemas/tools.py` — 定义两种输入和订单、任务、步骤、质检、复核、交付等
    严格输出 Schema，字段 alias 与 Java DTO 一致。
  - `agent-service/app/tools/readonly.py` — `_BusinessReadTool` 统一 Client 和静态元数据；七个子类
    映射精确 GET 路径并执行资源归属校验；`create_read_tool_registry` 确定性注册完整集合。
  - `agent-service/app/main.py` — lifespan 创建共享 Client 后构建 Registry，应用关闭时复用原有
    Client 关闭逻辑。
  - `agent-service/app/tools/__init__.py` — 导出七个 Tool、名称集合和工厂。
  - `agent-service/tests/integration/tools/test_read_tools.py` — 数据驱动覆盖七个 Tool 的正常、参数、
    权限、404、500、timeout、缺字段、资源串线、空集合和 Registry 场景。
  - `agent-service/tests/test_business_client.py` — 增加 lifespan Registry 装配及名称集合断言。
  - `Makefile` — 新增 `make test-tools`，并让根级 `make test` 覆盖 M1.4 协议与 M1.5 Tool。
  - 必要调用链：

    ```text
    Tool name + raw input + ToolContext
    → ToolRegistry.get
    → BaseTool.execute 权限/输入/整体超时
    → 具体 _execute
    → BusinessHttpClient.get
    → Java HTTP + 六字段信封 + data
    → Client 信封与 DTO 校验
    → Tool 资源归属校验
    → BaseTool 输出校验
    → ToolResult(data/error)
    ```

- 异常、安全与边界：
  - 空或非法 ID 映射 `PARAM_VALIDATION_ERROR`，缺权限映射 `PERMISSION_DENIED`，两者均不发 HTTP。
  - Java 404 映射 `RESOURCE_NOT_FOUND`；500 映射 `UPSTREAM_UNAVAILABLE`；传输或整体 timeout
    映射 `TOOL_TIMEOUT`；缺字段、非法枚举或 ID 串线映射 `RESPONSE_VALIDATION_ERROR`。
  - Python 前置权限不能代替 Java 授权；没有写操作、幂等、并发更新或人工确认变化。
- 开发中发现并修复：
  - 测试先行时因只读 Tool 尚不存在产生 1 个预期收集错误，生产实现后 M1.5 69/69。
  - 首次 Ruff 报告 21 项：本次导出列表未排序，以及既有中文教学注释的全角标点、行长和业务
    中文原文歧义检查。保留教学注释含义并调整排版；固定业务响应原文不能修改，仅定点添加
    `noqa: RUF001`。最终 Ruff 和 mypy 均通过，无残余运行影响。
  - 最终验收首次误在 `agent-service` 子目录调用根级 `make validate`；第二次多行 shell 中的
    `cd agent-service` 持续影响后续命令，且未启用 `set -e` 使末尾成功掩盖前置失败。最终改用
    子 shell 隔离目录并启用 `set -e`，同组锁文件、基础配置、Markdown 和 diff 检查真实通过。
- 替代方案：
  - 采用的替代方案及原因：无临时生产替代方案。`httpx.MockTransport` 是自动化 HTTP 边界测试
    夹具，并已补真实 Java 固定数据 7/7 验收，不作为跨服务验证的替代。
  - 已覆盖/未覆盖：覆盖七个 Tool 独立调用、异常契约和真实 Java 只读链路；不覆盖下一任务的
    重试、重复调用检测、HTTP 调试入口和 Agent 自动决策。
  - 局限、风险和移除条件：无临时方案需要移除；MockTransport 测试继续作为确定性回归保留。
- 后续影响：
  - 对后续任务/里程碑：M1.6 RetryPolicy 应只消费 LOW/只读属性与 `error.retryable`，限制次数、
    退避和总预算；M1.7 可根据稳定 Tool 名与规范化输入检测重复；M2 可直接编排七个 Tool。
  - 对接口/数据/测试/部署：没有修改 Java API、固定数据、数据库或前端；Python 内部新增稳定
    Tool 名、权限名和 Schema，未来改名或字段变更必须同步 Workflow、模型 Tool Schema 和评测。
  - 兼容性风险：Tool 输出严格拒绝 Java 新增额外字段；这是有意的契约漂移门禁，Java DTO 变化
    时需要同步 Python Schema 和契约测试，不能静默放宽。
- 测试与验证：
  - `[预期失败] agent-service 内 uv run --frozen pytest -q tests/integration/tools/test_read_tools.py`
    — 收集阶段 1 个 `ImportError`，`READ_TOOL_NAMES` 尚不存在。
  - `[通过] make test-tools` — M1.4 协议 16/16，M1.5 七个只读 Tool 69/69。
  - `[通过] make test-agent-client` — M1.2/生命周期回归 10/10，包含 Registry 装配。
  - `[通过] agent-service 内 uv run --frozen pytest -q` — Python 汇总 120/120。
  - `[通过] make quality` — Ruff 全部通过；mypy strict 检查 24 个源/测试文件无问题。
  - `[通过] 真实 Java 固定数据验收` — 七个 Tool 针对 `ORDER-003` / `TASK-003` 调用 7/7。
  - `[通过] make test` — foundation/Compose、三服务 smoke、Python 分项、Java M0 56/56、Web
    7/7 和生产构建全部通过。
  - `[通过] docker compose up --detach --build agent-service + 三服务 smoke` — 新 Agent 镜像
    构建、容器重建和启动装配通过；Compose 同步重建依赖的 Java 镜像，固定数据卷未删除。
  - `[通过] uv lock --check` — 解析 42 个直接及传递依赖。
  - `[通过] make validate + Markdown code fence 检查 + git diff --check` — 基础结构、Compose、
    文档代码围栏和差异空白均有效。
  - `[未运行] make reset-demo` — 本次未修改固定数据，且该命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/schemas/tools.py`
  - `agent-service/app/tools/readonly.py`、`__init__.py`
  - `agent-service/app/main.py`
  - `agent-service/tests/integration/tools/test_read_tools.py`、`tests/test_business_client.py`
  - `agent-service/app/tools/base.py`、`models.py`、`registry.py`（只调整既有中文教学注释排版）
  - `Makefile`、`README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 未完成项：T140～T153 及 M2+ 能力均未实现。
  - 已知问题/阻塞：无阻塞；`max_retries` 尚不生效；没有 HTTP 调试入口、Run/Step 持久化或
    Agent 消费者；Java 测试仍有 Mockito 动态 Agent 的未来 JDK 兼容警告。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次形成细粒度 Tool 取证路径、严格业务事实 Schema、
    请求/响应资源绑定、空集合语义和两层权限边界的真实实现与测试证据。
- 下一建议任务：
  - `[T140] 定义只读 RetryPolicy`。

---

## 2026-08-08 — `[T140-T144] M1.6 Tool 重试`

- 里程碑：M1 Python Tool 层
- 任务类型：功能 / 修复 / 测试 / 文档
- 目标与范围：
  - 本次实现：为七个 LOW 风险只读 Tool 增加显式 RetryPolicy、封顶指数退避、最大重试次数、
    整体耗时预算和结构化重试日志，并验证可重试/不可重试错误的实际调用次数。
  - 明确不实现：不开发 T145+ 重复调用检测、Tool 调试 API、Run/Step、Workflow、LLM、RAG、
    Approval、写 Tool 重试、熔断、限流或随机抖动；不修改 Java API、固定数据和前端。
- 需求与关键决策：
  - 业务背景/固定数据映射：七个 Tool 仍只通过 Java API 获取订单、任务、生产进度、质检、
    复核和交付事实；不修改 `ORDER-003 → TASK-003 → ISSUE-001 → PENDING → BLOCKED` 黄金链路。
  - 方案选择及原因：`BusinessHttpClient` 继续只负责 HTTP 和 `ToolException` 映射，重试策略由
    具体只读 Tool 显式装配。这样 `retryable=true` 只表达故障可能恢复，不会自动授权未来写 Tool
    重放。BaseTool 没有 RetryPolicy 时保持 M1.4 单次调用行为。
  - 次数契约：`max_retries` 是首次 attempt 之外的额外次数；当前值 1，最多发送 2 个 Java 请求。
    策略和 Tool 元数据次数必须一致，避免展示值与实际执行值漂移。
  - 错误门禁：仅 `TOOL_TIMEOUT` 或 `UPSTREAM_UNAVAILABLE`、`retryable=true` 且还有剩余次数时
    重试。参数、权限、404、409、响应 Schema、资源归属错误和 Java 当前保守 500 不重试。
  - 耗时契约：`asyncio.timeout` 包住首次请求、退避、重试和输出校验的完整循环；重试不会得到
    新的 5 秒预算。退避使用 `min(initial × multiplier^(N-1), max)`。
  - 契约、状态或兼容性影响：不修改 Java 六字段信封、DTO、Tool 输入输出 Schema、稳定 Tool
    名、权限名和固定数据。失败时最终仍返回既有 `ToolResult.error`，只改变明确暂态读失败的
    请求次数与恢复机会。
- 核心实现：
  - `agent-service/app/tools/retry.py` — `RetryPolicy`：不可变/slots 策略，校验最大次数与有限正数
    退避参数，通过 `should_retry` 做错误白名单、可恢复标志和次数门禁，通过 `backoff_seconds`
    计算封顶指数退避。
  - `agent-service/app/tools/base.py` — `BaseTool.execute/_execute_with_retry`：在原整体 timeout 内执行
    重试循环，只捕获标准 `ToolException`；每次重试前写结构化日志并等待，最终沿用统一结果收敛。
  - `agent-service/app/tools/readonly.py` — `_READ_TOOL_RETRY_POLICY/_BusinessReadTool`：只给七个只读
    Tool 显式绑定最大 1 次、100 ms 起步、2 倍增长、1 秒上限的共享不可变策略。
  - `agent-service/app/observability.py` — `_LOG_EXTRA_FIELDS`：新增 `retry_number` 和
    `retry_delay_ms` 白名单，重试日志同时保留 Tool、Run、Trace 和错误码。
  - `agent-service/app/schemas/tools.py` — 更正既有三个类型别名的拼写回归，恢复
    `OrderIdentifier`、`TaskIdentifier`、`BusinessIdentifier`，不改变字段或 API 契约。
  - `agent-service/tests/test_retry_policy.py` — 覆盖策略校验、退避上限、门禁、暂态恢复、次数耗尽、
    总预算和元数据一致性；只读 Tool 集成测试覆盖七条路径的真实调用计数。
  - 必要的最小关键片段：

    ```text
    ToolException
    → 显式 RetryPolicy?
    → code 属于 timeout/upstream 白名单?
    → retryable=true?
    → retries_completed < max_retries?
    → 记录日志并退避
    → 再执行 _execute
    → 最终 ToolResult.data / ToolResult.error
    ```

- 代码解释与定位：
  - 整体调用/数据流：`BaseTool.execute` 完成权限和输入校验后进入整体 timeout，再调用
    `_execute_with_retry`；具体 `_execute` 通过 Client 请求 Java，标准异常由策略决定重试或抛回，
    最终输出 Schema/异常仍由公共协议转换成稳定 ToolResult。
  - 核心类、函数、接口或配置项：`RetryPolicy.should_retry/backoff_seconds`、
    `BaseTool.execute/_execute_with_retry`、`_READ_TOOL_RETRY_POLICY`、`_LOG_EXTRA_FIELDS`、Make 的
    `test-tools`。
  - 输入、输出、异常和边界：策略输入是标准 `ToolException` 与已完成重试数，输出是是否重试
    和等待秒数；非法策略在装配时失败。未知异常、Pydantic 校验错误和没有显式策略的 Tool 不进
    重试循环，写操作边界不变。
  - 关键代码位置（本次记录时）：`retry.py` 第20、50、70行；`base.py` 第109、194行；
    `readonly.py` 第27、46、68行；`observability.py` 第23行；`test_retry_policy.py` 第89、125、
    164、189、207行；`test_read_tools.py` 第375、471行；`Makefile` 第35行。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：参数、权限、资源、冲突和不可信响应立即失败；网络连接/timeout
    可有限恢复。Java 500 映射类别虽为上游不可用，但 `retryable=false`，Python 尊重信封不重试。
  - 幂等、并发或人工确认：本次只有 GET 只读 Tool；没有写操作和 Approval。显式策略门禁防止
    未来写 Tool 仅因复制 `max_retries` 元数据而被自动重放。
- 开发中发现并修复：
  - 首次测试收集先暴露工作区既有 `typeOrderIdentifier`、`typeTaskIdentifier`、
    `typeBusinessIdentifier` 拼写回归，导致任意 Tool 导入时 `NameError`；恢复既有类型名后全量
    Python 测试通过，无接口兼容影响。
  - 修复拼写后测试按预期因 `RetryPolicy` 尚不存在产生 1 个 `ImportError`，随后完成生产实现。
  - 首次 Ruff 报告 42 项，包含本次导出排序/测试格式及既有中文教学注释的全角标点。保留中文
    含义、调整标点和排版后 Ruff 与 mypy 全部通过，没有残余运行影响。
- 未完成项与已知问题：
  - 未完成项：T145～T153、M2+；jitter、熔断、跨实例重试预算和生产指标未实现。
  - 已知问题/阻塞：代码无阻塞；当前受限执行环境禁止访问宿主机 localhost 服务，本次无法重复
    验证真实 Java 重试成功链路和三服务 smoke。Java 当前所有通用 500 都不可重试。
- 替代方案：
  - 采用的替代方案及原因：默认 uv 缓存目录在受限环境中不可写，使用
    `UV_CACHE_DIR=/tmp/productline-agent-m16-uv-cache`；localhost 被限制时使用
    `httpx.MockTransport` 对七个 Tool 做确定性失败后成功、持续 timeout 和不可重试分支验证。
  - 已覆盖/未覆盖的验收要求：覆盖 RetryPolicy、指数退避、最大次数、错误拦截、七个实际只读
    Tool 调用计数、总预算和日志字段；未覆盖本次真实 Java 暂态失败后恢复及完整三服务回归。
  - 局限、风险和转正/移除条件：临时缓存无生产影响，可随执行环境恢复而删除；MockTransport
    不能证明真实网络/Java 故障后成功，获得 localhost/容器网络权限后应补一次真实 Java 读重试
    验收。确定性边界测试仍应长期保留，不因真实验收而移除。
- 后续影响：
  - 对后续任务/里程碑：M1.7 应用稳定 Tool 名与规范化输入识别同一 Run 内重复调用，避免重试
    机制之外的模型重复取证；M2 Workflow 应把 Tool 总预算纳入整条诊断延迟预算。
  - 对接口/数据/测试/部署：Java/API/数据库/前端无变化；Python Tool 暂态读失败最多产生两个
    上游请求，日志消费者可读取两个新增字段。未来调整次数、错误白名单或退避需同步测试、文档
    和容量评估。
- 测试与验证：
  - `[预期失败] uv run --frozen pytest ...` — 先发现既有 Schema `NameError`；更正后按预期出现
    `RetryPolicy` 导入错误，证明测试在生产实现前失败。
  - `[通过] UV_CACHE_DIR=/tmp/productline-agent-m16-uv-cache make test-tools` — M1.4 16/16，
    RetryPolicy 与七个只读 Tool 92/92。
  - `[通过] UV_CACHE_DIR=/tmp/productline-agent-m16-uv-cache make test-agent-foundation` — 8/8。
  - `[通过] agent-service 内 UV_CACHE_DIR=... uv run --frozen pytest -q` — Python 144/144。
  - `[通过] UV_CACHE_DIR=/tmp/productline-agent-m16-uv-cache make quality` — Ruff 通过；mypy strict
    检查 26 个源/测试文件无问题。
  - `[通过] agent-service 内 UV_CACHE_DIR=... uv lock --check` — 解析 42 个直接及传递依赖。
  - `[通过] make validate + Markdown code fence 检查 + git diff --check` — 基础结构、Compose、
    文档围栏和差异空白有效。
  - `[失败：环境] UV_CACHE_DIR=... make test` — foundation/Compose 配置通过，随后 smoke 无法访问
    `127.0.0.1:18000/health`；Java/Web 目标未执行，不把该命令记录为通过。
  - `[失败：环境] .venv/bin/python 真实 Java 只读调用` — localhost 连接被限制；日志显示安排
    1 次重试，第二次仍连接失败并返回 `UPSTREAM_UNAVAILABLE`，没有成功链路结果。
  - `[未运行] make reset-demo` — 本次不修改固定数据，且命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/tools/retry.py`、`base.py`、`readonly.py`、`__init__.py`
  - `agent-service/app/observability.py`、`app/schemas/tools.py`
  - `agent-service/tests/test_retry_policy.py`、`tests/integration/tools/test_read_tools.py`、
    `tests/test_observability.py`
  - `agent-service/app/clients/business.py`、`app/main.py`、`app/tools/models.py`（既有中文注释排版）
  - `Makefile`、`README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：多实例同时故障时没有 jitter，可能同步重试；只读请求量在暂态故障时最多
    放大至两倍；没有持久化 Run/Step 和恢复率指标。
  - 后续兼容注意事项：不能把 Java `UPSTREAM_UNAVAILABLE` 直接视为可重试，必须保留
    `retryable` 双门禁；写 Tool 必须另行设计幂等、版本和结果未知恢复流程。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次有真实代码和调用次数测试支撑“故障属性不等于重试
    授权”、只读边界、封顶退避、整体预算和可观测性取舍，直接影响 Agent Tool 结果可靠性。
- 下一建议任务：
  - `[T145] 定义单次 Run 的 Tool 调用签名`。

---

## 2026-08-08 — `[T145-T149] M1.7 重复调用检测`

- 里程碑：M1 Python Tool 层
- 任务类型：功能 / 测试 / 文档
- 目标与范围：
  - 本次实现：生成 Tool 名与规范化参数指纹，在单次 Run 复用的 `ToolContext` 中保存调用记录，
    拦截相同 Tool 和参数，提供显式 `force_refresh`，并覆盖顺序、并发和七个只读 Tool 测试。
  - 明确不实现：不开发 T150+ Tool 调试 API，不实现结果缓存、TTL、数据库 Run/Step、跨进程/
    实例去重、Workflow、LLM、RAG 或 Approval；不修改 Java API、固定数据和前端业务功能。
- 需求与关键决策：
  - 业务背景/固定数据映射：M1.7 防止未来 Agent 在相同事实没有变化时循环调用 Java Tool；不
    修改 `ORDER-003 → TASK-003 → ISSUE-001 → PENDING → BLOCKED` 黄金事实链路。
  - 指纹契约：先完成权限和 Pydantic 输入校验，再将稳定 Tool 名与已校验参数转换为 key 排序、
    紧凑 JSON，使用 UTF-8 SHA-256 得到 64 字符小写十六进制指纹。语义等价参数不受字典顺序
    影响，Tool 名或参数变化会产生不同指纹。
  - 数据最小化：Run 账本只保存 Hash，不保存原始 Tool 参数；Hash 用于稳定比较，不作为加密、
    权限或不可逆安全证明，也不写入重复拦截日志。
  - 生命周期：`ToolContext.model_post_init` 为本次 Run 创建私有 `RunToolCallLedger`，不参与
    Pydantic 序列化。一次 Run 必须复用同一上下文；避免使用缺少清理时机的进程全局字典。
  - 并发边界：`try_reserve` 使用仅包围 Set 查询/插入的短 `Lock`，并发相同调用只能有一个通过；
    锁内没有 HTTP、sleep 或输出校验。
  - 执行顺序：合法逻辑调用在 HTTP 前占位。首次执行即使最终 404、timeout 或响应错误也保留
    指纹，避免模型循环；确需重新获取时必须显式 `force_refresh=True`。
  - 重试边界：M1.6 `_execute_with_retry` 位于一次逻辑调用内部，账本只在进入重试循环前占位
    一次，因此网络 retry 不会触发 `DUPLICATE_CALL`。
  - 刷新契约：`force_refresh` 是 `BaseTool.execute` 的 keyword-only 控制参数，不属于业务输入
    Schema且不进入 fingerprint；只绕过本次门禁，不删除原记录。
  - 契约、状态或兼容性影响：`ToolResult` 现有 `DUPLICATE_CALL` 错误码开始实际使用，错误固定为
    `retryable=false`；现有两参数 `execute(raw_input, context)` 调用保持兼容。Java HTTP/DTO、
    Tool 名和业务 Schema 无变化。
- 核心实现：
  - `agent-service/app/tools/deduplication.py` — `build_tool_call_fingerprint` 负责规范 JSON 和
    SHA-256；`RunToolCallLedger.try_reserve` 负责并发安全的首次/重复/强制刷新判定。
  - `agent-service/app/tools/models.py` — `ToolContext.model_post_init/tool_call_ledger` 建立并暴露不
    序列化的 Run 级内存账本；`run_id` 语义更正为一次 Agent Run，而不是一次 Tool 调用。
  - `agent-service/app/tools/base.py` — `BaseTool.execute(..., force_refresh=False)` 在输入校验后、
    timeout/retry/HTTP 前登记指纹；重复时记录 `duplicate_tool_call_blocked` 并返回标准失败结果。
  - `agent-service/app/tools/__init__.py` — 导出指纹函数和账本类型，供测试及后续 Workflow 使用。
  - `agent-service/tests/test_tool_call_deduplication.py` — 覆盖规范化、指纹变化、同参拦截、不同参数/
    Run、强制刷新、并发占位和控制参数类型。
  - `agent-service/tests/integration/tools/test_read_tools.py` — 对七个只读 Tool 参数化验证同参只发
    一个 HTTP 请求，以及 `force_refresh` 明确放行第二个请求。
  - 必要的最小关键片段：

    ```text
    validated_input
    → SHA256(tool_name + canonical_arguments)
    → context.tool_call_ledger.try_reserve
    → False: ToolResult.error(DUPLICATE_CALL)
    → True: timeout → retry loop → Java → output Schema
    ```

- 代码解释与定位：
  - 整体调用/数据流：调用方在一次 Run 中复用 ToolContext；每次 Tool 调用先通过权限和输入门禁，
    再原子登记指纹；首次或强制刷新进入现有 M1.6 调用链，普通重复请求在 Java HTTP 前结束。
  - 核心类、函数、接口或配置项：`build_tool_call_fingerprint`、`RunToolCallLedger.try_reserve`、
    `ToolContext.model_post_init/tool_call_ledger`、`BaseTool.execute(force_refresh)`、`DUPLICATE_CALL`、
    Make 的 `test-tools`。
  - 输入、输出、异常和边界：输入是已校验 Pydantic Model；账本输出是否获得执行占位。重复调用
    返回无 data 的标准 ToolResult；非法 `force_refresh` 作为编程接口误用抛 ValueError；权限或
    输入错误不占账本。
  - 关键代码位置（本次记录时）：`deduplication.py` 第16、38、45行；`models.py` 第23、36、
    42行；`base.py` 第110、142、149行；`test_tool_call_deduplication.py` 第69、104、114、175、197行；
    `test_read_tools.py` 第267、298行；`Makefile` 第35行。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：非法输入和缺权限仍在指纹前返回，不发 HTTP；timeout/网络错误仍由
    M1.6 内部有限 retry；逻辑重复固定返回不可重试 `DUPLICATE_CALL`，不泄露参数或 fingerprint。
  - 幂等、并发或人工确认：当前功能是 Agent 读 Tool 防循环，不等同 Java 写接口幂等。短锁只
    保证同一进程中共享同一 ledger 的并发占位；没有跨服务事务或 Approval 变化。
- 开发中发现并修复：
  - 测试先行阶段因 `build_tool_call_fingerprint` 尚不存在产生 1 个预期 ImportError，实现后专项
    9/9。
  - 首次 Ruff 报告 8 个既有中文教学注释的全角标点和行长问题；其中 `readonly.py` 注释写成
    200ms，与实际 `initial_backoff_seconds=0.1` 不符。已更正为 100ms 并调整排版，不改变运行
    配置；最终 Ruff/mypy 通过。
- 未完成项与已知问题：
  - 未完成项：T150～T153 Tool 调试 API 及 M2+；结果缓存、持久化和分布式去重未实现。
  - 已知问题/阻塞：无阻塞。独立创建的两个 ToolContext 即使 `run_id` 相同也不会共享账本；
    进程重启、多 worker 和多实例不会保留或协调记录；失败调用默认保留记录，恢复必须显式刷新。
- 替代方案：
  - 采用的替代方案及原因：无临时替代方案。进程内 Run 账本是 T146 明确要求的当前目标方案，
    用上下文持有而非全局字典是为了让生命周期随 Run 结束并避免内存清理任务。
  - 已覆盖/未覆盖的验收要求：完整覆盖 T145～T149；不覆盖计划外的分布式去重、缓存、持久化和
    HTTP 暴露。
  - 局限、风险和转正/移除条件：当前账本适用于单进程、一次 Run 复用一个上下文的 M1/M2 链路；
    多 worker、断点恢复或跨实例执行时，需要由 Run 持久化设计替代或扩展，不能直接声称全局去重。
- 后续影响：
  - 对后续任务/里程碑：M1.8 调试 API 需要在一次调试 Run 中复用 ToolContext，并明确是否允许
    暴露 `force_refresh`；M2 Workflow 必须创建一次 Run 级上下文并在全部 Tool 步骤中复用。
  - 对接口/数据/测试/部署：Java API、数据库、固定数据、前端和部署配置无变化；Python 内部
    `BaseTool.execute` 新增兼容的 keyword-only 参数。多进程部署前需重新评估账本共享方式。
- 测试与验证：
  - `[预期失败] agent-service 内 uv run --frozen pytest -q tests/test_tool_call_deduplication.py` —
    收集阶段 1 个 ImportError，生产指纹函数尚不存在。
  - `[通过] 同命令` — M1.7 专项 9/9。
  - `[通过] make test-tools` — M1.4 协议 16/16；M1.5～M1.7 115/115。
  - `[通过] agent-service 内 uv run --frozen pytest -q` — Python 全量 167/167。
  - `[通过] make quality` — Ruff 通过；mypy strict 检查 28 个源/测试文件无问题。
  - `[通过] agent-service 内 uv lock --check` — 解析 42 个直接及传递依赖，锁文件有效。
  - `[通过] 真实 Java ORDER-003 只读验收` — 首次成功、同 Run 同参 `DUPLICATE_CALL`、
    `force_refresh=True` 后再次成功。
  - `[通过] make test` — foundation/Compose、三服务 smoke、Python M1 分项、Java 56/56、Web
    7/7 和 Vue 生产构建全部通过。
  - `[通过] docker compose up --detach --build agent-service + make smoke` — 使用最终运行代码重建
    Agent 镜像后，Java、Agent 和 Web 三服务健康检查全部通过。
  - `[通过] make validate + Markdown code fence 检查 + git diff --check` — 基础结构、Compose、
    修改文档围栏和差异空白有效。
  - `[未运行] make reset-demo` — 本次不修改固定数据，且该命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/tools/deduplication.py`、`models.py`、`base.py`、`__init__.py`
  - `agent-service/tests/test_tool_call_deduplication.py`
  - `agent-service/tests/integration/tools/test_read_tools.py`
  - `agent-service/app/tools/retry.py`、`readonly.py`（仅更正既有注释格式和 100ms 事实）
  - `Makefile`、`README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；上下文未复用会绕过检测，多进程不会共享，Hash 也不能替代敏感数据
    治理。当前没有缓存旧结果或自动判断业务数据是否需要刷新。
  - 后续兼容注意事项：后续 Workflow 不得为同一 Run 的每个 Tool 重建 ToolContext；如果增加
    输入别名、浮点或敏感字段，应同步验证规范序列化与指纹碰撞语义。
- Agent 面试价值评估：
  - 有价值，已更新 `doc/needCare.md`。本次直接解决 Agent 循环调用、并发重复请求、调用成本和
    可评测停止条件问题，并形成 retry/duplicate/cache/idempotency 四类语义的真实设计取舍。
- 下一建议任务：
  - `[T150] 实现仅开发环境启用的 Tool 调试 API`。

---

## 2026-08-08 — `[T150-T153] M1.8 Tool 调试接口`

- 里程碑：M1 Python Tool层（达到M1停止线）
- 任务类型：功能 / 接口 / 测试 / 文档
- 目标与范围：
  - 本次实现：提供`POST /internal/tools/{tool_name}/invoke`，只在development环境注册；使用
    Pydantic调试请求、应用级ToolRegistry和现有BaseTool执行链返回标准ToolResult；提供Swagger
    请求/响应示例，并让相同调试Run跨HTTP请求复用M1.7账本。
  - 明确不实现：不进入M2，不创建Session/Message/Run/Step表，不实现Workflow、LangGraph、
    LLM Tool Calling、RAG、SSE、Approval、生产调试后台或新的Java接口；不修改固定业务数据。
- 需求与关键决策：
  - 业务背景/固定数据映射：调试接口让开发者在Agent尚不存在时，直接使用七个只读Tool验证
    `ORDER-003`等固定事实链路。它调用Tool而不是直拼Java URL，因此不会形成第二套业务契约。
  - 环境门禁：`create_app`只在`Settings.environment == "development"`时包含Router；test和
    production路由表/OpenAPI均没有该路径，访问得到404，而不是仅在处理函数内部返回403。
  - 请求契约：`ToolDebugInvokeRequest`严格拒绝额外字段，包含目标Tool的`arguments`、
    `BusinessIdentity`、Python快速门禁`permissions`、`run_id`和布尔`force_refresh`。Trace ID
    继续由中间件从`X-Trace-Id`取得，不在Body建立第二来源。
  - 执行契约：Router按稳定路径名从ToolRegistry取Tool，构造/复用ToolContext后调用
    `BaseTool.execute`。权限、输入Schema、M1.7去重、M1.6重试、Java Client、输出Schema和错误
    收敛全部复用现有实现，没有调试旁路。
  - 双层错误语义：已找到Tool并完成执行时，即使业务资源、权限、timeout或响应失败，HTTP请求
    仍返回200，具体失败放在标准`ToolResult.error`；未知Tool返回HTTP 404，请求Schema错误由
    FastAPI返回422，同一Run更换身份/权限返回409。
  - Run上下文：若每个HTTP请求都新建ToolContext，M1.7账本会被绕过。因此
    `ToolDebugRunContextStore`按`run_id`复用上下文，使用当前请求Trace做浅复制并共享PrivateAttr
    账本；身份和权限必须与首次调用一致。
  - 内存边界：调试Store最多保存128个Run并按最久未使用顺序淘汰，防止development接口被任意
    run_id无限占用。淘汰后再次使用旧Run会建立新账本，此能力不冒充持久化或分布式Session。
  - Swagger契约：路径参数示例为`get_order_detail`，请求示例使用`ORDER-003`，HTTP 200同时提供
    标准成功与Tool错误示例，开发者可从`/docs`直接执行。
- 核心实现：
  - `agent-service/app/api/tool_debug.py`：`ToolDebugInvokeRequest`定义HTTP输入；
    `ToolDebugRunContextStore.resolve`实现有界Run上下文复用；`invoke_tool`完成Registry查找、Trace
    注入、上下文冲突门禁和BaseTool调用；路由元数据提供Swagger示例。
  - `agent-service/app/main.py`：仅development创建调试Store并注册Router；lifespan仍创建共享
    BusinessHttpClient和七个只读Tool Registry。
  - `agent-service/tests/integration/test_tool_debug_api.py`：覆盖环境隐藏、OpenAPI、成功和标准失败、
    跨请求重复检测、force_refresh、未知Tool、上下文冲突、非法容量与LRU淘汰。
  - `Makefile`：`make test-tools`纳入M1.8专项，形成M1完整独立验收入口。
  - 必要的最小流程：

    ```text
    POST /internal/tools/{tool_name}/invoke
    → FastAPI校验ToolDebugInvokeRequest
    → ToolRegistry.get(tool_name)
    → ToolDebugRunContextStore.resolve(run_id, identity, permissions, trace_id)
    → BaseTool.execute(arguments, context, force_refresh)
    → ToolResult.data / ToolResult.error
    ```

- 代码解释与定位：
  - 整体调用/数据流：开发者通过Swagger或HTTP提交调试信封；FastAPI先验证外层请求，Router选择
    Tool并恢复Run上下文；Tool自身再验证`arguments`并调用Java，响应由既有ToolResult协议返回。
  - 核心类、函数、接口或配置项：`ToolDebugInvokeRequest`、`ToolDebugRunContextStore.resolve`、
    `invoke_tool`、`create_app`的development条件注册、`test-tools`。
  - 输入、输出、异常和边界：Body输入是调试控制信息加Tool原始参数，输出是动态data但固定
    `success/data/error`外形。HTTP层错误与Tool层错误分离；生产环境没有路由；Store只保存有界
    ToolContext且不保存额外业务结果。
  - 关键代码位置在全部修改后重新核对并以最终回复链接为准。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：全部继续由BaseTool/BusinessHttpClient映射到标准Tool错误；接口
    不捕获并改写ToolResult。未知或非法路径在进入Tool前失败。
  - 身份与权限：development调用方可提供调试身份/权限，但同Run不可切换；Python快速门禁不能
    替代Java最终权限校验。生产环境不注册Router，降低误暴露风险。
  - 幂等、并发或人工确认：本次只有七个只读Tool；Store短锁只保护LRU查询/更新，实际HTTP不
    在锁内。没有写Tool、Approval或生产幂等语义变化。
- 开发中发现并修复：
  - 测试先行首次执行8项：非开发环境隐藏2项通过，目标development路由相关6项按预期失败；
    实现后专项扩展为12/12通过。
  - 首次Ruff报告19项：新路由中文说明标点和import排序，以及工作区已有M1.7中文讲解注释的
    全角标点与一行超长。保留全部中文含义，只调整标点、换行和导入格式；无运行行为变化，
    最终Ruff/mypy通过。
  - 最终复核发现Swagger成功示例把`ORDER-003`写成`IN_PRODUCTION`，与固定事实
    `QUALITY_CHECKING`不一致；已改成真实`orderId/productType/status`响应并增加OpenAPI断言，
    不涉及运行数据修改。
- 未完成项与已知问题：
  - 未完成项：M2+，包括Agent Session/Message/Run/Step持久化、确定性Workflow、动态Agent、
    RAG、SSE和Approval。
  - 已知问题/阻塞：无阻塞。调试Store仅当前进程有效且上限128；淘汰、重启、多worker或多实例
    不共享。同一Run身份/权限变化返回409，没有独立的Run结束/删除接口。
- 替代方案：
  - 采用的替代方案及原因：无临时替代方案。development条件路由、标准ToolResult和Swagger
    示例是T150～T153目标实现；有界进程内调试Store是为了在没有M2 Run表时保留M1.7跨请求语义。
  - 已覆盖/未覆盖的验收要求：完整覆盖T150～T153及M1“所有只读Tool可脱离Agent调用”的停止
    线；不覆盖生产管理API、持久化Run、分布式共享或用户级授权。
  - 局限、风险和转正/移除条件：Store只服务development手工调试。M2建立正式Run生命周期后，
    Workflow应使用持久化Run/Step而不是依赖该Store；调试Store可继续保留为有界开发工具，但
    不能升级为生产状态源。
- 后续影响：
  - 对后续任务/里程碑：M1到此验收完成并停止。M2可以先通过调试API确认每个Tool事实，再把
    同一Registry和BaseTool接入确定性Workflow；正式Run上下文仍需独立设计。
  - 对接口/数据/测试/部署：新增Python内部开发HTTP接口和OpenAPI Schema；Java、数据库、固定
    数据和前端无变化。Compose的Agent环境本就是development，因此本地`/docs`可见；生产部署
    必须明确设置`ENVIRONMENT=production`。Make的Tool回归增加M1.8专项。
- 测试与验证：
  - `[预期失败] agent-service内uv run --frozen pytest -q tests/integration/test_tool_debug_api.py` —
    首次8项中路由目标相关6项失败，证明测试先于实现。
  - `[通过] 同命令` — 最终M1.8专项12/12。
  - `[通过] make test-tools` — M1.4协议16/16；M1.5～M1.8集合127/127。
  - `[通过] agent-service内uv run --frozen pytest -q` — Python全量179/179。
  - `[通过] make quality` — Ruff通过；mypy strict检查31个源/测试文件无问题。
  - `[通过] agent-service内uv lock --check` — 解析42个直接及传递依赖。
  - `[通过] docker compose up --detach --build agent-service + make smoke` — 最终Agent镜像和三服务
    健康检查通过。
  - `[通过] 真实调试API调用Java ORDER-003` — 首次成功、同Run同参DUPLICATE_CALL、当前Trace
    正确、force_refresh后再次成功。
  - `[通过] make test` — foundation/Compose、三服务smoke、Python M1分项、Java 56/56、Web
    7/7及Vue生产构建全部通过。
  - `[命令位置错误后通过]` 最终组合检查首次在仓库根目录直接执行`uv lock --check`，因该目录
    没有`pyproject.toml`返回非零；改到`agent-service`目录后通过。锁文件和运行代码无需修改。
  - `[未运行] make reset-demo` — 本次不修改固定数据，且该命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/api/__init__.py`、`app/api/tool_debug.py`、`app/main.py`
  - `agent-service/tests/integration/test_tool_debug_api.py`
  - `agent-service/app/tools/deduplication.py`、`models.py`（仅保留并整理已有中文讲解注释）
  - `Makefile`、`README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；Compose development会暴露调试接口到本机8000端口，因此不能把
    当前Compose配置原样当生产部署；Store淘汰会重置该调试Run的重复检测历史。
  - 后续兼容注意事项：新增Tool时自动可被Registry路径调用，但仍需Swagger/契约测试覆盖其
    Schema；修改调试请求、HTTP/Tool错误分层或Store容量语义时需同步OpenAPI和测试。
- Agent面试价值评估：
  - 有价值，已更新`doc/needCare.md`。本次体现Tool可独立验证、开发/生产控制面隔离、标准结果
    协议、Trace、Run上下文复用和有界状态取舍，能够真实解释如何把Tool问题与模型路由问题分层。
- 下一建议任务：
  - M1停止线已满足。若用户确认进入M2，下一最小任务为`[T201]`创建Agent Session基础模型，
    并与T202～T205的数据表/迁移边界一起规划。

---

## 2026-08-08 — `[T201-T206] M2.1 Agent 基础数据表`

- 里程碑：M2 确定性订单诊断
- 任务类型：功能 / 数据模型 / 迁移 / 测试 / 文档
- 目标与范围：
  - 本次实现：创建`agent_sessions`、`agent_messages`、`agent_runs`、`agent_steps`四张Agent自有
    SQLAlchemy模型；建立首个Alembic revision；实现Run/Step异步Repository增删查；提供隔离
    PostgreSQL专项验收并将开发数据库迁移到head。
  - 明确不实现：不进入M2.2/M2.3，不实现Run合法状态流转、Step开始/成功/失败服务、Workflow、
    LangGraph、LLM、RAG、SSE、Approval或前端Agent布局；不修改Java接口和固定业务数据。
- 需求与关键决策：
  - 业务背景/固定数据映射：四张表只记录Agent会话和执行过程。`ORDER-003`订单、任务、质检、
    复核和交付事实仍必须通过Java只读Tool取得，Python不为Java业务表建立ORM映射。
  - 数据层级：Session拥有按序Message和Run；Run可关联触发它的用户Message并拥有按序Step。
    `(session_id, sequence_number)`与`(run_id, sequence_number)`唯一约束防止同一作用域出现两个
    相同序号。
  - 状态契约：Run状态固定为`PENDING/RUNNING/SUCCEEDED/FAILED/WAITING_APPROVAL/CANCELLED`；
    Step类型为`CONTEXT/TOOL/RULE/LLM`，Step状态为`PENDING/RUNNING/SUCCEEDED/FAILED`。当前只
    稳定存储契约，不提前实现M2.2/M2.3服务行为。
  - 枚举选择：使用Python`StrEnum`和数据库VARCHAR Check Constraint，不使用PostgreSQL私有
    enum，保留类型和数据库约束，同时降低后续增加状态时修改原生enum类型的迁移复杂度。
  - 事务边界：Repository执行`flush`以在当前事务内尽早暴露外键、唯一约束等错误，但不隐式
    `commit`。后续生命周期服务可把Run与多个Step放在同一事务内整体提交或回滚。
  - 删除语义：Session删除级联Message、Run、Step；Run删除级联Step；Message删除对Run使用
    `SET NULL`，避免删除请求文本时连带抹除已经发生的运行证据。
  - 数据最小化：Step只预留受控`input_summary/output_summary`，不默认存完整Prompt、Token、
    密钥或原始业务响应；具体脱敏和截断策略留给T217实现。
- 核心实现：
  - `agent-service/app/models/agent_runtime.py` — `AgentSession`、`AgentMessage`、`AgentRun`、
    `AgentStep`及四组枚举：定义字段、关系、默认值、索引、外键、唯一约束和检查约束。
  - `agent-service/app/repositories/agent_runtime.py` — `AgentRunRepository`、
    `AgentStepRepository`：提供`create/get/list_by_*/delete`，稳定排序并让上层拥有事务。
  - `agent-service/migrations/versions/0001_agent_runtime_base.py` — `upgrade/downgrade`：按外键依赖
    正序创建、逆序移除四表；不接触Java Flyway表。
  - `agent-service/migrations/env.py` — 通过导入`AgentSession`加载模型包，使Alembic
    `target_metadata`包含四张表，而不是只看到空`Base`。
  - `agent-service/tests/test_agent_persistence.py` — metadata白名单、真实migration、Schema drift、
    CRUD、级联、重复序号异常和downgrade集成测试。
  - `scripts/test-agent-persistence.sh`、`Makefile` — 使用随机宿主端口、tmpfs和退出清理的独立
    PostgreSQL容器执行`make test-agent-persistence`，并纳入完整`make test`。
  - 必要的最小流程：

    ```text
    上层生命周期服务（M2.2以后）
    → Database.session / AsyncSession事务
    → AgentRunRepository.create + AgentStepRepository.create
    → flush触发数据库约束
    → 上层统一commit或rollback
    ```

- 代码解释与定位：
  - 整体调用/数据流：未来HTTP/Workflow先创建或取得Session和用户Message，再创建PENDING Run；
    每个上下文、Tool、规则或LLM动作作为有序Step归属Run；当前M2.1只提供底层持久化能力，没有
    自动执行这条链路。
  - 输入、输出、异常和边界：Repository输入是已构造ORM对象或稳定ID，输出是持久化对象、列表、
    可空查询结果或删除布尔值。空查询返回`None`/空列表；重复序号、非法外键和检查约束由
    SQLAlchemy/数据库异常暴露给上层，当前不包装为Tool错误。
  - 核心类、函数、接口或配置项：四个Model、四组`StrEnum`、两个Repository、migration
    `upgrade/downgrade`、`migrated_database_url`fixture和`test-agent-persistence`Make目标。
  - 关键代码位置在全部修改后重新核对并以最终回复链接为准。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：本次不是HTTP或Tool层，不新增权限/超时错误映射。数据库约束作为
    持久化异常向事务调用方传播；测试验证重复Step序号必然失败并可rollback。
  - 幂等、并发或人工确认：`delete`对不存在ID返回False；序号唯一约束提供并发冲突的最终防线，
    但自动序号分配尚未实现。没有写Tool或Approval语义变化。
  - 敏感信息：模型未设置Token/密钥字段；Step只保存摘要。`final_result`是为T211预留的JSON，
    后续写入前仍需定义脱敏、大小和版本契约。
- 开发中发现并修复：
  - 测试先行首次执行因`app.models`不存在产生1个预期收集错误，实现后消除。
  - 首轮数据库集成测试误连本机`127.0.0.1:5432`而不是Docker发布端口，返回“role agent does
    not exist”。根因是本机PostgreSQL和Docker同时监听5432；改为专项脚本启动随机宿主端口、
    tmpfs临时数据库并在退出时自动删除，避免误用或污染本机/开发数据库。
  - 首次Repository CRUD在查询触发SQLAlchemy`autobegin`后再次调用`session.begin()`，产生
    `InvalidRequestError`；测试改为在当前事务继续删除并由调用方显式commit，运行代码无需绕过
    SQLAlchemy事务语义。
  - 首次mypy报告asyncpg缺少`py.typed`；在测试导入处使用精确`import-untyped`说明，未关闭全局
    strict检查。
  - 完整Ruff发现既有`tool_debug.py`导入块空行及中文全角标点格式漂移；只做机械格式修正，不
    改变M1.8行为。
  - 同步Python学习手册时发现`httpx`仍被写成dev依赖，而当前`pyproject.toml`已将其作为运行时
    Java Client依赖；已按真实配置更正，不修改锁文件或依赖版本。
- 未完成项与已知问题：
  - 未完成项：M2.2 Run生命周期、M2.3 Step记录，以及后续Workflow、RAG、动态Agent、SSE和
    Approval。
  - 已知问题/阻塞：无阻塞。持久化Run尚未与`ToolContext.run_id`和调试API绑定；Run/Step字段
    目前不会自动流转。没有Step摘要脱敏/截断、数据保留/归档或生产数据库角色隔离。
- 替代方案：
  - 采用的替代方案及原因：无临时业务替代方案。随机端口tmpfs PostgreSQL是正式测试隔离策略，
    用于真实验证PostgreSQL/Alembic而不依赖或污染开发库。
  - 已覆盖/未覆盖的验收要求：完整覆盖T201～T206的模型、migration和Run/Step增删查；不覆盖
    T207以后状态机、自动记录、业务诊断或跨实例恢复。
  - 局限、风险和转正/移除条件：数据库集成用例在普通Python全量测试中若未提供专用环境变量会
    安全跳过，完整验证必须运行`make test-agent-persistence`；该目标需要Docker可用。它不是
    SQLite替代测试，不需要在后续“转正”，但CI必须执行根级专项或完整`make test`。
- 后续影响：
  - 对后续任务/里程碑：M2.2可直接基于`AgentRunStatus`和Run Repository实现合法状态流转；
    M2.3可基于Step字段记录摘要、错误和耗时。后续不能为每次Step独立commit，也不能把
    `final_result`当作最新Java业务事实。
  - 对接口/数据/测试/部署：Java API、Tool Schema、固定数据和前端无变化；Python数据库新增四表
    及`agent_alembic_version=0001_agent_runtime_base`。新环境启动Agent功能前需要执行
    `make agent-migrate`；当前应用启动不会自动迁移。
- 测试与验证：
  - `[预期失败] agent-service内uv run --frozen pytest -q tests/test_agent_persistence.py
    tests/test_alembic.py` — 收集阶段1个`ModuleNotFoundError`。
  - `[通过] make test-agent-persistence` — 隔离PostgreSQL专项5/5。
  - `[通过] agent-service内uv run --frozen pytest -q` — 180通过、3个数据库集成用例按安全门禁
    跳过；同3项已由专项真实执行。
  - `[通过] make quality` — Ruff通过；mypy strict检查36个源/测试文件无问题。
  - `[通过] docker compose build agent-service + make agent-migrate` — 开发库revision和四表存在。
  - `[通过] docker compose up --detach --build agent-service + make smoke` — 最终镜像及三服务健康。
  - `[通过] make test` — foundation/Compose、三服务smoke、Python M1分项、M2.1专项、Java
    56/56、Web 7/7和Vue生产构建全部通过。
  - `[未运行] make reset-demo` — 本次不修改固定业务数据，且命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/models/__init__.py`、`models/agent_runtime.py`
  - `agent-service/app/repositories/__init__.py`、`repositories/agent_runtime.py`
  - `agent-service/migrations/env.py`、`migrations/versions/0001_agent_runtime_base.py`
  - `agent-service/app/database.py`、`app/api/tool_debug.py`（后者仅机械格式）
  - `agent-service/tests/test_agent_persistence.py`、`tests/test_alembic.py`
  - `scripts/test-agent-persistence.sh`、`Makefile`
  - `README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；开发库Java/Python仍共用角色；应用启动不会自动执行migration；
    `final_result`和摘要字段尚无大小/保留策略。
  - 后续兼容注意事项：修改状态枚举、字段或约束必须新增Alembic revision并运行`alembic check`；
    M2.2必须显式限制状态转换，不能因为数据库允许任意合法枚举值就允许状态倒退。
- Agent面试价值评估：
  - 有价值，已更新`doc/needCare.md`。本次建立Agent Run/Step可观测性事实模型，体现Agent元数据
    与Java业务事实的边界、事务归属、顺序约束、摘要数据最小化和真实migration验证，能形成
    可举证的Agent工程设计取舍。
- 下一建议任务：
  - `[T207-T213] M2.2 最小Run生命周期`。

---

## 2026-08-09 17:30 — `[T207-T213] M2.2 最小 Run 生命周期`

- 里程碑：M2 确定性订单诊断
- 任务类型：功能 / 状态机 / 并发安全 / 测试 / 文档
- 目标与范围：
  - 本次实现：在M2.1的`agent_runs`表和Repository上实现Run创建、开始、成功、失败四个生命周期
    操作；保存开始/结束时间、标准JSON结果、失败错误码和错误步骤；用隔离PostgreSQL验证合法与
    非法流转、资源不存在和并发终态竞争。
  - 明确不实现：不进入M2.3，不自动创建Step；不接入Tool调试API、HTTP入口、LangGraph、确定性
    Workflow、LLM、RAG、SSE或前端；不实现`WAITING_APPROVAL`、`CANCELLED`、暂停恢复和审批；
    不修改Java接口、固定业务数据或数据库Schema。
- 需求与关键决策：
  - 最小状态图只开放`PENDING → RUNNING → SUCCEEDED/FAILED`。数据库枚举约束只保证状态值合法，
    生命周期服务负责限制合法边及终态字段的一致性。
  - 成功终态保存`final_result`并清空错误字段；失败终态保存`error_code/error_step`并清空结果，
    避免同一Run同时表现为成功和失败。结果是本次执行快照，不作为最新Java业务事实。
  - Repository使用带预期状态条件的单条`UPDATE ... RETURNING`实现compare-and-set。并发成功和
    失败都从RUNNING抢终态时只有一个事务能更新，避免“先查再写”的丢失更新。
  - 条件更新未命中后再读当前记录：不存在映射为`RunNotFoundError`，状态不匹配映射为
    `InvalidRunTransitionError`，为后续入口层保留稳定、可区分的错误语义。
  - `final_result`先执行标准JSON序列化和复制，拒绝`datetime`、NaN等跨语言不稳定值；时钟可注入
    并拒绝无时区时间，确保测试确定性和部署时间语义明确。
  - Service和Repository均不隐式commit，事务继续由未来HTTP/Workflow调用方控制。失败码暂不
    绑定`ToolErrorCode`，因为Run还可能失败在CONTEXT、RULE或LLM步骤。
- 核心实现：
  - `agent-service/app/services/run_lifecycle.py` — `RunLifecycleService`：提供`create_run`、
    `mark_running`、`mark_succeeded`、`mark_failed`，集中状态规则、时间、结果和错误字段校验。
  - `agent-service/app/services/run_lifecycle.py` — `RunNotFoundError`、
    `InvalidRunTransitionError`、`RunLifecycleValidationError`：分离资源缺失、状态冲突和调用参数错误，
    暂不耦合HTTP或Tool协议。
  - `agent-service/app/repositories/agent_runtime.py` — `transition_status`：限制可更新字段，并在数据库
    单条语句中原子比较预期状态、更新目标状态和返回新Run。
  - `agent-service/tests/test_agent_persistence.py` — 五个M2.2集成用例：成功、失败、非法输入/流转、
    缺失Run和两个独立事务竞争终态。
  - `scripts/test-agent-persistence.sh`、`Makefile` — 脚本透传pytest过滤参数；新增
    `make test-run-lifecycle`独立验收，完整`make test-agent-persistence`保留M2.1～M2.2联合回归。
  - 必要的最小流程：

    ```text
    上层在AsyncSession事务内构造RunLifecycleService
    → create_run：INSERT PENDING + flush
    → mark_running：WHERE status=PENDING原子更新RUNNING与started_at
    → mark_succeeded或mark_failed：WHERE status=RUNNING原子抢占唯一终态
    → 上层commit；异常时整体rollback
    ```

- 代码解释与定位：
  - 整体调用/数据流：当前集成测试先创建父`AgentSession`，再由Lifecycle创建PENDING Run；开始和
    结束动作通过同一个Service调用Repository条件更新。未来Workflow可以复用这条链，但本次未
    自动接线。
  - 核心类、函数、接口或配置项：`RunLifecycleService`四个公开方法、`_transition`、
    `_json_snapshot`、三类内部异常、`AgentRunRepository.transition_status`、五个真实数据库用例及
    `test-run-lifecycle`Make目标。
  - 输入、输出、异常和边界：创建输入稳定Run/Session/可选Message ID，转换输入Run ID及结果或
    错误定位，输出更新后的`AgentRun`。标识空白/超长、无时区时钟、非标准JSON、未知Run和非法
    状态均在Service边界拒绝；父Session/Message外键错误仍由数据库在flush阶段暴露。
  - 关键代码位置在全部修改和文档追加后重新核对，并以最终回复中的绝对路径行号为准。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：本次是内部生命周期层，不新增HTTP状态或权限校验；不把Java或Tool
    错误转换逻辑复制到Run服务。错误码只保存机器可读定位，不保存异常堆栈、Token或原始业务响应。
  - 幂等、并发或人工确认：重复开始、跳过RUNNING和终态回退被拒绝；并发终态由数据库CAS保护。
    这不是完整请求幂等，也没有Approval；失败后若需整次重试，未来应创建新Run并保留关联，而非
    重置历史终态。
- 开发中发现并修复：
  - 测试先行首次收集因`app.services`不存在产生1个预期`ModuleNotFoundError`，完成Service后消除。
  - 首次完整`make quality`发现已提交M2.1模型中的中文学习注释存在导入间距、空行、尾随空白和
    全角标点格式漂移；保留原说明含义，仅在`app/models/agent_runtime.py`机械调整格式，未修改
    模型字段、约束或运行行为。
- 未完成项与已知问题：
  - 未完成项：M2.3 Step自动记录、摘要、错误和耗时；Tool/Workflow生命周期接线；
    `WAITING_APPROVAL/CANCELLED`操作；Run级整次重试关联、超时回收、崩溃恢复、SSE和保留策略。
  - 已知问题/阻塞：无阻塞。调试Run内存上下文与持久化Run仍是两套生命周期；`final_result`尚无
    大小限制和归档策略；本地Java/Python数据库角色仍未隔离。
- 替代方案：
  - 采用的替代方案及原因：无临时业务替代方案。沿用M2.1的随机端口、tmpfs隔离PostgreSQL，
    是正式数据库集成测试策略；本次没有用内存Store或SQLite替代真实并发语义。
  - 已覆盖/未覆盖的验收要求：覆盖T207～T213最小生命周期、结果/错误保存、非法流转和并发竞争；
    未覆盖Step、Workflow、审批、取消或生产调度能力，均未包装为已完成。
  - 局限、风险和转正/移除条件：普通Python全量测试在未提供专用数据库环境变量时安全跳过8个
    数据库用例，CI和开发验收必须执行`make test-agent-persistence`或完整`make test`；专项需要
    Docker，但无需迁移为SQLite测试。
- 后续影响：
  - 对后续任务/里程碑：M2.3应复用同一事务所有权，在Run的执行窗口内记录Step，不能让每个Step
    自行commit；Workflow接入时必须在异常路径调用`mark_failed`，并把具体失败Step名称保存到
    `error_step`。
  - 对接口/数据/测试/部署：没有Schema、Alembic revision、Java API、Tool Schema、固定数据或
    前端契约变化；Agent镜像新增Service模块。未来公开HTTP/SSE前需单独设计生命周期错误映射和
    结果Schema，不能直接暴露内部异常文本。
- 测试与验证：
  - `[预期失败] make test-agent-persistence` — 首次收集阶段1个`ModuleNotFoundError`，目标Service
    尚不存在。
  - `[通过] make test-run-lifecycle` — M2.2隔离PostgreSQL专项5/5。
  - `[通过] make test-agent-persistence` — M2.1～M2.2持久化联合回归10/10。
  - `[通过] agent-service内uv run --frozen pytest -q` — 180通过、8个数据库用例按环境门禁跳过；
    同组用例已由专项真实执行。
  - `[通过] make quality` — Ruff通过；mypy strict检查38个源/测试文件无问题。
  - `[通过] docker compose up --detach --build agent-service + make smoke` — 最终Agent镜像和三服务
    健康检查通过。
  - `[通过] make test` — foundation/Compose、三服务smoke、Python M1分项、M2.1～M2.2专项、
    Java 56/56、Web 7/7和Vue生产构建全部通过。
  - `[未运行] make reset-demo` — 本次不修改Java固定业务数据，且命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/services/__init__.py`、`app/services/run_lifecycle.py`
  - `agent-service/app/repositories/agent_runtime.py`
  - `agent-service/app/models/agent_runtime.py`（只机械修复既有中文注释格式）
  - `agent-service/tests/test_agent_persistence.py`
  - `scripts/test-agent-persistence.sh`、`Makefile`
  - `README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；已知非阻塞边界见“未完成项与已知问题”。
  - 后续兼容注意事项：增加状态边必须同时更新Service、并发/非法流转测试和文档；公开
    `final_result`前必须固定Schema和大小策略；不要把历史结果快照当作最新Java业务事实。
- Agent面试价值评估：
  - 有价值，已更新`doc/needCare.md`。本次真实实现并验证了Agent Run显式状态机、数据库CAS并发
    保护、结果/错误互斥、标准JSON快照及事务边界，能够回答Agent可观测性和并发一致性取舍。
- 下一建议任务：
  - `[T214-T220] M2.3 最小Step记录`。

---

## 2026-08-09 18:00 — `[T214-T220] M2.3 最小 Step 记录`

- 里程碑：M2 确定性订单诊断
- 任务类型：功能 / 可观测性 / 并发安全 / 数据最小化 / 测试 / 文档
- 目标与范围：
  - 本次实现：为CONTEXT、TOOL、RULE、LLM Step提供开始、成功和失败记录；自动关联RUNNING父Run；
    保存受控输入输出摘要、错误码、起止时间和毫秒耗时；用真实PostgreSQL验证父Run门禁、非法
    流转、摘要保护和并发终态竞争。
  - 明确不实现：不进入M2.4，不定义Workflow State或诊断Schema；不接入Tool调试API、LangGraph、
    确定性Workflow、LLM、RAG、SSE或前端；不自动分配Step序号，不增加Trace ID、retry_count、
    恢复/回收或Run终态聚合检查；不修改Java接口、固定数据或数据库Schema。
- 需求与关键决策：
  - Step最小状态图为`start_step → RUNNING → SUCCEEDED/FAILED`。T214记录的是已经开始的动作，
    因此Service直接插入RUNNING；M2.1保留的PENDING状态留给未来排队/调度能力，本次不虚构调度器。
  - `start_step`要求父Run存在且为RUNNING，使用`SELECT ... FOR UPDATE`刷新并锁定父Run。该短事务
    与Run终态UPDATE串行化，避免检查后Run结束、随后又插入新Step的竞争窗口。
  - Step终态使用`UPDATE ... WHERE step_id=? AND status=RUNNING RETURNING ...`。成功清空错误码，
    失败保存机器错误码，两者同时写入输出摘要、结束时间和毫秒耗时；并发成功/失败只有一个胜出。
  - 完成前读取`started_at`计算耗时。CAS失败后使用`populate_existing`强制刷新ORM identity map，
    防止返回会话中缓存的旧RUNNING状态。
  - 摘要只接受调用方构造的字符串，不自动序列化业务对象；合并空白、遮盖常见Bearer Token、
    API Key、access token、password和secret值，超过1000字符截断。该策略是纵深防御，不等同
    完整PII/DLP，未来Workflow仍必须基于字段白名单构造摘要。
  - Repository和Service继续只flush不commit；上层拥有事务。父Run行锁只用于Step记录短事务，
    后续不能跨Java HTTP、模型调用或人工等待长期持有。
- 核心实现：
  - `agent-service/app/services/step_lifecycle.py` — `StepLifecycleService.start_step`：校验ID、正序号、
    Step类型和名称，规范化输入摘要，锁定RUNNING父Run并创建关联Step。
  - 同文件 — `mark_succeeded/mark_failed/_finish`：区分成功和失败字段，计算耗时，以CAS抢占唯一
    终态，并在冲突后读取数据库最新状态。
  - 同文件 — `_normalize_summary`和`STEP_SUMMARY_MAX_LENGTH`：压缩空白、常见凭据遮盖、1000字符
    截断；不记录或输出原始凭据。
  - 同文件 — `StepNotFoundError`、`InvalidStepTransitionError`、`StepRunUnavailableError`、
    `StepLifecycleValidationError`：区分Step缺失、状态冲突、父Run不可用和参数错误，暂不绑定HTTP。
  - `agent-service/app/repositories/agent_runtime.py` — `AgentRunRepository.get_for_update`：锁定并刷新
    父Run；`AgentStepRepository.get_fresh/transition_status`：刷新ORM缓存并原子更新Step终态。
  - `agent-service/tests/test_agent_persistence.py` — 六个M2.3真实数据库用例，覆盖成功、失败、父Run
    门禁、非法数据/流转、缺失Step、摘要保护、并发终态和父Run锁阻塞。
  - `Makefile` — 新增`make test-step-lifecycle`，并把联合目标说明扩展为M2.1～M2.3。
  - 必要的最小流程：

    ```text
    上层短事务
    → 锁定RUNNING Run
    → INSERT RUNNING Step + input_summary + started_at
    → commit并释放父Run锁
    → 实际执行CONTEXT/TOOL/RULE/LLM动作(未来Workflow)
    → 新短事务以CAS写入SUCCEEDED/FAILED、output_summary和duration_ms
    ```

- 代码解释与定位：
  - 整体调用/数据流：当前集成测试创建并启动父Run，再直接调用StepLifecycleService；未来Workflow
    应在动作前后分别使用短事务调用start/finish，不能把网络或模型等待包进父Run锁事务。
  - 核心类、函数、接口或配置项：`StepLifecycleService`三个公开方法、四类内部异常、摘要规则、
    父Run锁查询、Step CAS更新、6个集成测试和`test-step-lifecycle`Make目标。
  - 输入、输出、异常和边界：输入稳定Step/Run ID、正序号、`AgentStepType`、非空名称和可选摘要；
    输出更新后的`AgentStep`。父Run不存在/非RUNNING、Step不存在/已终态、无时区或倒退时间、空
    错误码和非法标识被明确拒绝；重复序号仍由数据库唯一约束在flush时拒绝。
  - 关键代码位置在全部修改和文档追加后重新核对，并以最终回复中的绝对路径行号为准。
- 异常、安全与边界：
  - 参数/权限/超时/上游异常：本次不新增HTTP、权限或Java错误映射；未来Workflow应将Tool错误码
    传给失败Step，但不能保存完整异常堆栈或原始响应。
  - 幂等、并发或人工确认：重复终态被拒绝，成功/失败竞争由数据库CAS保护；父Run行锁保护开始
    关联。这不是消息幂等、分布式锁或exactly-once，也没有Approval变化。
- 开发中发现并修复：
  - 测试先行首次执行因`InvalidStepTransitionError`等尚未从`app.services`导出产生1个预期收集
    `ImportError`，完成Service和导出后消除。
  - 任务开始的质量基线发现已提交M2.2讲解注释存在6个Ruff全角标点问题；保留用户增加的中文
    解释含义，仅机械调整标点、空白和方法间距，未改变Run生命周期行为。
  - M2.3首次质量检查在15个数据库用例通过后报告2个可修复的`__all__`和测试导入排序问题；按
    isort顺序调整，最终Ruff和mypy strict通过。
  - 最终组合验证第一次误在`agent-service/`目录执行`make quality`，该子目录没有此根级目标而
    立即退出；返回仓库根目录重跑后通过。这是命令工作目录错误，不是代码或环境故障。
- 未完成项与已知问题：
  - 未完成项：M2.4 Workflow State/诊断Schema，以及Tool/Workflow自动Run/Step记录、Step序号自动
    分配、Trace/retry_count、Run终态聚合检查、崩溃回收、SSE和前端步骤展示。
  - 已知问题/阻塞：无阻塞。摘要正则不能覆盖所有凭据、个人信息和业务敏感字段；调试Run内存
    上下文与持久化Run仍未关联；本地Java/Python数据库角色仍未隔离。
- 替代方案：
  - 采用的替代方案及原因：无临时业务替代方案。真实PostgreSQL用于验证行锁、CAS和ORM缓存刷新，
    没有用内存Store或SQLite替代。现有字段足够覆盖T214～T220，因此没有制造空Alembic revision。
  - 已覆盖/未覆盖的验收要求：覆盖Step开始/成功/失败、摘要、耗时、Run关联和自动化测试；未覆盖
    Workflow接线、全量DLP、序号分配和恢复能力，均未包装为已完成。
  - 局限、风险和转正/移除条件：普通Python全量在没有专用数据库变量时安全跳过13个集成用例；
    CI和开发验收必须执行`make test-agent-persistence`或完整`make test`。摘要正则只能作为长期
    纵深防御，不能替代后续字段白名单和合规策略。
- 后续影响：
  - 对后续任务/里程碑：M2.4可定义结构化Workflow State，M2.5接入节点时应在动作前后使用短事务
    调用Step服务，并决定并发安全的序号分配；Run成功前应检查所有Step终态或由固定Workflow严格
    保证完成顺序。
  - 对接口/数据/测试/部署：无数据库Schema/Alembic、Java API、Tool Schema、固定数据或前端契约
    变化；Agent镜像新增Step服务。未来公开查询/SSE前需设计响应Schema、权限和摘要展示规则。
- 测试与验证：
  - `[预期失败] make test-agent-persistence` — 首次收集阶段1个`ImportError`，目标Step服务尚不存在。
  - `[通过] make test-step-lifecycle` — M2.3隔离PostgreSQL专项6/6，包含父Run行锁阻塞实证。
  - `[通过] make test-agent-persistence` — M2.1～M2.3联合回归16/16。
  - `[通过] agent-service内uv run --frozen pytest -q` — 180通过、14个数据库用例按环境门禁跳过；
    同组用例已由专项真实执行。
  - `[通过] make quality` — Ruff通过；mypy strict检查39个源/测试文件无问题。
  - `[命令位置错误后通过] agent-service内make quality → 根目录make quality` — 第一次因子目录
    不存在根级Make目标而退出，切回仓库根目录后通过。
  - `[通过] docker compose up --detach --build agent-service + make smoke` — 最终Agent镜像和三服务
    健康检查通过。
  - `[通过] make test` — foundation/Compose、三服务smoke、Python M1分项、M2.1～M2.3专项、
    Java 56/56、Web 7/7和Vue生产构建全部通过。
  - `[通过] make validate + Markdown code fence检查 + sh -n + git diff --check` — 基础目录与Compose
    配置、修改文档围栏、测试脚本语法和差异空白均通过。
  - `[未运行] make reset-demo` — 本次不修改Java固定业务数据，且命令会删除本地持久卷。
- 变更文件：
  - `agent-service/app/services/step_lifecycle.py`、`app/services/__init__.py`
  - `agent-service/app/repositories/agent_runtime.py`
  - `agent-service/app/services/run_lifecycle.py`（只机械修复已提交讲解注释格式）
  - `agent-service/tests/test_agent_persistence.py`
  - `Makefile`
  - `README.md`、`agent-service/README.md`、`doc/pythonKnowledge.md`
  - `docs/ROADMAP.md`、`docs/STATUS.md`、`docs/TEST_REPORT.md`
  - `doc/needCare.md`、`doc/record.md`
- 风险与遗留：
  - 已知风险/阻塞：无阻塞；摘要规则和自动接线等非阻塞边界见“未完成项与已知问题”。
  - 后续兼容注意事项：摘要上限或脱敏规则变化需同步测试和展示契约；新增Step类型/状态需要新增
    Alembic revision；不能跨网络调用持有父Run锁，也不能把历史Step摘要当最新Java业务事实。
- Agent面试价值评估：
  - 有价值，已更新`doc/needCare.md`。本次建立Agent步骤级执行证据，真实实现父Run一致性、Step
    并发终态、ORM缓存刷新、耗时和摘要最小化，能够说明可观测性与数据安全的工程取舍。
- 下一建议任务：
  - `[T221-T226] M2.4 Workflow状态模型`。
