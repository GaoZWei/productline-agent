# KB-02.3 知识资料、版本、任务模型与存储隔离设计

## 解决的问题

现有全量入库会清理catalog之外的资料并替换旧分块，直接承载页面上传会影响新增资料及历史引用；现有知识表还不能分别表达草稿、确认、发布和处理失败。
本设计确定独立管理表、原件存储和版本状态边界，让后续开发可以逐项实现上传预览、候选索引、发布切换及历史回查。

## 核心作用

本设计承接KB-02.1 Java授权和KB-02.2 Python调用契约，为数据库迁移、文件接收及处理流程提供模型与约束。
资料按逻辑文档、规范版本、草稿修订及索引批次组织，操作记录绑定人工意图，任务记录保存处理结果，检索只读取当前发布指针。
Java继续裁决权限，Python依据自有知识数据执行确认、版本及状态事务；文件或外部模型调用不占用长期数据库事务。
KB-02.3阶段只形成设计文档；后续实现进度及边界见本文第九至十一节，不把整体设计视为全部已实现。

## 一、设计决定与当前事实

| 编号 | 决定 | 来源或默认值 |
|---|---|---|
| D01 | 新增独立管理与检索表，旧CLI继续使用原知识表 | 2026-10-29用户已确认 |
| D02 | 未发布草稿允许重新上传修正，每次增加修订号，旧预览和任务失效；发布后必须上传新的规范版本 | 2026-10-31用户已确认；不是在线编辑，旧任务历史记录保留，详见4.2 |
| D03 | 首版使用同一PostgreSQL实例中的Agent自有表，原件使用本地持久化目录及Docker命名卷 | 沿用现有部署；不增加对象存储、消息队列或复杂任务平台 |
| D04 | 管理库准备完成并验收后一次性切换问答源，不混查、不自动回退旧库 | D01的切换约束；知识库页与订单页使用同一服务端数据源 |
| D05 | 默认单个Agent实例负责管理任务，重启后任务明确中断且由人受控重试 | 首版部署限制，不声称已具备多实例任务调度 |

现有16份规范根据catalog中的明确替代关系归为14份逻辑资料，其中2份各有一个历史版本；不根据文件名推断关系。
旧数据仍在`knowledge_documents`和`knowledge_chunks`；旧Repository存在全局文件路径/正文哈希唯一约束、删除旧Chunk及裁剪目录外文档的行为。
旧就绪检查要求文档ID集合与固定catalog相同，不能直接用于动态管理库。现有Chunk ID由规范身份、章节、正文哈希和重复位置签名生成，不包含Embedding模型身份。

实现依据：[原模型](../../agent-service/app/models/knowledge.py)、[旧入库Repository](../../agent-service/app/repositories/knowledge.py)、[就绪检查](../../agent-service/app/services/knowledge_index_capabilities.py)、[分块身份](../../agent-service/app/knowledge/chunking.py)。

## 二、身份、不可变内容及关系

| 身份 | 含义 | 变化规则 |
|---|---|---|
| document_id | 同一份逻辑资料，串联其规范版本 | 创建后稳定，不用文件名或规范版本号充当主键 |
| version_id | 一版规范，例如同一资料的1.0与2.0 | 规范版本号在同一逻辑资料内唯一，字符串精确匹配，不作浮点比较 |
| revision_no | 未发布版本的第几次文件/元数据修订 | 从1递增；修正草稿创建新修订，原修订原件与处理历史保留 |
| generation_id | 对某个修订进行的一次索引构建 | 每次人工重试使用新批次，失败批次保留；批次内Chunk不得重复 |
| citation_document_id | 沿用现有引用格式的规范身份 | 初始纳管保留catalog document_id，新上传版本使用其稳定version_id |

新资料、版本、任务、索引批次和操作ID采用服务端生成的大写前缀加UUID大写十六进制字符，长度不超过128；UUID不用于随机化固定演示业务数据。
新索引可复用稳定Chunk算法，使用`citation_document_id`作为分块输入中的规范身份，初始纳管不重写已有Chunk ID。
同一规范版本发布后封存`published_revision_no`，重新生成向量不能改写这份正文。首版固定现有Embedding身份，模型/维度升级另行规划，不在启动时自动重建。

```mermaid
erDiagram
    LIBRARY ||--o{ DOCUMENT : contains
    DOCUMENT ||--o{ VERSION : has
    VERSION ||--o{ REVISION : retains
    REVISION ||--o{ GENERATION : builds
    GENERATION ||--o{ CHUNK : contains
    OPERATION ||--o{ TASK : starts
    REVISION ||--o{ TASK : binds
```

图中名称是下节表名的简称，展示整体目标；当前模型及上传解析实现见第九至十一节。

## 三、八张新表的职责与字段

