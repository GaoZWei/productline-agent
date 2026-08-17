# 当前开发状态

- 当前里程碑：M4 RAG规范检索（进行中）
- 当前子阶段：M4.1 文档准备（T401～T407，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T407
- 当前场景：`knowledge-base`包含14份当前有效和2份历史失效的固定演示规范；JSON目录集中保存八个计划元数据字段、生命周期和替代关系，Markdown正文按DOM、质量、坐标系、复核和交付分类
- 通过测试：真实跨服务E2E最近一次8/8；Python汇总308通过/31个需外部环境的用例按门禁跳过；M4.1文档目录3/3；`make test-knowledge-docs` 3/3；隔离PostgreSQL持久化与API最近一次30/30；Web最近一次7个测试文件16/16及生产构建通过；Ruff和mypy strict（76个源文件）通过；Compose配置最近一次校验通过
- 失败测试：最终结果0；开发中先以缺少`knowledge-base/catalog.json`的预期失败验证新测试有效，随后只修正新增测试及用户既有路由说明注释的Ruff格式门禁
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M4.1增加统一规范目录、JSON目录清单、14份有效演示文档、2份历史失效文档和`make test-knowledge-docs`验收入口；所有正文明确标记为非真实行业标准
- 已知非阻塞问题：当前只有静态文档和目录清单，尚无知识库表、元数据Pydantic Schema、Loader、分块、向量化、检索、有效期查询门禁或规范引用；当前评测只用可控Subject验证基础设施，尚无具体模型供应商和真实模型指标；“高分二号”到`GF-2`别名样本会暴露现有字面证据策略缺口，未在无真实模型对比前放宽安全校验；`IntentRouter`、实体合并器和决策器仍是分离的内部组件，尚无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；模型调用异常直接回退，当前只对结构或实体证据失败重试一次；TTL目前只阻止继续访问，尚无后台物理清理；首次诊断若在成功响应前失败，调用方拿不到该轮新建的`session_id`；清除会话会级联删除其Agent Message/Run/Step，尚无归档策略；当前只有订单业务页实际接入Adapter，任务与质检页面尚未建设；`batch_id`和`satellite_type`没有Java事实可供重校验；演示身份Header不是完整认证；诊断仍为单次HTTP响应，没有SSE，建议不能确认执行；未预期节点异常可能遗留RUNNING Step，尚无崩溃恢复；具体诊断模型客户端和真实模型评测未装配；没有Step重试次数/Trace持久化或跨实例调用账本；调试Run与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T408～T413 实现 M4.2 知识库数据模型、pgvector、全文检索字段、DocumentMetadata Schema和数据库迁移
