# Business Service

项目文档入口见[文档总导航](../docs/README.md)，当前进度和实际验证见[STATUS](../docs/STATUS.md)。

Java 21 + Spring Boot 3.5 + Spring Data JPA + Flyway 的遥感数据产线业务服务。当前已提供固定演示数据、查询/写入接口、统一响应和 Trace ID，以及 M0.7 开发故障模拟。

使用 Docker 启动：

```bash
docker compose up --build business-service
```

使用本机 JDK/Maven 测试：

```bash
mvn --file business-service/pom.xml test
```

服务使用以下环境变量连接 PostgreSQL：

```text
SPRING_DATASOURCE_URL
SPRING_DATASOURCE_USERNAME
SPRING_DATASOURCE_PASSWORD
PORT
```

健康检查继续兼容 `GET /health`。

V4增量新增ORDER-006～030，不修改V2/V3及既有记录。只读`GET /api/orders`返回按订单号排序的
`data.orders`；overview每个任务包含`reworkTasks`（无返工为[]）。固定基线及场景边界见
[演示数据](../docs/demo/DEMO_DATA.md)，独立V3升级保留测试为`DemoMigrationUpgradeIntegrationTest`。

## M8.1 返工领域、契约与存储（T801～T805已验收）

`ReworkArtifact`标识具体成果及原样保留的业务版本；`ReworkProcessingEvidence`要求成果、非空处理说明和至少一个
非空证据引用，并复制引用列表，避免调用方后续修改登记材料。`ReworkProcessingSnapshot.recorded`从Java返工实体
提取返工、生产任务和来源问题身份，拒绝缺少来源或关联不一致的登记；`requireBelongsTo`核对重新读取实体的业务身份，
不依赖Java对象是否为同一个实例。`unrecorded`以Optional.empty显式保留历史缺证据，来源问题为空时也不补造问题。

`ReworkRound.from`从Java实体提取返工/任务/来源问题身份，并接收明确的正整数轮次；不根据已有记录、时间或随机ID
推断轮次，也不自动给历史记录补轮次。它不负责分配轮次、证明连续性或校验下一轮是否允许创建，这些留待后续应用和持久化。
`ReworkInspectionItem`要求检查项、人工结论PASSED/FAILED、检查说明及非空证据引用；引用列表不可变。
`ReworkInspection.recorded`绑定轮次和完整处理材料，保存检查身份、人员标识、时间及检查项，非空检查项全部PASSED时
才汇总为PASSED，否则为FAILED；这只是汇总人工输入，不执行自动成果检查。同轮多次检查分别保留调用方提供的身份和时间，
检查ID唯一性与历史落库由后续仓储保证，模型不选择当前有效检查。
`requireAppliesTo`核对资源/轮次及完整成果和处理材料，成果标识/版本、处理说明或引用变化均拒绝沿用旧检查；
比较的是登记值，不证明相同引用下的原件内容未变，也不替代后续并发版本、封存修订或原件校验。

`ReworkTransitionPolicy`从Java返工实体、轮次及当前已选检查计算不可变的`Transition`变更提议，携带操作、前后状态和
原因/检查/复核材料。所有操作要求原生产任务COMPLETED及资源关联正确，原实体、任务版本和历史均不改变。

| 操作 | 要求的返工/问题状态 | 提议的返工/问题状态 | 材料要求 |
| --- | --- | --- | --- |
| START | PENDING / OPEN | RUNNING / PROCESSING | 当前返工与轮次 |
| BLOCK或FAIL | RUNNING / PROCESSING | BLOCKED或FAILED / PROCESSING | 非空异常原因 |
| RESUME | BLOCKED或FAILED / PROCESSING | RUNNING / PROCESSING | 非空恢复说明 |
| COMPLETE | RUNNING / PROCESSING | COMPLETED / RESOLVED | 与本轮及完整处理材料一致的PASSED检查 |
| REVIEW通过 | COMPLETED / RESOLVED | COMPLETED / CLOSED | 适用的PASSED检查、APPROVED及非空复核说明 |
| REVIEW退回 | COMPLETED / RESOLVED | COMPLETED / OPEN | 适用的PASSED检查、REJECTED或REWORK_REQUIRED及非空说明 |

