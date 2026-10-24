# 演示重置与重复运行

适用场景：完成ORDER-003复核和返工演示后，恢复初始状态，再从诊断开始演示。所有命令在仓库根目录执行。

## 1. 会清除什么

当前`make reset-demo`会停止当前Compose项目的全部服务，删除该项目的PostgreSQL数据卷，然后重新启动PostgreSQL和Java。

| 内容 | 重置结果 |
| --- | --- |
| Java业务数据 | 恢复30个固定订单；清除新增写入，恢复23条预置复核和3条预置返工；清空幂等、操作日志；任务版本归零 |
| Agent会话、Run、Step、Approval及操作日志 | 一并清除，旧Session和确认单不能复用 |
| 知识文档、Chunk和向量 | 一并清除，需要重新迁移和执行Embedding入库 |
| 本地代码、`.env`、知识源文件、已导出的演示快照 | 保留 |

这是全量演示重置，当前没有“只清业务写入并保留知识向量”的独立入口。重置前保存需要保留的Run/Step及操作证据；已保存的2026-10-22记录见[演示链路](AGENT_DEMO_FLOW.md)和[快照](demo/order-003-20261022.json)，它们不包含之后新增的记录。

开始重置前结束当前演示、停止新请求，确认没有正在提交的复核或返工。当前订单是否为版本2不影响重置操作，但重置后必须从新会话开始。

## 2. 执行顺序

Mac终端如果找不到Docker或凭据助手，只为当前终端补入工具路径：

```sh
cd /Users/gao/Desktop/productline-agent
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ps
```

核对显示的是准备重置的本地Compose项目。以下第一条命令会删除该项目的数据库卷；不要在需要保留的数据库上执行。

```sh
# 1. 清空演示数据库，恢复Java固定数据，校验Flyway V1～V4、任务版本和写入历史。
make reset-demo

# 2. 构建Agent，执行Agent迁移，使用当前Embedding配置重新生成并写入知识索引。
make knowledge-ingest

# 3. 构建页面并恢复Agent和Web服务。
docker compose build web-console
docker compose up -d agent-service web-console
```

每条成功后再执行下一条。`make knowledge-ingest`已包含`alembic upgrade head`，无需再单独运行迁移；它会调用真实Embedding Provider并消耗Token，不会调用对话模型或创建复核/返工任务。当前16份文档和80个Chunk需重新生成向量，不复用已删除数据卷中的向量。

`make reset-demo`成功只说明Java固定数据已恢复；完成知识入库并启动页面后，才具备完整Agent演示条件。不要以单个`/health`成功代替知识索引校验。

## 3. 重置后的检查

先检查服务健康与知识能力，这些GET请求不调用模型：

```sh
docker compose ps
curl --fail --silent --show-error http://127.0.0.1:8080/health
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:5173/health
curl --fail --silent --show-error http://127.0.0.1:8000/api/agent/capabilities
```

默认页面为`http://localhost:5173`；若本地修改了服务端口，使用`.env`中对应的端口。当前DBeaver连接使用`127.0.0.1:15432`，容器内部数据库端口仍是5432，重置不需要创建新数据库角色或更改模型密钥。

在发起任何新对话前，执行只读SQL检查初始版本、历史清空和知识恢复：

```sh
docker compose exec -T postgres sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "
SELECT 'task_version=' || version FROM production_tasks WHERE task_id = 'TASK-003';
SELECT 'reviews=' || COUNT(*) FROM review_records;
SELECT 'reworks=' || COUNT(*) FROM rework_tasks;
SELECT 'idempotency_records=' || COUNT(*) FROM idempotency_records;
SELECT 'java_operation_logs=' || COUNT(*) FROM operation_logs;
SELECT 'agent_runs=' || COUNT(*) FROM agent_runs;
SELECT 'approvals=' || COUNT(*) FROM approval_records;
SELECT 'knowledge_documents=' || COUNT(*) FROM knowledge_documents;
SELECT 'knowledge_chunks=' || COUNT(*) FROM knowledge_chunks;
SELECT 'agent_migration=' || version_num FROM agent_alembic_version;
"
```

