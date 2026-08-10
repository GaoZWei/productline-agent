# 当前项目 Python 工程学习手册

本文面向第一次接触 Python 后端项目的开发者，以本仓库 `agent-service` 的真实实现为准，并通过 Java Spring Boot 和 Node.js 服务进行类比。

本文描述的是当前 M1.1～M2.5 已实现能力，不是通用 Python 项目模板。后续代码变化时，应先以仓库实现、`doc/detailed-plan.md` 和 `doc/record.md` 为准，再同步更新本文。

## 1. 先建立整体认识

当前 `agent-service` 是一个独立的 Python 后端服务，主要承担未来的 Tool 封装、Workflow、
Agent、RAG、Approval 和运行记录。现阶段只完成工程基础、健康检查、数据库基础、迁移骨架、
最小可观测性、Java 异步 HTTP Client、标准错误映射、Tool 基础协议和七个只读业务 Tool；
只读 Tool 已实现一次有限退避重试和 Run 内重复调用检测。M2.1 已增加 Session、Message、Run、
Step持久化基础，M2.2～M2.3已实现最小Run/Step状态流转，M2.4已定义Workflow状态与结构化诊断
Schema，M2.5已实现固定LangGraph数据加载节点、状态合并、失败中断和Step记录适配；诊断规则、
HTTP入口和大模型调用尚未实现。

### 1.1 Python、Java、Node 工程对应关系

| Python Agent Service | Java Spring Boot | Node.js Service | 主要作用 |
| --- | --- | --- | --- |
| `pyproject.toml` | `pom.xml` | `package.json`、`tsconfig.json`、ESLint 配置 | 项目、依赖和工具配置 |
| `uv.lock` | Maven 通常没有同等锁文件 | `package-lock.json` | 锁定精确依赖版本与哈希 |
| `.python-version` | JDK 版本要求/Toolchains | `.nvmrc` | 指定 Python 3.12 |
| `.venv/` | 项目 classpath 与本地运行环境 | `node_modules/` | 保存项目解释器和已安装依赖 |
| `app/main.py` | `Application.java` + 最小 Controller | `server.mjs` / `main.ts` | 应用入口和 HTTP 组装 |
| FastAPI | Spring MVC | Express/NestJS | Web 框架和路由 |
| Uvicorn | 内嵌 Tomcat/Netty | Node HTTP Server | 监听端口并执行 Web 应用 |
| Pydantic | DTO + Bean Validation + Jackson | Zod/class-validator | 运行时校验和序列化 |
| SQLAlchemy | JPA/Hibernate | Prisma/TypeORM | 数据库访问和 ORM |
| Alembic | Flyway/Liquibase | Prisma Migrate/Knex | 数据库结构版本管理 |
| pytest | JUnit 5 | Vitest/Jest | 自动化测试 |
| Ruff | Checkstyle + 部分 Spotless | ESLint + 部分 Prettier | 代码规范和静态问题检查 |
| mypy | Java 编译器类型检查 | `tsc` | 检查 Python 类型提示 |

这些工具只是职责相近，不是完全等价。例如 Python 类型提示默认不会在运行时强制校验，
而 Java 类型由编译器强制；Python 对外部输入的运行时校验主要由 Pydantic 完成。

### 1.2 当前服务之间的边界

```text
Web Console
采集页面上下文、展示业务事实和未来的 Agent 结果
        ↓
Python Agent Service
未来通过 Tool 调用 Java，负责编排、归纳和 Agent 自有状态
        ↓ HTTP API
Java Business Service
负责订单、任务、质检、复核、交付事实及最终写入
```

Python 可以保存 Agent 自有的 Run、Step、Approval 或 RAG 元数据，但不得为 Java 的订单、
生产、质检、复核和交付表建立 ORM 映射，也不得绕过 Java API 读取或修改业务事实。

## 2. 当前目录结构

```text
agent-service/
├── .python-version                 # uv 使用的 Python 主版本
├── pyproject.toml                  # 项目、依赖、pytest、Ruff、mypy 配置
├── uv.lock                         # uv 生成的精确依赖锁文件
├── Dockerfile                      # Python 服务生产镜像
├── README.md                       # 本模块启动和数据边界说明
├── alembic.ini                     # Alembic 入口配置
│
├── app/                            # 正式运行代码，类似 src/main/java 或 src/
│   ├── __init__.py                 # 标识 app 为 Python 包
│   ├── main.py                     # FastAPI 应用工厂、健康接口、Uvicorn 入口
│   ├── settings.py                 # 环境变量与配置校验
│   ├── database.py                 # 异步 Engine、Session 和 ORM 元数据根
│   ├── observability.py            # JSON 日志和 Trace ID 中间件
│   ├── models/
│   │   └── agent_runtime.py         # Session、Message、Run、Step ORM 模型
│   ├── repositories/
│   │   └── agent_runtime.py         # Run、Step异步增删查和原子状态更新
│   ├── services/
│   │   ├── run_lifecycle.py         # 最小Run生命周期与内部异常
│   │   └── step_lifecycle.py        # Step记录、摘要保护和耗时
│   ├── workflows/
│   │   ├── order_diagnosis.py       # 固定LangGraph加载节点与失败路由
│   │   └── recording.py             # Workflow到Step生命周期的短事务适配
│   ├── clients/
│   │   └── business.py             # 调用 Java 的异步 HTTP Client
│   └── schemas/
│       ├── business.py             # 身份、成功信封和强类型响应
│       ├── tools.py                # 七个只读Tool的输入输出Schema
│       └── workflow.py             # Workflow状态与结构化诊断Schema
│
├── migrations/                     # Alembic 迁移环境
│   ├── env.py                      # 加载配置、Base.metadata 和异步连接
│   ├── script.py.mako              # 生成迁移文件时使用的模板
│   └── versions/
│       └── 0001_agent_runtime_base.py # 创建四张 Agent 自有表
│
└── tests/                          # 测试代码，类似 src/test/java 或 *.spec.ts
    ├── test_health.py
    ├── test_database.py
    ├── test_observability.py
    ├── test_alembic.py
    ├── test_business_client.py
    ├── test_agent_persistence.py   # 隔离PostgreSQL迁移、Repository与生命周期测试
    └── test_order_diagnosis_workflow.py # 固定节点、合并和失败中断测试
```

本地运行后还会看到以下生成目录：

```text
.venv/          uv 创建的项目虚拟环境
__pycache__/    Python 字节码缓存
.pytest_cache/  pytest 测试缓存
.mypy_cache/    mypy 类型检查缓存
.ruff_cache/    Ruff 检查缓存
```

这些目录可以删除后重新生成，不应提交到 Git，也不能当成项目源码阅读。

## 3. Python 版本、依赖和虚拟环境

### 3.1 `.python-version`

[`agent-service/.python-version`](../agent-service/.python-version) 内容为：

```text
3.12
```

它告诉 uv 当前项目使用 Python 3.12，作用类似 Java 项目要求 JDK 21，或 Node 项目通过
`.nvmrc` 要求 Node 22。

即使本机默认 `python3` 不是 3.12，也应通过 uv 运行：

```bash
cd agent-service
uv run python --version
```

不要依赖系统默认 `python3`，否则可能使用错误解释器或找不到项目依赖。

### 3.2 `pyproject.toml`

[`agent-service/pyproject.toml`](../agent-service/pyproject.toml) 是 Python 工程的核心配置。
它同时承担 Maven `pom.xml`、Node `package.json`、TypeScript/Ruff/mypy/pytest 配置的部分职责。

项目和 Python 版本：

```toml
[project]
name = "productline-agent-service"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
```

运行时依赖：

```toml
dependencies = [
  "alembic>=1.16,<2.0",
  "asyncpg>=0.30,<1.0",
  "fastapi>=0.116,<1.0",
  "httpx>=0.28,<1.0",
  "pydantic>=2.11,<3.0",
  "pydantic-settings>=2.10,<3.0",
  "sqlalchemy[asyncio]>=2.0.41,<3.0",
  "uvicorn[standard]>=0.35,<1.0",
]
```

这些依赖是服务启动所必需的，会进入生产镜像。

开发依赖：

```toml
[dependency-groups]
dev = [
  "mypy>=1.16,<2.0",
  "pytest>=8.4,<10.0",
  "pytest-asyncio>=1.0,<2.0",
  "ruff>=0.12,<1.0",
]
```

这些依赖用于测试和质量检查，不需要进入生产镜像。

```toml
[tool.uv]
package = false
```

表示当前目录是一个直接运行的应用，不需要把自身构建成发布到 PyPI 的 Python 库。

### 3.3 `uv.lock`

[`agent-service/uv.lock`](../agent-service/uv.lock) 类似前端的 `package-lock.json`。

```text
pyproject.toml：声明允许的依赖版本范围
uv.lock：记录本次解析出的精确版本、传递依赖、下载地址和哈希
```

它由 uv 自动维护，不应手工编辑。依赖变化时使用 `uv add`、`uv remove` 或 `uv lock` 更新。

项目测试和镜像使用：

```bash
uv run --frozen ...
uv sync --frozen ...
```

`--frozen` 表示只允许使用现有锁文件；如果 `pyproject.toml` 和 `uv.lock` 不一致，命令失败，
不会在测试或构建过程中静默升级依赖。它与前端生产环境使用 `npm ci` 的目标相近。

