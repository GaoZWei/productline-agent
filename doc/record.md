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
