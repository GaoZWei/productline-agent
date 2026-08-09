# Agent 面试关注点

本文件只沉淀对 Agent 岗位面试有实际价值、且已由项目实现或验证的内容。它不是开发流水账，也不替代 `doc/record.md`。

## 记录门禁

一次开发至少满足以下一项，才增加面试关注点：

1. 体现 Agent、Tool、Workflow、RAG、上下文、路由、Approval 或评测设计；
2. 体现模型与业务事实、权限、安全或写操作之间的边界；
3. 解决幻觉、可重复性、错误处理、重试、幂等或可观测性问题；
4. 存在可以真实说明的技术取舍、工程难点或故障定位过程；
5. 明确影响后续 Tool 路径、Schema、评测指标或 Agent 结果可靠性。

普通文件调整、无 Agent 关联的配置、常规样板代码和尚未实现的规划不记录。没有面试价值时不创建空条目，也不为了丰富简历强行包装。

每个有效条目说明：

- 为什么对 Agent 面试有价值；
- 需要掌握的原理和设计取舍；
- 可能的面试问题与回答要点；
- 有事实支撑时才给出简历表述；
- 尚未实现、不能在面试中声称已完成的能力。

---

## M0.1 服务职责边界

### 面试价值判断

辅助关注。M0.1 的目录、启动脚本和健康检查本身不是 Agent 简历亮点；真正值得理解的是 Java 业务事实层、Python Agent 编排层和 Web 交互层为什么必须分开。

### 与 Agent 开发的关系

本项目采用以下职责边界：

```text
Web Console：采集页面上下文、展示步骤与引用、承载人工确认
Python Agent Service：Tool 封装、Workflow、Agent 决策、RAG、运行记录
Java Business Service：业务事实、权限、状态校验、一致性和最终写入
```

Python Agent 不直接读取或修改 Java 业务数据库。页面传入的订单、任务和用户信息也
只能作为上下文提示，服务端仍需重新校验。

### 需要掌握的设计取舍

- Java 保持业务规则和数据一致性，避免模型或 Python 编排层绕过业务约束。
- Python 更适合承载模型调用、Tool 协议和动态工作流，但不能成为业务事实来源。
- Web 提供的 `order_id` 不能直接信任，否则“这个订单”可能被错误上下文或越权请求
  解析到不应访问的数据。
- 第一阶段采用垂直业务闭环，而不是提前建设通用 Agent 平台，降低范围和验证难度。

### 可能的面试问题

**为什么不让 Agent 直接查业务数据库？**

回答要点：直接查询会绕开权限、状态语义、审计和兼容层；数据库结构变化还会直接
破坏 Tool。Java API 应提供经过校验的稳定业务事实，Agent 只通过结构化 Tool 使用。

**为什么 Java 和 Python 要拆成两个服务？**

回答要点：Java 承载已有业务能力和强一致性约束，Python 承载模型生态与编排；拆分
不是为了技术栈数量，而是为了明确“事实和写入由谁负责”。

### 简历表述建议

不建议把 M0.1 单独写成简历成果。可以在项目架构说明中表述：

> 设计 Java 业务事实层、Python Agent 编排层与 Web 人工交互层的职责边界，禁止
> Agent 绕过业务 API 直接访问生产数据。

### 不能过度声称

M0.1 完成时三个服务主要是可启动骨架，尚未实现 Python Tool、Workflow、RAG、动态 Agent 或人工确认闭环。

---

## M0.2 领域状态契约与 Agent 事实边界

### 面试价值判断

重要基础。领域实体本身不是 Agent 核心算法，但统一状态契约直接决定 Tool Schema、模型可见事实和后续诊断规则是否可靠。

### 与 Agent 开发的关系

订单诊断需要组合订单、任务、生产步骤、质检问题、复核和交付状态。M0.2 将这些对象及状态统一定义在 Java 业务服务中，使后续 Python Tool 只能消费明确的结构化事实，而不是让模型从自由文本猜测业务状态。

### 需要掌握的设计取舍

- Java Enum、DTO 和数据库 `CHECK` 使用相同的大写状态字符串，避免 Java、Python
  和前端各自维护一套含义不同的状态。
- Entity 负责持久化关系，DTO 负责未来接口契约；后续 API 不应直接序列化 JPA
  懒加载实体。
- `Order` 作为聚合根维护任务和交付关系，关系方法阻止子对象跨订单或跨任务重挂。
- 模型只能归纳事实。例如模型可以根据 `OPEN + PENDING + BLOCKED` 判断质量复核
  阻塞，但不能自行生成不存在的复核结果。

### 可能的面试问题

**领域模型和 Agent Tool 有什么关系？**

回答要点：Tool 的输入输出 Schema 应来源于稳定业务契约。领域状态不统一时，模型
会面对模糊或冲突字段，Prompt 再复杂也无法保证可靠判断。

**为什么不能直接把 JPA Entity 返回给 Tool？**

回答要点：Entity 含持久化和懒加载语义，容易暴露内部结构、产生循环引用或随数据库
重构变化；接口 DTO 才是跨服务稳定边界。

**数据库约束能解决所有 Agent 事实问题吗？**

回答要点：不能。数据库约束可保证枚举、外键和非空等结构正确；跨对象业务组合仍需
Java 服务校验，模型也必须基于多个 Tool 结果做归纳。

### 简历表述建议

这一部分更适合作为 Agent 可靠性设计的支撑，不宜写成普通 CRUD：

> 统一订单、生产、质检、复核与交付状态契约，为 Python Tool 提供结构化事实边界，
> 并通过 DTO、聚合约束和数据库校验降低模型使用歧义数据的风险。

### 不能过度声称

M0.2 尚未提供 Java HTTP 查询接口，也没有完成 Python Tool 调用。当前验证范围是
领域模型、数据库映射和 Repository 查询。

---

## M0.3 确定性业务场景与 Agent 评测基线

### 面试价值判断

核心关注。M0.3 的价值不是“写了初始化 SQL”，而是为后续 Tool 调用、诊断路径和
Agent 回归评测建立可重复的业务事实基线。

### 与 Agent 开发的关系

五组固定订单对应五条不同诊断分支：

| 场景 | 关键事实 | 后续 Agent 预期行为 |
| --- | --- | --- |
| `ORDER-001` | 正常生产 | 不报告异常，说明仍在生产 |
| `ORDER-002` | 生产步骤失败 | 查询进度并定位“影像预处理”失败 |
| `ORDER-003` | 问题 `OPEN`、复核 `PENDING` | 查询质检、复核和交付，定位质量复核阻塞 |
| `ORDER-004` | 问题已处理、复核待完成 | 判断阻塞在复核，而不是重复报告问题未处理 |
| `ORDER-005` | 生产、质检、复核完成 | 判断已满足交付条件 |

这使后续评测可以判断 Agent 是否选择了正确的 Tool 路径、是否遗漏事实、是否补造
业务状态，以及模型或 Prompt 变更后是否发生回归。

### 需要掌握的设计取舍

- 固定数据不用随机值和当前时间，确保模型、Prompt、Tool 或 Workflow 变化前后可用
  相同输入比较。
- `ORDER-003` 是黄金链路：

  ```text
  TASK-003 = COMPLETED
  ISSUE-001 = COORDINATE_SYSTEM + OPEN
  REVIEW-003 = PENDING
  DELIVERY-003 = BLOCKED
  ```

- `ORDER-003` 不预置返工任务，因为后续诊断建议正是“创建返工任务”；提前写入会让
  Agent 建议与业务事实冲突。
- 数据库字段和外键保证结构合法，跨对象状态校验器补充“未完成任务却已交付”等业务
  组合约束。
- 重置通过同一组迁移恢复数据并计算快照，连续执行结果一致，便于回归和问题复现。

### 可能的面试问题

**为什么 Agent 项目需要固定测试数据？**

回答要点：模型输出可能变化，但底层业务事实和预期结论必须确定；否则无法判断错误
来自模型、Prompt、Tool、数据还是环境，也无法进行稳定回归。

**这五个订单和普通测试夹具有什么区别？**

回答要点：它们不仅验证数据库映射，还代表 Agent 的关键决策分支。后续可以基于它们
评估 Tool 选择、事实一致性、根因判断和建议是否匹配业务状态。

**如何降低 Agent 补造业务事实的风险？**

回答要点：业务事实只来自 Java Tool；模型负责路由、归纳和解释；用固定场景验证
输出必须能追溯到 Tool 结果，写操作还需要人工确认和 Java 再校验。

**数据库约束和状态一致性校验为什么都需要？**

回答要点：外键、枚举等单表结构由数据库保证；“存在 OPEN 问题但交付 READY”属于
跨对象语义，需要业务层判定，并在未来写接口提交前执行。

### 简历表述建议

> 为订单诊断 Agent 构建可重复的业务场景与黄金测试链路，覆盖生产失败、质检阻塞、
> 待复核和可交付状态，用于验证 Tool 路径、业务事实一致性和诊断结果回归。

### 不能过度声称

- M0.3 完成时尚未实现 Java 业务查询接口；该限制已在 M0.4 解除。
- 截至 M0.4，尚未实现 Python Tool、Agent E2E 评测、动态路由或准确率指标。
- 状态一致性校验器已经实现并测试，但尚未接入后续业务写接口。

---

## M0.4 Java 查询契约与 Tool 事实接口

### 面试价值判断

核心关注。M0.4 首次把 Java 业务事实变成可被后续 Python Tool 消费的 HTTP 契约，
直接影响 Tool Schema、错误语义、证据可追溯性和 Agent 诊断结果的可靠性。

### 与 Agent 开发的关系

8 个只读端点分别提供订单、任务、进度、质检、复核和交付事实，并保留一个订单总览
端点。Python Agent 仍不能直接读取业务数据库；后续 Tool 只能把这些 Java 响应校验为
结构化 Schema，再交给 Workflow 或模型归纳。