### 3.4 `.venv/`

`.venv/` 是 uv 创建的项目虚拟环境，近似前端的 `node_modules/`，但还包含项目选择的
Python 解释器环境和依赖提供的命令。

创建或恢复环境：

```bash
cd agent-service
uv sync --frozen
```

推荐通过 uv 执行命令：

```bash
uv run python -m app.main
uv run pytest
uv run ruff check .
```

这样不需要手工执行 `source .venv/bin/activate`，也能保证使用项目环境。

## 4. 应用入口与配置

### 4.1 `app/__init__.py`

[`agent-service/app/__init__.py`](../agent-service/app/__init__.py) 表示 `app` 是可导入的
Python 包，因此可以写：

```python
from app.settings import Settings
from app.database import Database
```

它类似 Java 的 `package` 体系或 Node 的模块目录，但它不是服务启动入口。

Python 模块第一次被 `import` 时会执行模块顶层代码。应避免在模块顶层执行数据库写入、
Java API 调用或模型调用；类、函数和轻量应用组装可以放在顶层，真实资源操作应放进明确
生命周期。

### 4.2 `app/main.py`

[`agent-service/app/main.py`](../agent-service/app/main.py) 相当于：

```text
Spring Boot Application
+ 最小 Controller
+ Bean 生命周期组装
```

或者 Node 的：

```text
createApp()
+ Router
+ server.listen()
```

#### `HealthResponse`

```python
class HealthResponse(BaseModel):
    service: str
    status: str
```

这是 Pydantic 响应模型，类似 Java Record/DTO：

```java
public record HealthResponse(String service, String status) {}
```

也类似 TypeScript 接口加运行时 Schema。Pydantic 会在运行时校验并序列化返回内容，不只是
给编辑器提供提示。

#### `create_app`

```python
def create_app(settings: Settings | None = None) -> FastAPI:
```

它是应用工厂，负责：

- 取得或接收测试注入的配置；
- 定义应用启动/停止生命周期；
- 创建 FastAPI 对象；
- 注册 Trace 中间件；
- 注册 `GET /health`。

允许注入 `Settings` 的主要目的，是让测试使用 `environment="test"`，而不必修改真实环境变量。

#### lifespan

```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    # yield 之前：应用启动
    yield
    # yield 之后：应用停止
```

它类似 Spring Bean 的初始化/销毁生命周期，也类似 Node 启动时初始化资源并在 `SIGTERM`
时关闭资源。

当前启动阶段会：

```text
配置 JSON 日志
→ 创建 Database 管理对象
→ 保存到 application.state.database
→ 记录 service_started
```

关闭阶段会：

```text
释放 SQLAlchemy Engine/连接池
→ 记录 service_stopped
```

`application.state` 是 FastAPI/Starlette 的应用级共享状态，使用效果近似保存一个供全局访问的
Spring 单例 Bean 或 Express `app.locals`，但它本身不是完整的 IoC 容器。

#### 路由装饰器

```python
@application.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
```

类比 Java：

```java
@GetMapping("/health")
public HealthResponse health() { ... }
```

类比 Express：

```typescript
app.get("/health", async (req, res) => { ... });
```

装饰器把下面的函数注册为 HTTP 路由，`response_model` 让 FastAPI 使用 Pydantic 校验响应。

#### `app` 与 `main`

```python
app = create_app()
```

这是 Uvicorn 要加载的 FastAPI 对象。字符串 `app.main:app` 表示：

```text
app.main  → Python 模块 app/main.py
app       → 该模块中的变量 app
```

```python
if __name__ == "__main__":
    main()
```

表示只有将该模块作为程序入口运行时才启动服务器；如果其他模块只是 `import app.main`，
不会进入这个条件块。

### 4.3 `app/settings.py`

[`agent-service/app/settings.py`](../agent-service/app/settings.py) 相当于 Spring 的：

```text
application.yml
+ @ConfigurationProperties
+ Bean Validation
```

也类似 Node 的 `dotenv + config.ts + Zod`。

`Settings(BaseSettings)` 会从环境变量和可选 `.env` 文件读取配置：

```python
service_name: str = "agent-service"
environment: Literal["development", "test", "production"] = "development"
host: str = "0.0.0.0"
port: int = Field(default=8000, ge=1, le=65535)
log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
database_url: str = "postgresql://..."
business_service_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8080")
business_connect_timeout_seconds: float = 2.0
business_read_timeout_seconds: float = 3.0
business_write_timeout_seconds: float = 3.0
business_pool_timeout_seconds: float = 1.0
```

例如 `PORT=99999` 会因超过 65535 在启动时被 Pydantic 拒绝，而不是等 Uvicorn 绑定端口
时才返回难理解的错误。

`async_database_url` 负责将仓库现有配置：

```text
postgresql://user:password@host:5432/database
```

转换为 SQLAlchemy 异步驱动地址：

```text
postgresql+asyncpg://user:password@host:5432/database
```

`@lru_cache` 让 `get_settings()` 在一个进程中只构建一次 Settings，类似 Spring 单例配置 Bean
或 Node 在模块顶层导出的单例配置对象。

M1.2 已读取 `BUSINESS_SERVICE_URL` 和四项分离的 HTTP 超时。Base URL 只接受 HTTP/HTTPS，
超时必须大于 0 且不超过 60 秒。Compose 传入的模型相关变量仍未被 `Settings` 定义或使用，
模型配置要等后续 Agent 阶段，不能把环境变量存在误认为功能已实现。

## 5. 数据库基础

### 5.1 组件关系

```text
FastAPI / 未来的 Workflow
        ↓
SQLAlchemy AsyncSession
        ↓
SQLAlchemy AsyncEngine 与连接池
        ↓
asyncpg PostgreSQL 驱动
        ↓
PostgreSQL（Docker 中使用 pgvector/pgvector:pg16）
```

这些职责应区分：

- `asyncpg`：建立连接、发送 SQL、接收 PostgreSQL 结果；
- SQLAlchemy：管理 Engine、连接池、Session、ORM 和 SQL；
- Alembic：管理表结构版本，不负责日常查询；
- PostgreSQL 镜像：数据库进程，不是 Python 依赖；
- FastAPI：HTTP 框架，不应直接管理底层连接。

### 5.2 `app/database.py`

[`agent-service/app/database.py`](../agent-service/app/database.py) 类似 Java 的 DataSource、
EntityManagerFactory 和 JPA 基础配置，也类似 Node 的 PrismaClient/TypeORM DataSource。

#### `Base`

```python
class Base(DeclarativeBase):
```

它是所有 Agent 自有 SQLAlchemy Model 的共同元数据根。M2.1 已定义：

```python
class AgentRun(Base):
    __tablename__ = "agent_runs"
```

类比 JPA：

```java
@Entity
@Table(name = "agent_runs")
public class AgentRun { ... }
```

当前 `AgentSession`、`AgentMessage`、`AgentRun` 和 `AgentStep` 继承 `Base`。Approval 和 RAG
表仍未实现。

不得定义 `ProductionOrder(Base)` 去映射 Java 业务表。业务事实必须通过 Java API Tool 获取。

#### `Database`

`Database` 封装：

```text
AsyncEngine
→ async_sessionmaker
→ 单次 AsyncSession 上下文
→ 关闭时 dispose
```

创建 Engine：

```python
self.engine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
)
```

Engine 保存驱动、数据库地址和连接池配置。`pool_pre_ping=True` 会在复用连接前检查连接是否
有效，降低数据库重启后取得失效连接的概率。

创建 Engine 不等于立即查询数据库。真正进入 Session 并执行 SQL 时才需要实际连接，所以
当前 `/health` 可以在数据库不可用时仍表示 Python 进程存活。

Session Factory：

```python
self.session_factory = async_sessionmaker(
    bind=self.engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

它类似 Java 的 EntityManagerFactory，不代表某一次数据库操作。

当前 Repository 的使用方式：

```python
async with database.session() as session:
    result = await session.execute(...)
```

`async with` 会在正常返回或异常时都关闭 Session，类似 Java 的 try-with-resources 或 Node
的 `try/finally` 资源释放。

### 5.3 当前数据库边界

本地 Compose 当前让 Java 和 Python 使用同一 PostgreSQL 数据库和开发角色。现阶段通过：

- Python 不定义 Java 业务表 ORM；
- Alembic 使用独立版本表；
- 业务事实只允许通过 Java API 获取；

保持代码边界，但这不是生产级权限隔离。M2.1 已开始持久化 Run/Step，开发环境仍沿用共享
角色属于已知限制；进入生产前必须为 Agent 配置独立数据库、Schema 或最小权限角色。

### 5.4 M2.1 的 Model 与 Repository

[`agent-service/app/models/agent_runtime.py`](../agent-service/app/models/agent_runtime.py) 类似一组
JPA `@Entity` 或 TypeORM Entity，定义四层关系：

```text
AgentSession
├── AgentMessage（用户或助手消息）
└── AgentRun（一次用户请求的执行）
    └── AgentStep（一次可定位的执行步骤）