当前代码和知识源对应的预期：

此处是全量重置并重新入库后的基线，完整规模为30订单、34任务、38步骤、24问题、23复核、
3返工、31交付。3条返工为V4预置数据；重置清除人工新增写入，再恢复预置返工，不能把全库返工为0作为成功条件。
仅应用V4增量迁移时，原人工记录会保留，复核和返工总数可高于该基线。

```text
task_version=0
reviews=23
reworks=3
idempotency_records=0
java_operation_logs=0
agent_runs=0
approvals=0
knowledge_documents=16
knowledge_chunks=80
agent_migration=0014_review_source_run
```

能力接口还必须返回知识索引`READY`且`ready=true`。上述知识数量只对应当前语料，修改知识源后应按当时入库摘要核对。

最后重新加载浏览器页面，选择ORDER-003，核对：

| 字段 | 初始值 |
| --- | --- |
| TASK-003 | COMPLETED，版本0 |
| ISSUE-001 | COORDINATE_SYSTEM，OPEN |
| REVIEW-003 | PENDING，暂无新增复核记录 |
| DELIVERY-003 | BLOCKED |
| 运行历史 | 空列表，首次发送后开始产生新Run |

不要使用重置前打开的草稿卡片、Session、Approval或历史结果继续确认。浏览器刷新会清空抽屉内存会话，页面重新从Java加载事实。

## 4. 下一轮演示

按[统一页面演示链路](AGENT_DEMO_FLOW.md#1-页面操作与实际效果)依次操作：

```text
诊断ORDER-003
→ 同一Session生成TASK-003复核草稿
→ 核对并确认复核（任务版本0→1）
→ 创建独立返工确认单
→ 核对并确认返工（任务版本1→2，返工PENDING）
→ 保存本轮新的Run/Step、操作结果和实际耗时
```

每次确认完成后先看成功或失败结果，不要用反复确认验证效果。成功创建返工不等于成果已修正、问题已关闭或允许交付；下一轮从版本0重演时再执行完整重置。

重置保证业务初始条件可重复，不保证真实模型每次输出、Token或耗时完全相同。首次失败要保留Run ID与Trace，不把第二次成功当作第一次错误已经修复；诊断以MAX_ITERATIONS成功结束时也必须如实保留原因。

## 5. 独立验证重置能力

```sh
make test-demo-reset
```

该命令在脚本内部创建独立项目、随机端口和临时数据卷，不重置当前演示项目。它先恢复固定数据，通过临时Java接口提交一次复核和返工，再次重置并比较两次快照，同时检查新增记录清除、Agent迁移和Web/Agent/Java健康入口。测试关闭模型配置及Embedding密钥，不进行真实模型调用或重新生成向量；最后清理临时项目和数据卷。

通过输出应包含`demo reset verification passed`和两次一致的`snapshot`。`knowledge_chunks=0`是该隔离测试的预期，完整演示环境仍需按第2节执行真实入库并检查READY。

## 6. 常见中断与恢复

| 现象 | 处理 |
| --- | --- |
| Docker凭据助手找不到 | 按第2节补当前终端PATH后重试失败的构建步骤 |
| Agent表不存在 | 执行`make knowledge-ingest`，它会先应用Agent迁移；不手动创建表 |
| 知识NOT_INDEXED或文档/Chunk为0 | 核查Embedding本地配置后完成真实入库，再检查READY |
| 重置后页面还显示版本2或旧草稿 | 重新加载页面，重新选择订单并核对Java快照；不继续操作旧确认单 |
| 端口冲突 | 保持现有本地端口配置；DBeaver不要误连本机5432的另一个PostgreSQL |
| 模型或检索报错 | 保存新Run ID、Trace和失败Step，按错误定位，不用再次删除卷掩盖问题 |

本文件只规定重置与恢复步骤，不自动执行当前项目的破坏性操作。现有统计和页面展示问题继续按[当前状态](STATUS.md)跟踪。