M0.4 已验证 `ORDER-003` 可以经 HTTP 得到：

```text
TASK-003 = COMPLETED
ISSUE-001 = COORDINATE_SYSTEM + OPEN
REVIEW-003 = PENDING
DELIVERY-003 = BLOCKED
```

### 需要掌握的设计取舍

- 不直接序列化 JPA Entity，而是在只读事务中映射为 DTO/响应 Schema，避免懒加载、
  循环引用和数据库重构直接污染 Tool 契约。
- 父资源不存在返回 `404`；父资源存在但没有任务、问题或复核记录返回 `200 + []`。
  这一区分让 Tool 能判断“业务上暂无数据”和“输入 ID 错误/资源不存在”。
- 步骤按业务序号排序，其余集合按稳定 ID 排序。确定性顺序便于 Schema 测试、结果
  对比和 Agent 回归评测，减少无业务意义的输出波动。
- 质检接口由 Java 执行 `OPEN`/`CLOSED` 枚举过滤，模型无需从描述文本猜测状态。
- 保留聚合接口用于页面和排障，但 Agent 第一版计划使用多个细粒度 Tool。这样能记录
  实际调用路径、定位单个上游失败，并让诊断证据对应具体事实源。
- 交付和复核返回记录数组，不凭没有时间字段的数据模型猜测“最新一条”。如果未来
  业务确认唯一当前状态，应先补数据库约束或明确时间/版本规则，再收敛 Schema。

### 可能的面试问题

**为什么已经有订单总览接口，还要设计多个 Tool？**

回答要点：总览接口适合页面首屏和排障，但一个大 Tool 会隐藏 Agent 的决策路径，任一
子查询失败也更难降级。细粒度 Tool 能按意图选择事实、记录步骤、区分失败来源，并对
不同订单评测 Tool 路径；是否合并应结合延迟和可靠性指标，而不是固定追求越细越好。

**空数组和 404 对 Agent 有什么实际影响？**

回答要点：空数组是可靠业务事实，例如任务存在但没有复核；404 表示调用前提不成立。
如果混为一谈，Workflow 可能错误重试、让模型补造记录，或把数据缺失误报为业务正常。

**如何保证 Java 响应适合作为 Tool Schema？**

回答要点：返回显式 DTO 和稳定枚举，集合有确定顺序，正常、空结果、非法过滤和 404
均有真实 HTTP 集成测试；下一步 Python 侧还必须做响应 Schema 校验，不能信任任意 JSON。

**聚合查询是否存在性能问题？**

回答要点：当前实现按任务查询步骤、问题和复核，固定演示数据下简单且可验证；任务量
增大时可能形成多次查询。应先增加 SQL/耗时观测，再按真实瓶颈改为批量查询或投影，
同时保持外部响应契约不变。

### 简历表述建议

> 设计并实现面向 Agent Tool 的 Java 业务事实查询契约，覆盖订单、生产、质检、复核
> 与交付 8 个只读接口；通过明确空结果/404 语义、确定性排序和黄金链路契约测试，
> 降低模型补造事实并支撑后续 Tool 路径评测。

### 不能过度声称

- Java HTTP 事实接口和 Python 通用 HTTP Client 已完成；正式端点 data Schema、具体 Tool 和
  Agent 实际调用尚未实现。
- M0.4 完成时尚未实现权限校验、统一错误响应、Trace ID、超时重试或故障模拟；其中
  Java 统一错误响应和 Trace ID 已在 M0.6 完成，Java 故障模拟已在 M0.7 完成，Python Tool
  错误映射和只读有限重试已在 M1.3～M1.6 完成。
- 聚合接口已通过固定规模集成测试，但没有生产规模性能数据，不能声称已解决 N+1 或
  达到某项吞吐/延迟指标。
- 尚未实现动态 Tool 路由和 Agent E2E 评测，不能把接口测试等同于 Agent 准确率。

---

## M0.5 Agent 写操作的业务安全边界

### 面试价值判断

核心关注。M0.5 的重点不是两个 POST 接口本身，而是证明未来 Agent 即使产生了错误、
重复或过期的写请求，Java 事实层仍能通过权限、状态、幂等、并发和审计边界阻止不可靠
结果落库。

### 与 Agent 开发的关系

未来 Approval Workflow 只有在用户确认后才会调用 Java，但“已经确认”不代表请求一定
安全：确认后可能重复点击、网络超时重试，业务状态也可能在草稿生成后被其他用户修改。
因此 Java 写接口重新查询任务和问题，并独立校验：

```text
用户/角色
→ Idempotency-Key 与请求指纹
→ 任务和问题归属/状态
→ expectedVersion
→ 单事务业务写入、版本递增、幂等结果和操作日志
```

这形成两层边界：Agent/Workflow 负责“是否获得人工确认”，Java 负责“此刻是否仍允许
写、是否已经写过、并发状态是否仍一致”。

### 需要掌握的设计取舍

- 幂等和乐观并发解决不同问题：幂等键识别同一业务动作的重试，`expectedVersion`
  阻止两个不同动作基于同一旧状态同时成功；两者不能互相替代。
- 幂等记录保存操作类型、请求哈希、操作者和首次结果引用。同键同请求直接重放原结果；
  同键换内容返回 `409`，避免调用方误复用键。
- 版本递增使用 `UPDATE ... WHERE version = expectedVersion`。更新行数为 0 就说明读取后
  状态已变化，可在事务内稳定返回 `409`；这比把 JPA 强制乐观锁推迟到提交阶段更容易
  控制错误语义。
- “同一问题不能重复创建活动返工”是业务防重；`Idempotency-Key` 是请求防重。即使调用
  方错误地换了新幂等键，业务规则仍会拒绝第二个活动返工。
- 操作日志与业务写入处于同一事务，并保存关键前后状态、操作者和幂等键哈希；既能为
  Agent 写路径排障，也避免日志成功但业务回滚或业务成功却无审计记录。
- 复核接口只追加历史记录，不擅自联动关闭问题或改变交付状态。未明确的状态机不能由
  Agent 或接口实现自行推断。

### 可能的面试问题

**有了 Approval，为什么 Java 还要再次校验？**

回答要点：Approval 证明用户确认了某个草稿，但不能证明提交时权限和业务状态仍未变化。
Java 是最终事实和写入边界，必须重新读取资源、校验权限/归属/状态/版本，并保证事务一致性。

**幂等键和 version 有什么区别？**

回答要点：幂等键处理同一请求因重试或重复点击被执行多次；版本号处理不同请求都基于
同一旧快照的并发竞争。本项目测试了同键重放只写一次，也测试了两个不同幂等键携带同一
版本时只有一个成功。

**为什么不用纯 JPA 的 `OPTIMISTIC_FORCE_INCREMENT`？**

回答要点：实际测试发现版本更新延迟到事务提交，服务返回时拿到旧版本，并发异常也越过
业务方法变成 `500`。改成条件更新后，更新行数立即表达冲突，可回滚子记录并稳定映射 409。

**如何避免 Agent 写操作无法追责？**

回答要点：不记录模型“声称做了什么”，而由 Java 在成功事务中记录实际操作类型、目标、
操作者、关键前后状态和幂等关联；后续还需用 Trace ID 串联 Agent Run、Tool 调用与业务日志。

### 简历表述建议

> 为 Agent 人工确认后的 Java 回写接口设计双重防护：以幂等请求指纹避免重复执行，
> 以业务版本条件更新拦截过期/并发写入，并在同一事务记录关键前后状态，确保写操作
> 至多执行一次、冲突可识别且结果可追踪。

### 不能过度声称

- 当前只完成 Java 写入底座，尚未实现 Python 写 Tool、Approval Workflow、确认/取消
  流程或“未确认调用次数为 0”的 Agent 安全测试。
- `X-User-Id` 和 `X-User-Role` 是阶段性 Header 上下文，尚未接入 JWT、网关或真实权限
  系统，不能声称完成生产级认证授权。
- M0.5 完成时只稳定 HTTP 状态；统一错误码、错误体和 Trace ID 已在 M0.6 完成。
- 操作日志保存的是本次操作相关的关键字段快照，不是完整事件溯源系统；幂等记录也尚无
  TTL、归档和跨服务全局键治理。
- 复核写入不会自动关闭问题或推进订单/交付状态，不能声称已实现完整业务状态机。

---

## M0.6 Tool 错误控制流与链路标识

### 面试价值判断

核心关注。M0.6 的价值不只是把 Spring 异常变成统一 JSON，而是为后续 Python Tool
建立可机器判定的失败契约：Agent Workflow 可以依据 HTTP 状态、稳定错误码和
`retryable` 决定澄清输入、停止、重新读取状态或进入人工处理，而不是解析易变的错误文案。

### 与 Agent 开发的关系

Java `/api` 端点现在统一返回：

```text
success + code + message + data + trace_id + retryable
```

其中 400、401/403、404、409、500 分别对应参数、权限、资源、业务冲突和系统异常。
Trace ID 在入口校验或生成，并同步到响应 Header、响应体和 Java 日志 MDC。后续 Python
Tool 可以把同一 ID 保存到 Run/Step，用一条标识串联 Agent 决策与 Java 端异常证据。

### 需要掌握的设计取舍

- HTTP 状态表达通用协议语义，稳定 `code` 表达跨服务业务分类。401 和 403 复用
  `PERMISSION_DENIED`，但由 HTTP 状态区分“没有身份”和“身份存在但权限不足”。
- `message` 只用于人类排障，Workflow 不应据此写字符串匹配分支；内部 500 详情只写
  服务日志，响应使用固定安全文案，避免堆栈、SQL 或实现细节进入模型上下文。
- 当前所有通用错误的 `retryable=false` 是保守策略。特别是写请求返回 500 时，客户端
  不知道事务是否已经成功；自动生成新幂等键重试可能重复写入。后续只能对明确识别的
  只读暂态异常开放重试，并设置次数、退避和总耗时上限。