统一使用Agent现有Alembic元数据，不创建Java业务实体或Flyway迁移。时间字段使用服务端UTC时区时间。
ID为`VARCHAR(128)`，哈希为64位SHA-256十六进制字符串，计数器为非负`BIGINT`，修订号为正整数。
下列字段是整体迁移目标；KB-02.4建立首批四表，KB-02.5补齐其余四表及版本封存关系，KB-02.6接入原件及上传解析应用。当前尚无对外管理接口或发布执行流程，实现边界见第九至十一节。

| 表名 | 职责 | 关键字段及约束 |
|---|---|---|
| managed_knowledge_libraries | 唯一内部知识库及读源切换 | `library_id=DEFAULT`单例，`source_mode=LEGACY/MANAGED`，`release_revision`，`source_catalog_hash`，创建/激活时间；不增加多知识库产品入口 |
| managed_knowledge_documents | 逻辑资料及当前发布指针 | `document_id`主键，`library_id`外键，`current_version_id`可空，`row_version`，创建人/时间；当前版本必须属于该资料 |
| managed_knowledge_versions | 规范版本及修订指针 | `version_id`主键，`document_id`外键，`specification_version`，唯一`citation_document_id`，`current_revision_no`，`published_revision_no`，`published_generation_id`，`publication_state`，来源与实际管理发布时间；唯一`(document_id, specification_version)` |
| managed_knowledge_revisions | 每次上传的不可变原件及元数据快照 | 联合主键`(version_id, revision_no)`，原件key/文件名/格式/字节数/raw_hash，正文快照及normalized_hash，metadata_hash、业务元数据、创建人/时间；原件key唯一，解析结果仅允许由空写入一次 |
| managed_knowledge_index_generations | 修订对应的索引批次 | `generation_id`主键，版本/修订外键，Provider、模型、1536维度、index_version、分块策略版本及输入哈希，`build_method=GENERATED/COPIED_LEGACY`、`state=BUILDING/READY/FAILED`和时间；批次输入不可变 |
| managed_knowledge_chunks | 某索引批次的检索正文与向量 | 联合主键`(generation_id, chunk_id)`，章节路径、顺序、正文、正文哈希、词元数、全文检索字段及VECTOR(1536)；唯一`(generation_id, chunk_index)`，新增本表独立GIN与HNSW索引 |
| managed_knowledge_tasks | 解析/索引任务的输入与结果 | `task_id`，`operation_id`，`task_type=PARSE/INDEX`，版本/修订/可空索引批次，状态、owner_id、attempt_no、retry_of_task_id、Trace及时间、受控错误码；同一操作的同类任务不重复，单一修订同类任务只能有一个排队或执行中实例 |
| managed_knowledge_operations | 人工动作、幂等、确认及审计 | `operation_id`，actor、Java动作、目标类型/ID、幂等键、input_hash、confirmation_snapshot、状态、结果身份/受控错误码及时间；唯一`(actor_id, action, idempotency_key)`，不保存Token或整篇正文 |

### 3.1 元数据与来源

每个修订保存标题、document_type、satellite_type、product_type、processing_level、specification_version、effective_date、expiry_date及permission_scope；使用显式类型字段参与SQL过滤，不能只藏在任意JSON中。
版本号与所属version行一致，日期满足失效日不早于生效日。元数据哈希覆盖这些业务字段，由服务端按规范化JSON计算，不能相信调用方自报哈希。
来源保存`CATALOG_IMPORT/UPLOAD`、可空原catalog document_id、catalog快照哈希及原生命周期/替代关系；导入按明确替代边分组，不能猜测文件名。

旧catalog的`ACTIVE/HISTORICAL`是来源信息，不直接承担新库发布状态。旧版被新版本替代时，不补造规范失效日，也不把停用伪装成规范失效。
旧作者/发布时间无法核实时保留未知；新管理库的导入时间、操作人和发布时间只记录实际发生的管理操作。

### 3.2 关系及唯一性

- `current_version_id`通过`(document_id, version_id)`组合外键绑定所属资料；版本的发布索引必须通过版本/修订/批次组合关系绑定本版本封存的修订。
- 在version表显式增加`UNIQUE(document_id, version_id)`，在generation表增加`UNIQUE(version_id, revision_no, generation_id)`，作为上述组合外键的合法引用目标。
- version的`current_revision_no`为必填正整数，`(version_id, current_revision_no)`指向修订的循环外键使用`DEFERRABLE INITIALLY DEFERRED`，允许同一事务先插版本再插修订，但提交时不得悬空。
- 通过部分唯一索引限制每份逻辑资料最多一个`PUBLISHED`版本；指针、发布状态和索引READY的跨行一致性由Repository事务保证，不能声称单个CHECK已覆盖跨表语义。
- 原件raw_hash、normalized_hash及metadata_hash不作跨版本全局唯一约束；允许只改元数据或版本号而正文相同。幂等和版本唯一约束负责重复请求保护。
- 复用单份资料的读取、规范化和分块能力，不把新库所有历史版本送入旧catalog的跨文档重复检测器，也不套用旧表的全局正文唯一约束。
- 同一Chunk ID在不同索引批次可出现，但必须代表同一规范身份、章节及正文；联合主键让历史索引共存，默认检索只选择发布批次。
- 创建表时先建立主体再补充循环指针外键；先插入空发布指针的资料，再插入版本、修订和批次，最后更新指针，不改已有迁移。

