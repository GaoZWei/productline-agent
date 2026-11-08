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
当前没有新增HTTP、业务状态写服务或页面，既有实体/DTO不变；权限、并发版本、人工确认和证据原件校验仍需后续应用实现。
领域记录中的人员与时间仅为待校验材料，不代表已通过认证；真实写服务须从实际身份和服务端时间取值。
详细边界见[详细计划M8.1](../docs/planning/detailed-plan.md#m81-返工领域与契约)。

T804冻结[返工生命周期契约v1](../docs/api/REWORK_CONTRACT.md)：列明新查询/动作、三端字段映射、角色与Tool权限、
独立人工确认、任务共享版本、原始幂等回执、当前检查/复核选择及存量只读边界。
检查通过与完成返工合并为一次明确确认的原子写入，不另设complete接口；下一轮必须独立确认创建。
新增路径目前仅在契约文档中，未增加Controller/DTO/Client或前端类型，不能把旧接口回归当作新HTTP已实现。
T805已完成V5增量存储和隔离升级验证，M8.1在此验收停止；下一最小任务T806返工详情查询，本轮不进入M8.2。

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

局部验证（无需数据库）：

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