- 409 不是网络失败，而是状态已变化。未来 Tool 应重新查询最新版本并让 Workflow
  重新判断或请求用户确认，不能原请求盲重试。
- 外部 Trace ID 只接受长度受限的安全字符；非法值被替换，避免换行或超长值污染日志。
- 使用 `ResponseBodyAdvice` 集中包装现有成功 DTO，避免逐个改 Controller；代价是未来
  生成 OpenAPI 时仍需显式描述 `ApiResponse<DTO>`，不能只依赖 Java 方法返回类型。

### 可能的面试问题

**统一异常对 Agent 有什么作用，为什么只看 HTTP 状态还不够？**

回答要点：Agent Tool 需要确定性的控制流。HTTP 状态便于基础分类，稳定错误码让不同
接口共享同一处理策略；参数错误应澄清，404 应核对上下文 ID，409 应刷新事实，权限失败
应停止并提示用户。错误文案不稳定，不适合机器分支。

**为什么 500 不直接标记为可重试？**

回答要点：读请求的部分暂态 500 以后可以重试，但通用异常无法证明操作是否安全；尤其
写请求可能已经提交但响应中断。默认不可重试更安全，写入恢复依赖原幂等键和状态查询，
只对明确的读超时/上游暂态异常建立白名单重试。

**Trace ID 和 Agent 的 Run ID 有什么区别？**

回答要点：Run ID 标识一次 Agent 执行，Run 内可能有多个 Tool/HTTP 调用；Trace ID
标识并关联具体请求链路。后续应在 Run/Step 中同时保存二者，支持从 Agent 结果定位到
某一次 Java 调用，而不是把它们混成一个概念。

**为什么 401 和 403 使用同一个业务错误码？**

回答要点：项目规划的跨服务错误分类只有 `PERMISSION_DENIED`，HTTP 仍精确保留认证缺失
与授权不足语义。这减少 Python Tool 的错误枚举数量，同时不丢失协议层差异；若未来确实
需要不同恢复流程，再以兼容方式扩展业务码。

### 简历表述建议

> 设计 Java 业务 Tool 的统一响应与错误控制流，稳定映射参数、权限、资源、并发冲突和
> 系统异常，并通过安全 Trace ID 关联响应与服务日志；采用保守重试语义，避免 Agent 对
> 结果未知的写请求盲目重放。

### 不能过度声称

- Python HTTP Client 和成功信封 Schema 已在 M1.2 实现；Pydantic 错误 Schema、ToolResult
  收敛和只读有限重试已在 M1.3～M1.6 实现。
- Trace ID 已进入 Java Header、响应体和 MDC，但尚未接入 Agent Run/Step、SSE 或跨服务
  可观测平台，不能声称已完成端到端链路追踪。
- 401/403 仍基于阶段性的用户/角色 Header，没有 JWT、网关身份或生产级 RBAC。
- Java 侧故障模拟已在 M0.7 完成，Python Tool 错误映射和有限重试已在 M1.3～M1.6 完成；
  仍没有 Workflow 降级或生产恢复率数据，不能把开发测试描述为 Agent 已经全面恢复。
- 统一 500 已验证隐藏详情，但当前不是完整的错误治理平台，也没有按具体基础设施异常
  建立可重试白名单。

---

## M0.7 Agent Tool 故障评测夹具

### 面试价值判断

核心关注。M0.7 为后续 Tool Client 提供可重复的失败输入，使超时、上游 500、权限失败
和响应 Schema 不合法都能自动测试。Agent 工程中“正常调用成功”通常不难，真正决定
可靠性的是失败如何分类、是否安全重试、是否保留 Trace，以及失败后 Workflow 是否停止
或降级。

### 与 Agent 开发的关系

只读 Java API 现在可以通过受控 Header 模拟：

```text
响应变慢
客户端等待超时
服务端 500
HTTP 200 但缺少必需字段
权限 403
```

这些场景分别对应后续 M1 的耗时预算、`TOOL_TIMEOUT`、`UPSTREAM_ERROR`、
`RESPONSE_VALIDATION_ERROR` 和 `PERMISSION_DENIED`。固定 Header 和固定行为让错误映射
测试不依赖随机网络抖动或临时关闭真实服务。

### 需要掌握的设计取舍

- HTTP 200 不代表 Tool 成功。必须先解析统一信封，再用 Pydantic 校验 `data`；缺字段
  应成为响应校验错误，不能把空值交给模型补造事实。
- 延迟和超时是不同测试：延迟用于验证耗时观测和预算，超时由客户端配置决定。本项目
  用服务端等待 300ms、客户端 80ms 的真实 HTTP 测试证明超时发生在调用边界。
- 故障开关默认关闭，Docker 本地开发显式开启；仅允许 GET `/api/**`，写请求忽略模拟
  Header，避免故障演练改变业务数据或绕过 M0.5 幂等/权限边界。
- 模拟值和延迟范围严格校验，配置还有 60 秒硬上限，避免一个错误 Header 无限占用线程。
- 500 和 403 继续走 M0.6 统一异常与 Trace；非法响应则刻意绕过信封包装，才能验证
  Python Client 不会盲信 Java 返回的任意 JSON。
- 使用阻塞 Servlet 线程是开发夹具的最小实现，真实且容易触发客户端超时，但不适合
  压测或生产混沌实验；更大规模演练应使用代理层、网络故障工具或隔离的测试环境。

### 可能的面试问题

**为什么要专门实现故障模拟，Mock HTTP Client 不够吗？**

回答要点：单元 Mock 能覆盖分支，但无法证明真实序列化、Trace Header、HTTP 超时和
Spring 异常链路正确。Java 端的确定性故障夹具可用于跨服务契约测试；两者应互补，不是
用端到端测试替代全部单元测试。

**为什么要模拟“200 但字段缺失”？**

回答要点：上游协议漂移、灰度版本不一致或部分序列化失败时，HTTP 仍可能成功。如果
Tool 只看状态码，模型会收到不完整事实并可能幻觉补齐。严格 Schema 校验必须把它转为
可观测的 `RESPONSE_VALIDATION_ERROR`。

**超时后应该自动重试吗？**

回答要点：只能对幂等读操作、明确暂态故障和剩余总预算内有限重试；写操作结果可能未知，
必须依赖幂等键和状态查询。M0.7 只提供故障输入，真正的次数、退避和总预算要在 M1 Tool
Client 中实现并评测。

**如何防止故障模拟成为生产后门？**

回答要点：默认关闭、环境显式开启、只作用于 GET、参数限幅、记录模拟类型，并在部署
检查中保证生产配置关闭。若系统安全等级更高，应把模拟组件放入独立 profile/构建产物
或由测试代理承担。

### 简历表述建议

> 为 Agent Tool 构建确定性故障评测夹具，覆盖延迟/超时、统一 500、权限拒绝和 HTTP
> 200 下的 Schema 缺失；通过默认关闭、仅只读注入、参数限幅和 Trace 透传保证演练可控，
> 为后续 Tool 错误分类、重试和降级测试提供真实 HTTP 基线。

### 不能过度声称

- Java 故障提供端、Python HTTP Client、ToolResult 错误映射、只读重试次数和退避已完成；
  熔断和 Workflow 降级尚未实现。
- M1.2 已验证 httpx 分项超时配置和 MockTransport `ReadTimeout` 传播，但尚未通过该 Client
  对真实 Java timeout 故障完成错误码映射。
- 没有生产混沌工程平台、网络分区、连接池耗尽或容量测试，不能声称完成全面故障演练。
- 延迟使用阻塞线程，适合固定测试但不能代表响应式、异步或生产级延迟注入方案。
- 模拟权限失败不等同于真实认证授权测试；真实身份仍未接入。

---

## M1.1 Agent 自有状态边界与最小可观测性

### 面试价值判断

辅助关注。uv、FastAPI 和测试工具配置本身不值得包装成 Agent 简历亮点；真正有价值的
是从工程入口明确“业务事实”和“Agent 运行状态”两类数据的所有权，并为后续 Tool Step
建立可贯穿 HTTP 请求的 Trace 基础。

### 与 Agent 开发的关系

Python 的 SQLAlchemy `Base` 只允许承载后续 Run、Step、Approval 和 RAG 元数据，不为
Java 的订单、任务、质检、复核或交付表建立 ORM 映射。业务事实仍必须通过后续 Java
HTTP Tool 获取。FastAPI 中间件为每个请求接受或生成安全 Trace ID，并输出结构化请求
日志，为以后把一次 Tool HTTP 调用关联到 Run/Step 留出稳定字段。

### 需要掌握的设计取舍

- SQLAlchemy Engine 在应用启动时创建，但不会立刻连接数据库；因此存活探针可以证明
  进程可服务，却不能证明数据库已经就绪。后续需要单独定义 readiness，而不是让健康
  检查含义模糊。
- 外部 Trace ID 只接受长度和字符受限的值，非法输入会替换，避免日志注入；Trace ID
  与未来 Run ID、Step ID 仍是不同维度。
- JSON 日志固定输出时间、级别、logger、消息和 trace；请求日志再增加方法、路径、状态
  和耗时。日志不输出数据库 URL、Token、请求正文或任意对象状态。
- 当前本地 Compose 为降低 M1.1 环境复杂度，Python 与 Java 共用一个 PostgreSQL 实例
  和开发角色；代码通过不定义业务 ORM、独立 Alembic 版本表保持边界，但权限层尚未强制。
  生产前应使用独立数据库/Schema 与最小权限角色。

### 可能的面试问题

**为什么 Agent 需要自己的数据库，又为什么不能映射 Java 业务表？**

