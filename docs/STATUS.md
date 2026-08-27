# 当前开发状态

- 当前里程碑：M6 人工确认和业务回写（进行中）
- 当前子阶段：M6.5 写 Tool（T634～T646，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T646
- 当前场景：复核回写和返工创建Tool只接收`approval_id`与幂等键，从`EXECUTING` Approval读取最终草稿、确认人和目标版本，调用真实Java写接口后校验资源归属与递增版本，并以比较更新保存首次执行结果；写Tool为高风险、无自动重试且不暴露给动态模型
- 通过测试：`make test-approval`Python单元44/44、隔离PostgreSQL 4/4、前端确认卡片5/5通过；`make test-agent-e2e`真实Java和PostgreSQL跨服务E2E 9/9通过；Java写接口定向集成测试12/12通过；完整持久化回归42/42、Python回归482/482（另44条外部环境测试按条件跳过）、mypy strict（133个源文件）、M6.5定向Ruff和`git diff --check`均通过；`make test-web`Web 23/23及生产构建通过
- 失败测试：测试先行阶段因写Tool模块尚不存在按预期失败；首次真实E2E发现Java动态UUID为小写、不符合Python业务标识契约，修正为大写后又发现幂等重放Trace变化会误判不同结果，现已改为只比较业务字段并保留首次Trace。修正后全部定向与完整回归通过；全量Ruff仍受既有文件注释标点/行长问题影响
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M6.5新增写Tool严格Schema、独立注册表、Approval执行结果迁移与短事务Store；ReviewDraft补齐`issue_id`并绑定最新质检问题，Java动态写入ID统一为大写安全格式，真实复核/幂等重放/返工链路已验证
- 已知非阻塞问题：确认卡片尚无Approval HTTP接口，未接入诊断侧边栏；写Tool也未注册到应用生命周期，Approval在Tool成功后仍停留`EXECUTING`，需由M6.6完成确认接口、过期/权限/任务版本重校验、执行锁和成功失败终态；当前草稿Workflow只创建`SUBMIT_REVIEW` Approval，`CREATE_REWORK` Approval的生产编排尚未接线；首个返工类型只覆盖黄金场景`COORDINATE_SYSTEM_FIX`；M6.3生成时已重新检索Citation并绑定质检问题，但执行前引用适用性仍需M6.6复核；当前只有内部Workflow和可替换模型协议，尚无具体草稿模型Provider；应用内浏览器无可用实例，M6.4只有DOM交互测试和生产构建验证，尚缺真实视觉检查；M5.4尚无具体动作模型供应商，M5.7因此诚实记录`configured=false`；当前快照表示Run创建时的进程配置，不是逐Step模型调用统计，具体调用模型、Token等字段仍由M7.1补齐；默认6轮不足以完成ORDER-003所需的订单、任务、质检、复核、交付、规范检索及FINISH全链路，M5.6通过显式10轮配置完成该路径；8次Tool预算当前通常不可达，但作为独立外部调用上限保留；规范问答的安全无结论响应视为已完成检索尝试但不会形成规范结论，M6.3会拒绝据此生成Approval；全量Ruff和格式检查仍受既有文件问题影响；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互、Run/Step持久化或具体问答/Rerank模型客户端；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验契约；权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；诊断没有SSE，未预期节点异常可能遗留RUNNING Step；没有Step重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T647～T654 开发M6.6确认前重新校验，补齐Approval有效期、权限与任务版本刷新、STALE判定、重复提交门禁、执行锁和并发确认测试
