# ORDER-003 统一页面演示链路

本记录对应2026-10-22已发生的一次固定演示。用户在页面完成复核与返工确认，随后只读回查数据库持久化接口和Java事实；整理记录时没有重发模型请求、再次确认或重置数据。

完整Run/Step快照保存在[本次演示快照](demo/order-003-20261022.json)，包含三条主链路Run的38个Step、三个失败Run的36个Step，以及独立批次的规范问答和状态查询。快照只保存演示业务标识、状态、受控步骤摘要、引用身份和操作结果，不包含账号、密钥、原始模型请求或响应。

## 1. 页面操作与实际效果

入口：`http://localhost:5173` → 选择ORDER-003 → 打开Agent助手。

| 顺序 | 页面操作 | 预期效果 |
| --- | --- | --- |
| 1 | 输入“请诊断 ORDER-003 为什么尚未交付，并说明根因和处理建议。” | 返回坐标系问题未关闭、待复核两项根因，以及返工和重新复核建议 |
| 2 | 在同一会话输入“请根据刚才对 ORDER-003 的诊断，为 TASK-003 生成复核草稿，仅生成草稿供我确认。” | 刷新Java任务和问题、检索现行规范，生成绑定TASK-003/ISSUE-001的待确认草稿 |
| 3 | 核对结论、意见、引用，确认复核并完成页面二次确认 | SUBMIT_REVIEW独立授权成功，新增REWORK_REQUIRED复核记录，任务版本0→1 |
| 4 | 点击“创建独立返工确认单” | 创建新的CREATE_REWORK Approval和Run；此时尚未创建业务返工任务 |
| 5 | 核对返工确认单并确认执行 | Java创建PENDING返工任务，任务版本1→2 |
| 6 | 顶部“运行历史”→“刷新记录”，分别选择诊断、复核和返工Run | 查看持久化状态、Step时间线、耗时、引用及人工确认记录 |

当前演示任务已是版本2，不能直接按初始版本0再次验收。恢复初始场景需另行执行已核对的重置流程，本次未重置。

## 2. 同一Session的真实关联

Session：`session-d0eb14f5ab2f4f87a9653b487082d825`。

```text
诊断 run-cf1e9e22d2af47269cb2e8b2bd20bc13
  ↓ source_run_id
复核 run-09ba330c04314f1bbcb4c585c20fbbc1
  ↓ source_run_id
返工 run-rework-13f63423a4eb49259156b4bfd96951e1
```

三条Run均为SUCCEEDED。复核和返工分别拥有Approval，分别确认；草稿生成和复核确认属于同一复核Run，确认不会另造一条复核Run。

| 阶段 | Step数 | Run总耗时 | 单独核对的耗时 | 对话Token | 退出原因 |
| --- | ---: | ---: | --- | ---: | --- |
| 动态诊断 | 24 | 11.729秒 | 无人工等待 | 18416 | MAX_ITERATIONS |
| 复核草稿及确认 | 12 | 39.957秒 | 草稿约11.341秒；等待确认28.365秒；写回237毫秒 | 12603 | APPROVAL_SUCCEEDED |
| 返工确认 | 2 | 220.488秒 | 等待确认220.431秒；写回47毫秒 | 0 | APPROVAL_SUCCEEDED |

耗时来自持久化时间戳：草稿生成时间为复核Run开始到Approval创建，人工等待来自APPROVAL Step，写回来自WRITEBACK Step。Run总耗时含人工等待，父子Step存在重叠，不能把所有Step耗时直接相加。

动态诊断在6轮预算结束时已收齐事实，由规则形成结论；实际原因保留MAX_ITERATIONS，不能描述成模型主动FINISH。Token仅表示已记录的对话模型用量，不包含查询Embedding或没有返回用量的失败调用，也不代表质量评测。

## 3. 关键Step与落库结果

完整步骤、顺序、状态、耗时、输入输出摘要和模型用量见JSON快照；以下列出业务核对点。

| 阶段 | 核心Step | 已核对结果 |
| --- | --- | --- |
| 诊断 | get_order_detail、get_related_tasks、get_quality_issues、get_review_result、get_delivery_status | 5个Java只读Tool Step成功 |
| 规范依据 | answer_specification、rerank_specification、generate_specification_answer | RAG与模型Step成功，带现行规范引用 |
| 草稿 | get_task_detail、get_quality_issues、generate_review_draft | 刷新事实并生成REWORK_REQUIRED草稿，5条引用 |
| 复核确认 | wait_for_review_confirmation → write_review_result | 人工确认成功，Java复核结果成功写入 |
| 返工确认 | wait_for_rework_confirmation → create_rework_task | 人工确认成功，Java返工任务成功创建 |

复核Approval：`approval-16f2008fa3d34098bae2712f944b6e89`。

返工Approval：`approval-rework-5392cfa497da41bcb1ad4d84627b32ac`。

返工任务：`REWORK-WRITE-5E45108C-6AFC-4ECC-B28B-EF975F321534`，类型COORDINATE_SYSTEM_FIX，状态PENDING。

