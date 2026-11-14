# M8返工生命周期契约 v1（M8.1～M8.4已验收，T821/T822 Python契约及内部只读Tool离线验收通过）

## 1. 适用范围与实现边界

本契约冻结后续Java查询/写入、Python Tool及前端共同使用的M8边界，关联[详细计划M8.1](../planning/detailed-plan.md#m81-返工领域与契约)。
T801～T805已完成领域、契约与SQL存储；T806接通GET R详情，T807接通POST R/start，T808接通POST R/block及R/fail，T809接通POST R/resume的Java校验与原子写入；T810完成本组跨操作一致性验收，T811/T812接通POST R/results成果及R/inspections人工检查登记，T813/T814完成更新材料与检查通过原子性验收，T815接通成果修订/检查历史GET并完成M8.3验收，T816接通任务级有效复核及本返工复核历史GET，T817/T818接通复核POST的通过关闭和退回OPEN分支。
T819受控首轮POST B及后继POST R/next-round、T820订单级只读交付条件查询均已通过本机验收，详见第23/24节。T821独立Python契约及T822内部只读Tool已通过离线验收，详见第25/26节；新Tool尚未生产装配，其余新增Java路径、新写Tool、独立Approval及前端接线尚未实现，不能描述为完整人工确认闭环。
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

以下为确定性权限映射，已接通的M8 Java读取及写入端点均落实REVIEWER角色校验；T822内部只读Tool落实REWORK_READ上下文门禁，生产角色映射、新写Tool及独立Approval仍待接线。新端点Java角色均为REVIEWER，缺失身份401、角色不足403，不扩展复杂RBAC。

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

下表GET R由T806实现，GET R/results及R/inspections由T815实现，GET R/reviews及任务级effective-reviews由T816实现，订单级delivery-conditions由T820实现并验收；T824前置已补齐operations/query的Java查询和Python Schema，列表仍待实现。`B=/api/tasks/{taskId}/reworks`，`R=B/{reworkTaskId}`；查询只返回Java事实，每次响应内部使用一致读取快照。

| 方法与路径 | data内容 | 对应后续实现 |
| --- | --- | --- |
| GET B | taskId、taskVersion、reworkTasks摘要数组、nextCursor | M8.2查询 |
| GET R | ReworkDetail | T806已实现，当前材料从V5读取；成果/检查/复核分别由T811/T812/T817～T818写入 |
| GET R/results | taskId、reworkTaskId、records处理修订数组、nextCursor | T815已实现，按processingRevision升序 |
| GET R/inspections | taskId、reworkTaskId、records检查数组、nextCursor | T815已实现，按inspectionSequence升序 |
| GET R/reviews | taskId、reworkTaskId、records复核数组、nextCursor | T816已实现，按reviewSequence升序 |
| GET /api/tasks/{taskId}/effective-reviews | taskId、taskVersion、issues有效复核分组数组 | T816已实现，T821/T822提供Python契约及内部只读Tool，诊断消费未装配 |
| GET /api/orders/{orderId}/delivery-conditions | order、tasks、deliveryRecords、blockers、hasBlockers | T820已开发待验收，字段及条件见第24节；无查询参数 |
| POST B/operations/query | 请求仅idempotencyKey；data固定为found及receipt（未见回执时显式null） | T824 Java/Client/独立只读核对Tool已验收，含真实查询联调；不恢复确认终态，见第28～29节 |

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
| POST B | sourceIssueId、expectedVersion、reason | T819已开发、待验收；CREATE_LIFECYCLE_REWORK，问题OPEN、无受控链及活动返工，创建受控PENDING首轮 |
| POST R/start | expectedVersion | T807已实现Java START_REWORK；PENDING/OPEN → RUNNING/PROCESSING，独立确认接线待后续 |
| POST R/block | expectedVersion、reason | T808已实现Java BLOCK_REWORK；RUNNING/PROCESSING → BLOCKED/PROCESSING |
| POST R/fail | expectedVersion、reason | T808已实现Java FAIL_REWORK；RUNNING/PROCESSING → FAILED/PROCESSING |
| POST R/resume | expectedVersion、reason | T809已实现Java RESUME_REWORK；BLOCKED或FAILED/PROCESSING → RUNNING/PROCESSING |
| POST R/results | expectedVersion、artifact、processingComment、evidenceReferences | T811已实现Java REGISTER_REWORK_RESULT；仅RUNNING/PROCESSING，生成新的processingRevision，旧修订保留 |
| POST R/inspections | expectedVersion、processingRevision、items | T812已实现Java REGISTER_REWORK_INSPECTION；仅RUNNING/PROCESSING，检查须绑定当前处理修订，通过分支原子完成本轮并将问题置为RESOLVED |
| POST R/review | expectedVersion、processingRevision、inspectionId、status、reviewComment | T817/T818已实现APPROVED/REJECTED/REWORK_REQUIRED；仅COMPLETED/RESOLVED，通过后关闭问题，退回后问题OPEN，本轮仍COMPLETED |
| POST R/next-round | expectedVersion、reason | T819已开发、待验收；CREATE_NEXT_REWORK，当前无后继轮COMPLETED/OPEN且有效复核为REJECTED或REWORK_REQUIRED，无活动返工；生成后继PENDING轮次 |

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

本节由T819实现首轮/后继创建和旧入口防绕过，已通过本机验收；T804冻结和T805迁移本身未改变旧创建行为。
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
首轮Java创建与后继创建已由T819开发，Python新首轮操作及CREATE_LIFECYCLE_REWORK确认快照仍待后续接线；旧写Tool不被静默切到新路径。
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

T804只冻结本文和三端字段映射，示例不是实际操作记录；T806交付GET R，T807交付POST R/start，T808交付POST R/block及R/fail，T809交付POST R/resume；T811/T812交付成果及检查POST，T815交付对应历史GET，其余新HTTP及三端确认验收留在后续任务。
T805已实现增量SQL存储和隔离升级测试，未修改旧迁移、固定数据或运行库；M8.1～M8.3已验收，详情、Java开始/异常/恢复、成果/检查登记及历史读取已接通。

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
T808未新增迁移、异常原因独立查询字段或历史分页；独立Approval/写Tool、页面及自动处理均未接入，受控恢复由T809单独实现，见下一节。

## 13. T809受控恢复实现边界

`POST R/resume`要求REVIEWER身份及安全Idempotency-Key，请求严格且仅含expectedVersion、reason，沿用第12节原样文本、UTF-16长度及无损UTF-8规则；不接受自报确认、身份、当前状态或时间。
复用T803 RESUME约束，锁父任务后重验归属、受控轮次、无后继、共享版本及原生产COMPLETED；仅返工BLOCKED或FAILED且来源问题PROCESSING可恢复，原状态条件更新为RUNNING，问题仍PROCESSING，版本只加一。
恢复说明保存于新操作RESUME_REWORK的operation_logs.after_state.reason，操作者和时间取实际请求身份及服务端审计时间；不重写原开始人员/时间、创建原因、旧异常原因或任何成果/检查/复核历史。
状态、版本、完整请求幂等绑定、新审计和固定12字段成功回执在同一事务提交或回滚。请求摘要包含operation、目标、原expectedVersion和reason原值，换用户/目标/版本/原因/动作不能复用同一键。
同请求重放只返回首次成功JSON；若后来再次阻塞或失败，旧恢复回执仍为首次RUNNING及原版本，不执行新恢复，当前事实通过详情另读。只恢复人工处理流程，不触发生产重跑、外部修正、自动检查或自动写入重试。
返回材料指针仍按当前修订和检查绑定，不把旧通过或旧复核作为最新结论；无轮次的存量拒绝恢复，不补造生命周期。
无新迁移、恢复说明独立查询、列表分页、Python独立Approval/写Tool或页面接线；Header不能证明已人工确认。T809交付时下一任务为T810，本组收口结果见下一节，尚不能登记成果、完成返工或关闭问题。

## 14. T810跨操作一致性验收边界

M8.2已完成详情、开始、阻塞/失败及恢复的Java验收；T810仅补充跨操作测试和Make入口，没有新增端点或变更运行实现、Schema、请求/响应及固定事实。
真实HTTP在独立schema中验证四种动作的全局同键竞争：不同操作或目标不能共用键提交，同键异内容不能接管结果，已提交的未完成预留返回409且保持原样。
四种动作分别与旧SUBMIT_REVIEW争同一任务版本，只允许一个提交，失败方不留下业务记录、幂等或审计；不代表已实现M8再次复核。
分别在幂等完成UPDATE、审计INSERT和回执INSERT注入数据库故障，要求状态、版本、开始元数据及操作记录整体回滚；移除故障后原键可重提，不在产品中增加自动重试。
开始→阻塞→恢复→失败后逆序重放所有旧请求，只返回各自原成功JSON及原版本，当前仍为FAILED/PROCESSING；ORDER-003固定关联事实逐行保持。
M8.2在停止线收口，当时下一最小任务T811成果登记现已接通，见下一节；人工检查已由T812接通，问题关闭、独立Approval和三端入口仍待开发，本组验收不扩大现有接口权限或宣称完整返工闭环。

## 15. T811成果登记实现边界

`POST R/results`要求REVIEWER身份和安全Idempotency-Key，严格且仅接受第4节四个请求字段，artifact也仅含artifactId/artifactVersion。
版本须为安全整数，材料遵守第2节UTF-16长度、原值和空白规则；拒绝未知/重复字段、类型强转、尾随JSON、NUL或未配对代理项，不接受自报修订、人员、时间、结论或确认。
Java预留完整请求幂等绑定，锁父任务后重新核对归属、受控轮次、无后继、共享版本及原生产COMPLETED；仅RUNNING/PROCESSING可登记，无生命周期的存量返回409且不自动纳管。
锁定本轮及来源状态，按本返工最大修订连续加一；修订或任务版本达到安全整数上限拒绝，不生成不安全数字。
在同一事务追加原样artifact、说明、证据引用与实际请求人/服务端UTC时间，任务版本加一，保存审计、幂等完成及固定12字段原成功回执；任一步失败全部回滚。
材料和回执不可覆盖，同键绑定operation、目标、原预期版本及完整材料（含引用顺序和说明空白）与用户；同请求重放只返回首次回执，不因后来阻塞或新修订重建结果。
成果版本文本相同也新增修订；原材料/检查/复核历史保留，当前详情按新修订绑定，inspectionId/reviewId为空，不把旧通过用于新材料。
成果登记后返工仍RUNNING、问题仍PROCESSING、原生产仍COMPLETED，不访问或执行引用、不验证原件、不生成检查结论或解除交付阻塞；人工检查已由T812接通、T814完成专项收口，T815已实现历史分页并完成M8.3收口，见第19节。
本任务仅交付Java登记底座，不改变旧DTO、迁移、固定数据或Python/前端契约实现；Header不是确认凭证，独立Approval/写Tool、确认失效处理与页面仍待后续。

## 16. T812人工检查登记实现边界

`POST R/inspections`要求REVIEWER身份及安全Idempotency-Key，严格且仅接收expectedVersion、processingRevision和items；每项严格包含checkItem、result、comment和evidenceReferences，按第2节格式原样校验。
不接受总体result、检查人/时间/序号、状态或确认字段；Java依据非空检查项确定总体结论，实际请求人和服务端UTC时间作为检查记录的人员与时间，不访问外部成果或证据。
预留完整请求幂等绑定并锁父任务后，重验归属、受控轮次无后继、共享版本、原生产COMPLETED、RUNNING/PROCESSING和明确的当前processingRevision；缺材料、旧修订、跨资源或非法状态拒绝且无副作用。
检查序号按本返工所有修订的最大inspectionSequence连续加一，正安全整数上限拒绝递增；旧检查及材料不可覆盖。
任一检查项FAILED则保存总体FAILED，返工仍RUNNING且问题PROCESSING；全部PASSED经既有领域COMPLETE约束，检查记录与返工COMPLETED、问题RESOLVED原子保存，原生产保持COMPLETED。
为避免公开“已通过但未完成”的中间状态，最小通过分支与T812一并接通、T814完成专项原子性收口；不另设complete接口、不关闭问题、不推进订单或交付。
检查、共享版本递增一次、幂等完成、审计和固定12字段原回执同事务提交或回滚；回执包含当前修订及本次inspectionId，reviewId为null。
同用户/键/操作/目标/原版本/修订/完整检查项重放只读首次回执；改变任一绑定或项/引用顺序冲突，后来的通过不能改写旧失败回执或再次执行旧操作，当前事实通过详情查询另读。
T812本身没有新增迁移或变更旧接口，不代表M8.3整体验收；历史GET和阶段验收已由T815完成。独立Approval/写Tool、确认快照失效处理、再次复核及页面仍待后续，Header不能证明人工确认。

## 17. T813失败检查与成果更新验收边界

T813只增加真实HTTP跨接口验收和Make入口，不新增端点或改变运行实现、Schema、固定事实及既有请求/响应。
成果标识、版本、说明或证据变化，以及相同材料再次登记，都会新增修订；旧检查与修订保留，当前inspection/review为空，未通过检查不完成返工或解决问题。
新检查必须同时满足最新expectedVersion与当前processingRevision，Java对旧版本、旧修订或二者都旧返回409且无副作用；同修订重复检查也必须使用最新版本。
旧登记及失败检查的成功请求可重放原回执，后来通过或更新材料不能重建旧结果、重复写入或使旧FAILED重新成为当前结论；已完成轮次不能再追加材料。
并发测试先持有父任务锁，确认两个HTTP写事务均实际等待锁后再放行，验证检查与更新、两次不同更新争同版本时只一方提交，失败方不留幂等、审计或额外记录。
更新事务在审计或回执写入失败时全部回滚，旧失败检查继续作为当前结论；移除故障并显式重新提交成功后，新修订才使旧检查不再适用，产品不自动重试或改键。
这里验收的是Java拒绝过期业务参数；Python Approval快照STALE、独立确认、写Tool和页面仍待M8.5～M8.7，不将后续能力描述为已实现，也不证明跨服务全局只执行一次。
T814检查通过的原子性专项收口已完成，见下一节；T815历史分页及M8.3整体验收已完成，见第19节；再次复核或关闭问题留待M8.4。

## 18. T814检查通过原子性验收与零行写入防护

检查通过仍沿用POST R/inspections，不新增端点、请求字段、迁移或状态；完成与问题解决是同一请求的原子副作用，不能另行确认或提交一半。
版本、检查INSERT、返工完成、问题解决、幂等完成、审计与回执各写入点抛出异常时全部回滚；在COMMIT时触发延迟约束失败同样返回500且零残留，不因方法主体已执行完就提前报告成功。
所有写入必须实际影响一行。T814修复共用audit/saveReceipt不返回写入数的缺口，开始、异常/恢复、成果及检查服务均检查返回值；SQL未抛异常但写入为零也返回409并整体回滚，不能提交缺少审计或原回执的成功。
三处事务中途暂停的真实HTTP验收确认：返工已更新但问题未更新、业务状态已更新但幂等未完成、回执尚未写入时，其他详情GET及SQL观察仍只能读取旧完整事实，释放后才读到本轮COMPLETED/问题RESOLVED和新检查。
同键同请求返回原始成功JSON，新键或新版本不能重复完成；没有检查项、空检查项及独立complete路径拒绝，失败历史与成果不覆盖。
故障解除后必须由调用方显式重提原未提交键；产品没有增加自动重试。既有成功状态码、回执结构和幂等绑定不变，HTTP错误仍不能让客户端猜测未知请求结果。
本轮只补强Java实际写入与事务成功边界，独立Approval/写Tool及页面仍待后续；问题只到RESOLVED，原生产/订单/交付不推进，T814之后的历史查询与阶段收口由T815完成，见第19节。

## 19. T815成果与检查历史查询及M8.3收口

新增`GET R/results`及`GET R/inspections`，要求REVIEWER身份，返回固定taskId、reworkTaskId、records、nextCursor；处理与检查记录复用第3节完整字段，不截断说明/引用、不按当前修订过滤旧材料或失败历史。检查返回自身真实轮次及处理修订，按本返工Java序号升序，不按ID或时间猜顺序。
只接受单值cursor及limit，limit默认20、范围1～100；未知/重复参数、空值、非整数或越界为400。无材料/未纳管存量返回records=[]、nextCursor=null，不自动补历史；任务/返工不存在404、路径归属不符409。
身份/参数检查后，每页使用独立REPEATABLE READ READ ONLY事务核对父任务、返工归属与材料，拒绝继承调用方读写事务。查询不修改版本、状态、材料、幂等或审计，历史读取不等于当前结论有效或允许执行后续动作。
首屏读取该类型最大Java序号作为上界，以末条返回序号向后分页，多读一条决定nextCursor；到末页显式null。后续追加记录不混入本次翻页，新首页可读到新增材料；各页仍为各自快照，不宣称跨页长期数据库快照。
游标由服务端HMAC签名，绑定用户/任务/返工/历史类型、末条序号及首屏上界；身份和资源上下文以摘要绑定，游标不携带明文用户标识。篡改、换人/目标/类型、格式错误均400，权限仍逐页重验。签名密钥仅保存在本Java实例内存，重启或跨实例会使原游标失效，客户端须重新从首页读取；当前不提供持久密钥或多实例共享游标能力，不把游标作为权限或人工确认凭证。
M8.3已验收：登记→失败检查→更新修订→通过检查仅到本轮COMPLETED/问题RESOLVED，完整历史与原回执保持；终态不能追加或改写材料。无新迁移、依赖、Python/前端装配、自动成果检查、再次复核或关闭问题。下一最小任务T816，但本轮停在M8.3停止线，不启动M8.4。

## 20. T816当前有效复核与复核历史实现边界

新增`GET /api/tasks/{taskId}/effective-reviews`，要求REVIEWER身份且不接受查询参数，固定返回taskId、taskVersion、issues；每个问题的7字段沿用第5节，所有缺失绑定及review显式null，legacyReviews始终为数组，无问题时issues=[]。问题按issueId稳定排序，只作展示顺序，不作为时序判断。
按每个问题最大真实roundNumber选最新受控返工，再取当前最大processingRevision及其最大inspectionSequence，包含最新FAILED；inspectionId保留真实当前检查，即使FAILED也不回退旧PASSED。仅当前检查PASSED时，在相同返工/轮次、修订、检查绑定内选最大reviewSequence，新轮、新材料或新检查不能沿用旧结论，不按ID、时间或存在任意APPROVED选择通过。
无生命周期时reworkTaskId/roundNumber/processingRevision/inspectionId/review均null，legacyReviews保持旧ReviewRecordDto及旧接口reviewId稳定顺序，不制造旧数据缺失的轮次、材料或有效结论；有生命周期时legacyReviews=[]，旧表历史不参与新有效判断。旧review/overview接口、原记录及当前Python规则保持不变。
新增`GET R/reviews`，返回第3节完整9字段复核记录，按本返工全部绑定下reviewSequence升序分页，旧失败、旧修订/检查对应复核仍完整保留；无记录/存量空历史返回[]和nextCursor=null，不从旧表合成新记录。复用T815默认20/最大100、单值cursor/limit校验、首屏序号上界、用户/任务/返工/REVIEWS类型签名绑定与单实例重启/跨实例失效边界。
有效查询在独立REPEATABLE READ READ ONLY事务内读取父任务版本、问题与绑定；历史每页同样使用独立只读快照核对父任务和归属，不继承外层读写事务或把跨页当作同一长期快照。缺身份401、非REVIEWER角色403、非法ID/参数/游标400、不存在404，历史路径归属不符409；错误不回显材料或内部摘要。
本轮只提供读取，不改变状态、版本、审计、幂等或存量，不新增迁移/依赖，不实现复核确认写入、问题关闭、下一轮创建、Python诊断切换或页面。T817仍须重新校验当前事实并独立确认，返回APPROVED也不代表本接口执行了关闭或解除交付阻塞；M8.4未整体验收，下一最小任务T817。

## 21. T817复核通过与问题关闭实现边界

新增`POST R/review`，严格且仅接受第4节五个字段，status的最终枚举为APPROVED/REJECTED/REWORK_REQUIRED；T817先接通APPROVED，T818已补齐两个退回结论，不把PENDING作为最终结论。版本/修订安全整数、检查ID和UTF-16说明遵循公共规则，说明原样保留，拒绝未知/重复字段、尾随JSON、类型强转和不能无损存储的文本。
要求REVIEWER身份与安全Idempotency-Key；新请求先预留完整请求绑定并锁父任务，重验归属、受控轮次无后继、共享版本、原生产COMPLETED、本轮COMPLETED及来源问题RESOLVED。明确修订必须为当前最大修订、inspectionId必须是该修订的最新PASSED检查，不能越过新失败或用旧通过覆盖新材料。重建真实完整处理材料与检查项后执行T803 REVIEW约束，来源问题和本轮状态锁保持至提交。
追加本返工全部绑定下的连续reviewSequence，复核身份由Java生成、reviewedBy取实际请求人、reviewedAt取服务端UTC。复核、来源问题CLOSED、一次共享版本递增、幂等完成、审计及固定12字段成功回执同事务提交；每步要求实际影响一行，异常、零行或COMMIT失败全量回滚，不能出现已关问题但缺审计/原回执的成功。
请求摘要绑定operation、任务/返工、原expectedVersion、processingRevision、inspectionId、status和原样reviewComment，实际用户另与幂等记录核对。相同请求只重放首次成功JSON，后来版本或其他问题变化不重建旧结果；换人/目标/操作/材料/版本或说明均不能借用同键，失败不自动换键重试。
本轮返工与原生产仍COMPLETED，原始原因、开始元数据、全部成果/检查、旧复核及旧回执保留，其他问题不被一并关闭。任务级有效复核和本轮历史可查询新APPROVED，旧review/overview接口与Python诊断保持，不自动推进订单或交付。
无新迁移、依赖、独立Approval/写Tool或页面接线，Header不是人工确认凭证，本Java接口不构成三端确认闭环；退回由T818接通，T819创建及T820交付条件查询已验收，M8.4已在停止线收口。

## 22. T818未通过复核与问题退回实现边界

同一POST R/review现已支持REJECTED及REWORK_REQUIRED，使用原五字段请求和固定12字段回执，不新增端点、状态枚举或迁移。
退回与通过分支执行同样的身份、归属、受控轮次无后继、原生产/本轮COMPLETED、问题RESOLVED、预期版本、当前修订及最新PASSED检查校验，不能因结论未通过就省略检查绑定，也不能越过最新FAILED或复用旧材料。
复用T803 REVIEW领域规则，将未通过结论、原样说明、真实复核序号、实际请求人及服务端UTC时间与来源问题OPEN、一次共享版本递增、幂等完成、审计及原回执在同一事务保存；每步实际一行，异常、零行或COMMIT失败全部回滚。
本轮仍COMPLETED，原生产不回退，创建原因、开始信息、成果、检查、旧复核及旧回执完整保留；只退回来源问题，不改其他问题、订单或交付，不自动创建返工、不重跑生产。
当前有效复核和完整历史输出真实REJECTED/REWORK_REQUIRED；详情允许动作表达下一轮的事实前提，也是T819写入时必须重新检查的条件，不是人工确认或权限凭证。
幂等绑定仍覆盖实际用户、操作、任务/返工、原版本、修订、检查、结论及原样说明；重放旧退回请求只返回首次OPEN回执，后继轮后来关闭问题也不被旧请求重新打开，新键不能在OPEN或CLOSED状态再次退回旧轮。
T818真实HTTP验收覆盖两种退回的完整处理链路、通过/退回/两种退回争同版本、同键重放、逐写入点和提交失败、提交前读取；该批次第二轮状态使用明确隔离SQL夹具，不代表验证过创建API。T819完整两轮HTTP用例现已独立通过本机验收，不能用此前T818结果代替本轮实际结果。
没有Python独立Approval/写Tool、确认界面或诊断切换；T819创建及T820交付条件查询现已通过本机验收，M8.4已收口。

## 23. T819受控首轮与下一轮创建实现边界

新增POST B受控首轮（sourceIssueId、expectedVersion、reason）及POST R/next-round（expectedVersion、reason），返回第4节固定12字段回执。严格拒绝缺失、未知、重复字段、尾随JSON、类型强转、不安全版本、非法资源ID及无法无损保存的说明；原因非空白、最多1000个UTF-16单元且原样保存。人员、UTC时间、返工ID、轮次和前驱均由Java确定，不接受自报确认或轮次。

新请求先保留全局幂等键，再锁父任务重读版本与状态；只允许原生产COMPLETED且安全可递增的最新版本。来源问题须同属父任务且OPEN，持锁保持到提交。活动返工包括旧PENDING/RUNNING/BLOCKED，以及受控FAILED；FAILED受控轮只能恢复，不能另建并行轮。

首轮要求同源问题尚无受控链，创建从1开始的真实受控轮次，不将旧COMPLETED/FAILED返工自动纳管或作为前驱。下一轮从路径确定前轮，必须受控、COMPLETED、无后继、问题OPEN，当前成果对应的最新检查PASSED，且同绑定最新复核为REJECTED或REWORK_REQUIRED；旧材料、旧检查、缺失复核或APPROVED都不能授权下一轮。连续轮次由Java在事务内加一，并由V5同源前驱/唯一后继约束兜底。

同事务写入新PENDING返工、生命周期、一次共享版本递增、幂等完成、审计和原成功JSON；所有实际写入数要求一行，异常、零行和COMMIT失败均整体回滚。新轮processingRevision、inspectionId、reviewId为null，不复制旧成果或结论。前轮全部创建/开始信息、处理、检查和复核证据保持；后继审计关联真实前轮reviewId、退回结论及原意见，新创建原因独立原样保存。问题仍OPEN，原生产仍COMPLETED，不自动开始、重跑生产或推进订单/交付。

摘要绑定操作、任务、来源问题或前驱、原expectedVersion和原样原因，实际用户另行绑定；相同成功请求先返回不可变原回执，不因新轮后来RUNNING/COMPLETED或问题CLOSED而重建PENDING结果或新建一轮。换人、换目标、换操作、改版本或原因均不能复用键；旧创建/旧复核的键不能当作新轮授权。该边界是Java请求幂等，不是人工确认凭证，也不代表Python已实现旧确认失效。

旧POST /api/tasks/{taskId}/rework继续使用旧请求/响应结构，增加相同父任务锁及受控链检查，防止新旧创建并发绕过轮次；匹配成功重放先于新状态校验，仍返回首次PENDING及原taskVersion。现有Python旧写Tool不切换新路径，旧记录不补造生命周期。独立Approval/Tool、确认界面和诊断消费新事实留待M8.5～M8.7。

`ReworkCreationApiIntegrationTest`已通过本机定向及make test-java-write验收，覆盖真实两轮HTTP、新旧入口及幂等并发、逐写入点/提交失败和事务外读取。未新增迁移、依赖或修改固定数据，T820及完整Java回归也已通过，M8.4在停止线收口；不宣称三端确认或页面闭环已验收。

## 24. T820订单交付条件查询及关闭并发边界

新增`GET /api/orders/{orderId}/delivery-conditions`，六字段信封及Trace规则不变。要求REVIEWER身份、合法`ORDER-[A-Z0-9][A-Z0-9-]*`且最多64位，不接受任何查询参数；缺身份401、角色不足403、参数400、订单不存在404。每次在独立REPEATABLE READ READ ONLY事务读取订单、全部关联任务、步骤、问题、有效复核、活动返工和交付记录，不对业务事实加写锁，不追加幂等或审计。

data固定为order（原OrderDto）、tasks、deliveryRecords（原DeliveryRecordDto数组）、blockers和hasBlockers。tasks按taskId排序，每项包含taskId、taskVersion、productionStatus、steps（原ProductionStepDto，按sequenceNumber/stepId排序）、issues（按issueId排序）及activeReworks（原ReworkTaskDto，按返工ID排序）。issues每项为issue（原QualityIssueDto）和effectiveReview（T816 EffectiveReviewSnapshot全部字段），不把历史复核扁平化后让调用方猜最新；交付记录按deliveryId排序。共享版本限制为安全整数，缺失/异常事实不伪造完整快照。

所有有效绑定直接复用T816仓储，在当前同一个事务查询，不调用另开快照的读取Service。受控问题必须CLOSED且当前轮/成果/最新PASSED检查下的有效复核APPROVED；旧轮、旧修订或旧检查上的未通过不永久阻塞新的当前通过，新轮或新材料没有有效通过时保持阻塞。无生命周期时明确保留旧规则：OPEN/PROCESSING尚未解决，任意旧非APPROVED仍阻塞，RESOLVED且没有旧通过也阻塞；不为存量编造轮次、最新复核或改变Python旧规则。

blockers每项固定code、taskId、resourceId、status四字段，无法适用的taskId/status明确null；status来自实际业务状态，缺复核时null。代码按订单条件、taskId下的生产/步骤/问题/活动返工、交付记录的顺序稳定输出，同资源可有多个不同原因，不提前停在首个条件：

| code | 来源及条件 |
| --- | --- |
| ORDER_BLOCKED | 订单明确BLOCKED |
| MISSING_PRODUCTION_TASKS | 订单没有生产任务 |
| PRODUCTION_TASK_NOT_COMPLETED | 任务状态不是COMPLETED |
| MISSING_PRODUCTION_STEPS | 任务没有生产步骤 |
| PRODUCTION_STEP_NOT_COMPLETED | 步骤状态不是COMPLETED |
| ACTIVE_REWORK | 同任务存在PENDING/RUNNING/BLOCKED返工或受控FAILED；包含无来源存量活动返工 |
| QUALITY_ISSUE_UNRESOLVED | 存量问题OPEN/PROCESSING |
| CONTROLLED_ISSUE_NOT_CLOSED | 受控问题不是CLOSED |
| EFFECTIVE_REVIEW_NOT_APPROVED | 受控问题缺当前有效复核或其不是APPROVED |
| LEGACY_REVIEW_NOT_APPROVED | 存量任意旧复核不是APPROVED，resourceId为真实reviewId |
| LEGACY_RESOLVED_ISSUE_WITHOUT_APPROVAL | 存量RESOLVED问题没有旧APPROVED |
| MISSING_DELIVERY_RECORDS | 订单没有交付记录 |
| DELIVERY_NOT_READY | 交付记录NOT_READY/BLOCKED/FAILED |

hasBlockers由本次blockers是否非空确定。没有已知阻塞不等于完整交付资格或人工授权；订单/交付仍返回真实原状态，不把QUALITY_CHECKING改成READY_FOR_DELIVERY，不自动交付，不新增完整交付状态机。其他问题、未完成生产、活动返工或实际交付BLOCKED都不能因关闭来源问题而被清除。旧overview、review、delivery等HTTP响应和Python诊断继续原行为，M8.5消费新事实前不能声称线上诊断已修复。

`DeliveryConditionsApiIntegrationTest`已编写并加入`make test-java-contract`：受控旧失败后当前通过、当前绑定变化与存量兼容、其他生产/问题/交付阻塞、订单隔离、真实后继轮通过、两问题HTTP关闭争共享版本、回执提交前HTTP读取及真实关闭穿过读取过程时的只读快照。本轮已在本机编译并通过定向及完整查询/写入/固定数据验收，M8.4已在停止线收口，不以历史通过结果代替本次执行。未新增迁移、依赖、固定资料修改或Python/前端接线，不自动进入M8.5。

## 25. T821 Python Schema与HTTP Client开发边界

初次按用户继续开发要求接续独立Python契约层时，保留前置M8.4待验收；本轮已独立补齐Java验收。`app.schemas.rework`提供严格、禁止额外字段且不strip的M8模型，`app.schemas.rework_delivery`提供T820事实结构；不复用或放宽旧`ReworkWriteResponseData`固定PENDING状态。新受控复核仅接收最终结论，存量PENDING/null说明保留在独立旧复核结构。

版本为严格JSON安全整数，序号为正安全整数，业务ID最多64位并完整匹配；nullable字段仍为必填键，不能把缺字段悄悄补成null。说明、成果版本和引用原样保留，按Java UTF-16单元及isBlank/strip空白语义校验，拒绝NUL和无法无损UTF-8保存的代理项；不strip、不改大小写、不把成果版本转数字。时间保留Java原始UTC字符串及纳秒精度，不接受自报人员/时间进入写请求。

详情/有效复核检查同一响应的轮次、修订和检查绑定，历史保留全部真实材料且不从数组选择有效结论；交付条件检查返回结构中的订单/任务/问题/记录及阻塞资源关联和hasBlockers自洽，不在Python重算阻塞规则。输入模型再次校验后才发送，已构造模型的可变嵌套列表也不能绕过请求校验。

`ReworkHttpClient`借用外层管理的`BusinessHttpClient`及其连接池，不独立关闭、构造发请求或注册Tool，支持以下已有Java路径：

| Python方法 | Java路径 |
| --- | --- |
| get_detail | GET R |
| get_results/get_inspections/get_reviews | GET R/results、R/inspections、R/reviews，单页limit/cursor |
| get_effective_reviews | GET /api/tasks/{taskId}/effective-reviews |
| get_delivery_conditions | GET /api/orders/{orderId}/delivery-conditions |
| create_first | POST B，CREATE_LIFECYCLE_REWORK |
| start/block/fail/resume | POST R/start、R/block、R/fail、R/resume |
| register_result/register_inspection/submit_review | POST R/results、R/inspections、R/review |
| create_next | POST R/next-round，CREATE_NEXT_REWORK |

所有调用只发一次请求，沿用六字段信封、身份/Trace/幂等Header及现有错误码；成功还必须绑定本次Trace、任务/返工或订单。历史页核对真实序号严格递增、页大小、轮次及记录身份，无自动翻页。写入核对操作、目标、原expectedVersion+1、创建前驱和本操作的状态/材料副作用；检查失败仍RUNNING/PROCESSING，通过才COMPLETED/RESOLVED，复核通过CLOSED而退回OPEN。旧成功回执不按后来GET重建，原请求/原键重放仍保留其原版本和状态。

写入网络/超时等不确定结果不允许自动重试，也不描述为确定未写入；GET B列表尚无Java实现，不暴露伪造空结果或假成功方法。T824现已提供原回执查询Client及独立只读核对Tool，公共Client只读POST仅增加合法任务下固定operations/query路径；遵守第28～29节边界，不把只读有界重试叠加到写Client，生产确认及终态恢复留待后续。

T821交付时仅内部传输层，无lifespan装配、新Tool/权限/Approval、诊断规则、自然语言入口或页面变更，Python不直连业务表。代码和MockTransport/纯Schema用例已编写，并纳入`make test-agent-client`及`make test-tools`；本轮已在本机通过pytest、mypy及相关格式/lint，修正测试标注并完成代码格式整理，历史相邻序号校验等价使用pairwise。离线用例不代表真实Python→Java联调或完整人工确认；M8.4的Java验收已独立通过，M8.5仍待写Tool及诊断接线，T822见下一节。

## 26. T822内部只读Tool与调用策略边界

新增`app.schemas.rework_tools`和`app.tools.rework_readonly`，显式调用`create_rework_read_tool_registry(ReworkHttpClient)`才创建六个内部Tool；构造、注册及枚举不访问Java，也不创建或关闭HTTP连接池。独立注册表不修改原`READ_TOOL_NAMES`七Tool、lifespan、生产Agent动作白名单、调试HTTP入口或服务端角色映射；当前代码可供后续编排使用，不表示生产已接线。

| Tool名称 | 输入 | 输出/调用 |
| --- | --- | --- |
| get_rework_detail | task_id、rework_task_id | ReworkDetail，GET R |
| get_rework_results | task_id、rework_task_id、limit/cursor | 一页处理修订，GET R/results |
| get_rework_inspections | 同上 | 一页人工检查，GET R/inspections，保留失败记录 |
| get_rework_reviews | 同上 | 一页受控复核历史，GET R/reviews，不选择有效结论 |
| get_effective_rework_reviews | task_id | Java当前绑定及独立存量记录，GET effective-reviews |
| get_delivery_conditions | order_id | 同一订单快照的已知条件，GET delivery-conditions，不构成交付授权 |

六Tool全部LOW风险，统一要求服务端`ToolContext.permissions`含REWORK_READ；请求身份、角色和Trace只取上下文，不从输入中获取。额外字段（包括自报角色、权限、确认、状态或过滤器）拒绝；身份角色及资源归属仍由Java最终校验，Python权限门禁不替代Java角色或当作确认凭证。

复用BaseTool的权限检查、严格输入、Run内指纹、总超时、重试及输出校验。默认总预算5秒覆盖HTTP、退避及输出校验，最多额外重试一次，支持显式`RetryPolicy(max_retries=0)`；只允许既有策略白名单中retryable=true的TOOL_TIMEOUT/UPSTREAM_UNAVAILABLE瞬时错误。参数、权限、404、409、响应格式/归属/Trace错误以及Java明确retryable=false的500不重试；Client每次只发一次GET，不叠加策略，取消向上传播而不留下后台重试。

历史默认limit=20、范围1～100，cursor是原值不透明字符串；拒绝空字符串、NUL/CR/LF及不可无损UTF-8编码的代理项，先于公共指纹计算处理。当前页使用同一组资源/参数重试，不自动翻页、合并不同读取快照、过滤失败或补造历史；重试可读到新快照，只返回最终完整成功结果，不能把多次尝试拼成同一事实。

逻辑调用指纹包含Tool名、资源及分页默认值，snake_case/别名和显式默认参数归一后得到同一指纹。同Run重复返回DUPLICATE_CALL而非缓存旧数据，显式force_refresh才再次获取；不同游标是不同逻辑调用，内部重试不重复登记逻辑调用，不把网络重试误拦为Agent循环。仍保留原进程内去重边界，不新增跨实例缓存或持久账本。

新增`tests/integration/tools/test_rework_read_tools.py`通过现有`make test-tools`目录收集完成离线验收，覆盖Tool→Client→MockTransport的权限/输入/真实GET、归属/Trace/格式拒绝、有限重试/总预算/取消、分页/存量/空历史、去重/刷新及独立注册表。本轮用例与正式Client/Tool入口、类型及相关格式/lint均已通过，实际结果见STATUS；Tool→Client→MockTransport不代替真实Python→Java/数据库联调或完整链路验收。T822未接写Tool、Approval、诊断或页面，后续T823内部映射见下节。

## 27. T823内部写Tool与确认执行边界

`create_rework_write_tool_registry(ReworkHttpClient, ReworkExecutionStore)`仅创建独立注册表，两个依赖必须显式注入，构造不发请求；不改旧写Tool、Approval表/动作枚举、lifespan、角色映射、Agent白名单或诊断。全部HIGH风险，默认总预算10秒，复核要求REVIEW_WRITE，其余要求REWORK_WRITE。

| Tool | Java操作 |
| --- | --- |
| create_lifecycle_rework | CREATE_LIFECYCLE_REWORK |
| start_rework | START_REWORK |
| block_rework | BLOCK_REWORK |
| fail_rework | FAIL_REWORK |
| resume_rework | RESUME_REWORK |
| register_rework_result | REGISTER_REWORK_RESULT |
| register_rework_inspection | REGISTER_REWORK_INSPECTION |
| submit_rework_review | SUBMIT_REWORK_REVIEW |
| create_next_rework | CREATE_NEXT_REWORK |

严格`ReworkWriteInput`只有approval_id和idempotency_key，额外的目标、正文、角色或confirmed字段均拒绝。`ReworkExecutionSnapshot`保存用户/Run、确认人/时间/有效期、EXECUTING状态、固定操作/原键、任务/原版本/来源问题、轮次/前驱、材料指针及明确请求Schema；请求类型、版本、首轮空绑定和复核材料须自洽。执行前复制并重新校验嵌套材料，防止可变列表借用Store引用；核对实际上下文身份、Run、确认人、时间、操作与键，缺失或冲突时零HTTP。

通过门禁后仅调用T821对应POST一次，身份/Trace只取上下文，业务参数只取捕获的确认快照。Client核对原回执资源、操作、版本+1、状态及请求材料，Tool补充确认轮次/前驱、成果修订递增及新检查/复核ID绑定；输出保留Java原回执及Trace，不重新GET拼造原结果。失败检查仍可返回RUNNING/PROCESSING，复核退回仍可返回COMPLETED/OPEN，不等同最终验收通过。

`ReworkExecutionStore`当前只有Protocol，无生产实现。未来确认服务负责独立人工确认、唯一执行权、权限/最新事实重校验和持久化；接口要求按EXECUTING及完整预期快照CAS保存结果，首次回执不可覆盖，同原请求重放只接受相同业务回执并保留首次Trace。Tool不临时生成确认、不取得执行权、不自行修改Approval终态；保存冲突发生在Java响应后，不能声称业务失败或回滚。

全部错误标为不可自动重试，包含Client网络错误和BaseTool外层预算超时；取消继续向上传播，不启动后台请求。默认同Run重复受既有指纹门禁拦截；显式force_refresh仍必须使用同确认快照和原键，不能换键或修订请求。超时、响应不匹配或结果保存失败都不证明Java未提交，结果未知核对留待T824；没有伪造Java尚未实现的操作查询。

`tests/integration/tools/test_rework_write_tools.py`通过`make test-tools`收集，使用MockTransport和明确的测试FakeStore验证九种路径/正文、权限/确认门禁、材料复制/完整快照保存冲突、回执绑定、失败检查/退回复核、多轮绑定、去重/原键重放/超时/取消和旧注册表隔离。已通过离线验收，不代表真实Java、数据库确认CAS、生产装配或三端确认已实现。

## 28. T824原写入回执查询前置能力

`POST /api/tasks/{taskId}/reworks/operations/query`是无副作用的查询，要求当前REVIEWER身份、合法任务ID、application/json及严格的`{"idempotencyKey":"原键"}`正文，不需要写入Idempotency-Key Header。原键完整匹配1～128个字母/数字/点/下划线/冒号/连字符，保留原值；拒绝类型强转、额外/重复字段、尾随JSON及任何URL查询参数，不接受自报用户、操作或确认。

`ReworkOperationQueryService`先校验身份/角色与参数，再开启独立REPEATABLE READ READ ONLY事务；父任务不存在404，在同一快照按父任务、实际用户和原键查询`rework_operation_receipts`。他人、其他任务或没有成功回执均返回同样的`{"found":false,"receipt":null}`，不泄露其他结果存在与否；旧写入仅有旧幂等记录时也不伪造M8回执。

命中时返回`{"found":true,"receipt":固定12字段原回执}`，核对存储元数据和正文的操作、日志ID、任务/返工、轮次、版本及材料存在关系；损坏回执作为服务端错误，不退化为found=false，不输出原始键、请求摘要或数据库材料。原回执不包含原请求全文，不能据此证明另一个草稿或不同材料已经提交；后续核对仍须绑定原确认快照、操作、资源及原键。

查询不读取当前状态拼造旧结果、不预留幂等键、不加写锁、不修改业务、审计或Approval。found=false只表示当前快照未见可见成功回执，写事务可能仍在进行或刚在快照之后提交；不是业务失败、未提交证明、重发授权或切换幂等键的依据。found=true也不表示成果仍为当前版本、仍有写权限或已完成独立人工确认。

`ReworkOperationQueryApiIntegrationTest`使用独占schema和真实HTTP验证九动作、失败检查/退回复核/下一轮后的原结果、实际用户/任务隔离、非法输入、旧写入、失败事务及ORDER-003保持；通过只读事务内父任务查询后独立HTTP写入提交，验证本次仍可found=false而后一次查询能命中。损坏存储绑定用显式测试仓储注入验证，不修改数据库约束。

Python新增`app.schemas.rework_operation_query`，严格同步原键及found/receipt必须自洽、null必填，`make test-agent-client`收集纯Schema用例；Java前置及Schema已验收，后续完成的Python Client/只读核对Tool及真实查询联调见第29节。生产Agent、确认服务及前端未接入，不声称自动恢复。

## 29. T824 Python只读核对与错误边界

`ReworkHttpClient.query_operation`单次只读POST，身份/Trace来自服务端上下文；请求仅原idempotencyKey，不发送写入Idempotency-Key Header。共享Client的新增只读白名单完整匹配`/api/tasks/TASK-合法ID/reworks/operations/query`，任务ID最大64字符；拒绝其他动作、编码、片段、查询参数、路径绕过及外部URL，普通写POST强制幂等键的行为保持。

`create_rework_operation_query_tool_registry`只注册独立`query_rework_operation`，LOW风险且要求REWORK_READ，不加入原七Tool、六个M8只读Tool、九写Tool、生产白名单或lifespan。严格输入只有approval_id/idempotency_key；原任务、操作、版本、轮次及材料从受信Store快照读取，核对原确认单、实际用户/Run、确认人/时间、原键和EXECUTING/SUCCEEDED/FAILED执行记录。尚未执行的确认状态拒绝，已确认执行记录过期仍可只读核对，但不发放写权限。

查询前复制校验嵌套材料，返回前再次读取并比较完整快照；原快照丢失、修改或归属变化时拒绝迟到结果。命中时共用写回执的操作/任务/返工/原版本+1/状态副作用和确认轮次/前驱/材料指针校验，输出approval_id、MATCHED_RECEIPT、原receipt及本次查询java_trace_id；未见成功回执输出UNKNOWN及显式null。Trace不是首次写请求Trace；回执不含完整原请求，不能据此证明不同正文已经提交，也不证明成果仍当前有效或订单可交付。

| 情况 | 核对结果/错误 | 行为 |
| --- | --- | --- |
| Java返回found=false | UNKNOWN，receipt=null | 不轮询、不重发写入、不生成失败事实 |
| 原回执与原快照可见绑定相符 | MATCHED_RECEIPT | 只读返回，不保存结果或推进Approval终态 |
| 输入/资源/权限/业务冲突 | 原有PARAM_VALIDATION_ERROR/RESOURCE_NOT_FOUND/PERMISSION_DENIED/BUSINESS_CONFLICT | 不重试，不伪装UNKNOWN |
| Java信封/Trace/资源/材料错误 | RESPONSE_VALIDATION_ERROR | 不重试，不把错误当未写入 |
| 查询网络/超时等明确瞬时错误 | TOOL_TIMEOUT/UPSTREAM_UNAVAILABLE | 仅只读Tool在总预算内最多额外一次重试，仍沿用原键 |
| 写入超时、响应丢失或结果保存冲突 | 写Tool原错误分类，retryable=false | 不自动调用写入或核对，不改变业务/确认终态；上层可显式调用核对 |

默认总预算5秒覆盖确认读取、HTTP、退避及最终快照校验；Client不叠加重试，Java明确retryable=false错误不重试，取消向上传播。同Run相同确认单/键拒绝重复逻辑调用；显式force_refresh才重新查询，不复用旧结果，不切换键。

`make test-tools`覆盖九动作回执、白名单/归属/确认门禁、错误矩阵、未知不轮询、读重试与写不重试、总预算/取消和迟到结果。`make test-rework-query-e2e`使用独占PostgreSQL、本机Java及真实HTTP，测试传输层在Java提交且返回完整回执之后丢弃响应，再验证只读核对找回原事实；另验证Java成功但FakeStore保存冲突、后来状态变化、他人查询缺失、UNKNOWN、实际写请求/业务/审计计数及ORDER-003保持。SQL仅作隔离测试准备与断言，产品Python不访问Java表；脚本清理本次Java进程、容器和临时目录，不读取.env或运行库。

T824内部查询/核对已验收，但Store只有接口、确认仍为明确测试替身；持久化确认服务、Run/Step接线、独立人工确认、终态恢复及页面属于M8.6/M8.7，不在此Tool中补建。下一最小任务T825，不自动开始。

## 30. T825 诊断有效复核视图与历史隔离

Java HTTP和旧ReviewResult契约不变。应用lifespan改用`create_diagnosis_read_tool_registry`，仍是七个既有只读名称和原权限，get_review_result沿用REVIEW_READ，身份/角色由Java最终校验，不增加模型动作或写权限；独立M8六只读/九写/核对注册表不整体装入生产。

诊断专用`GetDiagnosisReviewResultTool`在同一逻辑调用总预算内依次读取旧/review及M8/effective-reviews，返回强类型`DiagnosisReviewResult`。两个GET是独立读取快照，不声称全链路事务一致；当前结论只来自后者，历史只用于展示。默认总预算5秒和至多一次明确瞬时重试沿用既有只读策略，整体读取可重试但不叠加Client重试；有效查询失败、错Trace/归属或格式错误不退回旧记录推断成功。

| 字段 | 内容及用途 |
| --- | --- |
| task_id | 与原输入、旧历史及有效快照一致的任务 |
| reviews | 仅投影Java当前受控review及未纳管legacy_reviews，缺复核不制造PENDING；沿用旧标量记录格式供现有规则/Evidence使用 |
| history_reviews | 旧/review接口的完整历史记录，受控问题的旧记录不参与决策 |
| effective_reviews | 保留Java任务版本、全部问题、轮次/成果/检查/当前复核绑定及原样M8材料 |

Python只做投影，不按时间/序号从历史挑通过；投影必须与Java快照一致，历史不能混入其他问题。完整M8多轮复核历史仍由既有/reworks/{id}/reviews及get_rework_reviews提供，不把history_reviews描述为所有新轮次历史。旧标量投影的既有文本规范化不修改effective_reviews中的原样M8字段，也不是待人工确认的写草稿。

固定诊断及动态缺口检测比对已加载任务版本和问题集合，不一致给信息不足或保留缺口，不合并为可放行结论。复核场景看到有效快照包含问题时必须读取问题状态；受控问题要求CLOSED且Java当前review为APPROVED，RESOLVED仍需完成复核，旧成果的通过不能代替当前缺复核。未纳管问题继续使用Javalegacy_reviews和既有旧规则，旧离线/历史ReviewResult仍兼容；生产新Tool的有效快照为必填，不提供错误后的降级路径。

诊断HTTP的DiagnosisResult、BlockingStage和Evidence结构不变，Tool名称仍为get_review_result；当前复核缺失时可引用`effective_reviews.issues[index].review`且value=null，其余状态证据可引用投影的reviews[index].status。前端和Run历史保留证据原值，不回查新状态重算既有诊断；当前APPROVED也不直接标记订单可交付或已交付，仍检查其他既有阻塞。

T825已通过离线规则/错误路径、固定/动态Workflow回归、确认安全/隔离持久化、真实Agent/Java及新增两轮返工诊断验收，M8.5在停止线收口。`make test-rework-diagnosis-e2e`复用独占本机Java/PostgreSQL脚本，以确定性动作模型验证Java两轮真实写入：第一轮退回、第二轮待复核、通过关闭后旧拒绝不阻塞、旧历史/M8历史仍可读取、交付阻塞保留及ORDER-003原结论；不调用真实模型、不接入新写入确认或页面。下一最小任务T826未启动，不自动跨入M8.6。

## 31. T826 独立审批草稿与审查契约

本节新增内部Python/前端契约，不新增Java或Agent HTTP接口。九个M8 operation与第2节一致，按operation判别为明确草稿类型并复用T821 Java请求Schema；旧SUBMIT_REVIEW/CREATE_REWORK不作为新动作别名，旧ReviewDraft、旧ORM枚举和旧确认API保持原样，新草稿不能送入旧确认请求或作为T823已确认执行快照。

| 草稿字段 | 内容与边界 |
| --- | --- |
| operation | 首轮、开始、阻塞、失败、恢复、成果登记、人工检查、再次复核、后继创建九类固定动作 |
| target.task_id/task_version/source_issue_id | 本次审查目标、原版本与来源问题，不能编辑换目标或自行重置版本 |
| target.rework_task_id/round_number/previous_rework_task_id | 首轮全部null，既有轮次要求真实资源与自洽前驱；不补造存量轮次 |
| target.processing_revision/artifact | 当前成果修订与成果标识/版本必须同时存在或同时null；不是本次待登记的新成果 |
| target.inspection_id/review_id | 检查须绑定当前成果，复核须有检查；后继草稿必须保留前轮复核身份 |
| request | 对应Java动作的完整严格正文，序列化用Java camelCase；expectedVersion与目标版本一致 |

所有目标字段必填，缺失值必须显式null。首轮请求sourceIssueId与目标问题一致且不能继承已有轮次；检查/复核请求processingRevision与目标一致，再次复核inspectionId与目标一致。这里只检查结构和自洽，不能证明这些资源真的存在、是最新材料、检查已经通过或用户具有权限，事实读取/动作前提与确认前重校验分别待T827/T828。

`parse_rework_approval_draft`复制后校验，保留说明/证据/成果版本原值及Java UTF-16长度、严格类型和安全整数约束。`validate_rework_draft_edit`允许修改本次请求材料后再次审查，但operation及整个target不可替换；同时改目标版本与expectedVersion也不能绕过，不允许将新轮/新成果身份偷偷拼入旧审查。草稿不接收confirmed、approval_id、用户、幂等键或待执行Tool等自报授权字段，也不接受整体passed/检查人/作业调度信息来代替完整人工检查项。

`review_rework_approval_draft`纯函数生成`ReworkDraftReview`，包含完整draft、固定pending_tool、所需权限类别、effect_semantics=EXPECTED_IF_JAVA_ACCEPTS和expected_effects；元数据必须与动作匹配，不能隐藏副作用。pending_tool/required_permission不是执行授权，原生产的预期状态始终COMPLETED；登记说明后仍RUNNING/PROCESSING，人工检查任一FAILED仍RUNNING/PROCESSING，全部PASSED预期COMPLETED/RESOLVED而非最终验收。再次复核APPROVED预期COMPLETED/CLOSED并仅RECHECK_ONLY交付条件，REJECTED/REWORK_REQUIRED预期COMPLETED/OPEN，不自动创建下一轮、标记订单可交付或已交付。

审查包只描述Java接受请求时的条件性影响，没有确认人、确认时间、执行状态或唯一执行权；函数不读Java、不创建/持久化Approval、不调用Tool。新M8持久化适配及确认执行服务仍待后续，不能因Schema通过就声称已完成独立人工确认。前端`types/reworkApproval.ts`同步九动作判别联合、材料绑定、Tool/权限与审查包类型，仅提供编译期契约；运行时输入解码、确认卡片、HTTP/Agent接线和真实执行仍未实现。

T826已通过新Schema/编辑/影响边界与旧确认兼容测试、前端类型检查及类型契约、既有确认持久化/Tool/黄金诊断回归。`make test-approval`收集新增Python和前端契约用例，不将这些用例描述为真实新审批执行或数据库迁移验收；Java、固定数据、旧ORM/确认服务及写Tool保持。下一最小任务T827，不自动开始。
