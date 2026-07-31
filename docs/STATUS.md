# 当前开发状态

- 当前里程碑：M0 业务数据与 Java 接口（已完成）
- 当前子阶段：M0.8 最小前端业务页面（已完成，已完成“云端蓝灰”视觉改版）
- 已完成任务：T001～T057
- 当前场景：Vue 页面以云端蓝灰企业平台风格固定展示 `ORDER-001`～`ORDER-005`，默认打开 `ORDER-003`，可查看订单、任务、生产步骤、质检/复核与交付事实；页面只读取 Java API，不调用模型
- 通过测试：Java M0 回归 56/56；视觉改版后 Web Vitest 7/7；Vue TypeScript 检查与 Vite 生产构建通过；`npm audit --omit=dev` 为 0 个已知漏洞；既有 Docker Web 镜像构建及 `make test` 的基础检查、三服务冒烟和 M0.2～M0.8 分阶段验收全部通过
- 失败测试：最终结果 0；测试先行时 3 个前端套件因目标模块不存在而失败，生产服务测试因缺少 `createWebServer` 失败；实现后 7/7。开发中 TypeScript 7 与 `vue-tsc` 不兼容，固定到 TypeScript 6.0.3 后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M0.8 已将墨绿色视觉改为云端蓝灰色板，保留五单查询、错误/Trace 展示和 1000px、720px 响应式结构；本次纯视觉改版没有新增 `doc/needCare.md`
- 已知非阻塞问题：当前环境没有可用浏览器实例，视觉改版未完成真实桌面/移动端截图验收；组件测试、响应式 CSS 检查和生产构建已通过。`make reset-demo` 因会删除本地持久卷未执行；Python Tool、Workflow、RAG、Agent UI、SSE 和 Approval 均尚未实现
- 下一任务：T101 使用 uv 初始化 Python 项目
