# Web Console

M0.8 最小前端业务页面，使用 Vue 3、TypeScript、Vite、Pinia、Axios 和 Element Plus。
页面固定展示 `ORDER-001`～`ORDER-005`，默认打开黄金场景 `ORDER-003`，并从 Java
`/api/orders/{orderId}` 与 `/api/orders/{orderId}/overview` 读取业务事实。

## 本地开发

先启动 Java 服务，再启动 Vite：

```bash
make dev-business
npm --prefix web-console run dev
```

浏览器请求统一走同源前缀 `/business-api`。Vite 默认将该前缀代理到
`http://localhost:8080`，可通过 `VITE_BUSINESS_API_URL` 覆盖；业务路径发往 Java 前会
移除 `/business-api`。这种方式无需放开 Java CORS，也避免前端直接依赖部署域名。

## 测试与构建

```bash
make test-web
make build-web
```

`test-web` 覆盖统一响应解包、错误响应、非法响应结构、固定五单加载、快速切换竞态、
核心业务组件和生产代理；`build-web` 同时执行 Vue TypeScript 检查和 Vite 构建。

## 生产运行

Docker 镜像先构建 `dist`，再由轻量 Node 服务提供静态资源、SPA 回退和健康检查。
运行时设置 `BUSINESS_API_URL`，Node 会把 `/business-api/*` 转发到 Java 服务：

```bash
BUSINESS_API_URL=http://localhost:8080 PORT=5173 node web-console/server.mjs
```

当前页面只展示业务事实，不调用模型，也不包含 Agent 对话、SSE 或写操作确认能力。
