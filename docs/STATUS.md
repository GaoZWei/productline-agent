# 当前开发状态

- 当前里程碑：M6 人工确认和业务回写（进行中）
- 当前子阶段：M6.3 草稿生成 Workflow（T616～T623，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T623
- 当前场景：从会话最近的成功诊断读取历史结果，强制刷新Java任务版本与质检问题，重新检索当前日期和权限范围内的规范；模型草稿经过ReviewDraft、目标任务和完整Citation白名单校验后，Approval与来源Run原子进入WAITING_CONFIRMATION/WAITING_APPROVAL，全流程Java写接口调用次数为0
- 通过测试：`make test-approval`单元30/30、隔离PostgreSQL 3/3通过；完整持久化回归41/41、真实Java和PostgreSQL跨服务E2E 8/8通过；Python非外部依赖回归468/468通过，42项按数据库或E2E环境条件跳过且已由前述隔离命令覆盖相关持久化与黄金链路；mypy strict（127个源文件）、变更文件Ruff和3个新增Python文件格式检查通过；Web 18/18及生产构建、Compose健康检查与配置校验结果保持有效
- 失败测试：首轮历史诊断恢复测试发现严格Schema不能按Python模式接收数据库JSON中的枚举字符串，已改为标准JSON模式恢复并保留结构校验；最终定向、持久化和跨服务测试均通过。全量Ruff仍被既有文件的注释标点/行长问题拦截，全量格式检查仍有既有文件待格式化
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M6.3新增ReviewDraftGenerationWorkflow和DatabaseReviewDraftStore；最近诊断只作为生成线索，任务与质检事实强制刷新，规范引用按完整内容白名单校验，重复生成通过Run比较更新回滚孤立Approval
- 已知非阻塞问题：M6.3已在草稿生成时重新检索Citation，但确认执行前仍需由M6.6重新检查引用适用性、用户权限、任务状态和版本；当前只有内部Workflow和可替换模型协议，尚无具体草稿模型Provider、Approval HTTP接口或页面交互；首个返工类型只覆盖黄金场景`COORDINATE_SYSTEM_FIX`，写Tool仍需在T643再次校验；`EXPIRED`已是合法终态，但超时计算和过期任务属于T647；尚未调用Java写Tool，执行结果与错误持久化由后续阶段补齐；M5.4尚无具体动作模型供应商，M5.7因此诚实记录`configured=false`；当前快照表示Run创建时的进程配置，不是逐Step模型调用统计，具体调用模型、Token等字段仍由M7.1补齐；默认6轮不足以完成ORDER-003所需的订单、任务、质检、复核、交付、规范检索及FINISH全链路，M5.6通过显式10轮配置完成该路径；8次Tool预算当前通常不可达，但作为独立外部调用上限保留；规范问答的安全无结论响应视为已完成检索尝试但不会形成规范结论，M6.3会拒绝据此生成Approval；全量Ruff和格式检查仍受既有文件问题影响；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互、Run/Step持久化或具体问答/Rerank模型客户端；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验契约；权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；诊断没有SSE，未预期节点异常可能遗留RUNNING Step；没有Step重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T624～T633 开发M6.4前端确认卡片，展示影响对象、复核草稿和规范引用，支持编辑、确认、取消、二次确认与防重复点击
