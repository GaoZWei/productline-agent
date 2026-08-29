# 遥感数据产线 Agent

面向遥感数据生产订单、生产任务、质检、复核和交付环节的智能协同 Agent。项目第一阶段以 `ORDER-003` 未交付诊断为黄金链路，按“业务接口 → Tool → 确定性 Workflow → 动态 Agent”的顺序迭代。

当前进度为 **M7 可观测性里程碑进行中，M7.1 Run完整字段已完成**：Java业务事实经七个只读Tool进入固定LangGraph诊断链，Python输出
可追溯根因、字段证据和建议；Web订单页已经接入严格PageContext。诊断现在可以复用持久化Session继承
当前订单或任务，并继续通过Java事实重校验。内部路由器已具备六类意图、上下文Prompt注入、严格结构化
解析、一次Schema重试、`UNKNOWN`回退、来源化实体合并，以及固定置信度、缺参/冲突澄清和补参恢复；
60条固定样本、可注入评测执行器、指标、混淆矩阵和脱敏失败样本已经建立。首批14份有效演示规范和2份
历史失效版本已登记为严格元数据契约；Agent数据库已经具备知识文档、分块、pgvector和全文检索字段。
统一Loader现在可安全读取Markdown/纯文本、按标题和长度确定性分块、生成稳定ID并拦截重复正文；OpenAI兼容
Provider可按批生成固定1536维向量、有限重试瞬时错误，并将Chunk与索引版本写入pgvector。当前支持中文双字
预处理和GIN关键词排名，也支持同索引身份下的HNSW余弦检索、TopK和相似度阈值。两条检索路径在排名前
共享产品、卫星、文档类型、规范版本、当前生效时间和权限过滤；两路候选现在通过RRF融合、Chunk去重和
同章节相邻片段合并形成稳定混合TopK；可注入Reranker现在会严格校验候选分数、按相关性稳定重排、拦截
低相关片段，并在超时时显式回退原RRF顺序。检索结果现已保留规范名称、版本、章节、全部Chunk身份和原文，
Web具备可展开引用卡片；内部`SpecificationSkill`可从`SPEC_QA`决策执行固定RAG图，在无结果、重排超时或
生成引用异常时返回安全回答。50条RAG问题已标注预期文档和章节，统一评测器可比较纯向量、关键词、混合、
混合加重排策略的Hit@5、MRR和无关片段占比，并输出不含问题正文的失败样本。动态Agent已具备结构化动作选择、
确定性执行限制和多订单固定路径；Approval链已实现草稿、用户修改、确认前Java事实重校验、单次安全写回和可查询
操作日志，并由十场景安全矩阵及真实跨服务E2E验收。Run现在还会冻结页面上下文与组件版本，保存可选Router结果、
Token与Tool调用统计、总耗时和终止原因。具体模型供应商、统一路由HTTP、页面Approval生产接线、操作日志页面、
完整Step类型、SSE和运行历史页面仍未实现。

## 环境要求

- Docker Engine 或 Docker Desktop（支持 `docker compose`）
- GNU Make
- Java 21、Maven 3.9（运行 Java 领域测试）
- uv（自动安装和管理项目要求的 Python 3.12）
- Node.js 22（运行前端本地测试和构建）

## 快速开始

```bash
cp .env.example .env
make config
make dev
```

复制 `.env.example` 后只需修改 `.env` 即可切换端口、数据库和模型配置，不需要修改源码。`.env` 已被 Git 忽略，不应提交真实密钥。

服务默认地址：

| 服务 | 地址 | 健康检查 |
| --- | --- | --- |
| Web 控制台 | <http://localhost:5173> | <http://localhost:5173/health> |
| Python Agent | <http://localhost:8000> | <http://localhost:8000/health> |
| Java 业务服务 | <http://localhost:8080> | <http://localhost:8080/health> |
| PostgreSQL | `localhost:5432` | `pg_isready` |

停止服务：

```bash
make down
```

## 常用命令