## 四、状态、草稿修正与确认事务

### 4.1 状态定义

| 对象 | 状态 | 规则 |
|---|---|---|
| 规范版本 | DRAFT、PUBLISHED、SUPERSEDED、DISABLED、HISTORICAL | DRAFT只供预览；PUBLISHED且为当前指针才可检索；SUPERSEDED表示曾发布后被替代；DISABLED表示主动停用；HISTORICAL仅承接初始历史来源 |
| 索引批次 | BUILDING、READY、FAILED | READY表示索引完整，不等于已被发布；未被发布指针引用的批次不进入问答 |
| 任务 | QUEUED、RUNNING、SUCCEEDED、FAILED、INTERRUPTED、STALE | STALE表示目标修订或确认条件已变化，INTERRUPTED表示进程重启；旧失败历史不覆盖 |
| 人工操作 | CONFIRMED、EXECUTING、SUCCEEDED、FAILED、STALE | 创建于明确用户操作，CONFIRMED不是模型推断；发布中不提前标记成功 |

发布前必须满足解析成功、索引READY、修订匹配、权限允许、确认匹配及元数据有效。首版拒绝将未来生效或已过期版本发布为当前依据；已发布后到期的资料由检索日期过滤排除，不自动修改原规范日期。
被替代或停用的版本不能重新变成DRAFT；首版不提供恢复旧版发布或永久删除。
最终模型中，DRAFT的发布修订/批次指针必须为空，PUBLISHED/SUPERSEDED/DISABLED必须具有封存修订及批次，且封存修订等于该版本最后修订；HISTORICAL仅允许CATALOG_IMPORT来源，历史封存批次不表示曾在新平台实际发布。
PARSE任务不绑定generation，INDEX任务必须绑定generation；READY批次必须经完整Chunk数量、身份与向量校验，跨行完整性由事务内读取和条件更新验证。

### 4.2 未发布草稿重新上传

草稿修正仍通过上传文件完成，不提供在线正文编辑。只有DRAFT允许修正，规范版本号保持；修改规范版本号需新建version。
新上传创建`revision_no+1`的原件及元数据快照，原修订不覆盖，并在短事务中按预期document.row_version和current_revision_no切换草稿指针。
旧修订的预览、确认输入和执行中的任务不再适用于发布；排队或执行中的旧任务标记STALE，已完成任务的历史结果保留并注明所属修订。
旧任务迟到结果必须再次核对任务状态、owner_id及当前修订，不能写入新修订、移动发布指针或将旧预览标为当前。
已发布版本的重新上传一律要求新的规范版本；不会因修正草稿而改写已发布规范。

### 4.3 人工操作与幂等

UPLOAD、PUBLISH、DISABLE、RETRY_INDEX沿用KB-02.1动作，不新增Java动作。上传提交本身是明确人工操作，发布/停用/重试分别确认，不能复用模型建议或业务Review Approval。
确认快照使用服务端事实，绑定actor、action、library/document/version、revision_no、正文及元数据哈希、预期资料row_version、原发布指针和需要时的目标task/generation；不存凭据或无关上下文。
同一actor/action/幂等键和相同input_hash重放返回原操作/任务，载荷不同则冲突；新幂等键也不能突破版本唯一及同修订任务并发限制。
唯一约束处理首次并发，条件更新处理执行权；创建/推进操作、任务和指针的事务失败全部回滚。
UPLOAD操作成功表示原件、修订和解析任务已持久化，不等于解析成功；解析结果单独看task。PUBLISH须在实际切换发布指针后才成功，DISABLE须在指针清空后才成功。

### 4.4 发布与停用时序

1. 读取当前候选与资料事实生成预览；用户确认后调用Java校验对应动作，外部HTTP不放在数据库长事务中。
2. 在短事务中重新核对候选、修订、哈希和预期row_version，保存确认快照及幂等记录，预留新的执行row_version；没有匹配的READY索引时创建索引任务，已有完全匹配批次时复用并跳过向量构建。当前已发布指针保持可用。
3. 事务外构建向量，结果只绑定该任务、修订和索引身份。全部批次校验成功后才准备保存完整Chunk集合，不把半批数据标为READY。
4. 构建结束后先在事务外再次调用Java检查PUBLISH权限，再在最终短事务重新校验任务执行权、修订、预留row_version及确认快照；写入完整Chunk并将批次标READY，先把旧版本标SUPERSEDED，再发布新版本、切换指针、递增library.release_revision并完成任务/操作。
5. 任一条件变化或构建失败，旧发布版本不变。不能把Java早先授权或Embedding成功当成最终执行成功。

