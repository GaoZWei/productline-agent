# KB-02.1～KB-02.2 知识管理授权契约

## 解决的问题

新增上传、发布和独立问答入口需要统一的服务端授权依据，不能让页面或模型自行指定知识权限范围。
本阶段补充Java授权查询接口与Python严格调用Client，使调用方取得明确的权限与确认要求，并阻断错误用户、动作或请求关联的响应。
授权通过和目标版本当前可执行分别判断，避免将接口成功当成已经确认或完成发布。

## 核心作用

本链路位于后续知识管理应用服务与Java权限判断之间，Python接收身份和动作，复用连接池查询Java并校验权限范围、确认要求及本次用户/动作/Trace绑定。
Java只裁决身份上下文、动作与权限；知识版本、状态及确认快照由Python依据自有知识表在后续执行事务中核对，这是2026-10-29经用户确认的职责划分。
查询使用包含全部尝试与退避的总预算，只对明确瞬时错误有限重试，失败不缓存或静默放行。
链路本身不读写知识或业务表，不创建确认记录、不发布文档、不生成执行凭证，也不调用模型。

## 1. 请求与响应

`POST /api/knowledge/authorize`是无写入副作用的授权查询。POST只用于承载结构化查询条件，不要求`Idempotency-Key`。

| 位置 | 字段 | 契约 |
|---|---|---|
| Header | X-User-Id | 必填，非空白，最多128字符，不含CR/LF；不回显非法值 |
| Header | X-User-Role | 必须精确为REVIEWER，不能用大小写变体、ADMIN或页面声明替代 |
| Header | X-Trace-Id | 可选，沿用现有安全字符及长度限制；缺失或非法时由现有过滤器生成 |
| JSON | action | 必填，只接受下表中的完整大写动作名称 |

请求体只允许`action`。未知字段、数字枚举序号、非法类型、空正文、缺少动作及不支持的动作均拒绝；不得提交`permissionScope`、`confirmed`、知识版本或当前状态作为授权依据。

```json
{"action":"PUBLISH"}
```