未列出的状态组合一律拒绝，PENDING不能作为最终复核结论。调用方必须提供Java后续应用选定的当前有效检查，
策略只校验其适用性和通过结论，不从历史挑选检查；退回不创建下一轮，关闭不推进订单或交付。
提议不是执行回执或授权凭证，不能直接据此绕过人工确认；后续写入须刷新事实并校验权限、版本、幂等，再在同一事务落库。

上述对象本身没有JPA映射；T805以V5提供独立SQL存储，完整登记材料不等于成果存在、实际检查通过或返工完成。
T806已新增只读详情HTTP，T807～T809已新增Java开始、阻塞、失败和恢复写入，T811/T812接通成果与人工检查登记；M8 Python独立确认与页面尚未接入，既有实体/DTO不变，原件校验和后续复核仍待实现。
领域记录中的人员与时间仅为待校验材料，不代表已通过认证；真实写服务须从实际身份和服务端时间取值。
详细边界见[详细计划M8.1](../docs/planning/detailed-plan.md#m81-返工领域与契约)。

T804冻结[返工生命周期契约v1](../docs/api/REWORK_CONTRACT.md)：列明新查询/动作、三端字段映射、角色与Tool权限、
独立人工确认、任务共享版本、原始幂等回执、当前检查/复核选择及存量只读边界。
检查通过与完成返工合并为一次明确确认的原子写入，不另设complete接口；下一轮必须独立确认创建。
当前T806详情、T807～T809开始/阻塞/失败/恢复、T811/T812成果/检查登记及T815对应历史GET及T816有效复核/复核历史GET、T817复核POST的APPROVED分支已实现，其他新增路径仍为契约要求；未装配Python Client/Tool或前端类型，不能把旧接口回归当作其他新HTTP已实现。
T805已完成V5增量存储和隔离升级验证；M8.2已验收，M8.3已完成T811～T815成果/检查登记、更新一致性、完成原子性及历史查询验收，M8.4已接通T816有效复核/历史及T817/T818全部最终复核结论。T819受控创建和T820交付条件查询已开发待项目电脑验收，M8.4未整体验收；T821独立Python契约层已开发待验收，新Tool/确认和诊断尚未装配。

V5由Flyway在未来Java启动时执行，本轮只在隔离测试库应用；不改V1～V4、种子或运行库，不自动生成历史轮次/证据。

| 表 | 存储职责与关键边界 |
| --- | --- |
| rework_lifecycles | 绑定旧返工/任务/问题及真实轮次；连续同源前驱、唯一后继，创建身份不可改，开始人/时间成对且只登记一次 |
| rework_processing_revisions | 保存成果版本、说明、JSON证据及人员/时间；正修订号和UTF-16边界，记录追加后不可改写/删除 |
| rework_inspections | 保存本轮成果修订对应检查、顺序与JSON检查项；非空且结果与检查项汇总一致，保留失败历史 |
| rework_reviews | 单独保存M8复核及顺序，不复制或改写旧review_records；复合外键要求同返工/修订的PASSED检查 |
| rework_operation_receipts | 保存原始成功JSON回执，绑定幂等键、请求摘要、用户、任务/轮次、版本及审计；后来的实体状态不能覆盖回执 |

V5为旧身份列增加复合唯一键、为幂等/日志操作集合补入新操作，旧列和旧行不变。
SQL函数只校验材料格式、Java空白/UTF-16边界及人工结果汇总，不执行真实成果检查。
新历史与回执由触发器禁止更新/删除；生命周期允许一次开始元数据登记，禁止改写归属、前驱和创建身份。
数据库不自动选当前检查/复核，不校验操作者真实权限、不自动应用T803状态提议，也不分配连续成果/检查序号或执行业务写入。
后续Java应用仍须在同一事务内校验当前事实并递增任务版本；M8新幂等resource_id绑定返工ID，写回执前应flush匹配的幂等完成及审计，
或在同一事务显式延后这两个可延迟外键，不能提前提交部分结果。旧幂等资源含义不变，不伪造旧成功回执。

### T806 返工详情查询

`GET /api/tasks/{taskId}/reworks/{reworkTaskId}`要求`X-User-Id`及精确`X-User-Role: REVIEWER`，沿用六字段响应信封。
身份与ID检查后，`ReworkQueryService`在只读可重复读事务中核对父任务、返工归属及当前材料，返回真实轮次、前驱、共享任务版本和允许动作。
处理修订、检查和有效复核按序号及绑定读取，不跳过最新失败检查；缺少生命周期的存量字段保持null，allowedActions为空。
允许动作只表示当前事实前提，不证明对应写接口可用，也不代替人工确认。查询不改状态、任务版本、材料或日志；旧overview不变。
详细字段和失败边界见[契约第十节](../docs/api/REWORK_CONTRACT.md#10-t806详情读取实现边界)。`make test-java-contract`包含真实HTTP及数据库集成测试。

### T807 Java开始返工

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/start`要求REVIEWER身份和安全`Idempotency-Key`，JSON只接受整数`expectedVersion`。
拒绝重复键、尾随内容、浮点/字符串/布尔、未知字段和自报确认/状态/人员/时间；此局部严格解析不改变旧请求DTO行为。
Java锁父任务并重新读取事实，仅受控轮次、未开始/无后继、原生产COMPLETED及返工PENDING/问题OPEN可执行。
同一事务写RUNNING/PROCESSING、实际请求人及服务端UTC开始时间，任务版本只加一，原生产任务仍COMPLETED；不执行自动修正程序。
幂等完成、审计与固定12字段成功回执同事务保存，失败整笔回滚；同请求重放原回执，后来状态变化不重新写入，也不重建旧结果。
存量无轮次返回409，不自动纳管；Python独立确认/写Tool和页面接线留待后续，Header不能作为人工确认凭证。
详见[契约第十一节](../docs/api/REWORK_CONTRACT.md#11-t807开始返工实现边界)。`make test-java-write`包含开始操作的真实HTTP、并发及回滚测试。
ReworkRound内部轮次由int对齐为long并限制正安全整数，与既有JSON契约及V5范围一致；原非正数校验保留，不改旧迁移或固定数据。

### T808 Java阻塞与失败登记

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/block`及`/fail`要求REVIEWER身份和安全幂等键，JSON只接受expectedVersion和reason。
原因非空白且最多1000个UTF-16单元，保留原值及合法非BMP字符；拒绝未知/重复字段、尾随JSON、类型强转及不能无损写入UTF-8的文本。
复用T803约束，仅受控轮次无后继、原生产COMPLETED及返工RUNNING/问题PROCESSING时可登记；任务版本递增一次，问题仍PROCESSING。
异常原因写入本次`operation_logs.after_state.reason`，不覆盖原始创建原因和开始人员/时间，不删除或改写处理修订、检查、复核及历史。
同一事务保存新状态、版本、幂等完成、审计和原成功回执；同键换动作、原因、用户、目标或版本冲突，同请求只重放首次结果。
详情可读取最新BLOCKED/FAILED及当前材料指针；原因本身没有新增独立查询字段。HTTP错误不自动转为业务FAILED，也不触发自动恢复或重试。
详见[契约第十二节](../docs/api/REWORK_CONTRACT.md#12-t808阻塞与失败登记实现边界)，`make test-java-write`包含异常原因、证据保留、并发和回滚验证。
独立Approval/写Tool和页面仍待后续实现；Header不是人工确认凭证，Java写底座不构成完整确认闭环。

### T809 Java受控恢复

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/resume`复用严格expectedVersion/reason请求与REVIEWER、安全幂等键校验。
仅原生产COMPLETED、受控轮次无后继且返工BLOCKED或FAILED/问题PROCESSING可恢复；锁父任务后复查当前事实及版本，条件更新为RUNNING，问题仍PROCESSING，共享版本只加一。
恢复说明原样写入本次审计，不改创建原因、原开始人员/时间或旧异常原因；成果修订、检查、复核和旧回执全部保留，最新失败检查仍为失败。
复用异常操作的同一事务与原始成功回执机制；同请求只返回原结果，即使后来再次失败也不执行第二次恢复。
只恢复人工流程状态，不自动重跑、自动检查或执行成果修正；恢复说明没有新增独立查询页面或字段。
详见[契约第十三节](../docs/api/REWORK_CONTRACT.md#13-t809受控恢复实现边界)，`make test-java-write`包含真实HTTP恢复、材料保留、并发和回滚用例。

### T810 M8.2跨操作一致性验收

`ReworkWriteConsistencyIntegrationTest`使用独立schema，经真实HTTP验证四种动作共用全局幂等键、完整请求绑定及原始回执。
不同动作/目标争同键只能提交一次；与旧复核接口争同一任务版本时只能有一个成功，失败方不留下幂等、审计或业务记录。
分别在幂等完成、审计写入及回执写入时注入数据库故障，核对状态、版本和开始元数据全部回滚，移除故障后原键可重新提交。
开始→阻塞→恢复→失败后，逆序重放各旧请求只返回原回执，不改变当前事实；固定ORDER-003关联记录逐行保持。
`make test-java-write`纳入本组测试；验收范围与后续边界见[契约第十四节](../docs/api/REWORK_CONTRACT.md#14-t810跨操作一致性验收边界)。
本任务不增加业务接口或改写运行实现，M8.2收口不表示三端人工确认、成果登记、检查或问题关闭已完成。

### T811 Java成果登记

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/results`只接受expectedVersion、artifact、processingComment及evidenceReferences。
局部严格解析拒绝缺字段、未知/重复字段、类型强转、尾随JSON、非法UTF-16和无法无损存储的NUL；标识、版本及证据引用禁止首尾空白，所有文本按契约限制UTF-16长度并原样保存。
`ReworkResultService.register`重验REVIEWER身份、归属、受控轮次无后继、共享版本、原生产COMPLETED和返工RUNNING/问题PROCESSING。
持有父任务锁时分配连续processingRevision，锁定本轮与来源问题状态，在同一事务追加材料、记录实际请求人和UTC时间、递增任务版本并保存幂等、审计及原始回执。
相同成果版本文本也会新增修订，旧材料和历史结论不改写；详情仅对当前修订读取检查和复核，新回执中的inspectionId/reviewId为null。
仅登记材料，不访问证据链接或原件、不生成检查通过、不完成返工或关闭问题；Header仍不证明人工确认，独立Approval/写Tool及页面待后续。
`make test-java-write`包含真实HTTP、字段边界、并发和故障回滚；详见[契约第十五节](../docs/api/REWORK_CONTRACT.md#15-t811成果登记实现边界)。

### T812 Java人工检查登记

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/inspections`严格接收expectedVersion、processingRevision和非空items；每项包含checkItem、PASSED/FAILED、comment和证据引用，逐项校验UTF-16长度及无损存储规则。
`ReworkInspectionService.register`重验身份、归属、受控轮次无后继、共享版本、原生产COMPLETED及RUNNING/PROCESSING，只能检查当前成果修订；检查人和UTC时间取服务端，不接受自报总体结论、人员、时间或确认。
`ReworkInspection.recorded`汇总各项结果，任一FAILED则总体失败、返工仍RUNNING且问题PROCESSING；全部PASSED调用既有领域COMPLETE约束，将检查、本轮COMPLETED与问题RESOLVED一起提交。
为遵守冻结契约，通过分支的最小原子写入随T812一并接通，T814已完成专项验收；没有独立complete接口，不关闭问题或推进订单/交付。
检查序号在本返工所有成果修订间连续递增，材料与失败记录只追加；新检查、任务版本、幂等完成、审计及原始回执同事务保存或回滚，旧请求重放不覆盖最新事实。
`make test-java-write`包含真实HTTP登记、成果变更绑定、并发和故障回滚；详见[契约第十六节](../docs/api/REWORK_CONTRACT.md#16-t812人工检查登记实现边界)。
独立Approval/写Tool、确认快照失效处理和页面仍待后续；成果/检查历史已由T815实现，Header不是人工确认凭证，系统不执行自动成果检查。

### T813 检查失败与成果更新验收

`ReworkRevisionConsistencyIntegrationTest`在独立schema经真实HTTP走开始→登记→失败检查→更新成果→当前修订检查通过，逐项验证成果标识、版本、说明、证据变更及相同材料再次登记。
更新后当前inspection/review为空，旧修订和失败记录完整保留；过期任务版本或旧修订的检查请求返回409且无写入，终态也不能追加新材料。
检查失败可以在同一修订上再次检查，但必须使用最新共享版本；旧成功请求重放只返回原回执，不能重置当前事实。
并发用例先持有父任务锁，通过pg_stat_activity核对两个真实HTTP写事务均在等待，再放行检查与更新或两个更新，验证同版本只有一个提交且无额外修订。
更新的审计/回执故障保留旧FAILED检查为当前结论，移除故障后显式用原未提交键重提才切换新修订；产品没有新增自动重试。
本任务只补跨接口验收和Make入口，不改运行实现或接口；Java拒绝过期参数不代表已实现Python Approval的STALE状态或前端确认失效处理。
详见[契约第十七节](../docs/api/REWORK_CONTRACT.md#17-t813失败检查与成果更新验收边界)，`make test-java-write`纳入本组回归，独立确认仍待后续，历史分页已由T815实现。

### T814 检查通过原子性专项收口

`ReworkCompletionAtomicityIntegrationTest`经真实HTTP验证检查通过的全部写入点：版本、检查、本轮完成、问题解决、幂等完成、审计与原回执，任一步异常都回滚原材料、失败历史及业务事实。
审计或回执INSERT被触发器静默跳过也必须拒绝；共用`ReworkStartRepository.audit/saveReceipt`返回影响行数，所有M8开始、异常/恢复、成果及检查写服务统一检查一行写入，零行返回409并整体回滚。
延迟约束触发器在提交时失败，接口返回500且不遗留半次成功；三处写入边界暂停事务时，独立详情GET及SQL观察只能读到提交前完整事实。
旧成功请求只重放原回执，新键或新版本不能重复完成已完成轮次；没有检查项、空检查项或独立complete路径均不能完成返工。
成功只能到本轮COMPLETED、问题RESOLVED，原生产仍COMPLETED，订单及交付不推进；客户端错误不触发自动重试，Java接口也不证明已有独立人工确认。
`make test-java-write`包含本组验收及共用仓储全部调用方的零行回归；详见[契约第十八节](../docs/api/REWORK_CONTRACT.md#18-t814检查通过原子性验收与零行写入防护)。

### T815 成果修订与检查历史

`GET /api/tasks/{taskId}/reworks/{reworkTaskId}/results`及`/inspections`返回完整真实材料，按修订/检查序号升序，保留旧修订和失败记录；存量无记录返回空数组，不制造轮次或证据。
只接受cursor及limit（默认20，1～100），身份、归属和材料在每页独立只读可重复读快照内核对。签名游标绑定用户、任务、返工、历史类型和首屏上界，后续新增材料不混入本次翻页；末页nextCursor显式null。
签名密钥为实例内存状态；重启或跨实例后旧游标返回400，须重新从首页查询，当前不提供多实例共享游标。每页仍重验权限，游标不授予权限或证明人工确认；历史材料也不能替代当前有效检查。
`make test-java-contract`纳入真实HTTP分页、篡改/换人拒绝、只读快照及登记/检查幂等收口；`make test-java-write`保留全部既有写入验收。M8.3已验收，处理结果只到COMPLETED/RESOLVED；有效复核及复核历史由T816提供，再次复核写入与关闭问题留待后续。
详见[契约第十九节](../docs/api/REWORK_CONTRACT.md#19-t815成果与检查历史查询及m83收口)。

### T816 当前有效复核与完整复核历史

`GET /api/tasks/{taskId}/effective-reviews`要求REVIEWER身份且不接受查询参数，返回taskId、taskVersion和按issueId稳定排序的issues；缺任务404，非法ID/参数400。
每个问题选最大真实受控轮次，再选当前修订及其最大检查序号；只有该检查PASSED时才取相同绑定下最大reviewSequence的复核。最新失败检查返回自身inspectionId及review=null，新轮或新材料不继承旧通过，旧失败也不自动推翻后来同绑定的新通过。
没有生命周期时绑定保持null，legacyReviews返回原ReviewRecordDto数组；有生命周期时legacyReviews为空，旧表复核不参与新有效判断。旧`GET /api/tasks/{taskId}/review`和overview保持原样，Python诊断尚未消费新事实。
`GET /api/tasks/{taskId}/reworks/{reworkTaskId}/reviews`返回完整9字段复核记录，按reviewSequence升序保留旧轮次/修订/检查的历史；复用T815严格参数、归属校验、签名游标及单实例重启失效边界。
任务版本、问题分组及当前绑定在同一独立只读可重复读快照中读取，两个接口不写状态、幂等或审计、不执行确认或关闭问题；权限仍每次重验。
详见[契约第二十节](../docs/api/REWORK_CONTRACT.md#20-t816当前有效复核与复核历史实现边界)。`make test-java-contract`包含多轮/材料变化、旧数据兼容、历史完整性及快照一致性验收。

### T817 复核通过与问题关闭

`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/review`严格接受expectedVersion、processingRevision、inspectionId、status及reviewComment。版本/修订为安全整数，检查ID遵循业务ID规则，说明非空白且最多1000个UTF-16单元，原样保存；拒绝未知/重复字段、尾随JSON、类型强转及无法无损存储的文本。
T817接通APPROVED分支，T818已接通REJECTED/REWORK_REQUIRED并将问题回到OPEN；PENDING或非法枚举400。要求REVIEWER身份和安全Idempotency-Key，Header不证明人工确认。
持有父任务锁后重新校验归属、受控轮次无后继、共享版本、原生产COMPLETED、本轮COMPLETED/问题RESOLVED及明确当前修订和当前PASSED检查。重建完整材料后执行领域REVIEW约束，不能沿用旧修订、旧通过或越过最新失败关闭问题。
同一事务追加复核序号、实际请求人及服务端UTC时间，关闭来源问题、递增一次任务版本，保存幂等完成、审计及固定12字段原成功JSON；所有写入实际影响一行，异常/零行或提交失败全部回滚。同请求重放原回执，不重新关闭或从后来状态重建结果。
原生产和本轮仍COMPLETED，开始信息、成果/检查、旧复核及其他问题保持；不自动改变订单/交付，不执行自动成果检查或三端确认。Python仍使用原诊断规则，未宣称线上阻塞判断已切换。
详见[契约第二十一节](../docs/api/REWORK_CONTRACT.md#21-t817复核通过与问题关闭实现边界)，`make test-java-write`纳入真实HTTP、版本/材料拒绝、并发、逐写入点及提交原子性验收。

### T818 未通过复核与问题退回

沿用同一`POST /review`及严格五字段请求，REJECTED和REWORK_REQUIRED也必须绑定本轮当前成果修订及最新PASSED检查；检查通过不等于再次复核通过。
`ReworkReviewService.submitInTransaction`复用身份、归属、受控轮次无后继、共享版本、原生产/本轮COMPLETED及问题RESOLVED重验，经领域REVIEW规则决定退回；`ReworkReviewRepository.reopen`只将来源问题由RESOLVED条件更新为OPEN。
未通过结论、原样说明、请求人/UTC时间、连续复核序号、一次版本递增、审计及原成功回执同事务保存，异常、零行或提交失败全部回滚。
原生产、本轮完成、创建原因、开始信息和成果/检查历史保持；其他问题、旧表复核、订单及交付不变，不自动创建后继或重跑生产，下一轮Java创建留给T819。
有效复核及历史读取可见真实退回结论；旧请求重放只返回第一次OPEN回执，即使后继轮后来通过关闭问题，也不会重新打开问题。后继轮测试使用明确SQL夹具，不代表创建HTTP已实现。
`make test-java-write`包含两类退回、原通过分支、并发结论竞争、逐写入点/提交回滚及提交前读取；详见[契约第二十二节](../docs/api/REWORK_CONTRACT.md#22-t818未通过复核与问题退回实现边界)。M8独立Approval/写Tool和页面仍待后续。

### T819 受控首轮及下一轮创建（待项目电脑验收）

`POST /api/tasks/{taskId}/reworks`严格接收sourceIssueId、expectedVersion和reason，`POST /api/tasks/{taskId}/reworks/{reworkTaskId}/next-round`仅接收expectedVersion和reason；身份、角色、幂等键、严格JSON及UTF-16说明约束沿用M8契约。
`ReworkCreationService`先绑定完整请求与实际用户，成功重放直接返回原回执；新请求锁父任务，重验原生产COMPLETED、安全版本、OPEN问题归属和活动返工。首轮禁止已有受控链；后继必须来自无后继的COMPLETED受控轮、当前成果/最新PASSED检查及当前REJECTED/REWORK_REQUIRED复核，轮次连续加一。
同事务写入新PENDING任务、生命周期、一次版本递增、审计和原回执，实际写入必须一行；后继审计保留前轮真实退回结论及原始意见，新原因原样另存。新轮无材料、检查或复核，前轮证据和开始信息不变，不自动开始处理或推进订单/交付。
旧`POST /rework`保持请求/响应结构，并使用同一父任务锁拒绝受控链绕过；匹配的旧创建成功仍重放PENDING及原版本，不因后来状态改变而破坏旧Python Schema。Python仍使用旧路径，没有独立Approval/写Tool或页面接线；Header不是确认凭证。
`ReworkCreationApiIntegrationTest`已加入`make test-java-write`，包含完整两轮HTTP及原子性/并发用例；按用户要求本机未运行编译、测试或质量检查。项目电脑执行命令见[当前状态](../docs/STATUS.md)，实现边界见[契约第二十三节](../docs/api/REWORK_CONTRACT.md#23-t819受控首轮与下一轮创建实现边界)。

### T820 订单交付条件及关闭并发（待项目电脑验收）

`GET /api/orders/{orderId}/delivery-conditions`要求REVIEWER身份、合法ORDER-ID且不接受查询参数，返回order、tasks、deliveryRecords、blockers和hasBlockers。每个任务列出共享版本、生产状态、步骤、问题及T816有效复核和活动返工；阻塞含稳定代码及真实资源ID/状态，缺失值明确null。
`DeliveryConditionsService`在独立只读可重复读事务中调用查询仓储和T816仓储，避免跨Service快照拼接；受控问题须CLOSED且当前绑定APPROVED，旧受控失败保留历史而不永久阻塞新通过。未纳管问题明确保留原质检/复核规则，不猜测哪个旧通过最新。
仍检查同订单其他问题、生产/步骤、活动返工及实际交付记录；缺任务/步骤/交付记录显式列出，订单BLOCKED及交付NOT_READY/BLOCKED/FAILED保持阻塞。hasBlockers=false只说明列出的已知条件未发现阻塞，不代表完整交付资格或授权，不写订单/交付状态；旧HTTP和Python诊断不变。
`DeliveryConditionsApiIntegrationTest`加入`make test-java-contract`，包含真实复核关闭期间的快照/提交前读取、两个问题争共享版本及后继轮通过；全部尚未执行。先在项目电脑验收T819/T820和M8.4，再进入M8.5；接口、字段和代码清单见[契约第二十四节](../docs/api/REWORK_CONTRACT.md#24-t820订单交付条件查询及关闭并发边界)。

本机无Docker时，Java集成测试支持显式指定已准备好的隔离PostgreSQL，例如：

```bash
mvn --file business-service/pom.xml \
  -Dbusiness.test.jdbc-url=jdbc:postgresql://127.0.0.1:15433/business_service_test_t806 \
  -Dtest=ReworkQueryApiIntegrationTest test
```

该选项仅供测试，要求显式环回端口、`business_service_test_`前缀库名、无URL凭据/参数，固定测试用户及密码为`test`。
集成测试底座将每个Spring上下文的连接池限制为最多4条、最少空闲0条，避免多上下文共用隔离库时耗尽连接；仍支持父任务锁、两个HTTP写事务及独立观察连接同时执行，不改变服务运行连接池。
调用方须单独创建可丢弃测试库，测试会迁移和写入夹具；不会读取`.env`或自动选择开发/运行库。不传此选项仍使用原Testcontainers。
旧迁移/存储用例只改为共用连接获取函数，原断言保持；此测试入口不改变服务运行配置。

局部领域验证（无需数据库）：

```bash
mvn -q -o --file business-service/pom.xml -Dtest=ReworkTransitionPolicyTest,ReworkInspectionModelTest,ReworkProcessingModelTest,DomainModelValidationTest,BusinessStatusEnumTest,BusinessStateConsistencyValidatorTest test
```

根级`make test-business-domain`已纳入新模型测试，完整入口还需要可用的Docker，以运行原有PostgreSQL领域仓储回归。
`make test-business-data`包含`ReworkPersistenceIntegrationTest`，验证V4脏库到V5逐行保留、材料/归属约束、不可覆盖、事务回滚和独立事务防分叉。
原V3→V4历史升级测试显式固定target=4，保留原断言；V4→V5及重放由新增测试覆盖，不因新增迁移放宽旧测试。

## M0.5 写接口契约

| 接口 | 请求体 | 成功结果 |
| --- | --- | --- |
| `POST /api/tasks/{taskId}/review` | `issueId`、`status`、`reviewComment`、`expectedVersion` | 新复核记录和递增后的 `taskVersion` |
| `POST /api/tasks/{taskId}/rework` | `sourceIssueId`、`reason`、`expectedVersion` | `PENDING` 返工任务和递增后的 `taskVersion` |

两个接口都必须携带 `X-User-Id`、`X-User-Role: REVIEWER` 和 `Idempotency-Key`。`expectedVersion` 来自任务查询响应的 `version`；状态已经变化或两个请求并发修改同一版本时返回 `409`。相同用户以相同幂等键和相同请求重试时返回第一次结果，不会重复写入；同一幂等键改作其他请求时返回 `409`。

服务端生成的复核、返工和操作日志ID统一使用大写UUID片段，确保返回值满足Python侧业务标识契约，并可直接进入
写Tool的强类型响应和Approval执行结果。

M0.5 只建立 Java 侧最小权限上下文，Header 尚未连接真实认证系统。

独立验收：

```bash
make test-java-write
```

## KB-02.1 知识管理授权

新增无写入查询`POST /api/knowledge/authorize`，请求只包含`action`，使用现有`X-User-Id`和`X-User-Role: REVIEWER`演示身份。
成功返回`userId`、`action`、服务端确定的`permissionScope=INTERNAL_REVIEWER`及`confirmationRequired`；除READ外，UPLOAD、PUBLISH、DISABLE、RETRY_INDEX均要求人工确认。
成功不是执行凭证或已确认的证明。Java只裁决角色权限，后续知识版本、状态与确认快照由Python依据自有知识表在执行事务中核对。
接口不访问数据库或模型；Python严格调用Client已接入KB-02.6上传解析与预览应用，管理HTTP接口、页面及发布/停用仍待开发。
完整输入、错误与边界见[知识管理授权契约](../docs/knowledge/KNOWLEDGE_AUTHORIZATION.md)，最新进度见[STATUS](../docs/STATUS.md)。

局部验证：`mvn -o --file business-service/pom.xml -Dtest=KnowledgeAuthorizationApiTest,KnowledgeAuthorizationServiceTest test`（在仓库根目录执行）。

## M0.6 统一响应

所有 `/api` 业务端点使用以下响应结构；Actuator `/health` 保持原生健康检查结构。

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "success",
  "data": {},
  "trace_id": "trace-<uuid>",
  "retryable": false
}
```

调用方可通过 `X-Trace-Id` 透传 1～128 位安全字符组成的链路 ID；缺失或非法时服务会生成新 ID，并始终在响应 Header 与响应体中返回相同值。当前错误码包括 `PARAM_VALIDATION_ERROR`、`RESOURCE_NOT_FOUND`、`PERMISSION_DENIED`、`BUSINESS_CONFLICT` 和 `INTERNAL_SERVER_ERROR`。通用错误均不建议自动重试，尤其写操作必须沿用幂等和版本策略。

独立验收：

```bash
make test-java-errors
```

## M0.7 开发故障模拟

故障模拟默认关闭，Docker Compose 本地开发显式开启。它只作用于 `GET /api/**`，不会
注入复核或返工写接口：

| Header | 行为 |
| --- | --- |
| `X-Demo-Delay-Ms: 500` | 响应前延迟 500 毫秒，默认最大 2000 毫秒 |
| `X-Demo-Fault: timeout` | 默认保持连接 5000 毫秒后继续正常查询，用于触发短超时客户端 |
| `X-Demo-Fault: server-error` | 返回统一 `500/INTERNAL_SERVER_ERROR` |
| `X-Demo-Fault: resource-not-found` | 返回统一 `404/RESOURCE_NOT_FOUND` |
| `X-Demo-Fault: business-conflict` | 返回统一 `409/BUSINESS_CONFLICT` |
| `X-Demo-Fault: invalid-json` | 返回 HTTP 200 和故意损坏的 JSON 正文 |
| `X-Demo-Fault: invalid-response` | 返回 HTTP 200，但故意缺少必需的 `data` 字段 |
| `X-Demo-Fault: permission-denied` | 返回统一 `403/PERMISSION_DENIED` |

裸机启动时需显式设置 `DEMO_FAULTS_ENABLED=true`；生产环境不得启用。延迟和超时上限可
通过 `DEMO_FAULT_MAX_DELAY_MS`、`DEMO_FAULT_TIMEOUT_DELAY_MS` 调整，服务端硬上限均为
60000 毫秒。

独立验收：

```bash
make test-java-faults
```