回答要点：Agent 需要保存运行步骤、上下文、引用和审批草稿，但这些是编排状态，不是
订单事实。直接映射业务表会绕过 Java 权限、状态校验和审计，并把数据库结构耦合进 Tool；
两类数据应分别由 Python 和 Java 负责。

**Trace ID、Run ID 和 Step ID 应该如何配合？**

回答要点：Run ID 标识一次 Agent 执行，Step ID 标识其中一个节点或 Tool 调用，Trace ID
关联一次具体 HTTP 链路。一个 Run 可以包含多个 Step 和多个 Trace，持久化时应同时保存，
才能从最终回答定位到某个上游请求。

**为什么 `/health` 不直接查询数据库？**

回答要点：存活和就绪是不同语义。进程存活不应因暂时数据库故障被平台反复重启；需要
数据库的流量应由 readiness 控制。M1.1 只实现 liveness，readiness 尚未实现。

### 简历表述建议

不建议把 M1.1 单独作为成果。可在后续 Run/Step 和 Tool 链路完成后作为架构支撑说明：

> 区分 Java 业务事实与 Python Agent 运行状态的持久化边界，并以安全 Trace ID 和结构化
> 请求日志为 Tool 调用与 Run/Step 关联提供可观测性基础。

### 不能过度声称

- 当前已有 Java HTTP Client，但没有 Tool、Workflow、模型调用或 Agent 诊断。
- `Base` 只是 Agent 自有元数据入口，尚未实现 Run、Step、Approval 或 RAG 表。
- Trace 已由 Python Client 透传到真实 Java 查询链路，但尚未进入 Tool/Run/Step，也没有
  端到端 Trace/Run 查询。
- 本地开发尚未实现数据库角色级隔离，不能声称已经完成生产级数据权限边界。
- `/health` 是存活探针，没有数据库 readiness、指标平台或分布式追踪。

---

## M1.2 Java HTTP Client 事实门禁与跨服务上下文

### 面试价值判断

核心关注。M1.2 的价值不在“会用 httpx 发请求”，而在于把 Java 业务事实进入 Tool 和模型
之前的可靠性边界落实为强类型响应门禁、身份与 Trace 透传、写请求幂等约束和明确的错误/
重试停止线。

### 与 Agent 开发的关系

当前调用链已经可以真实执行：

```text
Python ContextVar Trace
→ 共享 BusinessHttpClient
→ Java /api/**
→ Java 六字段成功信封
→ Pydantic 信封校验
→ 端点 data Schema 校验
→ Header/Body Trace 一致性校验
→ 强类型 BusinessResponse
```

真实容器验收读取了 `ORDER-003=QUALITY_CHECKING` 并保持 `trace-m12-real`，证明 Python 已经
通过 Java API 获取业务事实，而不是直接读取 Java 数据库。非法 JSON、缺少 `data`、端点字段
缺失和 Trace 不一致都会在进入 Tool/模型前被拒绝。

简略描述：
1. FastAPI启动时创建一个共享Java Client。
2. Tool未来调用Client，Client补齐身份和Trace。
3. Java查询数据库并把DTO包装成统一响应。
4. Python先校验信封，再校验业务data，最后才交给Tool/Agent。

### 需要掌握的设计取舍

- FastAPI lifespan 只创建一个 `httpx.AsyncClient`，复用连接池，并在应用关闭时显式释放；
  不能让每次 Tool 调用都新建 Client。
- connect/read/write/pool timeout 分开配置。连接失败、上游处理慢、发送阻塞和连接池耗尽
  是不同故障，后续是否重试和如何观测也不同。
- 统一信封和端点 data 分两层校验。信封保证 `success/code/message/data/trace_id/retryable`
  完整，调用方模型保证订单或任务字段完整，避免 HTTP 200 下的不完整事实诱发模型幻觉。
- `BusinessIdentity` 透传用户、角色和可选 Bearer Token，Token 使用 `SecretStr` 避免对象
  调试输出泄露；Java 仍必须重新校验权限，Python Header 不是权限事实。
- POST 强制传递幂等键，但 Client 不自动重试。超时或 500 时写入结果可能未知，必须依赖
  Java 幂等、版本校验和后续状态查询，不能盲目重放。
- Client 只接受 `/api/` 相对路径，防止绝对 URL 绕过固定上游；`trust_env=False` 防止内部
  Java 流量被宿主机代理改道。这个决策来自测试实际发现的 SOCKS 代理初始化失败。
- M1.2 原先保留 `HTTPStatusError`、`TimeoutException` 和 `BusinessResponseValidationError`；
  M1.3 已完成统一 Tool 错误映射，M1.6 已完成只读有限重试，保持层次分离。

### 可能的面试问题

**为什么 HTTP 200 后还要做两层 Schema 校验？**

回答要点：状态码只说明 HTTP 传输成功，不能证明统一信封完整或业务对象字段可靠。先验证
信封，再验证具体 data，可以把协议漂移和业务 DTO 漂移分开定位，并阻止模型用不完整数据
补造事实。

**为什么 AsyncClient 要跟随应用生命周期，而不是每次请求创建？**

回答要点：共享实例复用 TCP/TLS 连接池，降低延迟和端口消耗；lifespan 统一创建和关闭，
测试也能验证资源已释放。它类似 Spring 中的单例 WebClient/连接池。

**为什么内部调用设置 `trust_env=False`？**

回答要点：默认继承宿主机代理可能让服务间流量离开预期网络，或因缺少代理扩展导致启动
失败。内部上游应只由受控 Base URL 和部署网络决定。本项目是在测试中真实发现 SOCKS 环境
变量问题后做出的修复。

**POST 超时为什么不能直接重试？**

回答要点：超时只代表客户端没有收到结果，服务端可能已经提交。安全恢复需要稳定幂等键、
版本校验、操作日志和必要时的状态查询；自动重试策略必须区分读写和剩余时间预算。

**Trace ID 和身份 Header 能被 Python 信任吗？**

回答要点：不能。Python 负责安全格式和上下文透传，Java 仍负责身份、权限和业务状态校验。
Trace 用于关联而不是授权；未来还要把 Trace 与 Run/Step 一起持久化。

### 简历表述建议

> 设计并实现 Python Agent 到 Java 业务服务的异步 HTTP Client，使用共享连接池和分项超时，
> 透传身份与 Trace；通过统一信封、端点 Pydantic Schema 和 Trace 一致性三重校验拦截不完整
> 业务事实，并以幂等键和“写请求不盲目重试”约束后续 Agent 回写边界。

### 不能过度声称

- 当前已完成 Client 和 Tool 基础协议，但还没有订单查询等具体业务 Tool，也没有模型自主调用。
- 4xx/5xx、超时和响应校验异常已由 M1.3 映射为统一错误码，具体只读 Tool 和有限退避重试已
  在 M1.5～M1.6 完成，但仍没有熔断。
- 当前只有统一成功信封和测试用端点 data Model；正式订单、任务、质检等 Tool DTO 尚未实现。
- POST 能发送身份和幂等键不等于 Approval 已完成；没有用户确认、草稿持久化或 Agent 写回。
- 已验证真实 `ORDER-003` 成功链路；M1.3 又验证了 6 条真实 Java 故障映射，但尚未进入
  Tool/Workflow/Agent 端到端链路。
- Token 只是安全透传能力，当前 Java 最小认证仍主要使用用户/角色 Header，不是生产级 JWT/RBAC。

---

## M1.3 面向 Workflow 的标准 Tool 错误语义

### 面试价值判断

核心关注。M1.3 的价值不是“把异常换个名字”，而是把 HTTP、Java 业务错误、网络故障和
响应契约漂移收敛成 Workflow 可稳定分支的机器语义，同时保留 Trace 和原始异常因果链，避免
模型或流程通过易变文案猜测失败原因。

### 与 Agent 开发的关系

当前失败链路已经可以真实执行：

```text
Java 业务错误 / 网络异常 / timeout / 非法响应
→ BusinessHttpClient
→ 校验失败信封或识别 httpx 异常
→ ToolException(code, message, retryable, trace_id, status_code)
→ 后续 ToolResult / Workflow 根据 code 分支
```

真实 Java 故障验收覆盖 400、403、404、500、超时和 HTTP 200 缺少 `data` 六条路径。参数、
权限、资源和冲突属于不可重试业务错误；500 继承 Java 的保守不可重试契约；网络和 timeout
标记技术上可恢复；非法响应会在事实进入 Tool/模型前被阻断。

### 需要掌握的原理和设计取舍

- Workflow 依据 `ToolErrorCode` 分支，不解析 `message`。文案可改、可本地化，也可能含业务
  对象；错误码才是稳定契约。
- 非 2xx 也不能只看状态码。Python 使用 `BusinessErrorEnvelope` 校验
  `success/code/message/data/trace_id/retryable`，再交叉核对 HTTP 状态、Java code 和
  Header/Body Trace；`404 + BUSINESS_CONFLICT` 会被当作契约错误而不是资源不存在。
- 401 和 403 都映射 `PERMISSION_DENIED`，便于 Workflow 统一停止，但 `status_code` 仍保留，
  让 API/UI 可以区分“未认证”和“已认证但无权限”。
- 网络异常对外使用固定安全文案，不泄露内部 URL、代理或连接详情；原始 `httpx` 异常通过
  `__cause__` 保留，日志和排障仍能定位技术原因。
- `retryable` 是故障属性，不是重试授权。timeout/网络错误可以是 `true`，但写请求结果可能
  未知；M1.6 的只读 Tool 策略已结合错误码、次数、退避和总预算执行有限重试。
- `BUSINESS_CONFLICT` 不应盲重试。409 通常表示状态或版本已变化，应重新读取最新事实，再由
  Workflow 或用户重新决策。
- 响应 Schema 错误不可重试，因为它通常表示契约漂移；重复请求相同版本并不会让缺失字段
  自动恢复，还可能放大故障。

### 可能的面试问题及回答要点