```

- `AgentSession` 保存 `session_id`、用户归属和时间，不保存 Java 订单事实；
- `AgentMessage` 用 `(session_id, sequence_number)` 唯一约束保证对话顺序；
- `AgentRun` 关联可选的请求消息，预留状态、最终结果、错误码、错误步骤和起止时间；
- `AgentStep` 用 `(run_id, sequence_number)` 唯一约束保证执行顺序，保存类型、状态、受控摘要和
  耗时。

Run 状态是 `PENDING/RUNNING/SUCCEEDED/FAILED/WAITING_APPROVAL/CANCELLED`，Step 类型是
`CONTEXT/TOOL/RULE/LLM`。代码使用 Python `StrEnum` 表达类型，并在数据库使用 VARCHAR 加
Check Constraint，而不是 PostgreSQL 私有 enum。这样 Python 仍有明确类型，后续增加状态时也
能通过普通 Alembic 约束迁移演进。

[`agent-service/app/repositories/agent_runtime.py`](../agent-service/app/repositories/agent_runtime.py)
类似 Spring Data Repository 或 TypeORM Repository，只封装 Run/Step 的增、删、查：

```python
async with database.session() as session:
    async with session.begin():
        repository = AgentRunRepository(session)
        await repository.create(run)
```

`create` 和 `delete` 会执行 `flush`，让重复序号、外键等错误在当前事务内尽早出现；它们不调用
`commit`。原因是后续生命周期服务需要把一次 Run 和若干 Step 放进同一个事务，由上层决定整体
提交或回滚。它类似 Java 中 Repository 参与外层 `@Transactional`，不应让每个 DAO 方法自己
提交。

数据库删除 Session 时级联 Message、Run、Step；删除 Run 时级联 Step。删除一条请求 Message
则把 Run 的 `request_message_id` 置空而不是删除 Run，用于保留已经发生的执行证据。当前只实现
数据结构和Repository。M2.2已实现合法Run状态流转，M2.3已提供可独立调用的Step记录服务；
Tool和Workflow自动接线仍未实现。

### 5.5 M2.2 的最小 Run 生命周期

[`agent-service/app/services/run_lifecycle.py`](../agent-service/app/services/run_lifecycle.py) 类似
Java中的`@Service`，在Repository之上集中控制以下状态机：

```text
create_run       → PENDING
mark_running     → PENDING → RUNNING
mark_succeeded   → RUNNING → SUCCEEDED
mark_failed      → RUNNING → FAILED
```

成功时保存`final_result`标准JSON快照并清空错误字段；失败时保存`error_code`和`error_step`并
清空结果。开始和结束时间使用带时区UTC时间，测试可以注入固定`now`函数，避免依赖真实时钟。

状态更新不是“先查询再普通update”，而是Repository执行近似SQL：

```sql
UPDATE agent_runs
SET status = :target_status, ...
WHERE run_id = :run_id
  AND status = :expected_status
RETURNING *;
```

这是一种compare-and-set。两个并发请求同时尝试把RUNNING标记为成功和失败时，数据库行锁和
旧状态条件保证只有一个更新成功。另一个更新影响0行，Service再查询当前状态并抛出
`InvalidRunTransitionError`，不会发生“最后提交的人覆盖第一个终态”。

内部异常分为：

- `RunNotFoundError`：Run不存在；
- `InvalidRunTransitionError`：当前状态不能进入目标状态；
- `RunLifecycleValidationError`：ID、错误信息、时间或结果快照不合法。

这些异常目前只服务Python内部调用，尚未绑定FastAPI HTTP响应或Tool错误码。Service和
Repository都不调用`commit`，调用方仍需用`session.begin()`控制一次业务操作的整体事务。
`WAITING_APPROVAL`和`CANCELLED`只存在于数据枚举，对应操作分别属于后续Approval或取消设计，
M2.2没有提前实现。

### 5.6 M2.3 的最小 Step 记录

[`agent-service/app/services/step_lifecycle.py`](../agent-service/app/services/step_lifecycle.py)类似
Java中的Step执行记录`@Service`。调用方开始一个步骤时传入稳定`step_id`、父`run_id`、序号、
类型、名称和可选输入摘要，Service创建已经处于`RUNNING`的`AgentStep`：

```text
start_step
→ 锁定并校验父Run必须是RUNNING
→ INSERT Step(status=RUNNING, started_at=UTC时间)
├── mark_succeeded → SUCCEEDED + output_summary + duration_ms
└── mark_failed    → FAILED + error_code + output_summary + duration_ms
```

父Run查询使用`SELECT ... FOR UPDATE`。它类似JPA的悲观写锁：如果Run正被另一个事务标记为终态，
开始Step的一方会等待并读取最终状态；如果Step先锁住Run并完成插入，Run终态更新会等待该事务
提交。这样避免在已经结束的Run下又并发开始新Step。该锁只保护“开始关联”的短事务，不应跨
Java HTTP或模型调用长期持有。

成功和失败都使用`UPDATE ... WHERE status = RUNNING RETURNING ...`抢占唯一终态。完成前先从
`started_at`与带时区`finished_at`计算毫秒耗时；时间倒退、缺少开始时间、重复完成和并发终态
都会被拒绝。`get_fresh`会刷新SQLAlchemy会话身份缓存，确保并发失败方看见数据库最新状态，
而不是继续使用先前加载的`RUNNING`对象。

输入输出不是原始请求/响应，而是由Workflow以后主动选择的摘要字符串。当前最小策略会：

- 合并换行和连续空白；
- 将常见`Authorization: Bearer`、`api_key`、`access_token`、`password`和`secret`值替换为
  `[REDACTED]`；
- 超过1000字符时截断并追加`...`；
- 空白摘要按`None`保存。

这只是纵深防御，不能识别所有个人信息、业务敏感字段或任意格式凭据。未来Workflow仍应先构造
字段白名单摘要，不能把完整Prompt、Java响应、Token或用户原文直接传给Step服务。

Service和Repository仍只`flush`而不`commit`，事务由调用方控制。当前序号由调用方提供，数据库
唯一约束只负责拒绝同一Run的重复序号；自动分配、重试次数、Trace ID和Tool自动记录不属于M2.3。

### 5.7 M2.4 的 Workflow 状态与诊断 Schema

[`agent-service/app/schemas/workflow.py`](../agent-service/app/schemas/workflow.py)只定义后续固定
Workflow交换的数据形状，不执行Tool、规则或模型。它包含两类不同的Python类型：

```text
OrderDiagnosisState（TypedDict）
→ 描述各节点共享字典中应该有哪些键和值类型
→ 主要由mypy和后续LangGraph节点做静态检查
→ Python运行时不会自动校验普通dict

