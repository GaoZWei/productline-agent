# Web Console

M2.9 订单业务与诊断页面，使用 Vue 3、TypeScript、Vite、Pinia、Axios 和 Element Plus。
页面固定展示 `ORDER-001`～`ORDER-005`，默认打开黄金场景 `ORDER-003`，并从 Java
`/api/orders/{orderId}` 与 `/api/orders/{orderId}/overview` 读取业务事实。Agent 侧边栏把当前
订单和用户问题提交给 Python `POST /api/agent/order-diagnosis`，展示阻塞环节、根因、字段级证据和建议。

## 本地开发

先启动 Java、Python 服务，再启动 Vite：

```bash
make dev-business
make dev-agent
npm --prefix web-console run dev
```

浏览器业务请求走同源前缀 `/business-api`，诊断请求走 `/agent-api`。Vite 默认分别代理到
`http://localhost:8080`，可通过 `VITE_BUSINESS_API_URL` 覆盖；业务路径发往 Java 前会
移除 `/business-api`；诊断请求默认代理到 `http://localhost:8000`，可通过
`VITE_AGENT_API_URL` 覆盖并移除 `/agent-api`。这种方式无需放开跨域，也避免前端直接依赖部署域名。
诊断客户端使用演示身份 `reviewer-001 / REVIEWER`，可分别通过 `VITE_AGENT_USER_ID` 和
`VITE_AGENT_USER_ROLE` 覆盖；这些 Header 只提供当前阶段的最小身份上下文，不是完整认证。

## 测试与构建

```bash
make test-web
make build-web
```

`test-web` 覆盖业务与诊断响应解包、结构化错误、非法响应、固定五单加载、切换竞态、
诊断抽屉结果、核心业务组件和生产代理；`build-web` 同时执行 Vue TypeScript 检查和 Vite 构建。

## 生产运行

Docker 镜像先构建 `dist`，再由轻量 Node 服务提供静态资源、SPA 回退和健康检查。
运行时设置 `BUSINESS_API_URL` 和 `AGENT_API_URL`，Node 会把两个同源前缀转发到对应服务：

```bash
BUSINESS_API_URL=http://localhost:8080 \
AGENT_API_URL=http://localhost:8000 \
PORT=5173 node web-console/server.mjs
```

当前侧边栏每次提交都会创建一次性 Session 与 Run，仅执行确定性 Workflow。它不包含多轮对话、
SSE、动态模型路由或写操作确认；处理建议仅用于展示，不代表已经执行。