**为什么不能让 Tool 直接抛 `HTTPStatusError`？**

回答要点：HTTP 只表达传输层，Agent Workflow 需要参数、权限、资源、冲突、超时、上游和
响应契约等稳定语义。统一异常使不同 Tool 使用相同分支、展示和后续 Run/Step 错误码，同时
不耦合 httpx 实现。

**既然已经有 HTTP 状态，为什么还校验 Java 错误信封？**

回答要点：网关 HTML、服务契约漂移或状态/code 配错都可能产生“看似合理”的 HTTP 失败。
严格信封和三方一致性校验可以防止 Workflow 用错误分类继续执行，也能把业务失败和协议失败
分开定位。

**`retryable=true` 为什么没有在 Client 里直接重试？**

回答要点：Client 只能判断网络故障可能恢复，不知道调用是只读还是写入。POST 超时可能是
响应丢失但事务已提交；重试必须由 Tool 风险策略结合幂等键、版本、次数和总预算决定。

**为什么 Java 500 映射为 `UPSTREAM_UNAVAILABLE`，但当前仍不可重试？**

回答要点：对 Python 而言 Java 是上游，所以类别是上游不可用；但 Java 当前对未知 500 采用
保守 `retryable=false`，尤其写操作结果未知。类别和重试决策是两个维度，不能混为一谈。

**为什么保留异常因果链？**

回答要点：给 Workflow/模型的错误必须安全稳定，运维排障又需要区分 ConnectError、ReadTimeout
等真实原因。固定外部文案加 `raise ... from ...` 同时满足安全边界和可诊断性。

### 简历表述建议

> 设计 Python Agent Tool 标准错误模型，将 Java 400/401/403/404/409/500、网络超时及响应
> 契约漂移统一映射为可供 Workflow 分支的结构化异常；通过错误信封、HTTP/code/Trace 一致性
> 校验和安全异常因果链，阻断不可信事实进入模型，并区分故障可恢复性与实际重试授权。

### 不能过度声称

- 当前已由 Tool 基类把标准异常转换为 `ToolResult`，M1.5 已实现具体只读业务 Tool，但不能
  声称“Agent 已能自主调用 Tool”。
- M1.6 已实现只读有限重试、封顶指数退避和总耗时预算；仍没有熔断、随机抖动或写 Tool 重试。
- `UNKNOWN_TOOL_ERROR` 已由 M1.4 执行边界触发；`DUPLICATE_CALL` 已由 M1.7 单次 Run 调用
  指纹检测实现，仍不能把注册表重名混同为重复业务调用。
- 真实故障验收是 6 个确定性开发场景，不是生产错误率、恢复成功率或性能指标。
- 错误尚未写入 Run/Step，也没有 SSE 错误事件或前端 Agent 错误展示。

---

## M1.4 Tool 基础协议与可信执行边界

### 面试价值判断

核心关注。M1.4 的价值不是创建一个抽象类，而是把未来每个业务 Tool 都必须遵守的输入、权限、
超时、输出和错误协议集中到一个不可绕开的公共执行入口。它让 Workflow 或模型只接触稳定的
Schema 和结果，不直接依赖具体 Tool 的 Python 异常或 Java 响应细节。

### 与 Agent 开发的关系

当前已实现的执行链为：

```text
raw_input + ToolContext(identity, permissions, trace_id, run_id)
→ BaseTool.execute
→ required_permissions 门禁
→ input_model Pydantic 校验
→ 整体 timeout
→ 具体 _execute
→ output_model Pydantic 校验
→ ToolResult(success, data, error)
```

`ToolRegistry` 使用稳定名称注册和获取 Tool，重复名称直接拒绝，避免后注册实例静默覆盖原 Tool。
M1.5 已在这套协议上实现七个只读业务 Tool；公共安全边界仍由 `BaseTool.execute` 负责，业务
子类只处理 Java 端点调用和资源归属校验。

### 需要掌握的原理和设计取舍

- `execute` 使用 Template Method：公共方法固定执行顺序，子类只实现 `_execute`。这样具体 Tool
  不能因复制粘贴遗漏权限、Schema、超时或错误收敛。
- 输入和输出都用 Pydantic。输入门禁阻止模型或调用方传入额外字段、空 ID 和错误类型；输出
  门禁阻止 Java 契约漂移或 Tool 拼装错误成为 Workflow 的业务事实。
- `ToolResult` 强制成功时只有 `data`、失败时只有 `error`，避免 Agent 面对矛盾状态后自行猜测。
  Workflow 应按 `error.code` 分支而不是匹配 `message`。
- 权限做两层校验：Python 根据 Tool 声明的 `required_permissions` 提前拒绝明显越权调用，Java
  仍是最终权限和业务状态裁决者。页面或模型传入的权限不能替代服务端校验。
- `timeout` 是单次 Tool 的整体耗时上限；Client 的 connect/read/write/pool timeout 是传输阶段
  上限。两者作用范围不同，不能只配置其中一个。
- M1.4 完成时 `max_retries` 只是元数据；M1.6 已通过具体只读 Tool 显式绑定 RetryPolicy，
  结合错误码、`retryable`、次数、退避和总预算执行重试，写 Tool 仍默认不重试。
- 未知异常对外固定映射 `UNKNOWN_TOOL_ERROR`，不泄露实现细节；原异常通过结构化日志保留，
  并附带 `tool_name/run_id/error_code`。安全返回和可诊断性需要同时满足。
- 注册重名是装配错误，使用 `DuplicateToolRegistrationError`；`DUPLICATE_CALL` 是单次 Run 中
  相同 Tool 和参数重复执行的运行时语义，已由 M1.7 实现。二者不能为了复用错误码而混淆。

### 可能的面试问题及回答要点

**为什么不让每个 Tool 自己实现输入校验和 try/except？**

回答要点：多个 Tool 手写会产生策略漂移，部分 Tool 可能漏权限、漏输出校验或泄露异常。
Template Method 把通用门禁集中在 `execute`，具体实现只处理业务调用，也更容易用一组协议测试
覆盖所有 Tool 的共同规则。

**为什么 Tool 输出也要再次做 Pydantic 校验？Java Client 已经校验过响应。**

回答要点：Client 校验 Java 信封和端点 DTO，具体 Tool 还可能聚合、重命名或计算字段。输出
Schema 是 Tool 与 Workflow 的最终边界，可以拦截 Tool 自身转换错误，防止不可信数据进入模型。

**Python 已检查权限，为什么 Java 还要再检查？**

回答要点：Python 是编排层，只能做快速拒绝；上下文可能来自页面或会话，不能被当作最终事实。
业务权限、对象归属和状态一致性必须由持有业务数据的 Java 服务重新校验。

**`ToolResult` 和抛异常相比有什么好处？**

回答要点：异常适合服务内部传播，Workflow 更需要可序列化、可展示、可持久化的稳定分支结构。
执行边界把 `ToolException`、timeout、Schema 错误和未知异常收敛为统一结果，后续 Run/Step、SSE
和评测可以复用同一错误语义。

**为什么 M1.4 的 `max_retries=3` 测试仍只调用一次？**

回答要点：该测试证明元数据本身不授权重试。M1.6 仍保留这条安全基线，只有具体只读 Tool
显式绑定受约束的 RetryPolicy 才重试，未来写 Tool 不会仅因次数大于零被自动重放。

### 简历表述建议

> 设计 Python Agent Tool 基础协议，以泛型 Pydantic Schema 和 Template Method 统一 Tool 元数据、
> 身份权限上下文、输入输出校验、整体超时及错误结果；通过稳定注册表和结构化异常收敛，阻断
> 非法参数、越权调用、响应漂移和未知异常进入 Workflow，同时为后续重试、Run/Step 与评测提供
> 可复用契约。

### 不能过度声称

- M1.4 当时只有协议和测试用 Echo Tool；具体只读业务能力以随后 M1.5 的实现和测试为证据。
- 没有接入 LLM、LangGraph 或动态 Tool Calling，不能声称模型已能选择和调用 Tool。
- M1.4 当时 `max_retries` 只是元数据；M1.6 已增加只读有限重试、封顶指数退避和总耗时预算。
- `run_id` 已用于日志和 M1.7 上下文内调用账本，但仍没有 Run/Step 表、持久化或 SSE 展示。
- 风险等级已建模，但写 Tool、Approval、人工确认和 Agent 写回仍未实现。
- Python 权限门禁不等于生产级 RBAC，Java 仍必须执行最终权限、对象和状态校验。

---

## M1.5 细粒度只读 Tool 与业务事实防串线

### 面试价值判断

核心关注。M1.5 把七个 Java 查询接口变成可独立验证的 Agent Tool，不只是 HTTP 字段搬运。
真正有面试价值的是：用细粒度 Tool 暴露可观察的取证路径，用严格 Schema 和资源归属一致性
阻断错误业务事实进入 Workflow，并明确区分“空集合”“资源不存在”和“上游响应不可信”。

### 与 Agent 开发的关系

当前真实调用链为：

```text
Workflow/测试准备 Tool 名称、order_id/task_id 和 ToolContext
→ ToolRegistry 获取七个只读 Tool 之一
→ BaseTool.execute 做权限、输入和整体超时门禁
→ 具体 _execute 调 BusinessHttpClient.get
→ Java 校验身份并查询业务事实
→ Client 校验双层信封、HTTP/code/Trace 和端点 DTO
→ Tool 核对请求 ID、父 ID 与嵌套资源归属
→ BaseTool 再校验 Tool 输出
→ ToolResult(success, data/error)
```

七个 Tool 分别读取订单详情、关联任务、任务详情、生产步骤、质检问题、复核记录和交付记录。
Python 不映射 Java 业务表，也不让模型直接生成这些事实。

### 需要掌握的原理和设计取舍