```bash
make help             # 查看全部命令
make config           # 展开并校验 Docker Compose 配置
make dev              # 构建并启动全部服务
make dev-business     # 只启动 Java 服务及其依赖
make dev-agent        # 只启动 Python 服务及其依赖
make dev-web          # 只启动 Web 服务及其依赖
make test             # 运行基础检查、服务冒烟和 Java 领域集成测试
make test-agent-foundation # 验证 M1.1 Python 工程基础
make test-agent-client # 验证 M1.2 Java HTTP Client
make test-agent-errors # 验证 M1.3 标准错误模型
make test-agent-tool-protocol # 验证 M1.4 Tool 基础协议
make test-tools        # 验证 M1.4～M1.8 Tool 协议、调用策略和开发调试 API
make test-agent-persistence # 在隔离 PostgreSQL 上验证 M2.1～M2.5 运行记录持久化
make test-run-lifecycle # 单独验证 M2.2 Run 生命周期与并发状态流转
make test-step-lifecycle # 单独验证 M2.3 Step 记录、摘要和耗时
make test-workflow-schemas # 单独验证 M2.4 Workflow 状态与诊断 Schema
make test-workflow-nodes # 单独验证 M2.5 固定节点、状态合并和失败中断
make test-diagnosis-rules # 单独验证 M2.6 阻塞阶段规则、信息完整性和优先级
make test-page-context # 验证 M3.1 页面上下文与事实重校验
make test-session-context # 验证 M3.2 会话过期、清除和继承
make test-intent-routing # 验证 M3.3 意图契约、Skill映射和UNKNOWN门禁
make test-router-prompt # 验证 M3.4 Prompt、结构化解析、一次重试和UNKNOWN回退
make test-knowledge-docs # 验证 M4.1 规范目录、元数据和版本关系
make test-knowledge-models # 验证 M4.2 知识Schema、数据库模型和迁移
make test-knowledge-loading # 验证 M4.3 文档加载、分块和重复检测
make test-knowledge-embedding # 验证 M4.4 Embedding生成、重试和pgvector重新索引
make test-knowledge-keyword # 验证 M4.5 中文关键词预处理、GIN检索和分数
make test-knowledge-vector # 验证 M4.6 Query Embedding、余弦检索、TopK和阈值
make test-knowledge-filters # 验证 M4.7 元数据、有效期、权限和误召回门禁
make test-knowledge-hybrid # 验证 M4.8 RRF融合、去重、相邻片段和混合TopK
make test-knowledge-rerank # 验证 M4.9 模型重排、超时降级和低相关片段拦截
make test-knowledge-citations # 验证 M4.10 引用结构、引用原文和前端卡片
make test-specification-qa # 验证 M4.11 规范问答Workflow、路由Skill和安全回答
make eval-rag          # 验证 M4.12 固定RAG评测集、四策略和失败样本
make quality          # 运行 Ruff 和 mypy 严格检查
make agent-migrate    # 执行 Agent 自有数据库迁移
make test-business-domain # 单独运行 Java 领域模型测试
make test-business-data   # 单独验证固定数据和业务状态组合
make test-java-contract   # 单独验证 8 个 Java 只读查询接口
make reset-demo       # 删除本地数据卷并重建 PostgreSQL、Java 和固定数据
make logs             # 跟踪服务日志
make ps               # 查看服务状态
```

`make reset-demo` 会删除本项目 Docker Compose 管理的本地数据库卷，仅用于重置演示数据；成功后输出订单数和确定性数据快照。固定 ID、状态与后续 Tool 对接注意事项见 [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md)，查询路径和响应结构见 [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)。

## 项目结构

```text
.
├── agent-service/       # FastAPI Agent 服务、Agent 自有持久化和后续 Tool/Workflow
├── business-service/    # Spring Boot 业务服务与领域模型
├── web-console/         # Vue 前端目标目录（当前为静态启动骨架）
├── knowledge-base/      # 固定演示规范、检索元数据和历史失效版本
├── doc/                 # 原始需求、细化计划与开发记录
├── docs/                # 路线图和当前状态
├── scripts/             # 根级验证脚本
├── docker-compose.yml
└── Makefile
```

## 开发约束

开始开发前阅读根目录 `AGENTS.md`。每次开发必须：

1. 只完成当前里程碑内的一个可测试任务；
2. 保证固定数据和 `ORDER-003` 黄金链路稳定；
3. 运行任务对应测试，并在 `docs/STATUS.md` 记录当前测试摘要、阻塞和下一任务；
4. 首次开发阶段时，在 `doc/detailed-plan.md` 对应二级标题下补充 `### 解决的问题`；
5. 实际功能开发按“核心解决的问题、实现的核心代码、实现的核心功能”三栏更新 `doc/record.md`；
6. 评估本次开发的 Agent 面试价值，只有有价值时才按“解决的问题/对项目的价值、与 Agent 开发的关系、可能的面试问题”三栏更新 `doc/needCare.md`。
