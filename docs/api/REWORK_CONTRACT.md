# M8返工生命周期契约 v1（T804冻结，T806～T808已实现详情、开始与异常）

## 1. 适用范围与实现边界

本契约冻结后续Java查询/写入、Python Tool及前端共同使用的M8边界，关联[详细计划M8.1](../planning/detailed-plan.md#m81-返工领域与契约)。
T801～T805已完成领域、契约与SQL存储；T806接通GET R详情，T807接通POST R/start，T808接通POST R/block及R/fail的Java校验与原子写入。
其余新增路径仍待实现；Python Client/Tool、独立Approval及前端新类型尚未接线，不能将Java写接口描述为完整人工确认闭环。
既有[Java业务契约](API_CONTRACT.md)的只读、复核及创建返工端点保持现有请求/响应，M8新增响应不得复用旧创建响应中固定PENDING的Schema。

约束范围为人工修正成果、登记处理证据、人工检查、再次复核及下一轮返工；不执行自动生产重跑或自动成果检查，不推进订单或交付状态。
文中所有示例都是契约样例，不是实际写入记录。身份Header是现有演示上下文，不能描述为真实认证令牌或人工确认凭证。

## 2. 公共格式、身份与权限

新端点沿用六字段信封`success/code/message/data/trace_id/retryable`和`X-Trace-Id`规则。
Java JSON使用camelCase；Python内部使用snake_case并显式绑定别名，前端保留JSON字段名。新请求拒绝未知字段，响应不得靠强制类型转换跳过校验。

| 项目 | v1要求 |
| --- | --- |
| 业务ID | Java生成/读取，1～64位，`^[A-Z]+-[A-Z0-9][A-Z0-9-]*$`；taskId使用`^TASK-[A-Z0-9][A-Z0-9-]*$`；不接受路径、URL或模型补造的ID |
| expectedVersion、taskVersion | 生产任务共享版本，JSON整数，0～9007199254740991；禁止字符串、布尔、小数及不安全整数；不另设可绕过任务版本的返工版本 |
| roundNumber、processingRevision、各sequence | 正整数且不超过9007199254740991；缺失历史信息以null表示，不使用0占位；序号由Java事务内分配 |
| artifactId、artifactVersion | 分别最多256、128个UTF-16单元，非空白、无首尾空白，原样保存；不是平台业务ID，不套大写ID正则、不转数字、不改变大小写 |
| 处理/检查/复核说明、异常/恢复/下一轮原因 | 非空白，最多1000个UTF-16单元；原样保存，不静默裁剪或改写 |
| evidenceReferences | 1～20项，每项非空白、无首尾空白且最多1024个UTF-16单元；只登记引用，不下载或执行引用，不把引用存在等同于原件真实完整 |
| 检查项 | 1～50项；checkItem非空白且最多128个UTF-16单元，result仅PASSED/FAILED，comment和evidenceReferences按上述规则 |
| 字符长度一致性 | Java与前端按UTF-16单元；Python须显式使用相同长度规则。各端不得自动strip标识、版本和引用，避免绑定值悄悄变化 |
| 人员与时间 | 写入人从实际请求身份确定，写入时间由Java生成UTC ISO-8601字符串；请求不得提交inspectorId、reviewedBy或登记时间 |
| Header | 新端点要求非空白且最多128位、无CR/LF的X-User-Id和精确REVIEWER角色；写入还要求1～128位`^[A-Za-z0-9._:-]+$`的Idempotency-Key |

以下为确定性权限映射，T806已落实READ_REWORK，T807/T808已落实Java START_REWORK/BLOCK_REWORK/FAIL_REWORK角色校验，独立Approval仍待接线；新端点Java角色均为REVIEWER，缺失身份401、角色不足403，不扩展复杂RBAC。

| operation | Python权限 | 独立人工确认 |
| --- | --- | --- |
| READ_REWORK | REWORK_READ | 否 |
| CREATE_LIFECYCLE_REWORK | REWORK_WRITE | 是，受控首轮创建，不能复用旧CREATE_REWORK确认单 |
| START_REWORK | REWORK_WRITE | 是 |
| BLOCK_REWORK | REWORK_WRITE | 是 |
| FAIL_REWORK | REWORK_WRITE | 是 |
| RESUME_REWORK | REWORK_WRITE | 是 |
| REGISTER_REWORK_RESULT | REWORK_WRITE | 是 |
| REGISTER_REWORK_INSPECTION | REWORK_WRITE | 是，卡片须列出通过时完成返工及问题变为RESOLVED的副作用 |
| SUBMIT_REWORK_REVIEW | REVIEW_WRITE | 是，区别于旧SUBMIT_REVIEW确认单 |
| CREATE_NEXT_REWORK | REWORK_WRITE | 是，不能复用上一轮创建或复核确认 |

Python由服务端角色确定权限集合，不接受页面或模型自报权限。Java重验身份、角色、资源归属、版本和状态；
Approval归属、草稿与实际确认人、有效期及唯一执行权由Python确认服务负责，Java不直接访问Agent表。
Java Header或请求中的approval_id不是人工确认的证明；新Java业务请求不接受confirmed、role、permissionScope或approval_id作为授权依据。

## 3. 读取接口与缺失历史

下表仅GET R已由T806实现，其余路径仍待实现；`B=/api/tasks/{taskId}/reworks`，`R=B/{reworkTaskId}`。查询只返回Java事实，每次响应内部使用一致读取快照。

| 方法与路径 | data内容 | 对应后续实现 |
| --- | --- | --- |
| GET B | taskId、taskVersion、reworkTasks摘要数组、nextCursor | M8.2查询 |
| GET R | ReworkDetail | T806已实现，当前材料从V5读取；材料写入仍待后续阶段 |
| GET R/results | taskId、reworkTaskId、records处理修订数组、nextCursor | M8.3 |
| GET R/inspections | taskId、reworkTaskId、records检查数组、nextCursor | M8.3 |
| GET R/reviews | taskId、reworkTaskId、records复核数组、nextCursor | M8.4 |
| GET /api/tasks/{taskId}/effective-reviews | taskId、taskVersion、issues有效复核分组数组 | M8.4，替代新生命周期中的历史混合判断 |
| POST B/operations/query | 请求仅idempotencyKey；data为found及receipt（未见回执时null） | Java部分在M8.2实现，供后续结果未知核对使用；这是只读查询，不要求确认或写入幂等Header |

列表/历史分页参数仅cursor和limit，limit默认20、最大100；cursor由服务端生成，绑定用户、任务、返工/历史类型及首屏序号上界，
后续页面按该上界读取，不能将cursor当权限凭证。非法/不匹配cursor为400；结束时nextCursor=null，空集合为[]。
历史按Java递增序号升序，返工列表按受控创建序号升序；不按UUID或客户端时间猜最新。存量记录使用已有稳定排序，不伪造生命周期序号。
详情和各历史页是各自的读取快照；写入必须重新读取，不能把多页内容当同一写入快照。

ReworkSummary字段为reworkTask（原ReworkTaskDto全部字段）、issueStatus（无来源时null）、roundNumber（无轮次时null）、
previousReworkTaskId（首轮/存量为null）和allowedActions数组。ReworkDetail在摘要外增加taskVersion、processing、inspection、review；
后三项无当前材料时均为null，不能补造空对象、通过结论或默认轮次。allowedActions仅为第2节写operation的子集，
只反映当前快照的允许操作，不是执行凭证。
历史只保留真实已登记记录，存量无证据时records=[]；旧overview.reworkTasks及旧DTO不增加必填字段、不改变既有状态值。

| 记录 | 必须返回的字段（除说明外均不省略） |
| --- | --- |
| 处理修订processing | processingRevision、artifact（artifactId/artifactVersion）、processingComment、evidenceReferences、registeredBy、registeredAt |
| 检查inspection | inspectionId、inspectionSequence、roundNumber、processingRevision、inspectorId、inspectedAt、result、items；items使用第2节字段 |
| 复核review | reviewId、reviewSequence、roundNumber、processingRevision、inspectionId、status、reviewComment、reviewedBy、reviewedAt |

人员、时间和各序号为服务端事实；外部材料引用不直接证明其内容未变化，不能将对引用字符串的相等校验描述为原件校验。
新详情/历史须先校验父任务存在及返工归属；不存在404、路径归属不匹配409，不泄露其他资源详情。
operations/query按用户及父任务限定幂等回执，不能读取他人的结果；found=false只表示当前快照没有可见成功回执，
不能据此证明原写入一定没有发生或自动重发。匹配回执返回首次成功内容，不读取后来状态拼造“原结果”。

## 4. 写入接口与请求体

所有下列新写入只接受明确列出的JSON字段，字段均必填；首轮创建通过sourceIssueId指定待核对的问题，其他动作从路径确定目标，
不能在请求中改报taskId、issueId、轮次、当前状态、人员或时间。
expectedVersion必须来自最新Java事实。所有写入仅在生产任务COMPLETED且资源关联正确时允许。

| 方法与路径 | 请求字段 | operation及业务前提 |
| --- | --- | --- |
| POST B | sourceIssueId、expectedVersion、reason | CREATE_LIFECYCLE_REWORK；问题OPEN、无受控前驱及活动返工，创建受控PENDING首轮；Java部分随M8.4/T819首轮/后继创建实现 |
| POST R/start | expectedVersion | T807已实现Java START_REWORK；PENDING/OPEN → RUNNING/PROCESSING，独立确认接线待后续 |
| POST R/block | expectedVersion、reason | T808已实现Java BLOCK_REWORK；RUNNING/PROCESSING → BLOCKED/PROCESSING |
| POST R/fail | expectedVersion、reason | T808已实现Java FAIL_REWORK；RUNNING/PROCESSING → FAILED/PROCESSING |
| POST R/resume | expectedVersion、reason | RESUME_REWORK；BLOCKED或FAILED/PROCESSING → RUNNING/PROCESSING |
| POST R/results | expectedVersion、artifact、processingComment、evidenceReferences | REGISTER_REWORK_RESULT；仅RUNNING/PROCESSING，生成新的processingRevision，旧修订保留 |
| POST R/inspections | expectedVersion、processingRevision、items | REGISTER_REWORK_INSPECTION；仅RUNNING/PROCESSING，检查须绑定当前处理修订 |
| POST R/review | expectedVersion、processingRevision、inspectionId、status、reviewComment | SUBMIT_REWORK_REVIEW；仅COMPLETED/RESOLVED，status为APPROVED/REJECTED/REWORK_REQUIRED |
| POST R/next-round | expectedVersion、reason | CREATE_NEXT_REWORK；当前轮COMPLETED/OPEN且有效复核为REJECTED或REWORK_REQUIRED，无活动返工；生成后继PENDING轮次 |

检查请求不提交总体result，由非空items确定：任一FAILED则总体FAILED、返工仍RUNNING/问题PROCESSING；全部PASSED则在同一事务
保存检查、执行T803 COMPLETE约束、将返工置为COMPLETED及问题置为RESOLVED。这是一次明确审查并确认的写操作，不再另设complete接口。
复核通过原子保存复核并关闭问题；退回保存结论并回到OPEN，本轮返工仍COMPLETED，不自动创建下一轮或改变交付状态。
下一轮的reworkTaskId、轮次和前驱由Java分配并核对真实前驱，不能由客户端指定；新轮无成果、检查或有效复核。

新写入成功的data为ReworkWriteReceipt，所有键固定存在：

| 字段 | 含义 |
| --- | --- |
| operation、operationId | 第2节operation及服务端操作日志ID；不是Approval身份或确认凭证 |
| taskId、reworkTaskId、taskVersion | 受影响任务、返工及本次事务递增后的任务版本；下一轮返回新返工ID |
| status、issueStatus、roundNumber | 事务完成后的返工/问题状态及真实轮次 |
| previousReworkTaskId | 首轮为null，后继轮为真实前驱ID |
| processingRevision、inspectionId、reviewId | 本次提交后当前有效的绑定；未登记或已失效时为null |

写入回执只记录该次成功，不代表以后查询仍处于该状态。任务版本在一次写事务内只递增一次，包括“检查通过+完成返工”的原子动作；
失败回滚不能遗留半条检查、部分状态变化、操作日志或成功幂等回执。未通过检查也是真实新检查写入，仍递增版本并审计。

开始请求示例：

```json
{"expectedVersion": 2}
```

登记成果请求示例：

```json
{
  "expectedVersion": 3,
  "artifact": {"artifactId": "demo-product-A", "artifactVersion": "release-2"},
  "processingComment": "已修正坐标系并重新生成成果，等待人工检查。",
  "evidenceReferences": ["report:coordinate-fix-2"]
}
```

检查请求示例：

```json
{
  "expectedVersion": 4,
  "processingRevision": 1,
  "items": [{
    "checkItem": "坐标系",
    "result": "PASSED",
    "comment": "人工核对成果坐标系与本次检查要求一致。",
    "evidenceReferences": ["report:coordinate-check-2"]
  }]
}
```

再次复核请求示例：

```json
{
  "expectedVersion": 5,
  "processingRevision": 1,
  "inspectionId": "CHECK-WRITE-TEST",
  "status": "APPROVED",
  "reviewComment": "已审查本轮成果及检查记录，确认通过。"
}
```

## 5. 当前材料与有效结论

processingRevision由Java按返工连续递增，当前修订是唯一提交目标。更新成果、说明或证据必须新增修订，旧修订不可覆盖，
并使旧检查失去对当前成果的适用性；不能因为artifactVersion文本相同就认为材料没有变化。
当前检查取当前processingRevision下最大的inspectionSequence，包含FAILED；不能越过新失败去取旧PASSED。
新检查必须引用当前修订，T802完整材料相等检查与T803 PASSED前提都必须满足，客户端指定inspectionId只是要求校验的目标。

有效复核须匹配当前返工/轮次、当前processingRevision和当前PASSED检查，取该绑定下最大的reviewSequence。
新轮、材料变化或无有效绑定时review=null，历史仍完整保留；不按随机ID、模型文本或“存在任意APPROVED”认定通过。
effective-reviews每项包含issueId、reworkTaskId、roundNumber、processingRevision、inspectionId、review和legacyReviews：
有生命周期时返回真实绑定及review（可null），legacyReviews=[]；无生命周期时这些绑定为null，legacyReviews保留旧ReviewRecordDto数组，
不伪造有效结论。后续Python对前者使用Java有效复核，对后者显式保留旧规则，旧历史查询不删记录、不混成新有效结论。

## 6. 独立确认、并发与幂等

每项新写入各有独立Approval及本次幂等键；检查确认卡片必须展示其对返工和问题的全部状态副作用，复核/下一轮不能复用旧确认。
写Tool仅接受approval_id与idempotency_key，从已确认快照获取业务参数；模型或页面不能直接覆盖确认后的正文、目标或版本。
快照绑定实际用户、operation、任务/返工/来源问题/轮次、expectedVersion、当前processingRevision/inspectionId及最终请求材料，
并保存既有确认生命周期所需的归属与有效期。登记/检查类输入可以编辑，但任何编辑都必须进入本次最终审查快照后再确认。

确认前Python重新读取Java事实并校验快照，变化时STALE、不写入，需重新生成可审查草稿；取消和过期同样零写入。
Java在写事务内再次核对角色、归属、版本、状态和当前材料，不能信任确认前的一次只读结果。
按现有“唯一执行权+幂等”处理重复确认；相同用户/键/operation/目标/完整请求（含原expectedVersion）重放返回首次成功回执，
不因后来状态变化再次落库；同键异用户、异operation、异目标或异内容均409，不将冲突悄悄改成新请求。
顺序为身份/权限及输入校验 → 查询匹配的成功幂等回执 → 无回执时重新校验当前业务事实 → 唯一版本更新及原子写入。
幂等键日志只保存哈希，保留原请求绑定和原成功回执；不得从当前实体重建旧回执。

超时或通用500时写入结果可能未知：先查本人Run/操作日志及Java回执，禁止自动换键重试。
查不到回执不代表未执行；需要恢复时由用户明确继续，用原键及原请求核对/重放，不能把新的事实拼进旧键。
Python只读Tool仅对明确瞬时错误有限重试，400/401/403/404/409或响应校验错误不重试。

## 7. 存量兼容与创建边界

本节是后续M8写服务启用时的要求，不在T804或仅有T805迁移时改变当前创建行为。
旧`POST /api/tasks/{taskId}/rework`继续接受sourceIssueId、reason、expectedVersion，并返回原reworkTask/taskVersion结构，
其记录保持旧生命周期，不自动补轮次；新受控首轮显式调用`POST /api/tasks/{taskId}/reworks`，返回第4节新回执。
旧复核写入仍只追加记录，不能通过旧接口伪装成M8问题关闭。新生命周期复核必须使用第4节新路径和独立确认。
旧创建的成功重放也必须保留首次PENDING及原taskVersion；M8执行导致当前状态变化后，不得用当前实体重建原创建回执，
以免破坏既有Python创建响应的固定PENDING约束。
首个受控创建同时保存真实轮次元数据，轮次从本功能受控链路的1开始，不声称编号覆盖未纳管的历史返工。
若同一来源问题已有受控链路，新旧首轮创建入口均不能跳过前驱再建“首轮”，应使用next-round；匹配成功幂等请求仍先返回原结果。
创建首轮仍检查既有PENDING/RUNNING/BLOCKED返工防重；受控链路中的FAILED只能恢复，不允许绕过为其创建并行轮次。

存量缺轮次/材料的返工保持原值，新详情roundNumber及材料为null、allowedActions=[]；不自动补轮次、检查、人员或时间，
也不提供本阶段计划外的自动纳管功能。查询仍可查看这些记录，有活动存量返工时不绕过原防重规则创建首轮。
新旧消费者并存期间，Python新增Schema/HTTP Client及前端新类型单独接线，不修改旧创建响应的PENDING约束或旧overview渲染契约。
首轮Java创建与后继创建在T819实现后，Python新首轮操作才接受CREATE_LIFECYCLE_REWORK确认快照；旧写Tool不被静默切到新路径。
Agent首版仍仅沿用坐标系返工语义，新增HTTP及领域类型不代表模型已获得其他质量问题的自动处置能力。
字段变化须在后续实现批次同步Java、Python、前端与测试，不能将本轮文档冻结当作三端已装配。

## 8. 错误、后续验收与停止线

| HTTP / code | 新接口的失败边界 |
| --- | --- |
| 400 / PARAM_VALIDATION_ERROR | 缺字段、未知字段、非法类型/枚举/长度、非安全整数、非法cursor；错误文案不回显完整证据、身份或原件引用 |
| 401或403 / PERMISSION_DENIED | 缺身份或权限不足；不得降级成无需确认的写入 |
| 404 / RESOURCE_NOT_FOUND | 父任务/返工/指定修订或检查不存在；无历史的集合成功返回[] |
| 409 / BUSINESS_CONFLICT | 归属/版本/状态/修订/检查过期、重复活动返工、非当前检查、同键异请求、缺生命周期元数据；不能靠重试绕过 |
| 500 / INTERNAL_SERVER_ERROR | 不暴露底层异常，retryable=false；写入按结果未知处理 |

既有错误码和信封不增加新变体，新请求合法但资源状态不允许时用409，不能把领域异常直接泄露为通用500。
后续需验收：未知字段和自报确认/权限拒绝；中文及非BMP字符长度一致；重复/并发确认；版本或材料变化；
最新检查失败但旧检查通过；旧成果通过不能放行新轮；通过检查的原子完成与回滚；退回后独立下一轮；
缺证据/轮次的历史只读；旧路径/DTO及ORDER-003初始黄金链路不变；写入超时核对不冒充未执行。

T804只冻结本文和三端字段映射，示例不是实际操作记录；T806交付GET R，T807交付POST R/start，T808交付POST R/block及R/fail，其余新HTTP及三端确认验收留在后续任务。
T805已实现增量SQL存储和隔离升级测试，未修改旧迁移、固定数据或运行库；M8.1已验收，M8.2已接入详情及Java开始/异常写入。

## 9. T805存储实现边界

V5新增rework_lifecycles、rework_processing_revisions、rework_inspections、rework_reviews及rework_operation_receipts，
通过复合外键约束返工/任务/问题、连续同源前驱、检查对应的成果修订及复核对应的PASSED检查。
旧幂等和审计操作集合扩展为支持新operation，旧行及旧字段不变；新回执还绑定原用户、请求摘要、返工资源、任务版本及日志。
新M8幂等resource_id固定为回执中的reworkTaskId，旧SUBMIT_REVIEW/CREATE_REWORK资源含义保持不变。
回执JSON约束核心身份/版本、键集合和状态枚举；完整HTTP类型、权限和条件组合仍由后续Java请求/响应及应用校验负责。

材料/检查/复核/回执追加后不可修改或删除；生命周期创建身份、归属与前驱不可修改，开始人员/时间成对且只记录一次。
新复核独立存入rework_reviews，不改写、复制或补造旧review_records；有效复核查询仍按第5节新旧分支实现。
数据库函数与约束不证明原件真实、操作者身份可信或检查当前有效，不自动流转业务状态、不应用Approval、不替代任务版本并发校验。
T805当时只以JDBC隔离夹具验证存储；T806新增只读Repository、应用服务与详情HTTP，业务写入仍待后续任务。
V5在未来Java启动时随Flyway应用，本次未部署或查询运行库；旧V1～V4迁移和ORDER-003固定事实保持原样。

## 10. T806详情读取实现边界

`GET /api/tasks/{taskId}/reworks/{reworkTaskId}`每次先校验请求身份和业务ID，再以REPEATABLE READ READ ONLY事务依次读取父任务、归属与当前材料。
父任务或返工不存在返回404，返工属于其他任务返回409且不返回材料；六字段信封和旧接口保持不变。
当前成果取最大processingRevision，检查只取该修订最大inspectionSequence，复核只取当前PASSED检查绑定下最大reviewSequence。
新修订、新检查或最新失败使旧检查/复核不再作为当前结论，历史数据不被删除；未登记字段显式为null。
allowedActions表达当前状态及材料前提，包含后续计划动作也不表示对应写接口已装配，不代替独立人工确认或执行时重校验。
详情不调用模型、不验证外部证据原件、不写状态/轮次/版本或操作记录，不纳管存量，也不实现列表、历史分页、操作回执查询及写HTTP。

## 11. T807开始返工实现边界

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/start`只接受application/json及唯一expectedVersion安全整数；拒绝重复键、尾随JSON、未知字段、类型强转和自报确认/状态/人员/时间。
Java重验REVIEWER身份、业务ID和安全幂等键。新请求先预留幂等绑定、锁父任务，再核对共享版本、生产COMPLETED、受控轮次、未登记开始信息、无后继及返工PENDING/问题OPEN。
同一事务将返工改为RUNNING、问题改为PROCESSING，按实际请求身份和服务端UTC时间写一次开始元数据，任务版本仅加一且原生产状态不变。
幂等完成、受控前后状态审计和固定12字段成功JSON回执同事务保存；任一步失败整笔回滚，不自动补轮次或迁移旧记录。
同用户、键、operation、目标和完整请求重放只返回首次回执；版本、用户、目标或操作不同返回409。后续状态变化不重写原回执或再次改变业务。
开始只登记人工处理流程，不调用成果修正程序。Header不是人工确认凭证，Java不访问Agent表；Python确认/写Tool、页面及独立回执查询HTTP仍在后续阶段。
本轮只对齐ReworkRound为long及正安全整数范围，不改变轮次分配、连续性、旧实体/DTO、V1～V5或固定数据；已有SQL范围保持。

## 12. T808阻塞与失败登记实现边界

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/block`及`/fail`只接受application/json中的expectedVersion和reason。
版本须为安全整数；原因须为非空白字符串、最多1000个UTF-16单元，原样保存空白和合法非BMP字符。拒绝类型强转、未知字段、重复键、尾随JSON，以及无法无损写入UTF-8文本的NUL或未配对代理项。
Java重新校验REVIEWER身份、归属、受控轮次、无后继、共享版本及原生产COMPLETED；仅返工RUNNING且问题PROCESSING允许登记，PENDING/BLOCKED/FAILED/COMPLETED均不能由本接口覆盖。
预留幂等绑定并锁父任务，按版本条件递增一次任务版本；锁定并保留问题PROCESSING，将返工条件更新为BLOCKED或FAILED。
异常原因记录在本次operation_logs.after_state.reason，不覆盖reworkTask.reason的原始创建原因；开始人员/时间、成果修订、检查、复核和历史记录均不变。
状态、版本、完整请求幂等绑定、审计和固定12字段成功回执同事务提交，审计或回执失败全部回滚。请求摘要包含具体operation及原因原值，同键换动作、用户、目标、版本或原因均409；同请求只重放首次回执。
返回本次提交后的状态和当前材料指针，不沿用旧修订或旧通过复核。HTTP超时或500不能自动推断业务FAILED，也不允许自动换键重试。
未新增迁移、异常原因独立查询字段或历史分页；独立Approval/写Tool、页面、受控恢复及自动处理均未接入，恢复仍按T809单独实现。
