# 当前开发状态

- 当前里程碑：M6 人工确认和业务回写（进行中）
- 当前子阶段：M6.2 复核草稿 Schema（T610～T615，已完成）
- 已完成任务：T001～T153、T201～T275、T301～T354、T401～T487、T501～T555、T601～T615
- 当前场景：Approval原始草稿和用户修改统一经过不可变ReviewDraft校验；最终结论、问题摘要、1000字符复核意见、规范Citation和返工建议均为强类型，JSON引用可在落库后恢复，草稿任务必须与Approval目标一致；本阶段不执行Java写接口
- 通过测试：一次性隔离pgvector、现有Java服务和全量Python回归499/499通过，包含8个跨服务E2E、ReviewDraft字段与跨字段规则、Citation JSON往返、Approval生命周期与真实数据库持久化及既有动态路径；Approval/Schema/持久化定向测试46/46通过；局部Schema与生命周期测试21/21通过；mypy strict（124个源文件）、变更文件Ruff及新增文件格式检查通过；Web 18/18及生产构建、Compose健康检查与配置校验结果保持有效
- 失败测试：首次Schema测试发现严格Citation不接受数据库JSON还原的数组，已在ReviewDraft入口仅将`section`和`chunk_ids`数组规范化为元组并保留其他严格校验；最终定向和全量测试均通过。全量Ruff仍被8个既有文件的57项注释标点/行长问题拦截，全量格式检查仍有76个既有文件待格式化
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16、Python 3.12.13（uv 管理）、uv 0.12.0、Node.js 22.22.2、npm 10.9.7、Docker Desktop 29.6.2
- 最近更新：M6.2新增Conclusion、ReworkType、ReworkSuggestion和ReviewDraft；Approval创建、用户修改与最终读取都强制执行同一Schema，规范引用复用Citation并拒绝重复Chunk，目标任务不可在编辑中替换
- 已知非阻塞问题：当前Schema只验证Citation结构和重复来源，不查询知识索引判断引用是否仍然有效、可访问或适用于最新日期，这些事实由M6.3草稿Workflow重新检索；首个返工类型只覆盖黄金场景`COORDINATE_SYSTEM_FIX`，写Tool仍需在T643再次校验；`EXPIRED`已是合法终态，但超时计算和过期任务属于T647；尚无Approval HTTP接口、页面交互或Java写Tool调用，执行结果与错误持久化由后续阶段补齐；M5.4尚无具体动作模型供应商，M5.7因此诚实记录`configured=false`；当前快照表示Run创建时的进程配置，不是逐Step模型调用统计，具体调用模型、Token等字段仍由M7.1补齐；默认6轮不足以完成ORDER-003所需的订单、任务、质检、复核、交付、规范检索及FINISH全链路，M5.6通过显式10轮配置完成该路径；8次Tool预算当前通常不可达，但作为独立外部调用上限保留；规范问答的安全无结论响应视为已完成检索尝试但不会形成规范结论，后续仍需评估是否增加可引用规范的独立缺口状态；全量Ruff存在8个既有文件的57项注释标点/行长问题，全量格式检查存在76个既有未格式化文件；M4.12可控Subject用于验证数据契约、策略执行和指标数学，不代表尚未接入的真实Embedding/Reranker质量，默认低相关阈值0.5和RRF`k=60`仍需真实Provider评测校准；规范问答仍是内部组件，尚未接入统一路由HTTP、页面问答交互、Run/Step持久化或具体问答/Rerank模型客户端；当前Query Rewrite只做NFKC和空白规范化，不处理别名、缩写或多轮指代；页面产品/卫星元数据只作为收窄提示且未由Java事实重校验契约；权限和生效日期仍必须显式提供；回答模型引用ID经过白名单校验，但尚无自动事实一致性或声明级引用覆盖评测；当前权限枚举只有`INTERNAL_REVIEWER`，50条评测均为DOM/GF-2/内部复核范围，尚无第二产品、卫星或权限范围的标注对比；当前检索只返回`ACTIVE`规范，不支持历史审计as-of查询；M4.5双字词元可能产生词义无关共同双字召回，M4.6 HNSW尚无大规模召回率和延迟评测；尚未提供全目录入库CLI、定时任务或HTTP管理入口；当前token数是不绑定供应商的确定性近似值，重复检测只判断规范化正文完全相同，第一版不支持PDF；路由组件仍无FastAPI统一入口、持久化路由Run/Step或真实自然语言分发；TTL无后台物理清理，Session无归档策略；任务与质检页面尚未建设，`batch_id`和`satellite_type`缺少Java事实重校验契约；演示身份Header不是完整认证；诊断没有SSE，未预期节点异常可能遗留RUNNING Step；没有Step重试次数/Trace持久化或跨实例调用账本；本地Java/Python数据库角色未隔离；Java测试仍有Mockito动态Agent的未来JDK兼容警告
- 下一任务：T616～T623 开发M6.3草稿生成Workflow，重新读取Java任务和质检事实、检索当前规范、生成并保存WAITING_CONFIRMATION Approval，同时断言Java写接口调用次数为0
