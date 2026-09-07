# Web Console

M7.6-G 订单业务与统一Agent页面，使用 Vue 3、TypeScript、Vite、Pinia、Axios 和 Element Plus。
页面固定展示 `ORDER-001`～`ORDER-005`，默认打开黄金场景 `ORDER-003`，并从 Java
`/api/orders/{orderId}` 与 `/api/orders/{orderId}/overview` 读取业务事实。统一Agent抽屉先查询
`GET /api/agent/capabilities`，再把当前订单提示和自然语言消息提交到`POST /api/agent/messages`；返回结果按
`ORDER_STATUS`、`DIAGNOSIS`、`SPECIFICATION_ANSWER`、`CLARIFICATION`和`APPROVAL`五类展示。
显式“固定诊断”仍调用`POST /api/agent/order-diagnosis`，模型未配置或不可用时不会被包装成动态Agent成功。

同一订单抽屉会复用首次响应的`session_id`，切换订单时清除本地Session、结果与事件流，迟到响应也不能覆盖新订单。
每轮统一消息及每次Approval确认都会先创建独立SSE事件流；页面实时展示Run、模型、RAG、Tool和Approval步骤、失败位置及耗时。
澄清只提交服务端给出的受控候选和来源Run；规范回答展示文档版本、章节和Chunk；Review与返工分别生成确认单，只有二次确认后
才会由Python请求Java重新校验并写入。顶部“运行历史”入口按当前用户分页展示Run，
选择记录后会并行读取详情和Step时间线，并展示受控Tool摘要、规范引用、Approval修改差异和错误定位。

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
make test-run-timeline
make test-run-history
make test-agent-page
make test-web
make build-web
```

`test-run-timeline`定向覆盖SSE分块解析、连接确认、有限重连、`Last-Event-ID`续接、事件归并、时间线、
诊断抽屉绑定和生产代理错误；`test-run-history`覆盖列表/详情Client、页面选择、历史Step、引用、Approval差异和失败展示，
并联动后端隔离数据库测试；`test-agent-page`覆盖统一Client、五类结果、Session/SSE、模型错误、Review/返工确认、真实PostgreSQL
四Skill生产集成，以及隔离Compose中的生产页面、Java/Agent代理、固定诊断与失败语义；`test-web`覆盖全部页面测试，
`build-web`同时执行Vue TypeScript检查和Vite构建。

## 生产运行

Docker 镜像先构建 `dist`，再由轻量 Node 服务提供静态资源、SPA 回退和健康检查。
运行时设置 `BUSINESS_API_URL` 和 `AGENT_API_URL`，Node 会把两个同源前缀转发到对应服务：

```bash
BUSINESS_API_URL=http://localhost:8080 \
AGENT_API_URL=http://localhost:8000 \
PORT=5173 node web-console/server.mjs
```

统一抽屉已完成四条生产路径；动态路径需要正确配置模型，规范问答和Review还要求知识索引状态为`READY`。
SSE历史只在单个Agent进程内短期保留，重连无法跨进程或跨实例恢复；演示Header也不是完整认证。
Approval卡片只把人工决定交给父级Client，浏览器不会直接调用Java；操作日志仍通过Run历史详情查看，尚无独立聚合页。