- 采用七个细粒度 Tool，而不是一个返回全部信息的“大而全”接口。后续 Agent 可以按问题选择
  取证路径，Run/Step、耗时和评测也能定位到具体事实来源；代价是调用次数更多，后续需要受控重试和重复调用检测。
- 输入 Schema 只接受受限格式的 `ORDER-*` / `TASK-*`，并禁止额外字段；避免路径穿越式输入、
  空标识和模型随意添加参数进入 Java 请求。
- 输出 Schema 使用 Java 枚举的 Literal、必填字段和 `extra=forbid`。Java 增删字段或返回未知状态时立即失败，不让 Workflow 根据半可信 JSON 猜测。
- 仅验证 JSON 形状不够。Tool 继续校验顶层父 ID 和嵌套任务/步骤/问题/交付记录是否属于请求的
  order/task，防止缓存、路由或上游缺陷造成跨订单事实串线。
- `[]` 是“查询成功但当前没有记录”，404 是“父资源不存在”，二者必须保留不同语义。把空质检问题当 404 会让诊断误判；把 404 当空集合又会掩盖错误上下文。
- Python 权限名用于编排层快速拒绝，身份与 Trace 仍透传给 Java；Java 是最终权限和数据边界。
- 每个 Tool 声明 LOW 风险和 `max_retries=1`。M1.5 当时元数据不执行重试；M1.6 已显式绑定
  RetryPolicy，timeout/网络暂态错误最多额外调用一次，Java 保守 500 仍只调用一次。

### 可能的面试问题及回答要点

**为什么不做一个 `get_order_overview` Tool 一次返回所有信息？**

回答要点：细粒度 Tool 让 Agent 的决策、证据来源和失败步骤可观察、可评测，并减少不相关数据
进入上下文。大接口调用少但掩盖取证路径、增加上下文噪声。当前项目先保证细粒度正确性，后续
可由确定性 Workflow 编排，不让模型随意并发或重复调用。

**Pydantic 已校验 DTO，为什么还要检查响应中的 ID？**

回答要点：Schema 只能证明“像一个合法任务”，不能证明“就是这次请求的任务”。请求
`TASK-003` 却返回结构合法的 `TASK-004`，若不做绑定校验会把别的订单事实交给模型，是比普通
反序列化错误更危险的事实污染。

**空数组为什么不能直接当成不存在？**

回答要点：空数组说明父订单/任务存在，只是没有子记录；404 表示父资源不存在。Agent 诊断中
“无质检问题”和“任务 ID 无效”会走完全不同的结论和澄清路径。

**这七个 Tool 如何控制幻觉？**

回答要点：业务事实只从 Java API 获取；输入限制、双层信封校验、严格端点 DTO、父子 ID 绑定、
稳定错误结果共同阻止模型补造或误用事实。它不能消除模型在归纳阶段的所有幻觉，后续仍需要
确定性 Workflow、引用、Run/Step 和评测。

### 简历表述建议

> 实现面向订单诊断的七个细粒度只读 Tool，以 Pydantic 严格映射 Java 业务契约并统一身份、权限、
> Trace 与错误语义；通过请求/响应资源 ID 绑定和空集合语义区分，阻断跨订单事实污染，为后续
> Workflow 取证路径、可观测性和确定性评测提供可靠输入。

### 不能过度声称

- 已实现七个 Tool 的独立调用与真实 Java 链路，但尚未接入 LangGraph、LLM Tool Calling 或
  前端 Agent 对话，不能声称模型已自主选择 Tool。
- M1.6 已实现 RetryPolicy；只有明确可恢复的 timeout/网络错误会重试，不能声称所有失败都会恢复。
- M1.7 已实现单次 Run 重复调用检测；仍没有通用并发调度、结果缓存或上下文预算优化。
- M2.1 已建立 Run/Step 表，但 Tool 调用尚未自动写入；也没有统一 Agent 评测。当前证据是 Tool
  契约测试与固定数据真实调用。
- 权限名是 Python 前置门禁，不代表完整 RBAC；最终授权仍依赖 Java。
- 本阶段只有读取，没有 Approval 或安全写回能力。

---

## M1.6 只读 Tool 的受约束重试与总预算

### 面试价值判断

核心关注。Agent 可能连续调用多个外部 Tool，短暂网络故障若完全不恢复会降低诊断成功率，
但无条件重试又会放大上游压力、拖长回答时间，甚至让写操作重复执行。M1.6 的价值是把
“错误可能恢复”和“这次调用被授权重试”分成两层，并用自动化测试证明次数和停止条件。

### 与 Agent 开发的关系

当前只读 Tool 的失败调用链是：

```text
Java/网络失败
→ BusinessHttpClient 转成 ToolException(code, retryable, trace_id)
→ BaseTool._execute_with_retry
→ RetryPolicy 同时检查错误码白名单、retryable 和剩余次数
→ 允许：记录 tool_retry_scheduled，等待退避后重新调用
→ 拒绝或预算耗尽：由 BaseTool.execute 转成 ToolResult.error
```

七个只读 Tool 最多额外重试 1 次，所以一次 Tool 执行最多发出 2 个 Java 请求。网络连接失败
和 httpx timeout 可以重试；参数、权限、404、409、响应 Schema 和资源归属错误不重试。
Java 通用 500 虽映射为 `UPSTREAM_UNAVAILABLE`，但当前信封为 `retryable=false`，因此仍不重试。

### 需要掌握的原理和设计取舍

- `retryable` 是异常的技术属性，不是执行授权。实际重试还要求 Tool 显式绑定策略、错误码属于
  `TOOL_TIMEOUT`/`UPSTREAM_UNAVAILABLE` 白名单并且仍有剩余次数。
- `max_retries=1` 表示首次调用之外最多再调用一次，即最多 2 次 attempt。把 retry 和 attempt
  混用容易产生 off-by-one，测试以调用计数直接锁定语义。
- 退避采用封顶指数公式 `min(initial × multiplier^(N-1), max)`。当前生产只重试一次、等待
  100 ms；策略单元测试覆盖多次增长和上限，为以后调参保留确定行为。
- `asyncio.timeout` 包住整个重试循环，所以首次请求、退避、后续请求和输出校验共享 5 秒预算。
  如果退避阶段耗尽预算，不会再赠送一次完整 timeout。
- 重试策略只显式装配到七个 LOW 风险只读 Tool。`BaseTool` 即使声明 `max_retries>0`，没有
  `RetryPolicy` 也不会重试，避免未来写 Tool 仅因复制元数据就产生副作用重放。
- 响应 Schema 错误通常代表契约漂移，不是短暂网络抖动；重试相同版本只会重复失败并增加负载，
  因此明确排除。
- 每次计划重试记录 Tool、Run、Trace、错误码、序号和退避时间，为后续 Run/Step 和恢复率评测
  提供字段基础；当前日志还不是持久化执行记录。

### 可能的面试问题及回答要点

**为什么不能看到 `retryable=true` 就直接重试？**

回答要点：异常只知道故障可能恢复，不知道操作是否安全。还要结合读写风险、错误类型、剩余
次数和总预算。写请求超时可能已经提交，必须使用原幂等键、版本校验和状态查询，而非普通重放。

**`max_retries=1` 到底会请求几次？**

回答要点：最多两次，第一次是正常 attempt，失败后还有一次 retry。本项目同时测试“第一次
连接失败、第二次成功”和“两次都失败后返回错误”，避免边界语义只停留在文档。

**为什么把总 timeout 放在重试循环外？**

回答要点：Tool 是 Agent 一次步骤，延迟预算应该约束整个步骤。如果每次 attempt 都重新获得
5 秒，多个 Tool 串行时总体响应时间会失控，也难以给 Workflow 建立可靠 SLA。

**Java 500 已映射为 `UPSTREAM_UNAVAILABLE`，为什么不重试？**

回答要点：错误类别和恢复授权是两个维度。Java 当前对未知 500 保守标记 `retryable=false`，
Python 尊重上游契约；只有明确的连接/timeout 暂态错误同时满足白名单和标志才重试。

**为什么当前没有 jitter？**

回答要点：当前每个只读 Tool 只重试一次，主要服务固定演示和确定性测试，先采用可预测的封顶
退避。多实例或更高重试次数时，应加入随机抖动避免惊群，并用指标验证参数，而不是声称当前
方案已解决大规模故障恢复。

### 简历表述建议

> 为 Agent 七个只读业务 Tool 实现受约束重试：以错误码白名单、上游 `retryable` 和显式读策略
> 三重门禁控制重放，使用封顶指数退避与整体超时预算限制放大效应，并记录 Trace/Run 关联的
> 重试日志；通过调用次数、暂态恢复、不可重试错误和预算耗尽测试验证停止条件。

### 不能过度声称

- 当前只有七个只读 Tool 使用重试；没有写 Tool 自动重试、熔断、限流、跨实例协调或自适应策略。
- 当前生产策略只允许一次重试，实际只用到 100 ms 首次退避；不能声称已验证多轮生产调参效果。
- 没有随机抖动，多实例并发故障下仍可能出现同步重试；增加 jitter 需要后续负载和指标验证。
- 本次受限执行环境无法访问宿主机 Java 服务，真实 Java 重试成功链路未重新验收；确定性
  MockTransport 覆盖七个 Tool 的失败后成功、持续 timeout 和不可重试分支。
- 没有 LangGraph、LLM Tool Calling、自动 Step 记录或 Agent E2E 恢复率指标，不能把 Tool 层
  测试描述为完整 Agent 容错能力。

---

## M1.7 Run 内 Tool 重复调用检测

### 面试价值判断

核心关注。LLM Tool Calling 常见问题不只是选错 Tool，还包括在信息没有变化时反复调用同一个
Tool，造成延迟、Token/接口成本、上游压力和循环执行。M1.7 将“同一次逻辑调用中的技术 retry”
与“Agent 再次发起相同业务调用”分开，并提供可测试的停止信号 `DUPLICATE_CALL`。