停用不调用Embedding：Java授权后在同一短事务核对目标为当前发布版本及row_version，设置DISABLED、清空当前版本指针、递增发布修订并保存操作结果。
停用后不自动恢复更旧版本，旧原件及Chunk继续用于已存在引用的回查。
执行中的身份上下文只在当前任务内存持有，数据库不保存Token；权限拒绝、凭据过期或Java不可用均停止最终发布，重启后必须由用户携带新的有效身份重新发起操作。

## 五、原件持久化与失败处理

KB-02.6已增加`KNOWLEDGE_STORAGE_ROOT`配置，本机默认解析为仓库根的`.local/knowledge-storage/`，Compose显式设为`/var/lib/productline-agent/knowledge`并挂载`knowledge-data`命名卷。
显式配置须为不含父级跳转的绝对路径；POSIX存储适配器拒绝目录链中的符号链接。默认目录已加入.gitignore，构造服务不创建目录，只有实际上传才惰性创建；本批没有重建容器或修改现有运行卷。

原件key固定为`versions/<version_id>/revisions/<revision_no>/original.md`或`original.txt`；客户端文件名只作展示，不参加目录拼接。
默认单文件最多10MiB，按流累计字节限制；只接受MD及UTF-8 TXT，解析校验编码与空内容，不展开压缩文件。
保留原字节及raw_hash；规范化正文另存数据库，normalized_hash使用现有BOM/换行规则，不能拿原字节哈希替代规范化内容哈希。

先写受控临时文件，完成长度/格式/编码/哈希检查，再原子创建最终原件入口并提交数据库引用。KB-02.6采用同文件系统硬链接创建及临时入口清理，避免普通改名覆盖已存在原件；最终入口创建后再次校验字节并同步目录。读取时按ID查库定位key，拒绝绝对路径、`..`及符号链接，物理路径不对外返回。
文件系统与数据库不构成同一事务：文件提交成功而DB失败时可能留下未引用文件。首版保留在受控目录，不自动删除、不纳入检索，排查通过脱敏操作身份进行；后续清理必须另设明确范围和审批。
读取原件缺失或校验失败时返回明确错误，不拿另一版或仓库文件冒充。DB中的既有引用原文不因原件下载失败而改写，备份恢复需同时覆盖数据库与原件卷。

## 六、任务中断与重试

首版单个管理任务实例使用进程唯一owner_id，以QUEUED→RUNNING条件更新领取任务；同修订同类任务的部分唯一约束防止并发重复启动。
管理服务激活时将旧owner的QUEUED/RUNNING任务记为INTERRUPTED，并记录受控原因；不自动执行外部模型或继续未完成的索引构建。KB-02.6的`start`可显式调用，也会在首个已授权管理调用时惰性运行；普通FastAPI启动只装配对象，不要求现有运行库已迁移。
对应尚未结束的发布/索引重试操作记为FAILED，保留中断原因；已成功接收文件的UPLOAD操作不改写为失败，其解析任务单独显示中断。
INDEX任务的人工重试必须重新校验Java RETRY_INDEX权限及目标修订，创建新操作、新task和新generation，通过retry_of_task_id保留原失败，不把原失败记录改成成功。
RETRY_INDEX只构建READY候选，不自动发布；成功后需要新的PUBLISH确认和Java权限检查才能切换指针，不复用原失败发布的授权。新发布可以复用该READY批次，不重复生成向量。
PARSE失败或中断通过UPLOAD重新上传修正草稿、生成新修订和解析任务，不借用RETRY_INDEX权限，也不新增未约定的Java动作。
旧修订或已不适用目标不能重试；新任务输入始终来自保留的不可变修订，不信任客户端提交的正文、状态或路径。
错误记录仅含内部白名单错误码、阶段、Trace及时间，不保存凭据、绝对路径、正文或供应商原始异常。
多实例租约、自动故障接管及跨实例队列不在本版，不能将单实例重启处理描述为已具备分布式恢复能力。

## 七、初始纳管、统一切源与就绪检查

### 7.1 初始16版本纳管

未来通过显式运维入口执行，要求明确人工确认并调用Java检查UPLOAD/PUBLISH权限，应用启动不纳管、不调用Embedding。
按catalog的替代关系建立14个逻辑document和16个version，各建立revision 1；14个当前版本准备为PUBLISHED，2个历史版本为HISTORICAL，保留原日期、类型、权限、替代关系和引用规范ID。
复制原件及既有80个Chunk/向量前，校验源文件、规范化正文、章节、Chunk身份、catalog快照和完整Embedding身份一致；`build_method=COPIED_LEGACY`记录复制来源，不能冒充重新调用了模型。
任一数据缺失或不匹配时停止，不隐式付费补齐、不删除旧数据。纳管过程可在源快照不变时重放，不重复建立资料、版本或批次；来源不同则冲突，不覆盖已纳管历史。
导入实际时间、操作人、任务和新的管理发布时间记录实际值；旧规范原发布人/时间未知时仍为空，不伪造旧平台发布记录。

