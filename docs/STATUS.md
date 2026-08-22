# 当前开发状态

- 当前里程碑：M4 RAG规范检索（已完成）
- 当前子阶段：M4.12 RAG评测（T477～T487，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487
- 当前场景：`SPEC_QA`可通过`SpecificationSkill`进入固定RAG图，确定性执行查询规范化、页面提示合并、关键词/向量召回、RRF、Rerank和带引用生成；50条固定问题标注预期文档与完整章节，统一评测器在相同安全过滤条件下比较纯向量、关键词、混合和混合加重排策略，并输出Hit@5、MRR、无关片段占比和脱敏失败样本
- 通过测试：真实跨服务E2E最近一次8/8；Python汇总399通过/38个需外部环境的用例按门禁跳过；M4知识与RAG测试91/91；M4.12独立评测与完整验收9/9；真实隔离PostgreSQL知识测试3/3，持久化、迁移与API最近一次37/37；Embedding维度环境变量回归4/4；Compose中Agent直连和Web代理健康检查均为200，`ORDER-003`页面同源代理诊断1/1并保持`QUALITY_REVIEW`黄金结果；Web 8个测试文件18/18及生产构建通过；Ruff全量通过，mypy strict（105个源文件）通过；Compose配置校验通过
- 失败测试：最终结果0；开发中先以缺少`app.evaluation.rag`验证新评测测试有效，首次质量检查发现6项新文件标点问题并修正；M4完整质量门禁同时清理4个既有M4文件中的9项纯格式问题，未改变运行逻辑或弱化断言
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M4.12新增50条RAG固定标注、统一四策略Subject、Hit@5/MRR/无关片段占比和脱敏失败样本，M4完整验收通过；同时修复Compose固定Embedding维度字符串解析并恢复页面同源代理诊断
- 已知非阻塞问题：M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互、Run/Step持久化或具体问答/Rerank模型客户端；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验，权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；诊断没有SSE或Approval，未预期节点异常可能遗留RUNNING Step；没有Step重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T501～T507 实现M5.1 Agent State扩展，包括动作、Observation、Tool History、Information Gaps、迭代计数、终止原因和序列化测试
