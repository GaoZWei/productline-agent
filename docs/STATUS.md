# 当前开发状态

- 当前里程碑：M4 RAG规范检索（进行中）
- 当前子阶段：M4.2 知识库数据模型（T408～T413，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T413
- 当前场景：严格`DocumentCatalog`可校验16份演示规范的类型、适用范围、版本、有效期、权限和替代关系；Agent数据库通过`knowledge_documents`保存文档身份与过滤元数据，通过`knowledge_chunks`预留稳定分块、向量和数据库自动生成的全文检索字段
- 通过测试：真实跨服务E2E最近一次8/8；Python汇总316通过/32个需外部环境的用例按门禁跳过；M4.2知识模型单元与目录12/12；隔离PostgreSQL持久化、迁移与API 31/31，其中M4.2定向集成2/2；Web最近一次7个测试文件16/16及生产构建通过；Ruff和mypy strict（79个源文件）通过；Compose配置最近一次校验通过
- 失败测试：最终结果0；开发中先以缺少`app.schemas.knowledge`的预期失败验证新测试有效，随后修正测试对模型注册和日期导入的遗漏
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M4.2增加严格`DocumentMetadata`/`DocumentCatalog`契约、知识文档与分块ORM、pgvector扩展、自动全文检索字段、Alembic迁移和`make test-knowledge-models`验收入口
- 已知非阻塞问题：当前尚无Loader、实际分块、Embedding生成与入库、检索索引、有效期查询门禁或规范引用；`embedding`暂不固定维度，需在M4.4选定模型后收紧；当前评测只用可控Subject验证基础设施，尚无具体模型供应商和真实模型指标；“高分二号”到`GF-2`别名样本会暴露现有字面证据策略缺口，未在无真实模型对比前放宽安全校验；`IntentRouter`、实体合并器和决策器仍是分离的内部组件，尚无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；模型调用异常直接回退，当前只对结构或实体证据失败重试一次；TTL目前只阻止继续访问，尚无后台物理清理；首次诊断若在成功响应前失败，调用方拿不到该轮新建的`session_id`；清除会话会级联删除其Agent Message/Run/Step，尚无归档策略；当前只有订单业务页实际接入Adapter，任务与质检页面尚未建设；`batch_id`和`satellite_type`没有Java事实可供重校验；演示身份Header不是完整认证；诊断仍为单次HTTP响应，没有SSE，建议不能确认执行；未预期节点异常可能遗留RUNNING Step，尚无崩溃恢复；具体诊断模型客户端和真实模型评测未装配；没有Step重试次数/Trace持久化或跨实例调用账本；调试Run与持久化Run仍未关联；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T414～T422 实现M4.3统一DocumentLoader、Markdown/纯文本解析、标题分块、稳定Chunk ID和重复文档检测