### 7.2 数据源统一切换

新singleton起始为LEGACY，现有CLI、固定测试及问答继续用原表。管理库准备完成前，草稿可预览，但公共发布/停用不作为线上已生效操作；初始纳管是受确认的内部准备流程。
全部纳管数据及索引验收后，由独立人工操作再次校验Java PUBLISH权限及源快照，在短事务将source_mode改为MANAGED并递增release_revision。
知识库问答与订单规范检索从同一服务端选择器取得模式；MANAGED只使用新表，LEGACY只使用旧表，不合并候选或在故障时静默切回旧表。
首版不提供MANAGED→LEGACY的反向切换，避免停用资料或新发布规则被旧库重新放行。旧CLI仍可维护旧表，但不能更新、裁剪新表或影响MANAGED发布集合。

### 7.3 检索、就绪和历史引用

新Repository按document当前版本指针、version封存修订和发布generation关联Chunk，先应用权限、产品、卫星、处理级别、版本及日期条件，再执行TopK。
查询Embedding生成在读取检索数据的短事务前完成；一次检索的source_mode、release_revision、发布指针与关键词/向量候选在同一REPEATABLE READ快照内读取，生成答案不持有该事务。
引用继续保留规范ID、规范版本、章节、Chunk ID及原文，历史版本和索引不被新构建覆盖。后续Run策略快照补充数据源模式、发布修订与实际索引身份，不能重写旧Run中未记录的字段。

新就绪检查依据实际发布集合及完整索引身份，不再比较固定16个catalog ID；草稿、历史、失败批次不占用发布集合的完整性统计。
所有资料停用时发布计数为0，`ready=false/NOT_INDEXED`并明确“无已发布资料”，不回退旧库。新计数契约必须允许0，并同步Python/前端Schema及测试，不能直接套用旧`expected_document_count>0`约束。
就绪代表索引可用，不保证当前问题有适用证据；过期资料仍由检索日期条件排除。现有关键词零召回和最终回答质量问题不会因表结构改变而自动解决。

## 八、后续开发切分与验收

| 任务 | 最小交付 | 停止线 |
|---|---|---|
| KB-02.4 | 新资料、版本、修订Schema/ORM和增量迁移，先建立library/document/version/revision四表及约束 | 迁移、引用关系、状态输入和并发约束可在隔离数据库验证；不接上传或线上迁移 |
| KB-02.5 | 操作/任务/索引批次/Chunk四表及约束，补齐循环引用与任务关系 | 管理模型完整，失败/重复/并发关系验证通过；不实现后台模型调用 |
| KB-02.6 | 原件存储适配及上传/解析应用服务 | 路径、大小、编码、修订替换和DB失败孤儿文件有明确行为；草稿不进问答 |
| KB-02.7 | 只读管理接口：资料列表、详情、版本及任务查询，接入READ授权 | 身份/范围过滤和脱敏结果可验证，不同时建设上传接口或页面 |
| KB-02后续接口任务 | 上传、修订、正文/分块预览及原件读取接口 | 完成原KB-02停止线；接入KB-02.6应用，不自动扩建发布或页面 |
| KB-03 | 索引执行、确认发布、停用、初始纳管及统一切源 | 原有KB-03停止线不变，按可测试小任务分别验收 |

循环外键分两次迁移建立：KB-02.4先建立资料→版本→修订及当前版本归属约束，仅开放DRAFT数据持久化；依赖generation的发布指针字段及状态约束到KB-02.5随新表、归属外键和索引一起加入，不先接受悬空批次ID。
迁移必须基于实施时真实Alembic head新增，不预先承诺固定迁移编号；不修改0014及此前迁移，也不把设计文档当作已执行迁移。

验收用例包括：同版本草稿修订替换与旧任务迟到、已发布版本不可改、同正文不同版本合法、幂等重放/冲突、两个发布并发、构建失败保留旧版、停用不回退、原件丢失/越界、重启不自动付费、旧CLI只影响旧表、初始14资料/16版本关系与原引用保留、切源后无混查、零发布资料的就绪状态，以及ORDER-003黄金链路回归。

KB-02.3验收只核对文档、关系、固定资料映射及当时的相关局部回归，不新增已实现的Agent面试关注点或功能里程碑记录；后续实现按下节范围及STATUS.md记录。

## 九、KB-02.4 首批Schema、ORM与迁移

### 解决的问题

只有设计文档时，资料、版本及修订仍无法持久化，也无法验证同一规范版本重复写入、修订指针悬空或跨资料引用等错误。
本任务建立独立基础表及严格内部快照，先让这些关系和失败回滚在数据库中可验证，为后续管理应用提供数据底座。

