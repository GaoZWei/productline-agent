# 当前开发状态

- 当前里程碑：M0 业务数据与 Java 接口（已完成）
- 当前子阶段：M0.8 最小前端业务页面（已完成）
- 已完成任务：T001～T057
- 当前场景：Vue 页面固定展示 `ORDER-001`～`ORDER-005`，默认打开 `ORDER-003`，可查看订单、任务、生产步骤、质检/复核与交付事实；页面只读取 Java API，不调用模型
- 通过测试：Java M0 回归 56/56；Web Vitest 7/7；Vue TypeScript 检查与 Vite 生产构建通过；Docker Web 镜像构建通过；`make test` 的基础检查、三服务冒烟及 M0.2～M0.8 分阶段验收全部通过
- 失败测试：最终结果 0；测试先行时 3 个前端套件因目标模块不存在而失败，生产服务测试因缺少 `createWebServer` 失败；实现后 7/7。开发中 TypeScript 7 与 `vue-tsc` 不兼容，固定到 TypeScript 6.0.3 后通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近治理更新：DOC-003 已建立 Agent 面试价值门禁；M0.8 经评估属于业务展示和普通前端可靠性实现，没有新增 `doc/needCare.md`
- 已知非阻塞问题：当前环境没有可用浏览器实例，未完成截图/视觉回归；`make reset-demo` 因会删除本地持久卷未执行，本次通过 Testcontainers 固定数据测试和真实容器五单查询替代；Python Tool、Workflow、RAG、Agent UI、SSE 和 Approval 均尚未实现
- 下一任务：T101 使用 uv 初始化 Python 项目
