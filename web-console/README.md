# Web Console

M3.2 订单业务与诊断页面，使用 Vue 3、TypeScript、Vite、Pinia、Axios 和 Element Plus。
页面固定展示 `ORDER-001`～`ORDER-005`，默认打开黄金场景 `ORDER-003`，并从 Java
`/api/orders/{orderId}` 与 `/api/orders/{orderId}/overview` 读取业务事实。Agent 侧边栏把当前
订单、页面上下文和用户问题提交给 Python `POST /api/agent/order-diagnosis`，展示阻塞环节、根因、
字段级证据和建议。订单、任务与质检 Context Adapter 均为纯函数；当前已有订单页只调用订单Adapter，
其余两个供后续对应页面复用。
同一订单抽屉会保存首次响应的`session_id`并在后续诊断中复用；切换订单时清除本地会话引用，避免跨订单
继承。服务端仍会重新校验每轮携带的页面上下文。

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

`test-web` 覆盖三个页面Context Adapter、业务与诊断响应解包、结构化错误、非法响应、固定五单加载、
切换竞态、诊断抽屉结果、核心业务组件和生产代理；`build-web` 同时执行Vue TypeScript检查和Vite构建。

## 生产运行

Docker 镜像先构建 `dist`，再由轻量 Node 服务提供静态资源、SPA 回退和健康检查。
运行时设置 `BUSINESS_API_URL` 和 `AGENT_API_URL`，Node 会把两个同源前缀转发到对应服务：

```bash
BUSINESS_API_URL=http://localhost:8080 \
AGENT_API_URL=http://localhost:8000 \
PORT=5173 node web-console/server.mjs
```

当前侧边栏可在同一订单内复用Session，但每轮仍执行确定性Workflow；尚未实现自然语言意图继承、澄清或
SSE。M6.4已提供可复用的复核确认卡片，能够展示目标任务、质检问题、目标版本，编辑草稿、核对规范引用并进行二次确认，但尚无
Approval HTTP接口，因此未接入当前诊断侧边栏；组件只发出确认或取消事件，不会直接执行Java写操作。