### 核心作用

本阶段承接Java授权与Python授权Client，定义内部知识库、资料、规范版本和修订的输入边界，由数据库保存关系、原件定位信息和元数据快照。
Schema拒绝非法状态、格式、日期、来源及不匹配的正文哈希；组合外键、唯一约束和延迟外键约束分别保护归属、重复版本和同事务创建版本/修订。
当前没有对外管理接口或Repository操作，授权仍须由后续应用在执行前调用Java，模型和页面不能借这些内部记录获得权限。

### 已实现范围

- [内部Schema](../../agent-service/app/schemas/managed_knowledge.py)：`ManagedKnowledgeLibraryState`、`ManagedKnowledgeDocumentState`、`ManagedKnowledgeDraftVersion`、`ManagedKnowledgeMetadata`及`ManagedKnowledgeRevisionSnapshot`。内部快照拒绝额外字段；元数据哈希由`metadata_digest`按固定JSON计算，覆盖业务字段、演示标识、维护主体和变更说明，不接受自报`metadata_hash`。
- [四表ORM](../../agent-service/app/models/managed_knowledge.py)：library/document/version/revision。规范版本号在同一资料内唯一，引用身份及原件key唯一；原件和正文哈希没有跨版本唯一限制。修订中的规范版本号通过组合外键与版本行一致。
- [0015增量迁移](../../agent-service/migrations/versions/0015_managed_knowledge_drafts.py)：基于`0014_review_source_run`新增四表、循环外键和`DEFAULT`库记录。该记录固定`LEGACY`且未激活；版本仅允许`DRAFT`，不导入固定语料、不修改旧表、不切换问答源。降级仅移除本迁移新增对象。
- 版本指向当前修订的外键为`DEFERRABLE INITIALLY DEFERRED`：允许同一事务先插版本再插修订，提交时没有对应修订则整笔回滚。`current_version_id`只校验资料归属，发布指针与状态的跨行一致性仍由后续发布事务负责。
- 正文快照保留规范化后的首尾空白；正文与规范化哈希必须成对，并核对实际SHA-256。原件字节哈希需要后续文件接收器计算，本阶段不接收或读取实际上传文件。

### 验收入口及后续边界

`make test-knowledge-models`包含新旧Schema测试及隔离PostgreSQL测试。新增持久化测试在独立数据库中以旧表哨兵验证`0014→0015→0014→0015`，并核对四表与ORM一致、外键、唯一约束、回滚和真实锁竞争；同一入口既有持久化测试继续验证完整旧迁移链及旧检索行为。
也可向专用测试PostgreSQL配置`AGENT_PERSISTENCE_TEST_DATABASE_URL`，在agent-service执行`.venv/bin/pytest -q tests/knowledge/test_managed_knowledge_persistence.py`；测试只迁移自行创建的临时库，连接用户须能创建/清理测试库。

快照冻结仅约束Schema对象；数据库字段不等于已具备业务不可变保护。修订号连续递增、原件落盘、解析结果只写一次、旧任务失效、操作幂等和封存均待应用服务实现。
KB-02.4验收时未增加Java/前端接口、文件目录/卷、后台任务或模型调用，发布修订及索引批次字段当时不存在；后续KB-02.5范围见第十节。KB-02.4不新增Agent面试关注点。

## 十、KB-02.5 操作、任务、候选索引与封存关系

### 解决的问题

首批四表不能保存人工操作、处理失败和重试关系，也无法区分已构建的候选索引与已封存的规范证据。
本任务补齐处理模型及数据库关系，让后续服务有地方保存幂等身份、确认快照、任务进度和历史分块，避免重复任务及跨版本引用。

### 核心作用

本阶段在资料、版本和修订之后接入操作、任务、索引批次及分块，输入为严格内部记录，输出为可验证的持久化关系。
确认记录绑定用户、动作、目标修订及哈希，任务关联操作、修订和重试来源；候选批次保留索引身份，分块按批次共存，规范版本通过组合外键引用本修订的封存批次。
数据库只保护已定义的结构和并发约束；Java授权、人工意图核验、文件及模型处理、重启恢复和最终发布事务仍须由后续应用实现。

### 已实现范围