### 与 Agent 开发的关系

当前公共执行链增加了一道 Run 级门禁：

```text
权限和输入 Schema 校验
→ Tool 名 + 已校验参数规范化
→ SHA-256 fingerprint
→ RunToolCallLedger 原子占位
→ 首次：继续 timeout / retry / Java 调用
→ 重复：HTTP 前返回 DUPLICATE_CALL
→ force_refresh：显式绕过本次门禁并重新读取
```

指纹包含 Tool 名和参数，因此 `get_order_detail(ORDER-003)` 与
`get_related_tasks(ORDER-003)` 不冲突；参数 JSON 的 key 顺序不同也会生成相同指纹。M1.6 retry
发生在一次 `execute` 内部，账本只在进入 retry 循环前记录一次，不会把第二个 HTTP attempt
错误地识别为 Agent 重复调用。

### 需要掌握的原理和设计取舍

- 先用 Pydantic 校验，再生成指纹。非法输入和缺权限请求不占账本；默认值、字段类型和参数顺序
  经过规范化后，语义等价输入会稳定命中同一调用。
- 账本只保存 SHA-256 十六进制指纹，不保存原始参数，减少身份、业务描述或未来敏感输入在内存
  记录和日志中扩散。Hash 用于稳定比较，不应当作加密授权或不可逆安全证明。
- `RunToolCallLedger.try_reserve` 使用只包围 Set 查询/插入的短锁。两个并发相同请求只能有一个
  进入具体 Tool，锁内没有 I/O，不会在 Java 慢请求期间占锁。
- 记录发生在实际调用前。首次调用即使返回 404、timeout 或 Schema 错误仍保留指纹，避免模型
  在没有策略变化时循环重试；需要重新获取时必须显式 `force_refresh=True`。
- `force_refresh` 是执行控制参数，不塞进每个 Tool 的业务输入 Schema，也不参与 fingerprint。
  它只放行本次执行，不清除历史，因此之后普通同参调用仍会被拦截。
- 这是防循环门禁，不是结果缓存。重复时返回标准错误，不返回第一次 data；是否复用旧结果应由
  后续 Workflow 状态或缓存策略明确决定。
- 当前账本归属于 `ToolContext`。一次 Run 必须复用同一上下文；这样无需全局字典和清理任务，
  但不能跨进程、实例或独立重建的上下文去重。

### 可能的面试问题及回答要点

**Tool retry 和重复 Tool Call 有什么区别？**

回答要点：retry 是一次逻辑调用内部为恢复网络暂态故障产生的多个 HTTP attempt，由确定性策略
控制；重复 Tool Call 是模型或 Workflow 再次用相同参数调用同一 Tool。前者不应触发
`DUPLICATE_CALL`，后者默认拦截。

**为什么不用原始 JSON 字符串直接比较？**

回答要点：JSON key 顺序、字段别名、默认值和调用方表示可能不同，字符串不同不代表语义不同。
先通过输入 Schema 得到统一类型，再对排序后的规范 JSON 和 Tool 名计算 Hash，才能稳定比较。

**为什么第一次调用失败后也不自动释放指纹？**

回答要点：如果失败后立即释放，模型可能在 404、权限、Schema 漂移等不可恢复错误上无限循环。
M1.6 已在一次调用内完成允许的暂态 retry；再执行必须由 Workflow 根据错误码决定，并显式使用
`force_refresh`。

**为什么不直接缓存第一次结果？**

回答要点：M1.7 的目标是检测和停止无意义循环，而不是定义数据新鲜度。自动返回旧结果可能掩盖
业务状态变化；缓存需要 TTL、失效、权限和版本语义，应该单独设计。

**这种去重能否支持多 worker 部署？**

回答要点：不能。当前账本是 Run 上下文内的进程内状态，适合 M1/M2 单进程确定性链路。多 worker
或断点恢复需要共享 Run 存储、唯一约束或分布式协调，并设计生命周期清理。

### 简历表述建议

> 为 Agent Tool 层实现 Run 内重复调用检测：对稳定 Tool 名和 Pydantic 规范化参数生成 SHA-256
> 指纹，以并发安全的内存账本在 HTTP 前原子占位，将模型重复调用统一收敛为
> `DUPLICATE_CALL`；区分内部 retry 与逻辑重复，并提供显式 `force_refresh` 控制事实刷新。

### 不能过度声称

- 当前尚未接入 LLM 或 LangGraph，测试证明的是 Tool 执行边界，不是模型循环率已经下降。
- 去重只在复用同一个 `ToolContext` 的单次 Run 中生效；同 `run_id` 的独立上下文不会自动共享。
- Tool 调用账本没有数据库持久化、TTL、跨进程/实例协调或服务重启恢复，不能因为 M2.1 已有
  Run/Step 表就称为分布式幂等系统。
- 当前不是缓存，不复用第一次结果，也没有基于业务版本判断数据新鲜度。
- `force_refresh` 已由 M1.8 开发调试 API 暴露，但尚未由 Workflow 根据业务版本、写后验证或
  数据新鲜度自动授权；调试入口不能等同最终用户权限策略。

---

## M1.8 开发专用 Tool 调试 API

### 面试价值判断

有价值。Agent 工程不能等到 LLM、Workflow 和前端全部完成后才验证 Tool。M1.8 建立独立的
Tool 调试面，把 Tool Schema、权限、Trace、重试、重复调用和 Java 契约从模型决策中解耦，
可以先证明“工具本身正确”，再定位未来问题究竟来自 Tool 还是 Agent 路由。

### 与 Agent 开发的关系

开发环境通过以下入口调用现有 Tool，而不是为调试另写一套 Java 直连逻辑：

```text
POST /internal/tools/{tool_name}/invoke
→ ToolDebugInvokeRequest
→ ToolRegistry
→ ToolDebugRunContextStore
→ BaseTool.execute
→ 标准 ToolResult
```

这条路径完整保留权限、输入Schema、M1.7去重、M1.6有限重试、Java Client、输出Schema和Trace，
所以调试结果能代表后续 Workflow 将使用的真实 Tool 行为。真实 `ORDER-003` 已验证首次查询成功、
同 Run 同参返回 `DUPLICATE_CALL`，以及 `force_refresh=true` 后重新获取Java事实。

### 需要掌握的原理和设计取舍

- 路由只在 `Settings.environment == "development"` 时注册。test和production不仅访问返回404，
  OpenAPI也不存在该路径，减少内部调试能力在生产环境的暴露面。
- 请求显式提供业务参数、调试身份、Python权限、Run ID和刷新控制；Trace ID继续从HTTP Header
  进入，避免Body和链路追踪产生两个事实来源。
- Tool业务失败返回HTTP 200下的标准`ToolResult.error`，因为调用协议已正常完成，Workflow需要
  稳定错误码分支；未知Tool、请求Schema错误和Run上下文冲突分别保留HTTP 404/422/409语义。
- 同一调试Run跨HTTP请求复用`ToolContext`，否则每次请求新建上下文会绕过M1.7。新请求浅复制
  当前Trace ID但共享私有账本，兼顾每次请求可追踪和Run内去重。
- 同一Run禁止更换身份或权限，避免先以一个安全上下文建立账本，再用另一身份继续执行造成审计
  混淆。Java仍会重新校验透传身份，Python权限只是快速门禁。
- 调试Run存储上限为128并按最久未使用淘汰，防止开发进程被任意`run_id`无限占用；因此它是
  有界调试状态，不是可靠Run持久化或分布式Session。
- Swagger示例属于可执行契约：开发者能直接填`ORDER-003`调用七个Tool，也能观察标准成功和
  失败信封，而不需要先接入LLM Tool Calling。

### 可能的面试问题及回答要点

**为什么需要Tool调试API，pytest直接调用不够吗？**

回答要点：pytest适合确定性回归，但HTTP调试入口还能验证FastAPI请求Schema、Trace中间件、
应用lifespan装配、共享Client、Registry和真实Java网络链路。它也是前后端或Agent编排接入前的
手工契约探针；两者互补，不能用Swagger手工测试替代自动化测试。

**为什么Tool失败仍返回HTTP 200？**

回答要点：HTTP请求和Tool执行协议是两层。已找到Tool并完成执行时，资源404、权限不足、timeout
等是`ToolResult.error`，上层按稳定错误码处理；路径中Tool不存在或请求Body无效才是HTTP层错误。
如果把所有Tool失败都改成HTTP异常，会绕过统一结果模型并让Workflow同时解析两套错误语义。

**为什么生产环境不只是返回403，而是完全不注册路由？**

回答要点：条件注册让生产路由表和OpenAPI都没有内部入口，减少误调用和信息暴露。仅依靠处理
函数里的环境判断仍会公开路径、参数Schema和Swagger文档，且容易在重构时漏掉门禁。

**为什么调试API需要复用Run上下文？**

回答要点：M1.7账本属于`ToolContext`。如果每个HTTP请求都创建新上下文，相同`run_id`也无法
识别重复。当前保存最近128个上下文，并在请求间共享账本；Trace ID随当前HTTP请求更新，身份和
权限则必须与首次调用一致。

### 简历表述建议

> 设计开发专用Agent Tool调试API，在不依赖LLM/Workflow的情况下通过Swagger调用七个业务Tool；
> 复用生产Tool执行链并保留Schema、权限、Trace、有限重试和Run内去重，采用条件路由注册隔离
> 生产环境，并以有界Run上下文支持跨请求重复调用与强制刷新验证。

### 不能过度声称

- 当前接口只在development环境启用，没有生产级管理端认证、RBAC、审计后台或网关隔离。
- 调试调用方可以填写身份和Python权限，这是本地开发能力，不代表最终用户可以自行提权；Java
  最终校验边界仍必须保留。
