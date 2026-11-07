# 知识库文档导航

本目录集中维护知识库的需求、资料台账、规范作用及语料与索引说明。这里的管理文档不加入`knowledge-base/catalog.json`，不作为业务规范参与检索。

## 阅读顺序

| 顺序 | 文档 | 主要用途 |
|---|---|---|
| 1 | [需求、资料台账与开发计划](KNOWLEDGE_REQUIREMENTS.md) | 查看已确认需求、16份资料信息、开发批次与验收要求 |
| 2 | [知识库规范作用说明](KNOWLEDGE_GUIDE.md) | 理解每份规范解决的问题、适用场景和业务边界 |
| 3 | [语料与索引说明](KNOWLEDGE_BASE.md) | 查看语料目录、元数据、版本约定、入库与索引历史说明 |
| 4 | [知识管理授权契约](KNOWLEDGE_AUTHORIZATION.md) | 查看KB-02.1 Java接口与KB-02.2 Python Client、动作权限及人工确认边界 |
| 5 | [资料、版本与存储隔离设计](KNOWLEDGE_STORAGE_DESIGN.md) | 查看隔离八表、上传解析应用、KB-02.7～02.10管理/预览/原件HTTP及收口、发布边界 |
| 6 | [KB-02收口验收入口及边界](KNOWLEDGE_STORAGE_DESIGN.md#十六kb-02-管理底座收口验收) | 复现真实Java授权、管理接口、实际Agent重启及黄金订单检查，区分后续未验范围 |
| 7 | [KB-03.1发布候选与确认校验](KNOWLEDGE_STORAGE_DESIGN.md#十七kb-031-发布确认请求快照与候选版本校验) | 查看已实现的Python确认契约、内容绑定与候选规则，以及未接入的发布事务边界 |
| 8 | [KB-03.2发布接收与索引预留](KNOWLEDGE_STORAGE_DESIGN.md#十八kb-032-发布接收事务幂等操作与候选索引任务预留) | 查看幂等接收、事务复查、READY复用、任务预留及尚未执行的索引/发布边界 |
| 9 | [KB-03.3候选索引构建与失败隔离](KNOWLEDGE_STORAGE_DESIGN.md#十九kb-033-按版本构建候选索引与失败隔离) | 查看领取、事务外生成、完整保存、取消/迟到结果及最终发布前的边界 |
| 10 | [KB-03.4最终发布复查与原子切换](KNOWLEDGE_STORAGE_DESIGN.md#二十kb-034-最终授权复查与发布切换事务) | 查看管理库发布、完整证据复核、幂等回执和仍未切换的问答读源 |
| 11 | [KB-03.5停用确认与原子停用](KNOWLEDGE_STORAGE_DESIGN.md#二十一kb-035-停用确认权限复查与停用事务) | 查看独立DISABLE授权、旧意图失效、历史保留及旧键不误停新版 |
| 12 | [KB-03.6索引失败任务受控重试](KNOWLEDGE_STORAGE_DESIGN.md#二十二kb-036-索引失败任务的受控重试) | 查看重试链、RETRY_INDEX权限隔离及READY后仍需新发布确认 |
| 13 | [KB-03.7首批纳管前置校验](KNOWLEDGE_STORAGE_DESIGN.md#二十三kb-037-首批演示规范纳管前置校验) | 查看授权后的只读源快照、完整索引校验及尚未执行的实际纳管 |
| 14 | [KB-03.8首批规范受确认纳管](KNOWLEDGE_STORAGE_DESIGN.md#二十四kb-038-首批演示规范受确认纳管) | 查看整批确认、原件复制、旧源锁内复查、原子纳管和成功重放 |
| 15 | [KB-03.9管理库已发布知识检索](KNOWLEDGE_STORAGE_DESIGN.md#二十五kb-039-管理库已发布知识检索读取) | 查看发布指针/范围过滤、双路同一快照、原引用及管理证据定位 |
| 16 | [KB-03.10管理库动态就绪](KNOWLEDGE_STORAGE_DESIGN.md#二十六kb-0310-管理库动态就绪检查) | 查看实际发布集合、零发布、全量证据校验及Python/前端契约 |

## 相关入口

- [文档总导航](../README.md)：项目架构、演示、开发、学习与面试资料的统一入口。
- [固定规范语料目录](../../knowledge-base/README.md)：原始规范保存在`knowledge-base/active/`和`knowledge-base/historical/`。
- [规范元数据目录](../../knowledge-base/catalog.json)：文档身份、适用范围、有效期及替代关系的事实来源。
- [项目总体计划](../planning/plan.md)：参阅M4 RAG规范检索与M7生产闭环集成相关章节。
- [项目详细计划](../planning/detailed-plan.md)：参阅M4各子阶段及M7.6-C知识库可运行入库，按任务需要读取。
- [当前状态](../STATUS.md)：查看实际完成情况、测试摘要、已知问题与下一任务。

## 维护约定

后续新增知识库专用的需求与说明文档统一放在本目录，并更新本导航。规范正文及`catalog.json`继续在原语料目录维护。
开发批次以需求文档和当前状态为准。现有规范为项目演示资料，不能作为正式行业标准。
