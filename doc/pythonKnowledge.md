# 当前项目 Python 工程学习手册

本文面向第一次接触 Python 后端项目的开发者，以本仓库 `agent-service` 的真实实现为准，并通过 Java Spring Boot 和 Node.js 服务进行类比。

本文描述的是当前 M1.1～M1.4 已实现能力，不是通用 Python 项目模板。后续代码变化时，应先以仓库实现、`doc/detailed-plan.md` 和 `doc/record.md` 为准，再同步更新本文。

## 1. 先建立整体认识

当前 `agent-service` 是一个独立的 Python 后端服务，主要承担未来的 Tool 封装、Workflow、
Agent、RAG、Approval 和运行记录。现阶段只完成工程基础、健康检查、数据库基础、迁移骨架、
最小可观测性、Java 异步 HTTP Client、标准错误映射和 Tool 基础协议；尚未实现具体业务 Tool
或大模型调用。

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
│   ├── clients/
│   │   └── business.py             # 调用 Java 的异步 HTTP Client
│   └── schemas/
│       └── business.py             # 身份、成功信封和强类型响应
│
├── migrations/                     # Alembic 迁移环境
│   ├── env.py                      # 加载配置、Base.metadata 和异步连接
│   ├── script.py.mako              # 生成迁移文件时使用的模板
│   └── versions/
│       └── .gitkeep                # 保留当前为空的迁移目录
│
└── tests/                          # 测试代码，类似 src/test/java 或 *.spec.ts
    ├── test_health.py
    ├── test_database.py
    ├── test_observability.py
    ├── test_alembic.py
    └── test_business_client.py
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
  "httpx>=0.28,<1.0",
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

它是未来所有 Agent 自有 SQLAlchemy Model 的共同元数据根。例如未来可以定义：

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

当前没有任何 Model 继承 `Base`，因此还没有 Run、Step、Approval 或 RAG 业务表。

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

未来使用方式：

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

保持代码边界，但这不是生产级权限隔离。开始持久化 Run/Step 或进入生产前，应为 Agent
配置独立数据库、Schema 或最小权限角色。

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

### 7.6 超时、可重试性和当前边界

四项超时分别控制 connect、read、write 和等待连接池的 pool timeout。它们必须大于 0 且
不超过 60 秒。分开配置可以区分“连接不上 Java”和“Java 已接收但业务处理过慢”，为后续
重试决策提供依据。

M1.3 只完成“错误分类”，仍然不会自动重试。timeout/网络错误上的 `retryable=true` 只说明
故障在技术上可能恢复，不代表每个调用都允许重放：

- M1.6 只能为明确的只读 Tool 增加有限次数、退避和总预算；
- POST 超时或网络中断时，Java 可能已经完成写入，不能仅凭 `retryable=true` 自动重放；
- 500 当前继承 Java 的保守 `retryable=false`，尤其不能对写请求猜测执行结果。

`UNKNOWN_TOOL_ERROR` 现在由 M1.4 `BaseTool.execute` 在具体实现抛出未知异常时生成；
`DUPLICATE_CALL` 仍依赖后续 M1.7 重复调用检测。Client 不会伪造这两类错误。

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

`risk_level`、`required_permissions`、`timeout` 和 `max_retries` 都是 Tool 元数据。当前已经执行
权限检查和整体超时，但 `max_retries` 只是为 M1.6 预留的策略参数；M1.4 不会因为错误标记为
`retryable=true` 就自动重放调用。`ToolContext.run_id` 当前用于调用关联和日志字段，不代表已经
实现 Run/Step 数据表或持久化。

`ToolRegistry.register` 遇到相同名称会抛 `DuplicateToolRegistrationError`，这是启动/装配错误；
它不是一次 Run 中相同参数被重复调用，因此不能使用 `DUPLICATE_CALL`。后者仍由 M1.7 实现。

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
```

- `alembic.ini`：指定迁移目录和 Python import 路径；
- `env.py`：加载 Settings、异步 Engine 和 `Base.metadata`；
- `script.py.mako`：创建新 revision 时生成 Python 文件的模板；
- `versions/`：保存实际迁移版本。

### 9.2 `target_metadata`

```python
target_metadata = Base.metadata
```

未来 Alembic 可以比较 SQLAlchemy Model 与数据库结构，并生成迁移差异。当前 `Base` 下还
没有 Agent Model，因此没有 Run/Step 等业务 revision。

### 9.3 独立版本表

```python
version_table = "agent_alembic_version"
```

Java Flyway 使用 `flyway_schema_history`，Python Alembic 使用 `agent_alembic_version`，两套
迁移记录不会混用。

当前数据库只创建了空的 `agent_alembic_version`，`migrations/versions/` 没有业务迁移文件。
`.gitkeep` 仅用于让 Git 保留空目录，没有运行时逻辑。

### 9.4 当前迁移命令

从仓库根目录执行：

```bash
make agent-migrate
```

该命令在 Docker Compose 网络内运行 Alembic，能直接使用 `postgres:5432` 和容器环境变量，
避免宿主机 PostgreSQL 占用 5432、容器主机名无法解析或本地凭据漂移。

未来创建迁移时，流程通常为：

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
make test-agent-foundation  # 运行 M1.1 的 6 个 Python 测试
make test-agent-client      # 运行 M1.2 的 10 个 Client 测试
make test-agent-errors      # 运行 M1.3 的 18 个标准错误测试
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

### 13.1 M1.1～M1.4 已完成

- uv和Python 3.12工程；
- FastAPI/Uvicorn启动；
- `/health` liveness；
- Pydantic Settings；
- 异步SQLAlchemy Engine/Session基础；
- Alembic骨架和独立版本表；
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
- pytest、Ruff、mypy；
- Docker/Compose运行。

### 13.2 当前尚未实现

- 订单、任务、进度、质检、复核和交付等具体只读Tool；
- 只读Tool的有限重试；
- 单次Run内的重复Tool调用检测；
- 数据库readiness；
- Run/Step实体和持久化；
- Workflow、动态Agent、模型调用；
- RAG、SSE和Approval。

环境变量、依赖或目录骨架存在，不等于相应功能已经完成。

### 13.3 T133 以后可能增加的结构

后续可能逐步形成：

```text
app/
├── schemas/
│   └── order.py                 # 端点业务DTO
├── tools/
│   ├── base.py                  # 已实现的Tool协议
│   ├── models.py                # 已实现的上下文和结果Schema
│   ├── registry.py              # 已实现的Tool注册与查找
│   └── get_order_detail.py      # 具体只读Tool
└── api/
    └── internal_tools.py        # 无Agent时调试Tool的内部接口
```

其中 `tools/base.py`、`tools/models.py` 和 `tools/registry.py` 已存在；`order.py`、
`get_order_detail.py` 和内部调试接口仍是预计结构，不代表功能已经实现。实际实现时仍以对应
任务和测试为准。

对于负责Java接口对接的开发者，下一阶段最值得关注：

```text
Tool如何把输入Schema错误统一成PARAM_VALIDATION_ERROR
→ 哪些只读错误允许有限重试
→ 每个Java data如何定义端点级Pydantic模型
→ 为什么Python只能通过Java API取得业务事实
```