DiagnosisResult/RootCause/Evidence/Suggestion/StepError（Pydantic）
→ 运行时真正校验诊断输出和错误结构
→ 非法字段、类型、长度或范围会产生ValidationError
```

如果类比Java，`OrderDiagnosisState`接近一个只用于编译期约束的接口化Map，而Pydantic模型更接近
带Bean Validation的不可变DTO。类比TypeScript时，TypedDict接近编译后会消失的`interface`，
Pydantic则更接近额外使用Zod执行运行时解析。

状态包含：

```text
run_id / order_id
order / tasks
progress / quality_issues / reviews / delivery
diagnosis
errors
```

这些业务对象直接复用M1.5已经验证过的Tool输出Schema，因此Workflow不需要重新发明第二套订单、
任务或质检DTO。`dict[task_id, ...]`用于保留“数据属于哪个任务”的关联，避免多个任务的数据在状态
合并后失去归属。

所有诊断Pydantic模型继承`WorkflowSchema`，统一启用：

- `extra="forbid"`：未知字段直接失败，避免节点悄悄传递未约定数据；
- `frozen=True`：模型字段不能被随意重新赋值，减少下游节点修改历史结果；
- `strict=True`：不把字符串数字等输入静默转换为目标类型；
- `str_strip_whitespace=True`：清理字符串首尾空白。

`Evidence`不是普通说明字符串，而是：

```text
source_type = TOOL
tool_name = 七个已注册只读Tool之一
field_path = 响应中的可定位字段路径
value = 单个标量事实
description = 人类可读解释
```

该结构阻止把“模型认为”“大概如此”或整段Java响应当成业务证据。模型以后可以负责归纳文案，
但订单状态、问题状态和数量等事实必须指向Tool字段。当前只允许标量`value`也是为了强迫证据落到
具体字段，而不是塞入难以审查的嵌套对象。

`DiagnosisResult`要求证据、建议和0～1置信度。`blocking_stage=NONE`时根因必须为空；其他稳定代码
必须至少包含一个根因。当前没有提前定义完整阻塞阶段枚举，因为该枚举和具体判断规则属于M2.6；
M2.4只先要求大写稳定代码，避免跨任务提前实现规则。

`StepError`复用`ToolErrorCode`并只保存步骤名、安全文案、`retryable`和可选Trace ID，不允许附加
原始响应或异常堆栈。这样M2.5节点失败后可以把错误放入状态，同时降低Token、业务载荷或内部异常
细节继续传播的风险。

### 5.8 M2.5 的固定 LangGraph Workflow

[`agent-service/app/workflows/order_diagnosis.py`](../agent-service/app/workflows/order_diagnosis.py)
把M2.4的`OrderDiagnosisState`真正交给LangGraph `StateGraph`执行。可以类比为：

| Python实现 | Java类比 | Node.js类比 |
| --- | --- | --- |
| `StateGraph` | 代码定义的流程状态机/责任链 | 显式编排的异步pipeline |
| node异步方法 | 一个只负责单阶段的Service方法 | 一个async middleware/handler |
| node返回增量dict | 返回局部状态变更对象 | 返回partial state |
| conditional edge | 根据结果选择下一状态 | 根据结果选择下一个handler或结束 |

当前固定顺序是：

```text
load_context
→ load_order
→ load_tasks
→ load_progress
→ load_quality
→ load_review
→ load_delivery
```

`load_context`先用`OrderIdInput`做运行时校验，并初始化M2.4声明的全部状态字段。后续节点通过
`ToolRegistry`查找已有只读Tool，并复用同一个`ToolContext`，所以权限、Pydantic输入输出校验、
有限重试和Run内重复调用检测都不会被Workflow绕过。

节点只返回它负责的增量，例如`load_order`返回`{"order": order}`。LangGraph把该增量与已有
状态合并，不要求每个节点复制整份状态。任务列表会按`task_id`稳定排序，进度、质检、复核结果
使用`dict[task_id, result]`合并；同一个多任务节点只有全部Tool调用成功后才提交该节点的字典更新，
避免返回难以区分的半份聚合结果。

Tool失败不是抛出一段自由文本，而是执行：

```text
ToolResult(success=false, error=ToolError)
→ 转成StepError(code/message/retryable/trace_id)
→ 追加到state.errors
→ conditional edge选择END
→ 后续Tool不再调用
```

[`agent-service/app/workflows/recording.py`](../agent-service/app/workflows/recording.py)定义
`WorkflowStepRecorder` Protocol，类似Java接口或TypeScript interface；测试可使用内存实现，运行时
使用`DatabaseWorkflowStepRecorder`。数据库实现会在动作开始前单独提交`RUNNING` Step，HTTP调用
结束后再用新事务标记成功或失败，因此不会把Java网络等待包在父Run行锁事务里。

每个Workflow实例绑定一个Run级`ToolContext`并只允许执行一次。Step序号按真实执行顺序递增，
Step ID由`run_id + sequence + step_name`的SHA-256摘要生成，不把完整Run ID复制到技术主键中。
当前编排到`load_delivery`即结束，尚未包含M2.6的`diagnose_by_rules`或M2.7的`format_result`。

## 6. Trace ID 与结构化日志

### 6.1 `ContextVar`

[`agent-service/app/observability.py`](../agent-service/app/observability.py) 使用：

```python
_trace_id: ContextVar[str]
```

保存当前异步请求的 Trace ID。不能使用普通全局变量，因为多个异步请求并发执行时会互相
覆盖。

它类似：

- Java 的 MDC/ThreadLocal，但适配 Python 异步上下文；
- Node 的 AsyncLocalStorage。

### 6.2 Trace ID 安全规则

请求头名称：

```text
X-Trace-Id
```

只接受 1～128 位以下字符：

```text
A-Z a-z 0-9 . _ : -
```

缺失或非法时生成：

```text
trace-<UUID>
```

这样可以拒绝换行、空格和超长值，避免日志注入或日志污染。

### 6.3 `JsonFormatter`

普通文本日志难以稳定按字段查询，`JsonFormatter` 将日志输出为：

```json
{
  "timestamp": "2026-08-01T00:00:00+00:00",
  "level": "INFO",
  "logger": "agent-service.request",
  "message": "request_completed",
  "trace_id": "trace-001",
  "method": "GET",
  "path": "/health",
  "status_code": 200,
  "duration_ms": 0.667
}
```

日志只复制白名单字段，不自动输出数据库 URL、Token、请求正文或任意 Python 对象。

### 6.4 `TraceIdMiddleware`

它类似 Java `OncePerRequestFilter` 或 Express Middleware：

```text
读取 X-Trace-Id
→ 校验或生成 Trace ID
→ 写入 ContextVar
→ 记录开始时间
→ call_next(request) 调用后续路由
→ 将 Trace ID 写回响应 Header
→ 记录状态码和耗时
→ finally 重置 ContextVar
```

`call_next(request)` 类似 Java 的 `filterChain.doFilter(...)` 或 Express 的 `next()`。

finally 中必须重置 ContextVar，否则工作进程复用异步上下文时可能污染后续请求。

## 7. Java HTTP Client

M1.2 新增的调用链是：

```text
未来的 Tool
→ BusinessHttpClient
→ httpx.AsyncClient 连接池
→ Java /api/**
→ 按 HTTP 状态校验成功/失败信封
→ 成功时校验端点 data Schema 并返回 BusinessResponse[DataT]
→ 失败时映射为 ToolException
```

它类似 Java 中封装好的 WebClient/Feign Client，也类似 Node 服务中带统一拦截和 Schema
校验的 Axios Client。Client 只负责可靠的 HTTP 边界，不负责决定调用哪个业务接口。

### 7.1 `BusinessIdentity` 与响应 Schema

[`agent-service/app/schemas/business.py`](../agent-service/app/schemas/business.py) 定义四类契约：

- `BusinessIdentity`：单次调用的用户 ID、角色和可选 Token；
- `BusinessSuccessEnvelope`：Java 成功响应的六个固定字段；
- `BusinessErrorEnvelope`：Java 失败响应的六个固定字段和错误码集合；
- `BusinessResponse[DataT]`：已校验的响应元数据和具体业务 data。

Token 使用 `SecretStr`，对象被打印或调试时不会直接显示原值。用户 ID 和角色禁止空值、
换行和超长内容，避免非法 Header 或日志污染。

成功信封使用严格 Pydantic Schema：

```text
success = true
code = SUCCESS
message = string
data = 必须存在
trace_id = 安全格式
retryable = false
```

`data: object` 只表示第一层必须存在；随后 Client 使用调用方传入的具体 Pydantic Model 再
校验一次。这样统一信封和订单、任务、质检等业务 DTO 不会混成一个巨型模型。

### 7.2 `BusinessHttpClient` 生命周期与连接池

[`agent-service/app/clients/business.py`](../agent-service/app/clients/business.py) 中的
`BusinessHttpClient` 只创建一个 `httpx.AsyncClient`。FastAPI lifespan 启动时创建它并放入：

```python
application.state.business_client
```

应用停止时执行：

```python
await business_client.aclose()
```

不能每次 Tool 调用都新建 Client，因为那会反复建立 TCP/TLS 连接，失去连接池复用，并增加
端口和资源泄漏风险。这个生命周期近似 Spring 单例 HTTP Client Bean，或 Node 应用级 Axios
实例。

Client 使用：

```python
trust_env=False
```

因此内部 Java 请求不会继承宿主机 `HTTP_PROXY`、`HTTPS_PROXY` 或 SOCKS 代理。M1.2 测试
实际发现本机代理会让 Client 初始化失败，所以内部服务地址只由 `BUSINESS_SERVICE_URL`
决定。

### 7.3 身份、Trace 和写请求幂等键

Client 根据 `BusinessIdentity` 生成：

```text
X-User-Id
X-User-Role
Authorization: Bearer <token>  # Token 存在时
```

Trace 优先使用方法参数；未显式传入时读取当前 `ContextVar`，再发送 `X-Trace-Id`。因此未来
请求路径可以保持：

```text
浏览器 Trace → Python 中间件 → ContextVar → Java Client → Java 日志与响应
```

POST 还必须传入安全格式的 `Idempotency-Key`。Client 只保证 Header 存在和格式合法，Java
仍负责判断相同用户、相同键和相同请求是否可以重放。当前没有 Approval 或写 Tool，不能因为
Client 支持 POST 就声称 Agent 已经可以安全回写。

### 7.4 GET、POST 与响应校验顺序

GET 支持查询参数，POST 支持 JSON Body。两者都只接受 `/api/` 开头的相对业务路径，避免
调用方传入绝对 URL 绕过配置的 Java 服务地址。

一次正常请求的顺序为：

```text
校验相对路径
→ 构造身份与 Trace Header
→ httpx 使用连接池和分项超时发送请求
→ 根据 HTTP 状态进入成功或失败分支
→ 成功：校验成功信封 → 校验具体 data Model → 校验 Trace → 返回 BusinessResponse
→ 失败：校验错误信封 → 核对 HTTP/Java code/Trace → 返回结构化 ToolException
```

HTTP 200 不等于业务响应可信。例如 Java 故障模拟返回缺少 `data` 的 JSON 时，Client 会抛出
`RESPONSE_VALIDATION_ERROR` 对应的 `ToolException`，不会把它当成空订单继续交给 Agent
归纳。这是防止模型基于不完整事实生成结论的第一道边界。

### 7.5 `ToolException` 标准错误模型

[`agent-service/app/errors.py`](../agent-service/app/errors.py) 中的 `ToolErrorCode` 是稳定机器
错误码，`ToolException` 保存：

```text
code         # Workflow 应据此分支
message      # 给人阅读，不用于字符串匹配
retryable    # 故障技术上是否可能恢复
trace_id     # 关联 Python、Java 日志
status_code  # 保留 HTTP 语义，例如区分 401 和 403
```

Java 错误映射如下：

| Java HTTP/code | Python `ToolErrorCode` | 当前 `retryable` |
| --- | --- | --- |
| 400 / `PARAM_VALIDATION_ERROR` | `PARAM_VALIDATION_ERROR` | `false` |
| 401、403 / `PERMISSION_DENIED` | `PERMISSION_DENIED` | `false` |
| 404 / `RESOURCE_NOT_FOUND` | `RESOURCE_NOT_FOUND` | `false` |
| 409 / `BUSINESS_CONFLICT` | `BUSINESS_CONFLICT` | `false` |
| 500 / `INTERNAL_SERVER_ERROR` | `UPSTREAM_UNAVAILABLE` | `false` |
| httpx 四类 timeout | `TOOL_TIMEOUT` | `true` |
| 其他 httpx 网络错误 | `UPSTREAM_UNAVAILABLE` | `true` |
| 非法 JSON/信封/data/Trace | `RESPONSE_VALIDATION_ERROR` | `false` |

错误响应也必须通过 Pydantic 信封校验，并核对 HTTP 状态、Java `code`、响应 Header/Body Trace。
例如“HTTP 404 + `BUSINESS_CONFLICT`”不是可信业务错误，而是契约漂移，会统一映射为
`RESPONSE_VALIDATION_ERROR`。网络异常只暴露固定安全文案，不把内部 URL 或连接详情交给
Workflow/模型；原异常仍保存在 Python 的异常因果链中，供日志排障。

### 7.6 超时、可重试性和读写边界

四项超时分别控制 connect、read、write 和等待连接池的 pool timeout。它们必须大于 0 且
不超过 60 秒。分开配置可以区分“连接不上 Java”和“Java 已接收但业务处理过慢”，为后续
重试决策提供依据。

M1.3 负责“错误分类”，M1.6 才在具体只读 Tool 上执行重试。timeout/网络错误上的
`retryable=true` 只说明故障在技术上可能恢复，不代表每个调用都允许重放：

- M1.6 只为七个明确的只读 Tool 增加有限次数、退避和总预算；
- POST 超时或网络中断时，Java 可能已经完成写入，不能仅凭 `retryable=true` 自动重放；
- 500 当前继承 Java 的保守 `retryable=false`，尤其不能对写请求猜测执行结果。

`UNKNOWN_TOOL_ERROR` 由 M1.4 `BaseTool.execute` 在具体实现抛出未知异常时生成；
`DUPLICATE_CALL` 由 M1.7 在同一 `ToolContext` 中检测到同名同参调用时生成。Client 不会伪造
这两类错误，因为它们分别属于 Tool 执行包装和 Run 调用控制，而不是 Java HTTP 错误。

### 7.7 Tool 基础协议如何协作

M1.4 新增的 [`agent-service/app/tools/`](../agent-service/app/tools/) 可以类比为：

| Python | Java 类比 | Node.js/TypeScript 类比 | 职责 |
| --- | --- | --- | --- |
| `BaseTool` | 抽象基类 + Template Method | 抽象类中的公共执行包装器 | 固定调用门禁和异常收敛顺序 |
| `_execute` | 子类受保护的抽象方法 | 子类实现的 `protected executeCore` | 只写具体业务调用 |
| `ToolContext` | 不可变请求上下文 DTO | readonly context object | 携带身份、权限、Trace 和 Run |
| `ToolResult` | 泛型结果对象 | discriminated result object | 用 `success/data/error` 表达结果 |
| `ToolRegistry` | Spring Bean 注册表 | `Map<string, Tool>` 容器 | 按稳定名称注册和查找 Tool |

公共调用顺序为：

```text
Workflow 或调试入口准备 raw_input + ToolContext
→ BaseTool.execute 检查 required_permissions
→ input_model 校验输入
→ 生成调用指纹并在 Run 账本中原子占位
→ asyncio.timeout 限制本次 Tool 的整体耗时
→ 具体 Tool._execute 调用 Java Client
→ output_model 再校验输出
→ 返回 ToolResult(success=true, data=...)
```

失败不会把不同异常类型直接泄露给上层：

```text
输入不合法                 → PARAM_VALIDATION_ERROR
缺少 Tool 所需权限         → PERMISSION_DENIED
ToolException              → 保留标准 code/retryable/Trace/HTTP 状态
整体执行超时               → TOOL_TIMEOUT
输出不符合 output_model    → RESPONSE_VALIDATION_ERROR
其他未知异常               → UNKNOWN_TOOL_ERROR
```

未知异常返回固定安全文案，避免实现细节进入 Workflow 或模型；原始异常通过
`logging.exception` 写入带 `tool_name`、`run_id` 和 `error_code` 的结构化日志，供开发排障。
`ToolResult` 还通过 Pydantic 校验保证成功时只有 `data`、失败时只有 `error`，避免上层遇到
“`success=true` 但同时有错误”这类矛盾状态。

`risk_level`、`required_permissions`、`timeout` 和 `max_retries` 都是 Tool 元数据。M1.4 当时
只有权限和整体超时生效；M1.6 增加了可选 `RetryPolicy`，并要求策略次数与 Tool 元数据一致。
仅设置 `max_retries` 不会自动重放，具体 Tool 必须显式绑定策略。这一门禁让未来写 Tool 默认
保持不重试。`ToolContext.run_id` 当前用于调用关联、日志字段和 M1.7 进程内账本归属。M2.1
虽已建立 Run/Step 数据表，但这份账本仍由上下文私有持有，Tool 调试链尚未写表，也不能跨实例
共享。

`ToolRegistry.register` 遇到相同名称会抛 `DuplicateToolRegistrationError`，这是启动/装配错误；
它不是一次 Run 中相同参数被重复调用，因此不能使用 `DUPLICATE_CALL`。后者由 M1.7 的调用
账本在运行时返回，两种“重复”的生命周期和处理对象不同。

### 7.8 M1.5 七个只读 Tool 如何协作

M1.5 的业务 Schema 位于 `app/schemas/tools.py`，具体 Tool 位于 `app/tools/readonly.py`。可以类比：

| Python 实现 | Java 类比 | Node.js/TypeScript 类比 | 职责 |
| --- | --- | --- | --- |
| `OrderIdInput` / `TaskIdInput` | Controller PathVariable 的校验 DTO | Zod 参数 Schema | 限制路径 ID 格式并拒绝额外字段 |
| `OrderDetail` 等输出模型 | Java API DTO + Jackson/Validation | API response type + Zod | 严格描述 Java `data` 字段 |
| 七个 `_BusinessReadTool` 子类 | 七个 Application Service adapter | 七个 typed API adapter | 把稳定 Tool 名映射到精确 Java GET 路径 |
| `create_read_tool_registry` | Spring 配置中注册七个 Bean | 依赖注入容器注册 provider | 使用共享 Client 装配完整集合 |

七个稳定名称与路径是：

```text
get_order_detail(order_id)        → GET /api/orders/{orderId}
get_related_tasks(order_id)       → GET /api/orders/{orderId}/tasks
get_task_detail(task_id)          → GET /api/tasks/{taskId}
get_production_progress(task_id)  → GET /api/tasks/{taskId}/progress
get_quality_issues(task_id)       → GET /api/tasks/{taskId}/quality-issues
get_review_result(task_id)        → GET /api/tasks/{taskId}/review
get_delivery_status(order_id)     → GET /api/orders/{orderId}/delivery-status
```

以 `get_quality_issues` 为例，完整顺序是：

```text
调用方传 {"task_id": "TASK-003"} 和 ToolContext
→ Registry 按 get_quality_issues 取出 Tool
→ BaseTool.execute 检查 QUALITY_ISSUE_READ
→ TaskIdInput 拒绝空值、非法格式和额外参数
→ _execute 调 BusinessHttpClient.get
→ Client 发送身份、角色和 X-Trace-Id
→ Java 返回 HTTP + 六字段响应信封 + data
→ Client 校验信封、Trace 和 QualityIssueList
→ Tool 核对顶层 taskId 及每个 issue.taskId 都是 TASK-003
→ BaseTool 校验最终输出
→ 返回 ToolResult(success=True, data=QualityIssueList(...))
```

这里有三层不同的“校验”，不能混为一层：

1. Client 校验传输协议是否可信，例如 HTTP/code/Trace 是否一致；
2. Pydantic 校验数据形状、必填字段、枚举状态和 ID 格式；
3. Tool 校验数据归属，例如请求 `TASK-003` 不能接收结构正确的 `TASK-004` 数据。

集合结果的 `[]` 保持成功语义。例如 `issues=[]` 表示任务存在且没有质检问题；Java 404 才表示
任务不存在。二者对后续诊断结论完全不同。

应用启动时，FastAPI lifespan 先创建共享 `BusinessHttpClient`，随后用它创建七个 Tool 并保存到
`app.state.tool_registry`；关闭时只需关闭共享 Client。M1.8 在 development 环境注册内部 HTTP
调试接口，外部开发者可以通过 REST/Swagger 选择 Tool；test和production环境不会注册该路由。

七个 Tool 都是 LOW 风险只读操作，并声明 `max_retries=1`。M1.5 完成时该字段只是元数据；
M1.6 已为这些 Tool 显式绑定 `RetryPolicy`。这里的 1 表示“首次调用失败后最多再调用一次”，
因此总调用次数最多是 2，而不是总共只调用 1 次。

### 7.9 M1.6 RetryPolicy 如何协作

`app/tools/retry.py` 的 `RetryPolicy` 是不可变策略对象，负责回答两个问题：当前异常能不能重试，
第 N 次重试前应该等多久。`BaseTool` 负责实际循环和结果收敛，`BusinessHttpClient` 仍只负责
HTTP 与错误映射。三者的分工是：

```text
BusinessHttpClient
把 HTTP/network/timeout 转成 ToolException(code, retryable, trace_id)
        ↓
RetryPolicy.should_retry
同时检查错误码白名单、retryable 标志和剩余次数
        ↓
BaseTool._execute_with_retry
记录日志 → 等待退避 → 再调用具体 _execute
        ↓
BaseTool.execute
最终转成 ToolResult.data 或 ToolResult.error
```

当前七个只读 Tool 的参数是：

| 参数 | 当前值 | 含义 |
| --- | --- | --- |
| `max_retries` | 1 | 首次调用之外最多再调用 1 次 |
| `initial_backoff_seconds` | 0.1 | 第一次重试前等待 100 ms |
| `backoff_multiplier` | 2.0 | 后续等待按 2 倍增长 |
| `max_backoff_seconds` | 1.0 | 单次等待最多 1 秒 |
| Tool `timeout` | 5.0 | 首次调用、退避、重试和输出校验共享的总预算 |

通用退避公式是：

```text
delay(N) = min(initial_backoff × multiplier^(N-1), max_backoff)
```

例如测试策略设置 10 ms 初始值、2 倍增长、50 ms 上限时，前四次退避是 10、20、40、50 ms。
当前生产策略只允许一次重试，所以实际只使用第一项 100 ms；保留通用公式是为了策略本身可测试、
以后调整次数时不需要重写执行循环。

允许重试必须同时满足：

```text
Tool 显式绑定 RetryPolicy
AND 还有剩余重试次数
AND exception.retryable = true
AND code 属于 TOOL_TIMEOUT 或 UPSTREAM_UNAVAILABLE
```

因此参数、权限、404、409、响应 Schema、资源 ID 串线都不会重试。Java 当前通用 500 虽映射为
`UPSTREAM_UNAVAILABLE`，但信封明确给出 `retryable=false`，仍不会重试；网络连接失败和 httpx
timeout 同时满足白名单与 `retryable=true`，才会重试一次。

`asyncio.timeout(self.timeout)` 包在整个重试循环外，而不是每次请求外。这意味着如果首次请求和
退避已经耗尽 5 秒，第二次请求不会获得新的 5 秒预算。总预算到期后，公共协议返回可重试的
`TOOL_TIMEOUT`，防止指数退避把一次 Tool 调用无限拖长。

每次安排重试会输出 `tool_retry_scheduled` 结构化日志，记录 `tool_name`、`run_id`、`trace_id`、
`error_code`、`retry_number` 和 `retry_delay_ms`。它能回答“哪个 Tool 因为什么重试了第几次”。
M2.1 已有 Run/Step 持久化结构，但当前重试事件尚未写入 Step；也没有随机抖动、熔断或跨实例
重试预算。

### 7.10 M1.7 如何识别重复 Tool 调用

M1.7 解决的不是 HTTP retry，而是未来模型或 Workflow 在同一次 Run 中反复请求相同事实的问题。
两者的区别是：

| 行为 | 发起者 | 是否算重复逻辑调用 |
| --- | --- | --- |
| M1.6 retry | BaseTool 为一次调用恢复暂态故障 | 否 |
| 相同 Tool 和参数再次执行 `execute` | Workflow、模型或调试调用方 | 是 |
| 相同 Tool 但参数不同 | Workflow、模型或调试调用方 | 否 |
| 显式 `force_refresh=True` | 明确要求重新读取的调用方 | 允许执行 |

`app/tools/deduplication.py` 的 `build_tool_call_fingerprint` 先取得经过输入 Schema 校验的 Model，
再执行：

```text
Tool 名 + 已校验参数
→ Pydantic JSON 模式转换
→ JSON key 排序和紧凑序列化
→ UTF-8
→ SHA-256
→ 64 个小写十六进制字符
```

使用校验后的参数而不是原始字典有两个原因：第一，字典字段顺序不应改变调用含义；第二，Schema
已经完成默认值、字段类型和文本规范化。Tool 名也进入指纹，因此相同 `ORDER-003` 参数调用
`get_order_detail` 和 `get_related_tasks` 不会互相冲突。账本只保存 Hash，不保存原始参数。

`ToolContext` 在创建后通过 `model_post_init` 建立私有 `RunToolCallLedger`。它类似 Java 中由一次
Run 上下文持有的 `Set<String>`，不进入 Pydantic 序列化或 API Schema。同一次 Run 的所有 Tool
调用必须复用同一个 `ToolContext`；账本随着上下文释放，不需要当前尚不存在的 Run 数据库表。

公共执行顺序现在是：

```text
权限校验
→ 输入 Schema 校验
→ 生成 Tool 名 + 参数指纹
→ RunToolCallLedger.try_reserve
→ 重复且未 force_refresh：DUPLICATE_CALL，不发 HTTP
→ 首次或强制刷新：整体 timeout → _execute_with_retry → 输出校验
```

权限和参数错误不会占用指纹，因为它们尚未形成合法 Tool 调用。账本占位发生在 HTTP 之前，
因此并发的两个相同调用只有一个能进入具体 Tool。短临界区使用 `threading.Lock`，锁内只有 Set
查询和插入，没有网络、sleep 或其他 I/O，不会把慢请求放在锁内。

一次逻辑调用即使最终 timeout、返回 404 或输出校验失败，指纹仍会保留。这样可以阻止模型在
没有新信息时循环调用；确实需要重新读取时，调用方显式传入：

```python
await tool.execute(tool_input, context, force_refresh=True)
```

`force_refresh` 是执行控制参数，不属于具体 Tool 的业务输入 Schema，也不参与指纹。它只允许
本次调用继续执行，不清除已有记录，所以之后普通同参调用仍会被拦截。

当前方案不是结果缓存：重复调用返回 `DUPLICATE_CALL`，不会返回第一次的 data。它也不是分布式
幂等机制：独立创建的两个 `ToolContext` 即使 `run_id` 字符串相同，也各自拥有账本；进程重启、
多 worker 或多实例之间不共享。M2 Workflow 必须建立“一次 Run 复用一个上下文”的生命周期，
M7 再决定是否把调用记录持久化。

### 7.11 M1.8 如何在没有 Agent 时调试 Tool

`app/api/tool_debug.py` 将已经验证过的 Tool 层暴露为开发专用 FastAPI 路由：

```text
POST /internal/tools/{tool_name}/invoke
```

请求不是直接拼 Java URL，而是提供五类信息：

```json
{
  "arguments": {"order_id": "ORDER-003"},
  "identity": {"user_id": "debug-user-001", "role": "REVIEWER"},
  "permissions": ["ORDER_READ"],
  "run_id": "debug-run-order-003",
  "force_refresh": false
}
```

`arguments` 仍交给目标 Tool 自己的 `input_model` 校验；`identity` 会由 Java Client 转成用户和
角色 Header；`permissions` 只负责 Python Tool 快速门禁，不能替代 Java 最终校验；`run_id`
用于复用 M1.7 账本；`force_refresh` 显式表达是否重新读取。Trace ID 不放在 Body，而是继续由
中间件从 `X-Trace-Id` Header 取得，保证 HTTP 响应、Python 日志和 Java 请求能够关联。

路由的执行顺序是：

```text
FastAPI校验ToolDebugInvokeRequest
→ ToolRegistry按路径tool_name查找Tool
→ ToolDebugRunContextStore创建或复用ToolContext
→ BaseTool.execute(arguments, context, force_refresh)
→ 权限/输入/去重/重试/Java/输出完整链路
→ 标准ToolResult
```

Tool 本身返回的参数、权限、Java、timeout 或响应错误使用 HTTP 200，因为 HTTP 调试请求已经
正常到达并完成，失败信息在 `ToolResult.error` 中供 Workflow 式分支判断。未知 Tool 是路径资源
不存在，返回 HTTP 404；HTTP Body 不符合调试 Schema 时由 FastAPI 返回422；同一 `run_id`
尝试更换身份或权限会返回409，避免一个调试 Run 混用不同安全上下文。

为了让两次 HTTP 请求仍能验证 M1.7，`ToolDebugRunContextStore` 在应用内复用最近128个 Run 的
`ToolContext`。第二个请求会换成当前 Trace ID，但浅复制保留原上下文的私有调用账本。存储使用
有界 LRU：超过128个时淘汰最久未使用的 Run，避免开发进程无限增长。它只是调试辅助状态，服务
重启、多 worker、多实例或被淘汰后不会恢复。M2.1 已有正式 Run/Step 表，但调试 API 尚未接入，
因此这个内存 Store 仍不能替代持久化生命周期。

路由在 `create_app` 构建阶段按 `Settings.environment == "development"` 条件注册。因此非开发
环境不仅调用得到404，生成的 OpenAPI 中也没有该路径。这比在处理函数内部返回403更彻底，
避免生产 Swagger 暴露内部调试入口。

## 8. 启动、请求和关闭顺序

### 8.1 标准本地启动

```bash
cd agent-service
uv sync --frozen
uv run python -m app.main
```

根目录使用 Docker Compose：

```bash
make dev-agent
```

可选的热重载调试命令：

```bash
cd agent-service
uv run uvicorn app.main:app --reload
```

`--reload` 适合本地调试，会监控代码变化并重启进程；它不是项目标准生产启动方式。

### 8.2 应用启动顺序

```text
uv 读取 .python-version
→ 选择 Python 3.12 和 .venv
→ Python 以模块方式加载 app.main
→ 创建模块级 FastAPI app
→ main() 读取 Settings
→ Uvicorn 加载 app.main:app 并监听端口
→ FastAPI 进入 lifespan
→ 配置 JSON 日志
→ 创建惰性 Database/Engine
→ 创建共享 BusinessHttpClient/HTTP 连接池
→ development 环境准备调试 Run 上下文存储和内部 Tool 路由
→ 服务开始接收请求
```

`python -m app.main` 中的 `-m` 表示按 Python 模块运行，而不是把文件当作无包上下文的脚本。
这样 `from app.settings import Settings` 等绝对包导入能保持一致。

### 8.3 一次 `/health` 请求

请求：

```bash
curl -H "X-Trace-Id: trace-001" http://127.0.0.1:8000/health
```

完整顺序：

```text
1. Uvicorn 接收 HTTP 请求
2. Uvicorn 将请求转换为 ASGI 调用
3. FastAPI 进入 TraceIdMiddleware
4. 中间件读取并校验 X-Trace-Id
5. Trace ID 写入 ContextVar
6. 中间件记录开始时间
7. call_next 进入 FastAPI 路由系统
8. 匹配 GET /health
9. 执行 health()
10. 创建 HealthResponse
11. Pydantic 校验并序列化响应
12. 返回 TraceIdMiddleware
13. 中间件写入响应 X-Trace-Id
14. 计算请求耗时并输出 JSON 日志
15. 重置 ContextVar
16. Uvicorn 返回 HTTP 响应
```

正常响应：

```json
{
  "service": "agent-service",
  "status": "UP"
}
```

`/health` 是 liveness，只证明 Python 应用进程可以响应，不访问 PostgreSQL。当前没有数据库
readiness 接口，不能声称数据库健康已由该接口验证。

### 8.4 应用关闭顺序

```text
进程收到停止信号
→ Uvicorn 停止接收新请求
→ FastAPI lifespan 进入 yield 之后
→ BusinessHttpClient.aclose() 释放 HTTP 连接池
→ Database.dispose() 释放 Engine/连接池
→ 输出 service_stopped
→ 进程退出
```

## 9. Alembic 数据库迁移

### 9.1 文件职责

```text
agent-service/
├── alembic.ini
└── migrations/
    ├── env.py
    ├── script.py.mako
    └── versions/
        └── 0001_agent_runtime_base.py
```

- `alembic.ini`：指定迁移目录和 Python import 路径；
- `env.py`：加载 Settings、异步 Engine 和 `Base.metadata`；
- `script.py.mako`：创建新 revision 时生成 Python 文件的模板；
- `versions/`：保存实际迁移版本。

### 9.2 `target_metadata`

```python
target_metadata = AgentSession.metadata
```

导入 `AgentSession` 会加载 `app.models` 包中的四个映射类；它们共享同一份 `Base.metadata`。
因此 Alembic `check` 或 autogenerate 能比较当前 Agent 模型与数据库结构。这里不能只导入空的
`Base` 而忘记模型，否则 metadata 中没有表，迁移差异会失真。

### 9.3 独立版本表

```python
version_table = "agent_alembic_version"
```

Java Flyway 使用 `flyway_schema_history`，Python Alembic 使用 `agent_alembic_version`，两套
迁移记录不会混用。

当前首个 revision 是 `0001_agent_runtime_base`，创建 `agent_sessions`、`agent_messages`、
`agent_runs` 和 `agent_steps`。`agent_alembic_version` 保存该 revision ID，不保存 Java Flyway
版本。

### 9.4 当前迁移命令

从仓库根目录执行：

```bash
make agent-migrate
```

该命令在 Docker Compose 网络内运行 Alembic，能直接使用 `postgres:5432` 和容器环境变量，
避免宿主机 PostgreSQL 占用 5432、容器主机名无法解析或本地凭据漂移。

后续创建迁移时，流程通常为：

```text
新增 Agent SQLAlchemy Model
→ 生成 revision
→ 人工检查 upgrade/downgrade
→ 在测试数据库验证
→ 执行 make agent-migrate
```

不能在 Python 迁移中创建或修改 Java 订单等业务表。

## 10. 测试和质量检查

### 10.1 pytest 配置

`pyproject.toml` 中定义：

```text
unit         不使用外部服务的隔离测试
integration  覆盖应用组件边界的测试
```

`asyncio_mode="auto"` 让 pytest 能执行 `async def` 测试；严格标记可以防止拼错 marker 后
测试被静默分类错误。

### 10.2 当前测试文件

[`agent-service/tests/test_health.py`](../agent-service/tests/test_health.py)：

- 使用 `httpx.ASGITransport` 在测试进程内调用 FastAPI，不监听真实端口；
- 显式进入 lifespan，覆盖启动和关闭；
- 验证 `/health`、安全 Trace 透传和非法 Trace 替换。

它类似 Spring MockMvc 或 Node Supertest。

[`agent-service/tests/test_database.py`](../agent-service/tests/test_database.py)：

- 验证 `postgresql://` 转为 `postgresql+asyncpg://`；
- 验证异步 PostgreSQL Engine 和 Session Factory；
- 不执行 SQL，因此不依赖外部数据库。

[`agent-service/tests/test_observability.py`](../agent-service/tests/test_observability.py)：

- 构造日志记录；
- 使用 `JsonFormatter` 序列化；
- 验证 Trace、方法、路径和状态码等结构化字段。

[`agent-service/tests/test_alembic.py`](../agent-service/tests/test_alembic.py)：

- 验证 `alembic.ini` 可以加载；
- 验证迁移目录、`env.py` 和模板存在；
- 不执行数据库迁移。

[`agent-service/tests/test_business_client.py`](../agent-service/tests/test_business_client.py)：

- 验证 Base URL 和 connect/read/write/pool 超时；
- 验证 FastAPI 启动/关闭与共享 Client 生命周期；
- 验证 GET/POST、身份、Token、Trace 和幂等键 Header；
- 验证正常信封、data Schema、非法 JSON、字段缺失和 Trace 不一致。

### 10.3 Ruff 与 mypy

Ruff 检查：

```bash
cd agent-service
uv run --frozen ruff check .
```

它覆盖 import 顺序、未使用代码、常见错误、现代 Python 写法等，类似 ESLint 加部分
Checkstyle/Spotless 能力。

mypy 严格类型检查：

```bash
cd agent-service
uv run --frozen mypy app tests
```

Python 类型提示默认不由解释器强制。例如：

```python
def get_name() -> str:
    return None
```

代码可能被 Python 加载，但 mypy 会报告返回值类型错误。因此 Python 项目的可靠类型边界
依赖明确类型提示、mypy 和 Pydantic 各自承担不同职责。

### 10.4 根级验收命令

[`Makefile`](../Makefile) 提供：

```bash
make test-agent-foundation  # 运行工程基础和结构化日志回归
make test-agent-client      # 运行 M1.2 的 10 个 Client 测试
make test-agent-errors      # 运行 M1.3 的 18 个标准错误测试
make test-tools             # 运行 Tool 协议、只读 Tool 和重试策略测试
make test-agent-persistence # 在隔离 PostgreSQL 上测试模型、迁移和 Repository
make test-run-lifecycle     # 单独测试Run成功、失败、非法流转和并发终态
make test-step-lifecycle    # 单独测试Step记录、摘要保护、耗时和并发终态
make test-workflow-schemas  # 单独测试Workflow状态与结构化诊断Schema
make quality                # Ruff + mypy strict
make agent-migrate          # 容器内执行 Alembic upgrade head
make smoke                  # 验证 Java、Python、Web 健康检查
make test                   # 当前仓库完整回归
```

## 11. Docker 与 Compose

### 11.1 `agent-service/Dockerfile`

[`agent-service/Dockerfile`](../agent-service/Dockerfile) 使用多阶段构建：

```text
官方 uv 镜像
→ 复制 uv/uvx 二进制
→ python:3.12-slim
→ 根据 pyproject.toml 和 uv.lock 安装生产依赖
→ 复制 app 与 migrations
→ 使用 .venv/bin/python -m app.main 启动
```

关键安装命令：

```dockerfile
RUN uv sync --frozen --no-dev --no-install-project
```

- `--frozen`：严格使用锁文件；
- `--no-dev`：不安装 pytest、Ruff、mypy 等开发依赖；
- `--no-install-project`：当前应用不作为 Python 库安装。

类比 Java 是“构建可运行 JAR 后 `java -jar`”，类比 Node 是“`npm ci --omit=dev` 后
`node server.mjs`”。

### 11.2 根级 `docker-compose.yml`

[`docker-compose.yml`](../docker-compose.yml) 中的 Agent 服务：

- 从 `agent-service/Dockerfile` 构建；
- 容器内监听 8000；
- 依赖 PostgreSQL healthy 和 Java 服务启动；
- 传入数据库、Java地址、日志和未来模型配置；
- 将宿主机 `AGENT_SERVICE_PORT` 映射到容器 8000。

PostgreSQL 镜像为：

```text
pgvector/pgvector:pg16
```

它提供 PostgreSQL 16 和 pgvector 扩展能力，但当前尚未实现 RAG 表、Embedding 写入或向量
检索，不能因为镜像支持 pgvector 就声称 RAG 已完成。

默认开发数据库名为 `remote_sensing_agent`，用户和密码由根级 `.env`/Compose环境变量提供。
真实密钥不得写入本文、源码、日志或提交记录。

## 12. Python 初学时需要重点理解的语法

### 12.1 缩进就是代码结构

Java和TypeScript用 `{}` 表示代码块，Python用缩进：

```python
if condition:
    do_something()
    do_another_thing()
```

缩进错误不仅影响格式，还可能改变逻辑或直接导致语法错误。

### 12.2 import 会执行模块顶层代码

```python
from app.main import app
```

第一次 import 时会执行 `main.py` 的模块顶层语句。它和 Node ES Module 首次加载时执行
顶层代码相似；Java中最接近的是类加载和静态初始化，但机制不完全相同。

因此应避免在 import 阶段进行网络调用、写数据库或调用模型。

### 12.3 装饰器

```python
@application.get("/health")
async def health():
    ...
```

装饰器接收并包装下面的函数。FastAPI使用它注册路由，pytest使用它注册测试标记，
`@lru_cache` 使用它增加缓存行为。

它与Java注解用途相似，但Python装饰器本身是运行时可执行函数，不只是元数据。

### 12.4 类型提示与运行时校验

```python
def create_app(settings: Settings | None = None) -> FastAPI:
```

`Settings | None` 和 `-> FastAPI` 是类型提示，主要供编辑器和 mypy检查。Python解释器默认
不会仅凭提示自动拒绝错误类型。

Pydantic模型：

```python
class HealthResponse(BaseModel):
    service: str
    status: str
```

会在运行时校验外部输入或输出。后续 Tool 的输入输出必须使用Pydantic，不能只依赖类型提示。

### 12.5 `async def` 与 `await`

```python
async def load_order():
    result = await client.get(...)
```

类似 Node 的 `async/await`。Java可类比 `CompletableFuture` 或响应式API，但当前Java业务服务
主要是同步Spring MVC，不应认为实现方式完全相同。

Python Agent后续会调用多个Java接口、模型和数据库，异步I/O可以让等待某个网络响应时
事件循环继续处理其他任务。

不能在异步函数中随意执行长时间阻塞操作，例如直接 `time.sleep(5)`，否则会阻塞事件循环。

### 12.6 `async with`

```python
async with database.session() as session:
    ...
```

它用于异步资源的进入和释放，类似Java try-with-resources或Node `try/finally`。即使代码抛出
异常，Session仍能执行清理。

### 12.7 `yield` 与 lifespan

在 `@asynccontextmanager` 中：

```python
async def lifespan(...):
    startup()
    yield
    shutdown()
```

`yield`之前是进入上下文，之后是退出上下文。FastAPI用它表达应用启动和停止，而不是普通
接口返回值。

### 12.8 `ContextVar`

`ContextVar` 保存当前异步调用链中的值，适合Trace、请求用户或Run ID。普通全局变量会在
并发请求间共享，`threading.local` 又不能完整表达异步任务上下文，因此需要专门的上下文变量。

## 13. 当前能力边界和后续目录

### 13.1 M1.1～M2.5 已完成

- uv和Python 3.12工程；
- FastAPI/Uvicorn启动；
- `/health` liveness；
- Pydantic Settings；
- 异步SQLAlchemy Engine/Session基础；
- Alembic骨架、独立版本表和首个 Agent 运行元数据 revision；
- Session、Message、Run、Step SQLAlchemy模型；
- Run/Step异步Repository、数据库约束和隔离PostgreSQL验收；
- PENDING→RUNNING→SUCCEEDED/FAILED最小Run生命周期；
- 最终结果JSON快照、错误码/错误步骤和带时区起止时间；
- 基于期望旧状态的原子条件更新和并发终态竞争保护；
- CONTEXT/TOOL/RULE/LLM Step开始、成功和失败记录；
- 父Run行锁门禁、Step自动Run关联和原子终态竞争保护；
- 输入输出摘要空白压缩、常见凭据遮盖、1000字符截断和毫秒耗时；
- 固定诊断`OrderDiagnosisState`十个必需状态通道；
- 严格`DiagnosisResult/RootCause/Evidence/Suggestion/StepError` Pydantic契约；
- Tool字段级标量证据约束、无阻塞根因互斥和0～1置信度校验；
- LangGraph固定上下文、订单、任务、进度、质检、复核和交付加载节点；
- 多任务稳定排序与按任务ID聚合、标准Tool错误到StepError及失败条件路由；
- Workflow调用Step生命周期的Protocol边界和数据库短事务适配；
- JSON日志和安全Trace ID；
- 共享异步Java HTTP Client和连接池；
- 身份、Token、Trace ID和幂等键透传；
- GET/POST封装与分项超时；
- Java统一成功信封和调用方data Schema校验；
- Java失败信封、HTTP/code/Trace一致性校验；
- HTTP、超时、网络和响应契约异常到`ToolException`的统一映射；
- Tool统一元数据、`ToolContext`和互斥的`ToolResult`；
- `BaseTool.execute`权限、输入、整体超时、输出和异常门禁；
- `ToolRegistry`名称注册、查找和重复名称拦截；
- 订单、关联任务、任务详情、生产进度、质检问题、复核结果和交付状态七个只读 Tool；
- 严格 Tool 业务 Schema、父子资源 ID 绑定和空集合成功语义；
- FastAPI lifespan 中使用共享 Client 装配只读 Tool Registry；
- 显式只读 RetryPolicy、封顶指数退避、最大重试次数和整体超时预算；
- 重试错误白名单与 `retryable` 双门禁，以及重试结构化日志；
- Tool 名与规范化参数 SHA-256 指纹；
- `ToolContext` 私有 Run 级调用账本、并发占位、`DUPLICATE_CALL` 和 `force_refresh`；
- 仅development注册的Tool调试API、标准ToolResult和Swagger示例；
- 跨调试HTTP请求复用的有界Run上下文，以及身份/权限一致性门禁；
- pytest、Ruff、mypy；
- Docker/Compose运行。

### 13.2 当前尚未实现

- 数据库readiness；
- Workflow自动创建/结束Run，以及调试API自动记录Step；
- 确定性诊断规则、动态Agent和模型调用；
- RAG、SSE和Approval。

环境变量、依赖或目录骨架存在，不等于相应功能已经完成。

### 13.3 当前 M2.5 结构和后续可能增加的内容

当前关键结构为：

```text
app/
├── models/
│   └── agent_runtime.py         # 已实现的四个Agent运行元数据模型
├── repositories/
│   └── agent_runtime.py         # 已实现的Run/Step增删查和原子状态更新
├── services/
│   ├── run_lifecycle.py         # 已实现的最小Run生命周期
│   └── step_lifecycle.py        # 已实现的Step记录、摘要保护和耗时
├── schemas/
│   ├── tools.py                 # 已实现的七个只读Tool输入输出Schema
│   └── workflow.py              # 已实现的Workflow状态与结构化诊断Schema
├── workflows/
│   ├── order_diagnosis.py       # 已实现的固定LangGraph加载图
│   └── recording.py             # 已实现的Step短事务记录适配
├── tools/
│   ├── base.py                  # 已实现的Tool协议
│   ├── deduplication.py         # 已实现的指纹和Run内调用账本
│   ├── models.py                # 已实现的上下文和结果Schema
│   ├── retry.py                 # 已实现的只读有限重试策略
│   ├── registry.py              # 已实现的Tool注册与查找
│   └── readonly.py              # 已实现的七个只读Tool和装配工厂
└── api/
    └── tool_debug.py            # 已实现的开发专用Tool调试接口与Run上下文存储
```

上述文件均已存在。M2.5已完成业务事实加载图和Tool Step记录，但尚未实现阻塞阶段判断、诊断结果
生成、Run终态、HTTP API或动态模型调用，不能把“状态加载完成”描述成“已有Agent诊断闭环”。

对于负责Java接口对接的开发者，下一阶段最值得关注：

```text
Tool如何把输入Schema错误统一成PARAM_VALIDATION_ERROR
→ 如何验证请求ID与响应父子资源属于同一业务对象
→ 空集合、404和响应Schema错误为什么是三种不同事实
→ 为什么 retryable、错误码白名单、只读策略和总预算要同时满足
→ 如何证明失败后最多调用两次，而非无限重试
→ 如何区分 Tool 内部 retry 与 Agent 重复逻辑调用
→ 为什么 force_refresh 必须由调用方显式表达
→ 为什么 Tool业务失败返回ToolResult，而未知路由仍使用HTTP错误
→ 为什么生产环境应在路由注册阶段隐藏调试接口
→ 为什么Python只能通过Java API取得业务事实
```