当前Java事实：TASK-003生产状态COMPLETED、版本2；ISSUE-001仍为OPEN；新增REWORK_REQUIRED复核记录；交付仍为BLOCKED。历史PENDING复核记录仍保留，不能把旧记录当成新写入丢失。创建返工只建立待处理任务，实际修改成果、关闭问题、重新复核和交付未在此链路实现。

两个成功操作日志均保存Java Trace和版本递增结果。顶层Run的Tool计数尚未合并确认阶段调用：诊断显示5、复核显示2、返工显示0；WRITEBACK Step和操作日志已证明发生业务写入，不能按顶部0推断没有Tool执行，也不能仅按已记录Step推导全部HTTP调用次数。

## 4. 实际失败与恢复情况

| Run或Trace | 实际失败 | 耗时 | 后续处理及边界 |
| --- | --- | ---: | --- |
| run-1f3a532543214ebdbd301c9dc513ac33 | Run为RESPONSE_VALIDATION_ERROR / execute_action；内部answer_specification Step为KEYWORD_SEARCH_FAILED | 7.654秒 | 没有Approval或WRITEBACK；随后新会话诊断成功。摘要只证明关键词检索失败，底层原因尚未定位，不能认定已经修复 |
| run-3aab59d22db84620bee86e5de40b0e25 | MODEL_OUTPUT_VALIDATION_ERROR / generate_review_draft | 12.252秒 | 同一Session下后续新请求生成草稿成功；失败Run没有Approval或WRITEBACK。尚未确认模型具体哪个字段不合法，不能用重试成功代替根因修复 |
| run-3ea07b53e024434ba5bce25d9daa1488 | PARAM_VALIDATION_ERROR / initialize，页面ORDER-001与目标ORDER-003不一致 | 1.290秒 | 历史失败已通过分发前确认切换修复；本轮只保留原记录，未重写历史 |
| trace-0ddb8bdd-432f-4bd9-ac51-a089121aba24 | SESSION_EXPIRED，旧会话过期 | 未记录 | 在Run创建前拒绝，只有此前页面保存的Trace；新建会话并重新诊断后继续。不得补造Run或耗时 |

失败模型Step中Token为0表示当前没有记录到用量，不能证明请求没有消耗Token。上述失败没有确认授权，不生成业务写入。后续成功请求是独立Run，不会把旧失败改为成功。

## 5. 独立批次的其他入口

| 能力 | Run | 耗时 | Step数 | 说明 |
| --- | --- | ---: | ---: | --- |
| 规范问答 | run-f7dbdb9338784c8e8837fe367da51d46 | 4.548秒 | 7 | 此前统一接口的真实规范问答批次，返回SPECIFICATION_ANSWER，引用已在该批次核对 |
| 状态查询 | run-b6ec1d30885140fcbb4a8413a571dacd | 1.015秒 | 5 | 统一入口返回ORDER_STATUS，1个Java只读Tool |

这两条记录与主链路Session不同，只作为入口覆盖的独立证据，不拼接为同一会话。

## 6. 保存方式与验证范围

- Run/Step、Approval和操作日志已由应用持久化；统一页面“运行历史”读取这些记录。本次又以只读API保存一份固定演示快照，数据库重置后仍可查看这次证据。
- 采集入口：`GET /api/agent/runs/{run_id}`、`GET /api/agent/runs/{run_id}/steps`、`GET /api/agent/approvals/{approval_id}/operation-log`及Java订单overview；没有调用POST或外部模型。
- 导出时通过项目RunDetailResponse、StepListResponse和OperationLogDetail Schema校验；核对同Session来源关系、成功终态、两个独立操作、版本0→1→2、失败Step及当前Java状态。
- 本轮在浏览器历史页实际查看返工成功、复核成功及模型输出校验失败记录；主链路用户操作与既有页面验证详见[准备清单](../Agent-interview.md)。本次没有重新点击任何确认按钮。
- 本记录不改变已知问题：确认阶段Tool计数遗漏、历史页缺少直接业务结果展示、会话过期缺少恢复引导、复核时间线沿用诊断名称，以及上表两次尚未定位的运行失败。
- 下一最小任务：处理确认阶段统计和结果展示；之后整理演示重置步骤。新增Agent面试关注点：无，本次补齐既有链路的实际证据与未解决边界。

## 7. 后续首问失败排查补充（2026-10-22）

新增失败Run `run-e587adbc3202488794d190fd40c37803`与此前关键词失败路径相同：Java只读成功，内部RAG报KEYWORD_SEARCH_FAILED，Run显示RESPONSE_VALIDATION_ERROR/execute_action。原记录未保存底层异常或查询原文，不能用后续修复替换历史原因。

已离线复现并修正规范问答与关键词查询的字符/词元上限冲突，同时增加不含原文的异常类型及计数日志。独立数据库回归与容器长查询检查通过，用户明确允许后只验证一次新会话首问：Run `run-4ccd1f6f37dd45249e888e7625897cff`成功，耗时10.997秒、24个Step成功、RAG返回5条引用、业务快照相同。新Run仍以MAX_ITERATIONS结束；本次未复核、返工或重置，也未改写前述JSON快照。该次成功不能证明所有首次请求均不再失败，具体再发原因需按新日志定位。