成功响应沿用既有六字段信封：

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "success",
  "data": {
    "userId": "reviewer-001",
    "action": "PUBLISH",
    "permissionScope": "INTERNAL_REVIEWER",
    "confirmationRequired": true
  },
  "trace_id": "trace-knowledge-001",
  "retryable": false
}
```

`userId`与`action`对应本次请求，`permissionScope`由Java固定返回现有范围`INTERNAL_REVIEWER`。
HTTP 200只说明本次角色权限检查通过；`confirmationRequired`是需要确认的策略，不表示用户已经确认，也不表示目标文档存在或状态适用。

| action | 后续使用场景 | confirmationRequired |
|---|---|---|
| READ | 文档列表、详情、历史原文、任务查询及规范问答的读取授权 | false |
| UPLOAD | 创建上传草稿的权限 | true |
| PUBLISH | 发布候选知识版本的权限 | true |
| DISABLE | 停用目标知识版本的权限 | true |
| RETRY_INDEX | 人工重试索引任务的权限 | true |

动作白名单只定义权限契约；上传解析应用、只读管理及上传修订HTTP已接入，发布、停用和索引重试功能仍待实现。首版所有动作共用REVIEWER演示角色，没有额外管理员、租户或跨用户授权模型。

## 2. 错误与失败边界

| 条件 | HTTP | code | retryable |
|---|---|---|---|
| 合法请求缺少或仅有空白X-User-Id | 401 | PERMISSION_DENIED | false |
| 用户ID超长或含CR/LF | 400 | PARAM_VALIDATION_ERROR | false |
| 合法请求角色缺失或不是REVIEWER | 403 | PERMISSION_DENIED | false |
| 缺少/非法action、未知字段或正文无法解析 | 400 | PARAM_VALIDATION_ERROR | false |
| 未预期的服务端异常 | 500 | INTERNAL_SERVER_ERROR | false |

失败响应沿用`success=false`、`data=null`及统一Trace ID，不暴露正文、凭据或内部异常。
请求校验可能先于身份业务判断，不承诺同时存在多个错误时的优先级；任何失败都不能产生授权成功结果。

Java授权服务无知识数据或外部Provider依赖，本任务不新增404或409来假装已查询到知识资源。
KB-02.2的Python Client已将连接失败、超时或响应校验失败收敛为明确异常，不能静默放行；超时与网络异常分别复用`TOOL_TIMEOUT`、`UPSTREAM_UNAVAILABLE`分类，权限拒绝和参数错误不得重试。
Java当前500的`retryable=false`仍不重试。无合法错误信封的其他状态不会被擅自认定为瞬时错误，而是响应校验失败。

## 3. 确认绑定、版本与状态职责

以下是知识写入必须遵守的执行契约；KB-02.6已实现UPLOAD接收确认和修订事务，**发布/停用/索引重试的确认与执行仍待实现**：

1. 用户上传提交、发布确认、停用确认或人工重试，分别形成明确操作意图，模型生成的建议不能充当确认。
2. Python保存并核对操作者、动作、目标文档/候选版本、内容身份及预期状态；KB-02.6已对UPLOAD事务落实，其他动作由后续应用实现。
3. 真正执行前重新调用Java检查对应动作，不复用旧请求的成功响应，也不把本接口当作可离线使用的授权票据。
4. Python从自有知识数据读取当前版本与状态，并在事务内通过条件更新等方式防止确认后目标已变化；不能只比较客户端或模型自报的字段。
5. 确认不匹配、版本/状态已变化、权限拒绝或Java不可用时停止执行，不覆盖旧发布版本，不执行替代动作。

Java仍负责既有订单、复核和返工的事实及最终业务写入；本职责划分不改变业务Review Approval契约。

## 4. 当前实现及停止线

调用链为`KnowledgeAuthorizationClient.authorize → BusinessHttpClient.post_readonly → KnowledgeAuthorizationController.authorize → KnowledgeAuthorizationService.authorize`。
Python请求/响应Schema与Java DTO/枚举共同限定动作、权限范围、字段名和严格布尔类型；响应还需匹配本次用户、动作和Trace，确认要求必须与动作一致。

`post_readonly`只允许`/api/knowledge/authorize`这一个固定路径，不接受路径变体或业务写入端点；现有写POST仍强制幂等键。
Python授权Client默认5秒总预算、最多额外重试一次、首次退避100ms，复用现有RetryPolicy错误白名单。
参数、权限、响应校验及不可重试的Java错误均直接停止；总预算包含退避与HTTP尝试，耗尽后返回不可重试的`TOOL_TIMEOUT`，调用方取消原样传播。
缺省或不符合Java规则的Trace在首次HTTP前规范化一次，重试复用同一标识；日志只记录Trace、错误码、重试序号和退避时长，不记录用户、Token、正文或供应商异常。

应用lifespan装配授权Client并借用既有连接池，启动不主动访问Java，不额外创建需要关闭的HTTP池。该Client独立承担授权查询的重试，后续Tool/应用调用不得再叠加一层自动重试。
局部测试覆盖输入/响应、请求关联、错误映射、重试上限、总预算、取消、无缓存及只读路径白名单；既有写Tool、领域一致性和黄金诊断规则作为必要回归。

本任务沿用M0.5的演示Header信任模型，尚未接入真实登录、签名令牌、可信网关或身份目录；不能将其称为生产认证方案。
Python调用组件已实现；KB-02.4/02.5已建立八表，KB-02.6已接入上传/修订、解析、预览及原件读取应用，KB-02.7～02.10已提供管理、上传修订、预览及原件HTTP。上传入口先查询UPLOAD权限再解析multipart，应用收到完整文件及命令后再次查询；预检不充当可复用执行票据。每次调用及幂等重放独立检查Java权限，预览/原件下载按所属修订过滤并且不激活管理恢复；文件提交本身是明确人工上传操作，不等于确认发布。前端、发布及索引执行仍待接入，未部署现有服务。

KB-02.3已形成[资料、版本与存储隔离设计](KNOWLEDGE_STORAGE_DESIGN.md)，KB-02.4～02.10已提供模型、上传解析应用及管理/预览/原件HTTP，收口已验证真实Java授权及实际Agent进程重启；仅在隔离测试环境执行，仍沿用演示Header信任模型。
KB-03.1已增加发布专用候选与确认校验应用，准备审查和提交确认均独立查询PUBLISH权限，Python读取当前知识事实并绑定实际用户及内容摘要；不新增Java动作或字段，不将授权结果作为确认记录。范围见[发布确认校验](KNOWLEDGE_STORAGE_DESIGN.md#十七kb-031-发布确认请求快照与候选版本校验)。
KB-03.2已将明确确认接入Python发布接收事务，每次PUBLISH授权后按范围重新核对事实并保存操作/索引预留，同键重放也重新授权。Java契约不变，授权HTTP不持有知识事务；接收成功不表示已发布，索引和最终发布前的授权/事务复核仍待实现。范围见[发布接收预留](KNOWLEDGE_STORAGE_DESIGN.md#十八kb-032-发布接收事务幂等操作与候选索引任务预留)。
KB-03.3已接入受控候选索引构建，领取前及完整保存前均独立检查Java PUBLISH权限，授权/模型调用不占用知识事务；原确认人及当前owner之外的调用不能领取，权限撤销后仅允许内部失败收尾。Java契约不变，READY候选不等于已发布。范围见[候选索引构建](KNOWLEDGE_STORAGE_DESIGN.md#十九kb-033-按版本构建候选索引与失败隔离)。
KB-03.4已在管理库内部最终发布前及完整证据准备后两次查询Java PUBLISH权限，Python核对原确认人、知识快照、READY索引及执行条件后原子切换版本。成功重放也重新授权，不把历史成功当作当前权限；Java契约及演示Header边界不变。范围见[最终发布事务](KNOWLEDGE_STORAGE_DESIGN.md#二十kb-034-最终授权复查与发布切换事务)。
KB-03.5已提供独立停用审查和明确确认，每次审查、提交与幂等重放均查询Java DISABLE权限，Python在自有知识事务内核对当前发布身份、计数和确认摘要。停用不借用PUBLISH授权，不调用模型或恢复旧版，旧键不能误停后来发布的新版。范围见[停用事务](KNOWLEDGE_STORAGE_DESIGN.md#二十一kb-035-停用确认权限复查与停用事务)。
KB-03.6已将RETRY_INDEX接入人工重试审查、接收、领取及保存前复查；不复用原PUBLISH授权，服务器仓库动作同时限制授权及任务类型，重试成功只完成READY候选。新的发布仍须新PUBLISH确认及当前权限。范围见[受控索引重试](KNOWLEDGE_STORAGE_DESIGN.md#二十二kb-036-索引失败任务的受控重试)。
KB-03.7～03.8已提供首批演示规范前置检查和内部受确认纳管：审查、确认及成功重放均分别检查UPLOAD/PUBLISH，初次纳管复制原件后再次检查两项权限；确认摘要绑定实际用户、范围、源指纹、库计数和索引身份，不新增Java动作。Python最终事务保护旧索引和管理库事实，历史导入不伪造原发布权限或时间。
KB-03.9新增显式管理库检索应用：每次先检查Java READ、实际用户/动作及只读策略，查询范围必须与授权范围相同，SQL再次按封存修订范围过滤；授权及查询向量生成均不持有SQL连接。不新增Java动作，不能靠过滤器或文档正文授予范围。
下一最小任务为KB-03.10管理库动态就绪检查；本轮仍无发布/停用/重试/纳管/检索HTTP或CLI及问答切源，内部状态不等于改变LEGACY线上召回。