- [处理Schema](../../agent-service/app/schemas/managed_knowledge_processing.py)：`ManagedKnowledgeConfirmation`、`ManagedKnowledgeOperationRecord`、`ManagedKnowledgeTaskRecord`、`ManagedKnowledgeGenerationRecord`和`ManagedKnowledgeChunkRecord`，拒绝额外字段及凭据/正文载荷；校验操作与快照身份、状态/时间/错误组合、重试输入、正文哈希及有限非零1536维向量。
- [处理ORM](../../agent-service/app/models/managed_knowledge_processing.py)：操作、任务、索引批次及Chunk四表，与首批四表共同构成八表管理模型。没有任务调度器、Repository或外部调用。
- 操作统一以规范版本为目标，保存`target_type=VERSION`及`target_id=version_id`；RETRY_INDEX的原任务在严格确认快照和新任务的`retry_of_task_id`中保存。KB-02.5只提供幂等键唯一约束；KB-02.6已接入UPLOAD同载荷重放和不同载荷冲突，其他动作仍待后续服务。
- 确认快照采用JSONB，Schema限制固定字段；数据库检查身份绑定、关键字段及键白名单，拒绝JSON空值身份或附加Token字段。该记录不等于已验证Java权限或已核实知识事实，执行前仍须重读自有数据并复查权限。
- 任务通过组合外键绑定同一版本/修订的操作及批次，原重试任务必须属于同一修订、同一类型；同一操作同类任务唯一，同一批次只关联一个索引任务。部分唯一索引限制同修订同类任务最多一个QUEUED/RUNNING实例；失败、中断和失效历史可保留。
- 原件解析任务仅允许UPLOAD且不绑定generation；索引任务仅允许PUBLISH/RETRY_INDEX并绑定generation。RETRY_INDEX必须指向原任务并使用新的attempt_no，原任务是否可重试及次数连续性仍由后续应用复核。
- 候选批次保存Provider、模型、1536维度、索引/分块版本、输入哈希及构建来源；READY要求正分块计数和完成时间，FAILED保存受控原因。实际数量、分块身份及向量完整性属于跨行校验，尚未实现。
- Chunk使用`(generation_id, chunk_id)`联合主键及批次内顺序唯一约束；不同批次可保留相同稳定Chunk身份，新增独立GIN和HNSW索引。内部快照保留元组不可变性，写入pgvector时转换为列表；现有测试使用`model_dump(mode="json")`，后续Repository须做同等转换。
- [版本状态Schema](../../agent-service/app/schemas/managed_knowledge.py)新增`ManagedKnowledgeVersionState`，保留上传入口专用的`ManagedKnowledgeDraftVersion`；后者仍拒绝自报发布状态。版本增加封存修订、批次和实际管理发布时间，HISTORICAL仅允许历史catalog来源且不伪造发布时间。
- [0016增量迁移](../../agent-service/migrations/versions/0016_managed_knowledge_state.py)基于0015，扩展发布状态及行内封存约束，增加同资料最多一个PUBLISHED版本的部分唯一索引，并通过版本/修订/批次组合外键防止引用其他版本的批次。0015及此前迁移保持原样。

### 验收与后续边界

`make test-knowledge-models`覆盖新旧Schema、八表与ORM一致性、非法输入、并发幂等键/活动任务排他、失败重试、历史分块共存及发布引用失败时原指针保留。
增量迁移可在隔离库升级/降级；0016降级前要求所有版本仍为DRAFT，有封存版本时整个降级事务失败，保留证据，不自动转换或抹去发布历史。

本批仍固定LEGACY读源，不执行资料纳管或问答切源。数据库外键不能证明候选READY、发布指针与状态一致、权限有效或确认仍适用；也没有禁止所有直接SQL修改的封存触发器，不能据此宣称发布闭环已完成。
KB-02.5验收时以上处理流程尚未接入；KB-02.6交付见第十一节，发布与停用执行仍待后续任务。KB-02.5不新增Agent面试关注点。

## 十一、KB-02.6 原件、上传修订与解析应用

### 解决的问题

只有八表模型时，真实文件仍无法安全保存，重复上传、草稿修正和迟到解析也缺少事务边界。
本任务把Java授权、独立原件和确定性解析接成内部应用服务，让接收结果、失败记录、旧修订及原文回查能够验证。

### 核心作用

上传输入为明确文件提交、业务元数据和可选目标快照；Java裁决UPLOAD权限，Python在短事务中复查资料、规范版本及修订，交付草稿/操作/任务身份。
文件写入及解析放在事务外，解析结果提交前再次检查owner、任务状态、当前修订和正文是否已写入；预览和原件读取分别验证READ权限。
该服务没有对外路由或Agent Tool注册，不生成向量、不切换LEGACY问答源、不发布规范，也不能让文档授予业务操作权限。

### 输入和处理约定

| 操作 | 命令目标 | 约束 |
|---|---|---|
| 新资料 | 无document/version及预期计数 | 服务端生成资料/版本身份及revision 1 |
| 已有资料新增规范版本 | document_id和expected_row_version | 同资料规范版本号唯一，原发布指针不变 |
| 修正未发布草稿 | document_id、version_id及预期资料计数/修订号 | 仅DRAFT且规范版本号保持，接收成功才创建revision_no+1 |