- Run上下文只保留最近128个并存在单进程内，淘汰、重启、多worker或多实例后不会恢复。
- Swagger和真实Java调用证明Tool链路可独立调试，不代表已完成LangGraph、LLM Tool Calling、
  确定性诊断Workflow或Agent端到端评测。

---

## M2.1 Agent Run/Step 持久化与可观测性基础

### 面试价值判断

核心关注。Agent 的可靠性不能只靠应用日志；一次用户请求需要稳定 Run，内部上下文读取、Tool
调用和规则判断需要有序 Step，才能回答“执行到哪里、依据是什么、在哪一步失败”。M2.1 把
Session、Message、Run、Step 建成 Agent 自有事实，并用真实 PostgreSQL migration 和 Repository
测试锁定结构，为后续 Workflow 可观测性和失败恢复提供可验证基础。

### 与 Agent 开发的关系

当前数据层级是：

```text
AgentSession
├── AgentMessage（用户/助手消息，按会话序号排序）
└── AgentRun（一次请求、状态、结果、错误定位）
    └── AgentStep（CONTEXT/TOOL/RULE/LLM、摘要、耗时）
```

这些表只保存 Agent 会话与执行元数据，不映射 Java 的订单、任务、质检、复核或交付表。未来
`ORDER-003` 的业务事实仍必须由 Java Tool 提供；Run/Step 只记录“Agent 如何取得和处理事实”，
不能成为第二套业务事实来源。

### 需要掌握的原理和设计取舍

- Run 和 Step 使用稳定字符串 ID，便于与 Trace、日志、SSE 和 ToolContext 关联；当前还未完成
  这些链路的自动绑定。
- `(session_id, sequence_number)` 和 `(run_id, sequence_number)` 唯一约束把消息顺序、执行顺序
  下沉到数据库，避免并发写入产生两个“第1步”。
- 状态和类型使用 Python `StrEnum` 加数据库 VARCHAR Check Constraint，而不是 PostgreSQL 私有
  enum。这样保留类型/数据约束，同时降低后续增加状态时修改数据库 enum 类型的迁移复杂度。
- Repository 只 `flush` 不 `commit`。`flush` 能尽早暴露外键和唯一约束，事务仍由上层生命周期
  服务控制，后续可以让 Run 状态与 Step 记录原子提交或整体回滚。
- Session 删除会级联 Message、Run、Step，Run 删除会级联 Step；删除请求 Message 只将 Run
  外键置空，保留已经发生的执行记录。这是“清理从属数据”和“保留运行证据”之间的取舍。
- Step 只预留输入/输出摘要，不默认保存完整 Prompt、Token、身份凭据或业务响应，避免可观测性
  变成敏感数据复制渠道。摘要如何脱敏和截断仍需 M2.3 实现。
- 数据库专项使用随机端口、临时数据目录的隔离 PostgreSQL，真实验证 upgrade、schema drift、
  downgrade 和约束，避免测试误连本机或开发数据库。

### 可能的面试问题及回答要点

**为什么 Agent 需要 Run/Step，结构化日志不够吗？**

回答要点：日志适合排障但不保证业务级结构、顺序和查询契约；Run/Step 能稳定关联一次请求的
状态、结果、错误步骤和执行证据，供前端进度、SSE、评测和恢复使用。日志与持久化记录互补。

**为什么 Repository 不直接 commit？**

回答要点：一次 Agent 执行会同时修改 Run 和多个 Step。如果每个 Repository 方法独立提交，
中途失败会留下互相矛盾的半成品。Repository 负责 flush 和约束反馈，上层服务负责事务边界。

**Run/Step 表会不会复制业务数据，形成两个事实源？**

回答要点：不会映射 Java 业务表；只保存执行状态和受控摘要。订单当前状态仍需重新调用 Java
Tool 获取。最终结果可以保存当次诊断快照，但必须明确它是历史执行结果，不是最新业务状态。

**如何保证 Step 顺序在并发下可靠？**

回答要点：每个 Run 的 `sequence_number` 有数据库唯一约束，Repository flush 时即可发现冲突。
M2.3 还需要设计序号分配或并发控制；当前只证明数据库会拒绝重复序号，不能声称已完成并发分配。

### 简历表述建议

> 设计 Agent Session/Message/Run/Step 持久化模型与 Alembic 迁移，以数据库唯一序号、状态约束、
> 外键级联和上层事务边界支撑可追踪执行；在隔离 PostgreSQL 上验证 migration drift、回滚、
> Repository CRUD 和约束异常，并保持 Agent 元数据与 Java 业务事实源隔离。

### 不能过度声称

- M2.2 已补充最小 Run 状态机；M2.3 自动 Step 记录仍未实现，不能声称 Workflow 已完整可观测
  或可恢复。
- Tool 调试 API、M1.7 内存账本与数据库 Run 仍未连接；服务重启后不能恢复 Tool 去重上下文。
- 尚无 LangGraph、诊断 Workflow、SSE、评测面板、Trace-to-Step 自动关联或数据保留/归档策略。
- 开发环境 Java 与 Python 仍共用数据库角色，代码边界已保持，但不是生产级数据库权限隔离。

---

## M2.2 Run 状态机、并发终态与结果快照

### 面试价值判断

核心关注。Agent 调用通常包含多个异步步骤，成功、异常处理、超时回调甚至重复消费可能并发更新
同一个 Run。只在数据库中定义合法状态字符串并不能阻止状态倒退或两个终态互相覆盖。M2.2 用
显式状态机和数据库 compare-and-set 更新，把一次执行的开始、成功结果或失败位置保存为一致、
可验证的运行证据。

### 与 Agent 开发的关系

当前只允许以下最小主链：

```text
create_run
→ PENDING
→ mark_running：RUNNING + started_at
├── mark_succeeded：SUCCEEDED + finished_at + final_result
└── mark_failed：FAILED + finished_at + error_code + error_step
```

成功与失败字段互斥：成功终态清空错误信息，失败终态清空`final_result`。`final_result`保存的是
这一次 Agent 执行结果快照，不是订单当前状态；未来仍要重新调用 Java Tool 获取最新业务事实。

### 需要掌握的原理和设计取舍

- 状态机位于`RunLifecycleService`，数据库Check Constraint只保证值属于枚举，两者职责不同。
- Repository使用单条`UPDATE ... WHERE run_id = ? AND status = expected_status RETURNING ...`。
  这是compare-and-set：只有仍处于预期状态的事务能更新。相比“先查状态、再更新”，它消除了
  查询与写入之间的竞争窗口。
- 条件更新失败后再查询：不存在时抛`RunNotFoundError`，存在但状态不符时抛
  `InvalidRunTransitionError`。这让未来API或Workflow能区分资源缺失与重复/过期动作。
- 生命周期异常暂不绑定HTTP状态码或`ToolResult`，避免底层执行状态被过早耦合到某个入口协议。
- 结果先经过标准JSON序列化并复制，拒绝`datetime`、NaN等PostgreSQL JSON字段或跨语言消费者
  可能无法稳定处理的值，避免到事务commit时才暴露错误。
- 时钟可注入且只接受带时区时间，使测试可以固定时间，并避免不同部署时区产生含糊时间戳。
- Service和Repository都不隐式commit；HTTP或Workflow调用方仍拥有事务边界，便于未来将Run和
  Step变更作为一个业务动作提交。
- 失败码没有强制复用`ToolErrorCode`。Run不仅可能因Tool失败，还可能因上下文、规则或LLM步骤
  失败；当前只约束非空和长度，统一错误词汇需在Workflow接入时设计。

### 可能的面试问题及回答要点

**数据库已经有状态枚举，为什么还要状态机？**

回答要点：枚举约束只能拒绝未知字符串，无法阻止`SUCCEEDED → RUNNING`或`PENDING → SUCCEEDED`。
业务服务必须定义合法边，并对每次转换的时间、结果和错误字段做一致更新。

**为什么不用先SELECT再UPDATE？**

回答要点：两个事务都可能读到RUNNING，然后一个写SUCCEEDED、另一个写FAILED，后写者覆盖先写者。
把预期状态放进UPDATE条件后，数据库原子决定胜者；失败方读回当前状态并返回状态冲突。

**Run失败后为什么不能在同一个Run上重置为RUNNING？**

回答要点：终态是一次执行的审计事实，重置会抹掉失败证据并让指标含义不清。需要重试整次执行时
应创建新Run，并通过后续字段关联原Run；该关联能力当前尚未实现。

**为什么要在写数据库前验证final_result是标准JSON？**

回答要点：Agent结果最终会被数据库、API、SSE和前端共同消费。提前验证能在稳定服务边界报错，
避免commit阶段才因不可序列化对象失败，也避免Python特有值泄漏到跨语言契约。

**这算幂等吗？**

回答要点：它实现的是状态转换的并发安全和重复动作拒绝，不等同于“相同请求返回相同响应”的
完整业务幂等。Run创建ID冲突、整次执行重试关联和消息消费幂等仍需后续设计。

### 简历表述建议

> 实现 Agent Run 显式生命周期与并发安全终态写入，通过数据库条件更新避免成功/失败竞争覆盖，
> 并对结果快照、错误定位和时区时间进行一致性校验；在隔离 PostgreSQL 上验证非法流转及并发
> 竞争场景。

### 不能过度声称

- 生命周期尚未接入Tool调试API、确定性Workflow或HTTP入口，当前由服务集成测试直接调用。
- M2.3 Step自动记录尚未实现，不能声称已经展示完整执行步骤、耗时或失败链路。
- `WAITING_APPROVAL`和`CANCELLED`只是M2.1预留枚举，M2.2没有实现暂停、恢复、取消或审批语义。
- 没有Run级重试关联、超时回收、心跳、崩溃恢复、跨实例调度、SSE或生产保留/归档策略。
- compare-and-set保证单次终态不互相覆盖，不代表整个Agent Workflow已经具备exactly-once语义。
