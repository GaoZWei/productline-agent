# Agent 开发面试问题与能力补强

面向岗位：Agent 应用后端开发｜核查日期：2026-09-16｜对象：目标简历 + productline-agent 项目

这份文档用一条业务链串起面试：**“这个订单为什么没有交付？依据是什么？能否生成复核意见，并安全创建返工任务？”** 面试官通常先确认你理解业务，再检查实现和取舍，最后用故障、指标和需求变更判断你能否独立负责系统。

当前仓库是简历中 Agent 内容的代码与验证依据。本文只核对仓库能够证明的内容；实际工作范围和个人贡献以你的真实经历为准。

## 阅读方法与证据口径

先练 Q01、Q03、Q04、Q06、Q07、Q11、Q19、Q21、Q25、Q27。每题按“结论 → 当前实现 → 具体例子 → 边界”回答，再用文末证据索引定位代码。

回答时区分：代码已实现、存在测试、历史记录通过、本次实际验证、后续设计。前四种不能相互替代；Stub、受控 Subject 和公式测试不能证明真实模型效果。

<a id="findings"></a>
## 先纠正七个容易影响回答的事实

| 核查发现 | 面试中如何准确表述 |
| --- | --- |
| README 仍停留在 M7.5，最新状态及统一入口代码已包含后续接线 | 以当前源码说明功能；README 是滞后的介绍，不能据此宣称统一入口未实现。[E01](#e01) [E02](#e02) |
| 状态文档把 Session/SSE 合称单进程 TTL 实现，但 Session 服务实际读写数据库 | Session 已持久化并有过期/所有者检查；SSE 历史与订阅、Run 内 Tool 指纹账本仍在进程内存。数据库持久化不等于所有多进程一致性问题已解决。[E04](#e04) [E08](#e08) [E23](#e23) |
| 动态图由模型选择只读动作，结果经确定性规则生成 | 自主性集中在取证路径，不应说“模型自主推理并裁定任意根因”。[E17](#e17) [E18](#e18) |
| Rerank 组件超时保留 RRF 候选，规范问答却返回 RERANK_UNAVAILABLE 并跳过生成 | 分别说明组件降级和下游业务策略，不能笼统说“重排失败后仍正常回答”。[E14](#e14) [E15](#e15) |
| `make eval-all` 依赖的是评测框架及指标测试 | 可以证明框架/公式的验收范围，不能作为真实模型效果达到简历数字的证据。[E26](#e26) |
| Approval CAS、Java 幂等已实现；Java 成功与 Python 终态提交之间仍有崩溃窗口 | 防重复业务副作用与自动恢复是两件事；状态文档明确尚无自动恢复任务。[E20](#e20) [E21](#e21) [E01](#e01) |
| 存在身份 Header 解析和角色门禁，但该解析函数不验证 Token 真实性；Compose 默认共享数据库角色 | 当前是演示身份方案和代码层职责隔离，不能说已完成生产认证与数据库最小权限隔离。[E24](#e24) |

历史状态另记录：2026-09-13 有一条 Router 版本断言与 108 项 Ruff 问题阻塞完整验收。这是**历史记录**，本次没有重跑，不能据此断言当前仍有同样数量的问题。[E01](#e01)

<a id="chapter-1"></a>
## 一、项目价值与个人贡献

开场先回答“为什么做、做到了什么”。如果这一层说不清，后续再多框架名也很难证明工程能力。

### Q01｜为什么订单诊断需要 Agent？直接做一个聚合查询页面不够吗？

**优先级：P0｜目标等级：L3**

**递进追问**

1. “查订单状态”和“解释为什么没交付”，各自的输入与决策复杂度有什么不同？
2. 如果所有问题都能由固定规则判断，增加模型究竟带来什么收益？
3. 哪类请求应明确不使用动态 Agent？如何比较增加的成本与价值？

**回答要点**：约束是跨系统取证和自然语言入口；当前状态查询走确定性流程，复杂诊断让模型选择只读动作，规则裁定结果；这样把不确定性放在可控位置。用相同订单的固定/动态路径、调用数、耗时、结论正确性比较价值；目前没有实测收益时，不承诺动态方案一定更快。

**项目依据**：[E03](#e03) 状态流程；[E17](#e17) 动态图与路径测试。

### Q02｜你从前端转向 Agent 后端，哪些能力已经得到证明？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 页面状态管理与后端状态机有哪些相似点？哪些保障不能从前端经验直接迁移？
2. 页面防重复点击与后端并发写入控制有什么差别？
3. 给你一个 Python 服务问题，你能独立分析连接、事务、异常和资源释放吗？

**回答要点**：可迁移的是契约、状态、交互和异常意识；新增责任是可信身份、服务端并发、数据库一致性与外部依赖治理。用一个后端闭环说明自己理解了什么，例如确认请求如何到 Java 写入；拿代码定位和反例验证支撑，尚未做过的负载测试与生产运维明确列为缺口。

**项目依据**：[E20](#e20) 确认服务；[E22](#e22) 异步资源与生命周期。

### Q03｜项目大量借助 AI 开发，你自己的设计与验证贡献是什么？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 选一个你真正理解的取舍：为什么这样设计，有什么替代方案？
2. AI 生成的测试如果与实现同时写错，你怎样发现？
3. 现场改变一个业务条件，你能判断改哪些边界，而不是让 AI 全仓重写吗？

**回答要点**：如实说明 AI 辅助范围；选三项实际参与且能举证的决策，逐一解释约束、方案和验证。可选素材是事实边界、独立 Approval、真实评测与替身区分，但不能把本文提供的思路倒写成自己过去已完成的工作。用需求变更和反例证明掌握程度。

**项目依据**：[E01](#e01) 计划/记录/现状的区别；[E19](#e19) 两次授权设计。

<a id="chapter-2"></a>
## 二、完整链路与服务边界

现在面试官会让你把“订单未交付”落到请求、状态和数据上，检查架构图是否能对应源码。

### Q04｜从用户输入到返工创建，完整请求链怎么走？

**优先级：P0｜目标等级：L3**

**递进追问**

1. Session、Turn、Run、Step、Approval 分别表示什么，什么时候创建？
2. ORDER-003 为什么定位到 QUALITY_REVIEW，而不是因为生产没完成？
3. 诊断完成后，复核和返工是否在同一次请求、同一授权中执行？

**回答要点**：消息进入统一服务后建立本轮运行，加载上下文并路由；状态/诊断/规范问答/Review 分别分发。黄金场景的依据是任务完成、坐标系问题未关闭、复核待处理、交付阻塞。Review 用新 Run 关联成功诊断，生成待审草稿；确认提交复核后，显式返工请求再生成独立 Approval。创建返工并不表示返工完成或订单已交付。

**项目依据**：[E02](#e02) 统一消息；[E18](#e18) 诊断规则；[E19](#e19) Review/返工。

### Q05｜为什么 Java 管事实、Python 管编排？直接访问数据库是否更快？

**优先级：P0｜目标等级：L3**

**递进追问**

1. Python 不直连业务表，避免了哪些具体一致性和权限问题？
2. 多次 Java 查询之间业务已经变化，诊断事实还是一个快照吗？
3. 代码约定不跨表访问，与数据库账号真的没有权限，是同一回事吗？

**回答要点**：业务校验和最终写入归 Java，Agent 自有状态与知识库归 Python；通过稳定契约复用业务规则。代价是网络开销和跨请求时间差；确认时刷新事实、Java 写时校验版本，仍不能把多次读说成全局一致快照。Compose 默认共享角色，物理权限隔离需补；必要时设计带版本的聚合读接口，但属于后续方案。

**项目依据**：[E07](#e07) 业务 Client；[E21](#e21) Java 写服务；[E24](#e24) 部署与身份。

### Q06｜“单主 Agent + 多 Skill”在代码里具体是什么？为什么不用多 Agent？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 业务 Skill 是 Python 分发单元、Prompt 文件，还是独立自治 Agent？
2. 哪些链路真的由 LangGraph 管理？为什么不直接写函数调用？
3. 什么需求出现后，多 Agent 才值得引入？代价如何验收？

**回答要点**：当前通过路由目录映射到业务执行单元，订单查询/任务跟踪可归同一状态 Skill；不是多个自治角色互相聊天。动态诊断图管理取证循环，状态查询等任务保留固定流程；图结构有利于显式状态和停止路径，但也增加状态维护成本。当前无法用“使用 LangGraph”推导出已实现 checkpoint、重启恢复或多 Agent 协作。

**项目依据**：[E03](#e03) 意图/Skill 映射；[E17](#e17) 图结构；[E02](#e02) 分发。

<a id="chapter-3"></a>
## 三、上下文、路由与澄清

架构能画出来之后，面试官会追问“这个订单”到底指谁。路由错对象，后面检索和写入再完善也可能处理错误目标。

### Q07｜页面、会话、执行三级上下文分别保存什么？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 页面仍在 ORDER-003，用户明确说 ORDER-004，应采用哪个对象？
2. 当前项目是否保存所有聊天历史作为长期记忆？
3. 业务状态为什么不能直接从 Session 继承为事实？

**回答要点**：页面提供当前界面提示；数据库 Session 保存最小可继承指代与澄清上下文并校验所有者/过期；Run 保存当次执行证据。来源优先级是本轮明确消息、已确认会话、页面、会话候选；本轮明确对象应胜出，但仍需 Java 验证。持久化最小上下文不等于长期语义记忆，历史状态不等于当前事实。

**项目依据**：[E04](#e04) Session；[E05](#e05) 来源优先级；[E25](#e25) Run 快照。

### Q08｜怎样证明模型提取的订单号真的来自用户本轮消息？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 模型看到了页面订单号，能否把它伪装成用户明确表达？
2. 同一优先级存在两个不同订单时，能直接取第一个吗？
3. “不要查 ORDER-003，查 ORDER-004”只做字符串存在校验够不够？

**回答要点**：服务端分别接收来源并赋级，不相信模型自报来源；提取结果需要本轮文本证据，最高优先级多值冲突进入澄清。原文中存在一个标识，只能证明出现过，不能充分证明否定、引用、纠正中的目标语义；这类语言反例应进入评测，不能宣称来源校验完全解决指代。

**项目依据**：[E05](#e05) 实体合并；[E06](#e06) Router Prompt 与解析。

### Q09｜0.85 的路由置信度意味着 85% 的正确概率吗？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 阈值 0.85、0.60 从哪里来，有没有校准？
2. 模型给 0.99，但必需参数缺失，是否允许执行？
3. 如何在少打扰用户与少错误分发之间选阈值？

**回答要点**：当前代码是固定分级，分数不是已校准概率。确定性顺序先处理 UNKNOWN、未解决冲突、缺参，再处理置信度和确认；高分不能越过缺参。后续在独立样本上按分数区间核对实际正确率，并比较错误执行率、澄清率、澄清后完成率，写操作授权仍独立存在。

**项目依据**：[E05](#e05) `confidence_level_for` 与决策；[E27](#e27) 路由评测。

### Q10｜澄清如何续接？能否重放上一轮的“确认”去处理新订单？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 为什么要绑定 Session 和来源 Run，而不只接收一个候选值？
2. 用户回答候选后，为何不再让模型重新路由一次？
3. 两个标签页同时澄清，旧响应迟到时前后端各该如何保护？

**回答要点**：服务端校验会话所有者、来源结果、待选字段及候选，恢复原决策后再走门禁；单字段选择不必重新承担模型漂移。前端隔离过时请求只是第一层，后端仍需处理旧来源与并发；当前有来源检查和数据库上下文更新，但不据此声称已证明所有多标签页冲突都串行化。

**项目依据**：[E02](#e02) 统一消息续接；[E04](#e04) Session；[E30](#e30) 页面交互测试。

<a id="chapter-4"></a>
## 四、Tool 与模型接入

路由之后，核心问题变成：模型输出在什么条件下才能获得实际执行权，以及依赖失败时会发生什么。

### Q11｜一个 HTTP API 包装成 Tool，除了 JSON Schema 还需要什么？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 输入合法但任务不属于当前订单，由哪一层拦截？
2. 上游 200 返回缺字段，能否当成业务数据为空？
3. 静态动作枚举已有 Tool 名，执行时为什么还要查 Registry？

**回答要点**：模型只能提出候选；参数 Schema 之外还要检查注册、风险、权限、资源归属、执行预算和返回契约。Registry 反映当前实例真实可用能力；响应缺字段是协议失败，不是“无问题”的事实。当前动态动作通过结构化 ActionDecision 交给本地执行器，不要未经证据把它描述成使用了供应商原生 `tools/tool_calls` 协议；二者都仍需要执行侧校验。错误类别决定后续停止、重试或澄清，不能统一吞成空结果。

**项目依据**：[E07](#e07) BaseTool、Client 与协议测试；[E17](#e17) 动作校验。

### Q12｜重试放在哪一层？一次用户请求最多会打多少次外部接口？

**优先级：P0｜目标等级：L4**

**递进追问**

1. HTTP 瞬时重试、模型结构纠错、Agent 重新规划有什么区别？
2. 多层各自重试两次，会怎样影响最坏耗时和请求数？
3. 写接口超时但可能已提交，为什么不能照搬只读重试？

**回答要点**：只读策略按明确错误和预算有限重试；模型 Client 处理传输类失败，上层 Router/Action 的一次结构纠错是另一种策略；动态图预算又是不同维度。不能把 `retryable` 当作每一层都应自动重放。逐层数最坏尝试和退避时间，写入不确定结果要依赖幂等与查询/恢复设计，不能换键盲重试。

**项目依据**：[E08](#e08) RetryPolicy；[E09](#e09) 模型 Client；[E20](#e20) 写失败边界。

### Q13｜Tool 调用去重、缓存和业务幂等是一回事吗？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 参数字段顺序不同，调用指纹应不应该一致？
2. 第一次读取后状态变化，确认前还允许再读吗？
3. 进程重启后，RunToolCallLedger 还能防止业务重复写吗？

**回答要点**：当前指纹由 Tool 名和校验后的规范化参数生成，账本按 Run 在进程内记录，主要拦截重复逻辑调用；它不缓存结果，也不提供跨重启业务幂等。确认刷新可走受控 `force_refresh`，绕过去重不等于绕过权限。Java 写入以稳定幂等键、请求绑定和事务作为最终防线。

**项目依据**：[E08](#e08) 指纹与账本；[E20](#e20) 刷新；[E21](#e21) Java 幂等。

### Q14｜Structured Output 能保证答案真实吗？如何区分配置可用与真实可用？

**优先级：P0｜目标等级：L3**

**递进追问**

1. JSON 语法合法、Schema 合法、业务合法，各自意味着什么？
2. 模型返回合法但未知引用 ID，或合法但越权 Tool，应在哪拒绝？
3. capabilities 显示配置有效，能否证明网络、模型和五类适配器已验证？

**回答要点**：公共 Client 校验响应和本地 Schema；五种适配器分别转换 Router、Action、Rerank、规范回答、Review 协议，业务模块再做白名单和事实约束。能力查询表示配置状态，不主动探测网络。现状文档仅记录真实 Router/状态入口验证，其他真实链路尚待验证；本地 HTTP Stub 不能替代 Provider 效果测试。

**项目依据**：[E09](#e09) Client；[E10](#e10) 适配器与本地 Stub 测试；[E01](#e01) 验证范围。

<a id="chapter-5"></a>
## 五、RAG 与引用

Tool 能证明订单发生了什么，RAG 才能说明适用规范要求什么。面试官会沿数据入库、召回、重排和生成逐层检查。

### Q15｜为什么这样分块？Chunk ID 稳定解决了什么问题？

**优先级：P1｜目标等级：L3**

**递进追问**

1. 当前按字符上限还是模型 Token 上限切分？统计值是否是实际计费 Token？
2. 在文档前面插一节，所有后续 Chunk ID 应不应该变化？
3. 表格跨行、标题改名、长段断句，会造成哪些检索和引用问题？

**回答要点**：当前按 Markdown 标题、段落/句末和字符上限分块，默认上限 1200 字符；token_count 是确定性近似。ID 结合文档、章节、内容哈希及重复出现次数，不依赖全局序号，减少无关插入造成的身份漂移。标题和正文变化仍可能改变身份；复杂表格/PDF 结构能力不能由 Markdown Loader 推导出来。

**项目依据**：[E11](#e11) `HeadingDocumentChunker` 与测试。

### Q16｜为什么向量维度相同也不能混用不同 Embedding 模型？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 查询向量与文档向量需要哪些身份一致？
2. 全量入库到一半 Provider 失败，用户会看到半套新索引吗？
3. 规范增至百万 Chunk 时，先在内存生成全部向量再事务写入还合适吗？

**回答要点**：当前校验 Provider、模型、维度、索引版本；相同维度不代表语义坐标一致。入库先完成外部生成，再在数据库事务中重建，避免部分更新；这是小目录的清晰方案。扩大规模后需要分批构建新版本、完整性验收和切换/回滚机制，不能把未来方案称为已实现。

**项目依据**：[E12](#e12) Embedding 与全量入库；[E13](#e13) 向量查询身份过滤。

### Q17｜中文关键词检索为什么这样做？它与向量召回各自擅长什么？

**优先级：P1｜目标等级：L3**

**递进追问**

1. “坐标系统一”和 `GF-2` 如何变成查询词元？
2. 当前是 BM25，还是 PostgreSQL 全文排名？
3. 长自然语言问题含多个限制词时，会不会过严匹配？如何验证而不是猜？

**回答要点**：当前中文采用相邻双字、英文/业务标识保留，使用 `plainto_tsquery` 与 `ts_rank_cd`，不是仅凭“关键词检索”就称 BM25。编号精确匹配和语义相似各有用途；应检查实际生成查询与失败样本，尤其长句、同义词、单字和否定。不能只用固定目录的少量命中推断通用中文效果。

**项目依据**：[E13](#e13) 中文预处理与 SQL；[E28](#e28) 四策略评测。

### Q18｜为什么元数据要在 Top-K 前过滤？过滤后就一定能召回够吗？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 历史版本相似度最高时，先取 Top-5 再删有什么问题？
2. 用户能否通过页面传旧日期或更高权限召回不适用规范？
3. SQL 带 WHERE 是否证明 HNSW 的实际访问计划和召回质量满足要求？

**回答要点**：当前两路查询共用生命周期、生效/失效日期、权限及产品等条件，逻辑上在结果排名截断前约束。服务端注入权限/当前日期，页面提示只收窄业务范围。SQL 正确不代表实际索引使用或强过滤下召回充足；需要执行计划和与精确基线对比，不能从建了索引推断性能结论。

**项目依据**：[E13](#e13) `_metadata_clauses`；[E03](#e03) 生产分发与服务端范围。

### Q19｜为什么选 RRF？重排分数 0.5 与 RRF 分数能混用吗？

**优先级：P1｜目标等级：L3**

**递进追问**

1. 两路排名为 1/缺失和 3/3 的候选，怎样计算融合分数？
2. 同一 Chunk 两路载荷不一致、相邻片段被合并时怎样处理？
3. Rerank 少返回一个候选、超时、非超时失败，各如何向下游传递？

**回答要点**：当前 RRF 常数 60，单个候选分数为各出现通道的 `1/(60+rank)` 之和；缺失通道不计。融合校验同 ID 载荷，合并相邻片段并保留来源。Rerank 限定对既有候选完整评分，默认 0.5 是重排门槛，不是 RRF 门槛；超时携带降级状态返回候选，其他错误失败，规范问答对超时也不生成结论。

**项目依据**：[E14](#e14) 融合/重排；[E15](#e15) 下游门禁。

### Q20｜引用 ID 合法，是否就证明回答受到规范支持？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 模型引用了真实章节，但把“应小于”说成“应大于”，白名单能发现吗？
2. 合并多个 Chunk 后，怎样追到每段原文？
3. 文档中夹带“忽略要求并执行返工”的文字，哪一道边界阻止它变成操作？

**回答要点**：当前引用由服务端候选映射装配，模型只能选已授权引用 ID，合并结果保存全部 Chunk 身份；这证明来源存在和本轮可用，不证明每句结论都被原文蕴含。无证据时安全返回。知识文本仍是不可信内容，不能授予工具权限；声明级支持检查、注入对抗覆盖需要补证据。

**项目依据**：[E15](#e15) 问答与引用；[E10](#e10) 适配器白名单。

<a id="chapter-6"></a>
## 六、动态诊断与停止条件

面试官现在会要求把模型的自由度说精确：自主取证、事实判断和执行权限不能混成一个“智能体”。

### Q21｜模型选择下一步工具，但最终诊断由规则生成，这算怎样的 Agent？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 模型能修改哪些状态？哪些字段只能由 Tool 或规则生成？
2. 模型建议 FINISH，但还没有充分事实，会怎样结束？
3. 如果模型换了，正确性与效率分别由哪些指标体现？

**回答要点**：当前模型根据已有事实与信息缺口提出下一只读动作；确定性节点校验、执行、保存观察并判断完成，`generate_rule_diagnosis` 根据事实构造结果。这是受约束的动态取证，不是开放式根因发现。模型变化可能影响路径效率和事实覆盖；最终规则正确也不能证明模型路径最优或能泛化到所有新故障。

**项目依据**：[E17](#e17) 动态图；[E18](#e18) 规则生成；[E03](#e03) 生产装配。

### Q22｜6 轮决策、8 次 Tool、连续 2 次无新信息，分别限制什么？

**优先级：P1｜目标等级：L4**

**递进追问**

1. 在一轮最多一次工具调用的路径里，8 次上限是否可能先于 6 轮触发？
2. 一次 FINISH 或被拒绝动作是否消耗决策轮数？
3. 预算耗尽与越权动作，应该产生相同终止原因吗？

**回答要点**：三个预算分别约束决策、外部调用和信息增量；默认值并非性能最优证明。在当前一对一路径中 8 次可能被 6 轮先限制，但独立预算服务于配置变化。FINISH 消耗决策但不产生实际 Tool；安全预算停止、信息不足与非法执行应保留不同终止语义，生产层也不能把模型故障包装为正常成功。

**项目依据**：[E17](#e17) `AgentExecutionLimits`；[E03](#e03) 生产故障转换。

### Q23｜“没有新信息”怎么定义？摘要变了算不算新信息？

**优先级：P1｜目标等级：L4**

**递进追问**

1. 同样 Tool 参数与不同 Tool 返回同样事实，有什么区别？
2. 系统读到暂态错误或缺字段，能否说“没有阻塞”？
3. 多任务订单只读了一个正常任务，是否足以判定订单可交付？

**回答要点**：动作指纹解决重复请求，信息充分度检测解决事实覆盖，二者不等价。围绕订单、任务、质检、复核、交付所需证据判断缺口；错误或未读取不能当作否定事实。当前有信息缺口检测和多种规则路径，但对任意多任务组合的完整性不能只用黄金单任务场景证明。

**项目依据**：[E18](#e18) `InformationGapDetector` 与诊断规则；[E17](#e17) Observation/停止路径。

### Q24｜五个固定订单的路径都通过，证明真实模型能诊断新订单了吗？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 路径测试中的下一动作是模型生成还是替身预设？
2. 新订单 ID、不同任务顺序、多个同时阻塞会不会改变结果？
3. 真实模型在两次运行中走不同但合法路径，怎样判定通过？

**回答要点**：当前固定路径测试可验证图、工具门禁和规则在指定动作序列下工作；受控动作不证明真实策略质量。新样本应改变 ID 和状态组合，期望围绕正确证据/结果/预算，而不强制唯一工具顺序；先验证业务约束，再单独比较成本与重复性。

**项目依据**：[E17](#e17) 固定路径测试；[E29](#e29) Agent 观测指标。

<a id="chapter-7"></a>
## 七、Approval 与写入安全

前面的诊断即使错了通常还能重新查询；到了写入，错误对象、重复执行和不确定结果都需要明确处理。

### Q25｜人工确认究竟确认了什么？为什么复核与返工要分别授权？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 用户改了草稿，写入内容以模型原稿还是用户最终稿为准？
2. 诊断建议“创建返工”，是否表示用户已授权创建？
3. 为什么新 Review Run 关联来源诊断，而不把旧成功 Run 改成等待？

**回答要点**：Approval 绑定目标、操作类型、草稿和版本，最终授权是用户可见且可修改的内容；模型生成建议不获得写能力。Review 独立 Run 保留诊断历史，提交复核与创建返工是两个副作用，当前各自创建 Approval；返工要求复核成功后显式请求。不能用一次“同意”顺带执行另一个动作。

**项目依据**：[E19](#e19) 草稿与编排；[E20](#e20) 最终稿确认测试。

### Q26｜两个用户或两个进程同时确认，为什么只会有一个执行者？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 先查询状态再在 Python 中判断，为什么不足以互斥？
2. CAS、Java 幂等键、任务版本，各自防什么问题？
3. 同一幂等键但不同请求内容，应该重放还是拒绝？

**回答要点**：确认服务通过数据库条件状态更新从 CONFIRMED 抢占 EXECUTING，只有成功者写；Java 再将幂等键绑定操作、请求摘要及调用人，并检查目标版本。CAS 防同授权并发执行，幂等防重复副作用，版本防过期事实。单元测试中的并发 Harness 可验证服务行为，但跨进程和真实数据库竞争必须单独验证。

**项目依据**：[E20](#e20) 确认/CAS；[E21](#e21) 业务事务；[E16](#e16) 安全矩阵。

### Q27｜Java 已写成功，Python 保存日志前崩溃，会发生什么？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 用户看到失败，是否意味着业务一定没有发生？
2. 原 Approval 停在 EXECUTING，现有服务会自动恢复吗？
3. 你会如何区分“确认未执行”和“执行结果未知”，避免换新键重复写？

**回答要点**：两个数据库提交不是一个原子事务；Java 成功后 Python 可能没有保存结果，业务存在但本地仍执行中。稳定幂等键防重复不代表本地自动完成，现状说明没有恢复任务。补强方案应记录可恢复执行意图，用原操作身份查询或重放获知结果，再条件更新本地状态；结果未知时不能先标成未执行并另建授权重做。

**项目依据**：[E20](#e20) 执行顺序/幂等键；[E21](#e21) Java 重放；[E01](#e01) 明确局限。

### Q28｜确认时业务没变，但引用规范更新了，原草稿还能提交吗？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 确认前刷新哪些事实？为什么还要 Java 在写入时检查版本？
2. 过期、取消、STALE 与写入失败分别允许怎样继续？
3. Approval 等待期间权限撤销或规范失效，目前各有多大保障？

**回答要点**：当前确认刷新任务/质检，核对目标版本、状态、归属和角色；Java 防读取到写入之间的变化。取消、过期和 STALE 都不能沿旧授权写入。确认服务当前不重新运行 RAG，规范依据沿用草稿生成时结果，因此不能声称覆盖规范变化；生产身份撤销也不能由演示 Header 保证。后续需明确规范变更后的重新审查策略。

**项目依据**：[E20](#e20) `_stale_reason`；[E19](#e19) 草稿检索；[E24](#e24) 身份边界。

<a id="chapter-8"></a>
## 八、异步、SSE 与运行观测

写入闭环解释清楚之后，还要证明服务在实际运行条件下不会耗尽连接、丢失状态或误导用户。

### Q29｜FastAPI 接口写成 async，就能支撑高并发吗？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 等待 HTTP/数据库与 CPU 密集工作，对事件循环的影响有什么不同？
2. HTTP Client 与数据库 Session 应该共享到什么粒度？
3. 为什么不在持有数据库事务时等待几十秒模型响应？

**回答要点**：异步主要让等待可让出执行权，不自动减少模型耗时或 CPU 开销。项目用应用生命周期管理客户端/引擎，数据库会话按操作使用；并发任务不能随意共用一个可变事务会话。外部等待与本地短事务应明确分开；需要逐调用检查，不能因为某处用了短事务就宣称全链路已优化。

**项目依据**：[E22](#e22) `create_app`、`Database`、Client；[E20](#e20) 跨外部调用执行步骤。

### Q30｜浏览器断开 SSE，服务端任务是否会取消？

**优先级：P1｜目标等级：L4**

**递进追问**

1. 当前 SSE 是 Token 流还是 Run/Step 事件流？
2. SSE 断连、用户取消 Approval、服务进程退出，是同一种取消吗？
3. 客户端取消 HTTP 等待，为什么不能据此断言 Java 写入已取消？

**回答要点**：当前 SSE 传运行事件，有心跳和短期回放；断连清理订阅，现状明确不取消正在运行的 Run。Approval 取消是受状态限制的业务动作；进程退出又是恢复问题。调用方不再等待，不能证明远端没有完成；后续若增加任务取消，需要规定只读阶段与写入临界阶段的行为。

**项目依据**：[E23](#e23) 订阅清理；[E19](#e19) Approval 取消；[E01](#e01) 断连边界。

### Q31｜扩为两个 Worker，哪些状态能共享，哪些会丢？

**优先级：P1｜目标等级：L4**

**递进追问**

1. Session 已在数据库，SSE 为什么仍可能跨 Worker 订阅不到？
2. 短期回放窗口外重连，怎样恢复最终结果？
3. 慢消费者导致队列满时，应该丢事件、断连接，还是拖慢整个 Run？

**回答要点**：数据库 Session/Run/Approval 可跨实例读取，但 SSE 的 `_streams`、订阅队列和调用账本在内存，`asyncio.Lock` 仅保护本进程。粘性路由可暂时缓解事件归属，不能解决重启回放；持久历史提供结果恢复，实时通道若要跨实例需共享事件机制。当前不能声称已有分布式事件总线或全量持久事件重放。

**项目依据**：[E04](#e04) Session；[E23](#e23) SSE；[E25](#e25) 历史查询。

### Q32｜有 Run/Step 为什么还不能直接定位所有故障？日志能记录多少内容？

**优先级：P1｜目标等级：L4**

**递进追问**

1. LLM Step 失败、Tool Step 失败、证据不足各应怎么展示和统计？
2. 子 Step 耗时可以直接相加当作 Run 总耗时吗？人工等待怎么处理？
3. 不保存完整 Prompt 和响应，怎样支持诊断？保存了 ID 又如何防越权查询？

**回答要点**：项目记录类型、终态、错误、版本及可选 Token/调用数，嵌套步骤需要按结构解释，父子耗时直接求和会重复计算。安全短路与系统故障分开；历史是当时证据不是当前业务事实。最小日志降低正文暴露，但减少重放细节，需受控样本/版本辅助；所有权过滤建立在可信身份前提上，演示 Header 仍是缺口。

**项目依据**：[E25](#e25) Run/Step 与历史；[E29](#e29) 观测指标；[E24](#e24) 身份。

<a id="chapter-9"></a>
## 九、指标与简历成果

这一章不教你背数字，而是检验数字是否有数据集、分母、版本、原始观测和实验条件。当前简历数字应视为待证实目标。

### Q33｜你说路由 90%+、参数提取与补全 95%+，分母分别是什么？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 60 条样本覆盖什么类别，是否有独立留出集？
2. 参数按整条全对还是按字段统计？页面自动填入能算模型提取正确吗？
3. 模型猜错但系统正确澄清，是路由错、执行错还是成功保护？

**回答要点**：仓库有 60 条路由数据，参数提取统计明确/同义/混淆类的期望字段，补全统计页面/会话指代类字段；澄清触发与错误 Skill 分发另计。报告需列每项分子分母、混淆矩阵和失败样本。现有框架/受控 Subject 不能支撑真实模型达到这些数字；先补真实预测和独立样本。

**项目依据**：[E27](#e27) 数据集、类别与公式；[E26](#e26) Subject 标记。

### Q34｜Tool 首次校验 88%+、最终成功 97%+，能证明模型会纠错吗？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 原始调用是否由模型产生，还是测试代码直接提供正确参数？
2. “首次校验失败后最终成功”是分子，纠错率的分母在当前实现里是什么？
3. 逻辑 Tool 调用、HTTP 重试、重复拒绝，在统计中如何区分？

**回答要点**：当前 Tool 指标接受 Outcome；首次通过率=首次参数校验通过数/全部用例，纠错成功率=首次校验失败但最终成功数/首次校验失败数，最终成功率=最终成功数/全部用例。平均重试和发生重复调用的用例比例也以全部用例为分母，与 Agent 按尝试统计的口径不同。Outcome 必须来自实际执行；即使最终成功，也要确认恢复来源，不能用公式名称证明模型自动修复。

手算自测：A 首次合法且成功，B 首次非法后修复成功，C 首次非法且最终失败，则首次通过为 1/3，纠错成功为 1/2，最终成功为 2/3。这只是公式示例，不是项目测量结果；若没有首次失败样本，代码的纠错率数值 0.0 应解释为无适用样本。

**项目依据**：[E29](#e29) Tool/Agent 指标；[E08](#e08) 执行与重试；[E26](#e26) Outcome 接口。

### Q35｜50 条问题中 Hit@5 从 76% 到 88%，到底改善了几条？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 同一 50 条、每题命中记一次时，数字是否对应 38 条与 44 条？
2. Top-5 无关占比由 30% 到 18%，返回不足五条时分母怎么算？
3. 同时加过滤、混合、重排和合并，如何判断收益分别来自哪里？

**回答要点**：若同一 50 条全部参与，76%/88%对应 38/44 条命中，净增六条；这是算术解释，不是本次测得结果。当前相关性要求文档和完整章节匹配，无关率分母是实际返回片段。四策略应共享数据与适用条件，再做单因素对照；还要报告旧命中丢失、新增命中、MRR、返回数与回答支持度，小样本不能直接外推线上。

**项目依据**：[E28](#e28) RAG 数据与相关性公式；[E14](#e14) 合并改变检索单位。

### Q36｜3 分钟到 30 秒、复核整理减少 50%，你如何测量？

**优先级：P0｜目标等级：L3**

**递进追问**

1. 起点是打开页面、发送请求还是模型开始？终点是展示答案还是人确认正确？
2. 人工组与 Agent 组是否处理同等难度，是否包含失败、修改和等待？
3. 减少整理时间但增加审核错误或返工，总收益还成立吗？

**回答要点**：系统耗时与人完成任务的耗时分开；诊断比较到正确识别阻塞并取得依据，复核比较到形成可提交意见，记录人工编辑和质量。相同任务随机/交叉安排避免先做组记住答案，失败和纠错不能丢掉。当前没有可追溯计时记录支撑这两项成果，应先陈述已实现辅助流程，不报节省比例。

**项目依据**：[E25](#e25) 系统耗时；[E19](#e19) 草稿/人工修改；[E01](#e01) 真实验证边界。

### Q37｜24 次异常里 23 次定位成功，空召回和断连也应该有失败 Step 吗？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 24 类固定场景、24 次实际运行、24 个测试函数，是同一回事吗？
2. 什么叫定位成功：有错误字段，还是命中预期故障环节？
3. 排查中位时长 9 分钟到 3 分钟，自动化运行日志能单独证明吗？

**回答要点**：固定矩阵覆盖多类边界，真实故障需稳定错误与预期 Step；空召回、重复决策、预算停止、SSE 断连有各自保护语义，不能全要求 FAILED。定位指标比较实际与预期，分母只包含适用且声明预期的样本；人工排查需独立计时。现有矩阵与公式不等于已经有“23/24、9→3”的实测证据。

**项目依据**：[E16](#e16) 异常矩阵；[E29](#e29) 观测公式；[E26](#e26) 报告标记。

<a id="chapter-10"></a>
## 十、综合设计与现场题

最后不再按模块提问，而是要求现场定位、写小段代码和安排工程优先级。这一章最适合检验是否真正理解项目。

### Q38｜现在要求支持一种新的返工类型，你从哪里开始改？

**优先级：P1｜目标等级：L4**

**递进追问**

1. 只给 Prompt 增加描述为什么不够？
2. Java 规则、Python Schema、Approval、知识规范和页面哪些地方受到影响？
3. 原来的坐标系返工以及老 Approval 如何保持安全兼容？

**回答要点**：当前返工仅覆盖坐标系修复。先定义新类型的业务前置状态和最终副作用，再增加 Java 契约/校验与 Tool Schema，接入草稿和独立授权，最后处理规范与展示。新增能力不意味着改写旧草稿语义；历史版本不兼容时需要明确拒绝或迁移，不默认重解释后执行。

**项目依据**：[E19](#e19) 返工编排；[E20](#e20) 失效规则；[E21](#e21) 业务写入。

### Q39｜现场写一个受限异步执行器，并解释如何验证它

**优先级：P1｜目标等级：L4**

**递进追问**

1. 给定异步只读函数，如何限制并发、单次超时和可重试错误？
2. 调用者取消时，如何释放并发名额且不把取消当作成功或普通重试？
3. 如何不用真实网络和长时间 sleep 验证边界？

**回答要点**：练习接口可设为 `execute_read(call, *, timeout_s, max_attempts)`，执行器持有并发限制，明确 `max_attempts` 含首次；只允许瞬时错误重试，保留取消传播，用上下文管理确保资源释放。时钟、退避和可控函数可注入；它是新增练习题，不是对仓库已有公共 API 的描述，也不适用于未经设计的写请求。

**项目依据**：[E08](#e08) 重试策略；[E09](#e09) 模型调用；[E22](#e22) 异步资源。

### Q40｜只有两周准备面试，你优先补什么？上线前又必须补什么？

**优先级：P0｜目标等级：L4**

**递进追问**

1. 真实模型全链路、更多框架、多 Agent、性能压测，如何排序？
2. 做内部只读试点与开启业务写入，门槛为什么不同？
3. 哪些失败应阻止发布，哪些可以带着明确限制进入小范围试点？

**回答要点**：面试优先建立准确叙述、完整验收、真实链路与指标证据；再补自己不理解的异步/事务和故障恢复。试点前必须解决可信身份和适用数据权限，写入前还要完成结果未知恢复、版本变化和审计验收。扩规模后再处理事件共享和压测；时间不足就保留明确只读范围，不能将测试替身包装成上线能力。

**项目依据**：[E01](#e01) 边界；[E24](#e24) 身份/数据库；[E26](#e26) 评测。

<a id="resume-map"></a>
## 十一、简历声明—证据—缺口—建议表述

### 11.1 Agent 职责与技能覆盖

以下是当前仓库能够支持的保守表述，工作经历和个人贡献仍需结合真实情况确认。

| 简历职责/技能 | 本地证据 | 仍需补证据或限定 | 当前建议表述 | 对应问题 |
| --- | --- | --- | --- | --- |
| 单主 Agent + 多业务 Skill，覆盖查询、跟踪、问答、诊断、复核、报告 | 意图目录、四个业务 Skill、五类返回结果 [E02](#e02) [E03](#e03) | 未定位到独立通用报告生成 Skill；不要将结构化诊断输出扩大成任意业务报告能力 | 构建统一自然语言入口，将状态、诊断、规范问答和复核草稿分发到受约束流程 | Q04、Q06 |
| 三级上下文、模糊指代与补参 | PageContext、数据库 Session、来源合并、澄清 [E04](#e04) [E05](#e05) | 原文存在性不等于完整语义解析；并发对话还需压力反例 | 实现页面提示、持久化会话指代与执行快照，结合来源优先级和确定性澄清 | Q07～Q10 |
| 标准化 Tool、权限透传、重试、降级、去重 | BaseTool、Client、Registry、Retry、账本 [E07](#e07) [E08](#e08) | 演示身份；去重是 Run 内进程账本；降级必须按组件说明 | 封装业务 Tool，校验输入/输出并分类错误，对只读瞬时故障有限重试 | Q11～Q14 |
| RAG、元数据过滤、Rerank、引用溯源 | Loader、Embedding、双路检索、过滤、RRF、引用 [E11](#e11)～[E15](#e15) | 真实 Embedding/Rerank 效果、声明级支持与注入防护需验证 | 实现版本与权限约束下的混合检索及来源可追溯回答流程 | Q15～Q20 |
| Agent + Workflow 混合执行 | 动态图、确定性状态流程、规范问答图 [E03](#e03) [E17](#e17) | 动态路径不等于模型自由裁定根因；框架不自动提供重启恢复 | 由模型选择受限只读动作，确定性节点控制执行与结果边界 | Q21～Q24 |
| 跨系统根因、依据、建议与结构化输出 | 规则、信息缺口、受保护诊断结构 [E18](#e18) | 固定组合覆盖不证明开放式根因发现 | 基于业务事实识别已支持的阻塞阶段，输出结构化依据和建议 | Q04、Q21、Q23 |
| 人工修改、确认与安全回写 | Approval、CAS、Java 版本和幂等 [E19](#e19)～[E21](#e21) | 结果未知恢复、规范更新、真实身份；返工仅坐标系类型 | 实现独立授权、确认前事实校验及幂等写回 | Q25～Q28 |
| Run/Step、SSE、历史复盘、回归对比 | 事件、历史、逐模型 Step、报告比较 [E23](#e23) [E25](#e25) [E26](#e26) | SSE 是运行事件；短期内存回放；版本记录不等于确定性重放 | 记录运行步骤与组件版本，推送执行状态，支持历史查询和离线报告差异比较 | Q30～Q32、Q37 |
| Python/FastAPI/Pydantic/asyncio/httpx/PostgreSQL/pgvector | 服务、客户端、异步数据库、向量查询 [E07](#e07) [E13](#e13) [E22](#e22) | “使用过”需通过现场编程、并发与事务解释升级为“熟悉” | 具备上述技术栈的项目实践，能说明所负责模块和验证范围 | Q02、Q29、Q39 |

### 11.2 六项量化成果逐项核查

| 简历数字 | 当前可找到的证据 | 缺失的证明 | 未补齐前的建议表述 |
| --- | --- | --- | --- |
| 核查/定位由约 3 分钟到 30 秒内 | 诊断链路与 Run 耗时字段；不等于业务效率实验 | 同任务人工/辅助记录、正确性、失败、计时端点和样本数 | 实现跨系统状态与阻塞证据聚合，效率收益待实测 |
| 意图 90%+；关键参数提取与澄清补全 95%+ | 60 条路由数据、分类指标、混淆矩阵 | 真实模型预测、版本、独立留出样本；提取/补全/澄清分开定义 | 建立包含指代、缺参、冲突等类别的路由评测集与回归框架 |
| Tool 首次校验 88%+；最终成功 97%+ | Tool 契约测试、Outcome 公式与重试实现 | 模型真实参数样本、实际执行观测、失败分母、纠错来源 | 实现参数校验、有限重试和重复调用检测，真实调用质量待采集 |
| 50 条 RAG：Hit@5 76%→88%；无关率 30%→18% | 50 条问题、四策略评测、相关性与指标代码 | 真实向量/重排排名、相同语料与条件的对照、逐题变化 | 建立四策略检索评测，包含命中、首相关排序和噪声指标 |
| 复核整理平均时间降低约 50% | 草稿生成、人工修改及回写闭环 | 同等质量草稿的配对计时、修改次数、完成/失败数据 | 实现任务事实与规范依据辅助的结构化复核草稿及人工审核 |
| 24 次异常中 23 次定位；排查中位数 9→3 分钟 | 24 类固定场景、错误定位和人工计时聚合接口 | 场景语义分类、实际演练记录、适用定位分母、人工计时 | 建立固定异常矩阵与运行步骤定位机制，排查效率待独立演练 |

这六项均**不能由本次静态核查确认达到**。它们可以成为实验目标，但补强目标是测得可信结果，不是调整样本让结果刚好符合简历。若实际效果更低，保留真实数字并说明改进过程，通常比无法解释的高分更有说服力。

工作经历还提到“AI Workflow 平台建设”。本仓库中的固定 Workflow 与 LangGraph 图，不足以证明另一个可配置平台的建设经历；若保留该描述，需要独立说明平台范围、本人贡献和可展示证据。数据产线和卫星服务两个前端项目的规模、性能及上传指标，也不能由本仓库替代证明。

### 11.3 推荐的两分钟项目介绍骨架

> 我以遥感订单的生产、质检、复核和交付为背景，实现了一个 Agent 后端项目。核心问题是用户询问订单为什么没交付时，系统需要跨业务接口取证，并把诊断建议与实际写入分开。
>
> 系统由 Vue 页面、Python Agent 服务和 Java 业务服务组成。页面提供上下文，Python 负责路由、受限工具编排、规范检索和运行记录，Java 管业务事实与最终写入。状态查询用确定性流程，复杂诊断让模型选择只读工具，最终依据规则和取回的事实生成结构化结果。
>
> 我重点准备讲清的机制是：参数来源与澄清、规范版本过滤、人工确认后的并发和幂等。当前项目有相应实现与测试，真实模型全链路、量化收益和崩溃恢复仍需补验证；我会按实际完成情况介绍，不把框架测试当模型效果。

这是一份组织方式，不应照背。把“我重点准备讲清”替换为你已经能独立讲解并验证的内容；若后续完成真实实验，在最后补一条最有证据的结果即可。

<a id="backlog"></a>
## 十二、按依赖排序的补强任务

### 12.1 任务与验收产物

下表都是**后续任务建议，本次未实施**。优先级针对求职准备；认证、授权与写入恢复是进入真实业务环境的硬门槛，不能因排在后面就带缺口上线。

| 编号/优先级 | 补强任务 | 依赖 | 可验收产物与完成条件 |
| --- | --- | --- | --- |
| B0 / P0 | 整理真实能力与目标成果边界，修正介绍文档事实冲突 | 无 | 一页声明清单；能正确区分数据库 Session 与内存 SSE、状态流与 Token 流、动态取证与规则诊断 |
| B1 / P0 | 重新运行项目门禁，根据实际失败修复，不沿用旧统计 | B0 | 保存本次 `make test`、`make quality`、`make eval-all` 的准确结果与环境；失败就记录原因；全绿仍只说明对应验收范围 |
| B2 / P0 | 贯通真实 Provider：模型适配与 Embedding 入库，再走完整业务链 | B1；可用凭据 | Router、Action、Rerank、规范回答、Review 各有真实记录；知识索引 READY；规范回答可对原文；两次授权各只有一次副作用；未覆盖项显式列出 |
| B3 / P0 | 从真实执行生成评测 Subject/Outcome，做指标来源核对 | B2 | 一条观测能追到实际 Run/Step/调用账本；完整报告带数据/组件版本、Provider 类型、分子分母；受控报告不能冒充真实结果 |
| B4 / P0 | 完成路由与 RAG 对照评测，补独立难例 | B3 | 路由逐类别结果；RAG 同语料四策略结果、变化样本、实际返回数；参数阈值在开发集调，留出集只验收 |
| B5 / P0 | 做业务效率与故障定位演练 | B2、B3 | 配对计时、质量检查、失败样本和参与者说明；异常矩阵区分失败与保护；数据不足时不输出收益比例 |
| B6 / P0 | 补 Approval 执行结果未知的恢复路径 | B1；先写恢复契约 | Java 成功后中断 Python 的故障用例可恢复，原幂等键复用，业务只写一次；未知结果不被当成未执行 |
| B7 / P0（上线前） | 接可信身份、资源授权与数据库最小权限；定义规范换版授权策略 | B1；明确部署边界 | 伪造身份、跨用户资源、Agent 账号越权业务表均被拒绝；旧规范草稿按明确策略重新审查；不能只校验 Header 格式 |
| B8 / P1 | 补异步负载与跨实例事件测试 | B1；跨实例时需 B7 | 可控慢依赖下连接/并发/取消行为稳定；数据库会话竞争有结论；跨实例事件、重连和最终结果查询有验收 |
| B9 / P1 | 按追问链完成模拟面试与需求变更演练 | B0～B5，核心深挖结合 B6 | 能讲两分钟主线、定位十个关键符号、独立完成 Q39；不会将未完成的补强说成已有能力 |

建议依赖顺序：`B0 → B1 → B2 → B3 → B4/B5 → B9`。B6 与 B7 是写入和上线安全工作；B8 是规模化工作。不要为了赶数字跳过 B3 的观测来源核对。

### 12.2 三项现场自测

1. **十分钟代码定位**：从统一消息入口追到 ORDER-003 诊断结果，指出两处模型无法绕过的门禁，以及一处尚未覆盖的生产边界。
2. **十五分钟故障分析**：解释 Java 已成功、Python 未落终态时的用户体验、现有保障和恢复设计；不能用“加重试”结束回答。
3. **二十分钟实验复核**：对一份评测报告说清被测对象、数据版本、分母和失败样本，并指出哪些数字不能证明业务收益。

<a id="evidence"></a>
## 十三、源码与测试索引

以下路径用于定位，测试是否实际运行以当前记录为准。

<a id="e01"></a>
- **E01｜资料来源与历史状态**：[README.md](/Users/gao/Desktop/productline-agent/README.md:1)、[docs/STATUS.md](/Users/gao/Desktop/productline-agent/docs/STATUS.md:1)、[doc/plan.md](/Users/gao/Desktop/productline-agent/doc/plan.md:1)
<a id="e02"></a>
- **E02｜统一消息入口、分发与澄清续接**：[agent-service/app/api/agent_messages.py](/Users/gao/Desktop/productline-agent/agent-service/app/api/agent_messages.py:1)、[agent-service/app/services/agent_messages.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/agent_messages.py:260)、[agent-service/tests/test_agent_messages.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_agent_messages.py:1)
<a id="e03"></a>
- **E03｜业务 Skill、确定性状态查询与生产装配**：[agent-service/app/routing/intent_catalog.py](/Users/gao/Desktop/productline-agent/agent-service/app/routing/intent_catalog.py:1)、[agent-service/app/workflows/order_status.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/order_status.py:12)、[agent-service/app/services/production_agent_skills.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/production_agent_skills.py:86)
<a id="e04"></a>
- **E04｜数据库 Session 与最小上下文**：[agent-service/app/services/session_context.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/session_context.py:75)、[agent-service/app/models/agent_runtime.py](/Users/gao/Desktop/productline-agent/agent-service/app/models/agent_runtime.py:90)、[agent-service/tests/test_session_context.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_session_context.py:1)
<a id="e05"></a>
- **E05｜实体来源、优先级与澄清门禁**：[agent-service/app/routing/entity_merge.py](/Users/gao/Desktop/productline-agent/agent-service/app/routing/entity_merge.py:23)、[agent-service/app/routing/decision.py](/Users/gao/Desktop/productline-agent/agent-service/app/routing/decision.py:30)、[agent-service/tests/test_entity_merge.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_entity_merge.py:1)
<a id="e06"></a>
- **E06｜路由 Prompt、结构化解析与实体证据**：[agent-service/app/routing/prompt.py](/Users/gao/Desktop/productline-agent/agent-service/app/routing/prompt.py:1)、[agent-service/app/services/intent_router.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/intent_router.py:1)、[agent-service/tests/test_intent_router_prompt.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_intent_router_prompt.py:1)
<a id="e07"></a>
- **E07｜Tool 协议与业务 HTTP 边界**：[agent-service/app/tools/base.py](/Users/gao/Desktop/productline-agent/agent-service/app/tools/base.py:1)、[agent-service/app/tools/registry.py](/Users/gao/Desktop/productline-agent/agent-service/app/tools/registry.py:1)、[agent-service/app/clients/business.py](/Users/gao/Desktop/productline-agent/agent-service/app/clients/business.py:44)
<a id="e08"></a>
- **E08｜有限重试与 Run 内调用账本**：[agent-service/app/tools/retry.py](/Users/gao/Desktop/productline-agent/agent-service/app/tools/retry.py:20)、[agent-service/app/tools/deduplication.py](/Users/gao/Desktop/productline-agent/agent-service/app/tools/deduplication.py:16)、[agent-service/tests/test_retry_policy.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_retry_policy.py:1)
<a id="e09"></a>
- **E09｜公共模型 Client 与配置能力查询**：[agent-service/app/clients/model.py](/Users/gao/Desktop/productline-agent/agent-service/app/clients/model.py:132)、[agent-service/app/services/model_capabilities.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/model_capabilities.py:7)、[agent-service/tests/test_model_client.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_model_client.py:1)
<a id="e10"></a>
- **E10｜五类结构化模型适配器**：[agent-service/app/model_adapters.py](/Users/gao/Desktop/productline-agent/agent-service/app/model_adapters.py:1)、[agent-service/tests/test_model_adapters.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_model_adapters.py:379)
<a id="e11"></a>
- **E11｜文档加载、确定性分块与稳定身份**：[agent-service/app/knowledge/chunking.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/chunking.py:34)、[agent-service/app/knowledge/loaders.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/loaders.py:1)、[agent-service/tests/knowledge/test_document_chunking.py](/Users/gao/Desktop/productline-agent/agent-service/tests/knowledge/test_document_chunking.py:1)
<a id="e12"></a>
- **E12｜Embedding、索引身份与全量入库**：[agent-service/app/knowledge/embeddings.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/embeddings.py:115)、[agent-service/app/services/knowledge_ingestion.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/knowledge_ingestion.py:64)、[agent-service/app/services/knowledge_index_capabilities.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/knowledge_index_capabilities.py:1)
<a id="e13"></a>
- **E13｜中文预处理、向量查询与公共过滤**：[agent-service/app/knowledge/search.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/search.py:60)、[agent-service/app/repositories/knowledge_search.py](/Users/gao/Desktop/productline-agent/agent-service/app/repositories/knowledge_search.py:27)、[agent-service/tests/knowledge/test_knowledge_search.py](/Users/gao/Desktop/productline-agent/agent-service/tests/knowledge/test_knowledge_search.py:1)
<a id="e14"></a>
- **E14｜RRF、去重合并与 Rerank 降级**：[agent-service/app/knowledge/hybrid.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/hybrid.py:55)、[agent-service/app/knowledge/reranking.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/reranking.py:107)、[agent-service/tests/knowledge/test_reranking.py](/Users/gao/Desktop/productline-agent/agent-service/tests/knowledge/test_reranking.py:1)
<a id="e15"></a>
- **E15｜规范问答、证据不足与引用**：[agent-service/app/workflows/specification_qa.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/specification_qa.py:1)、[agent-service/app/knowledge/citations.py](/Users/gao/Desktop/productline-agent/agent-service/app/knowledge/citations.py:1)、[agent-service/tests/knowledge/test_specification_qa_workflow.py](/Users/gao/Desktop/productline-agent/agent-service/tests/knowledge/test_specification_qa_workflow.py:272)
<a id="e16"></a>
- **E16｜异常矩阵与写入安全反例**：[Makefile](/Users/gao/Desktop/productline-agent/Makefile:106)、[agent-service/tests/test_approval_security.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_approval_security.py:386)、[agent-service/tests/knowledge/test_specification_qa_workflow.py](/Users/gao/Desktop/productline-agent/agent-service/tests/knowledge/test_specification_qa_workflow.py:223)
<a id="e17"></a>
- **E17｜动态动作图、预算与预设路径测试**：[agent-service/app/workflows/dynamic_diagnosis.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/dynamic_diagnosis.py:61)、[agent-service/app/workflows/action_decision.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/action_decision.py:1)、[agent-service/tests/test_dynamic_diagnosis_paths.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_dynamic_diagnosis_paths.py:417)
<a id="e18"></a>
- **E18｜信息充分度与确定性诊断**：[agent-service/app/workflows/information_gaps.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/information_gaps.py:13)、[agent-service/app/workflows/diagnosis_rules.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/diagnosis_rules.py:1)、[agent-service/app/workflows/diagnosis_generation.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/diagnosis_generation.py:38)
<a id="e19"></a>
- **E19｜Review 草稿、取消与独立返工授权**：[agent-service/app/workflows/review_draft.py](/Users/gao/Desktop/productline-agent/agent-service/app/workflows/review_draft.py:1)、[agent-service/app/services/approval_orchestration.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/approval_orchestration.py:66)、[agent-service/tests/test_review_draft_generation.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_review_draft_generation.py:1)
<a id="e20"></a>
- **E20｜确认刷新、CAS、写回与终态**：[agent-service/app/services/approval_confirmation.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/approval_confirmation.py:271)、[agent-service/app/repositories/approval.py](/Users/gao/Desktop/productline-agent/agent-service/app/repositories/approval.py:41)、[agent-service/app/services/approval_run_lifecycle.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/approval_run_lifecycle.py:1)
<a id="e21"></a>
- **E21｜Java 最终写入、版本与幂等事务**：[business-service/src/main/java/com/productline/business/application/BusinessWriteService.java](/Users/gao/Desktop/productline-agent/business-service/src/main/java/com/productline/business/application/BusinessWriteService.java:44)、[business-service/src/main/java/com/productline/business/domain/repository/IdempotencyRecordRepository.java](/Users/gao/Desktop/productline-agent/business-service/src/main/java/com/productline/business/domain/repository/IdempotencyRecordRepository.java:1)、[business-service/src/test/java/com/productline/business/api/BusinessWriteApiIntegrationTest.java](/Users/gao/Desktop/productline-agent/business-service/src/test/java/com/productline/business/api/BusinessWriteApiIntegrationTest.java:1)
<a id="e22"></a>
- **E22｜异步服务资源与数据库生命周期**：[agent-service/app/main.py](/Users/gao/Desktop/productline-agent/agent-service/app/main.py:55)、[agent-service/app/database.py](/Users/gao/Desktop/productline-agent/agent-service/app/database.py:22)、[agent-service/app/clients/business.py](/Users/gao/Desktop/productline-agent/agent-service/app/clients/business.py:44)
<a id="e23"></a>
- **E23｜进程内 SSE、短期回放与清理**：[agent-service/app/services/run_events.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/run_events.py:171)、[agent-service/app/api/run_events.py](/Users/gao/Desktop/productline-agent/agent-service/app/api/run_events.py:1)、[agent-service/tests/test_run_events.py](/Users/gao/Desktop/productline-agent/agent-service/tests/test_run_events.py:1)
<a id="e24"></a>
- **E24｜身份解析与部署授权边界**：[agent-service/app/api/identity.py](/Users/gao/Desktop/productline-agent/agent-service/app/api/identity.py:8)、[docker-compose.yml](/Users/gao/Desktop/productline-agent/docker-compose.yml:1)、[business-service/src/main/java/com/productline/business/application/BusinessWriteService.java](/Users/gao/Desktop/productline-agent/business-service/src/main/java/com/productline/business/application/BusinessWriteService.java:46)
<a id="e25"></a>
- **E25｜Run/Step、逐次 LLM 观测与历史结果**：[agent-service/app/models/agent_runtime.py](/Users/gao/Desktop/productline-agent/agent-service/app/models/agent_runtime.py:165)、[agent-service/app/services/model_invocation.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/model_invocation.py:1)、[agent-service/app/services/run_history.py](/Users/gao/Desktop/productline-agent/agent-service/app/services/run_history.py:1)
<a id="e26"></a>
- **E26｜评测 Runner、Subject/Outcome 和报告**：[Makefile](/Users/gao/Desktop/productline-agent/Makefile:120)、[agent-service/app/evaluation/suites.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/suites.py:43)、[agent-service/app/evaluation/reporting.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/reporting.py:1)
<a id="e27"></a>
- **E27｜路由数据与领域指标**：[agent-service/evaluation/router_cases.jsonl](/Users/gao/Desktop/productline-agent/agent-service/evaluation/router_cases.jsonl:1)、[agent-service/app/evaluation/router.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/router.py:28)、[agent-service/tests/evaluation/test_router_eval.py](/Users/gao/Desktop/productline-agent/agent-service/tests/evaluation/test_router_eval.py:1)
<a id="e28"></a>
- **E28｜RAG 数据、策略与相关性公式**：[agent-service/evaluation/rag_cases.jsonl](/Users/gao/Desktop/productline-agent/agent-service/evaluation/rag_cases.jsonl:1)、[agent-service/app/evaluation/rag.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/rag.py:278)、[agent-service/tests/evaluation/test_rag_eval.py](/Users/gao/Desktop/productline-agent/agent-service/tests/evaluation/test_rag_eval.py:1)
<a id="e29"></a>
- **E29｜Tool、Agent 与异常定位指标**：[agent-service/app/evaluation/tools.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/tools.py:64)、[agent-service/app/evaluation/agents.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/agents.py:90)、[agent-service/app/evaluation/observability.py](/Users/gao/Desktop/productline-agent/agent-service/app/evaluation/observability.py:80)
<a id="e30"></a>
- **E30｜页面交互、确认卡片与请求隔离**：[web-console/src/components/AgentWorkspaceDrawer.vue](/Users/gao/Desktop/productline-agent/web-console/src/components/AgentWorkspaceDrawer.vue:1)、[web-console/src/components/AgentWorkspaceDrawer.spec.ts](/Users/gao/Desktop/productline-agent/web-console/src/components/AgentWorkspaceDrawer.spec.ts:1)、[web-console/src/components/ReviewApprovalCard.spec.ts](/Users/gao/Desktop/productline-agent/web-console/src/components/ReviewApprovalCard.spec.ts:1)