- [上传Schema](../../agent-service/app/schemas/knowledge_management.py)拒绝调用方提交原件key、正文哈希或发布状态；文件名只作展示，拒绝目录分隔符及控制字符。演示标识、维护主体及权限范围沿用已确认元数据契约，操作人使用本次Java授权的实际用户。
- [原件适配器](../../agent-service/app/knowledge/storage.py)逐级使用目录描述符与NOFOLLOW，流式累计10MiB上限，校验UTF-8、非空和数据库不能保存的NUL字符。非法格式、大小、编码或空文件在接收前拒绝并清理临时文件，不改变原草稿或产生新修订。
- [上传服务](../../agent-service/app/services/knowledge_management.py)每次重新检查Java权限，幂等重放也不能复用旧授权。输入哈希覆盖文件原字节身份、文件名、元数据及目标快照；相同用户/UPLOAD/幂等键同输入返回原操作及任务，不同输入明确冲突。
- [事务Repository](../../agent-service/app/repositories/managed_knowledge.py)用幂等键事务锁及唯一约束保护重复提交，锁定资料后复查row_version、当前修订、DRAFT状态及规范版本号。接收事务保存修订、UPLOAD成功记录与PARSE任务，递增资料计数；旧排队/运行任务及待执行发布意图失效，旧完成结果不覆盖。
- [单份解析](../../agent-service/app/knowledge/managed_parsing.py)复用已有BOM/换行规范化、Markdown标题校验和稳定分块。分块输入只要求引用身份与标题，不补造旧catalog的ACTIVE或有效期，不调用跨文档重复检测器；同正文不同版本合法。
- 成功接收后，在独立事务领取当前owner的PARSE任务，事务外解析，最后原子写入正文/normalized_hash及任务成功状态；正文只由空写入一次。Markdown必须以与元数据匹配的一级标题开始，失败保留草稿、原件和PARSE_FAILED记录，UPLOAD仍表示接收成功。
- 修订变更、任务失效、owner变化或管理服务中断后，迟到结果不能覆盖当前正文。明确启动或首次授权管理调用将旧owner未完成任务标INTERRUPTED，未完成发布/索引重试操作及构建批次标失败；不重写成功UPLOAD，不自动执行旧任务或调用模型。
- 服务提供带修订及资料计数的正文/分块预览和授权原件读取。旧预览可历史回查并标记非当前修订，不等于有效发布确认；分块仅在内存中预览，不写向量或检索表。原件缺失/摘要不符明确失败，既有数据库原文不被其他文件替代。

### 文件与数据库失败边界

文件与PostgreSQL不共事务。原件入口创建而数据库提交失败时保留未引用文件，返回KNOWLEDGE_PERSISTENCE_UNAVAILABLE，不自动删除或纳入检索。
同一版本/修订路径再次上传相同字节可以校验复用；不同字节返回ORIGINAL_CONFLICT。此时可先以原文件重试完成接收，再上传下一修订，或新建规范版本，不能默默覆盖孤立原件。清理仍须另行明确范围。
数据库失败与解析失败分别处理；取消不会伪装成成功，已领取任务保留执行中事实供管理服务重新激活时标中断。

| 结果或错误码 | 含义 |
|---|---|
| UNSUPPORTED_FORMAT / FILE_TOO_LARGE / INVALID_ENCODING / EMPTY_DOCUMENT / INVALID_TEXT_CONTENT | 接收前拒绝，原草稿保持 |
| IDEMPOTENCY_CONFLICT | 同一幂等键携带不同输入 |
| STALE_DOCUMENT / STALE_REVISION / SPECIFICATION_VERSION_CONFLICT | 资料快照、当前修订或规范版本不匹配 |
| SEALED_VERSION_REQUIRES_NEW_VERSION | 已发布或其他封存版本不能重新作为草稿修改 |
| PARSE_FAILED / STORAGE_ERROR | 任务解析或原件访问失败，不等于上传记录应被删除 |
| PREVIEW_NOT_READY | 尚无可信解析正文，不能伪装空预览成功 |
| ORIGINAL_NOT_FOUND / ORIGINAL_INTEGRITY_ERROR / ORIGINAL_CONFLICT | 原件缺失、校验失败或禁止覆盖 |

### 装配、验证与后续边界

FastAPI lifespan仅装配`knowledge_management_service`，不主动查询Java、读取原件、创建目录或启动工作任务；现有健康检查无须先迁移新表。管理服务激活前必须已显式执行已有0015/0016迁移，本批没有新增迁移或部署。
`make test-knowledge-management`验证离线文件及解析边界，再用隔离PostgreSQL和真实授权Client/模拟Java响应验收应用；真实Java联调、HTTP管理路由及真实进程/容器重启仍待后续阶段。
共享数据库夹具只迁移自动创建的测试库；mypy配置显式命名空间，使测试辅助模块与Python导入路径一致，不改变运行模块加载。
下一最小任务为KB-02.7只读管理接口。当前仍是单管理实例、无分布式租约、无后台模型/索引任务执行、无发布或停用接口，也没有旧版本恢复发布及永久删除。
