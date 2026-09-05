SHELL := /bin/sh
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help config validate test smoke test-agent-foundation test-agent-client test-agent-errors test-agent-tool-protocol test-tools test-agent-persistence test-run-lifecycle test-step-lifecycle test-sse-events test-run-timeline test-run-history test-model-runtime test-model-adapters knowledge-ingest test-knowledge-ingestion test-agent-messages test-agent-read-skills test-workflow-schemas test-workflow-nodes test-diagnosis-rules test-diagnosis-generation test-diagnosis-api test-page-context test-session-context test-intent-routing test-router-prompt eval-router test-knowledge-docs test-knowledge-models test-knowledge-loading test-knowledge-embedding test-knowledge-keyword test-knowledge-vector test-knowledge-filters test-knowledge-hybrid test-knowledge-rerank test-knowledge-citations test-specification-qa eval-rag test-approval test-agent-e2e quality agent-migrate test-business-domain test-business-data test-java-contract test-java-write test-java-errors test-java-faults test-web build-web dev dev-business dev-agent dev-web down logs ps reset-demo

help: ## 显示可用命令
	@awk 'BEGIN {FS = ":.*## "; printf "用法: make <target>\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

config: ## 展开并校验 Docker Compose 配置
	$(COMPOSE) config

validate: ## 检查 M0.1 必需目录、文件与 Compose 配置
	./scripts/check-foundation.sh
	$(COMPOSE) config --quiet

test: validate smoke test-agent-foundation test-agent-client test-agent-errors test-tools test-agent-persistence test-workflow-schemas test-workflow-nodes test-diagnosis-rules test-diagnosis-generation test-business-domain test-business-data test-java-contract test-java-write test-java-errors test-java-faults test-web ## 运行当前阶段全部自动检查

smoke: ## 验证 Java、Python 和 Web 健康检查
	./scripts/smoke-services.sh

test-agent-foundation: ## 验证 M1.1 FastAPI、数据库、Alembic 和结构化日志基础
	cd agent-service && uv run --frozen pytest -q tests/test_health.py tests/test_database.py tests/test_observability.py tests/test_alembic.py

test-agent-client: ## 验证 M1.2 Java HTTP Client 配置、生命周期和响应契约
	cd agent-service && uv run --frozen pytest -q tests/test_business_client.py

test-agent-errors: ## 验证 M1.3 标准 Tool 错误模型和跨服务错误映射
	cd agent-service && uv run --frozen pytest -q tests/test_tool_errors.py

test-agent-tool-protocol: ## 验证 M1.4 Tool 基础协议、执行门禁和注册表
	cd agent-service && uv run --frozen pytest -q tests/test_tool_protocol.py

test-tools: test-agent-tool-protocol ## 验证 M1.4-M1.8 Tool 协议、调用策略和开发调试 API
	cd agent-service && uv run --frozen pytest -q tests/test_retry_policy.py tests/test_tool_call_deduplication.py tests/integration/tools tests/integration/test_tool_debug_api.py

test-agent-persistence: ## 在隔离 PostgreSQL 上验证 M2.1-M2.5 运行记录持久化
	./scripts/test-agent-persistence.sh

test-run-lifecycle: ## 验证Run生命周期、完整字段和隔离PostgreSQL持久化
	cd agent-service && uv run --frozen pytest -q tests/test_run_observability.py
	./scripts/test-agent-persistence.sh -k "run_lifecycle or run_observability"

test-step-lifecycle: ## 在隔离 PostgreSQL 上验证 M2.3/M7.2 Step 记录、完整类型和安全摘要
	./scripts/test-agent-persistence.sh -k "step_lifecycle or step_type_migration"

test-sse-events: ## 验证 M7.3 SSE事件、回放、心跳及诊断/RAG/Approval发布
	cd agent-service && uv run --frozen pytest -q tests/test_run_events.py tests/test_intent_router_prompt.py tests/test_dynamic_diagnosis_workflow.py tests/knowledge/test_specification_qa_workflow.py tests/test_review_draft_generation.py tests/test_approval_confirmation.py
	./scripts/test-agent-persistence.sh -k "publishes_ordered_sse_progress"

test-run-timeline: ## 验证 M7.4 SSE客户端、重连、时间线和诊断抽屉联动
	npm --prefix web-console test -- --run src/api/runEventClient.spec.ts src/observability/runEventTimeline.spec.ts src/components/AgentRunTimeline.spec.ts src/components/AgentDiagnosisDrawer.spec.ts src/api/agentClient.spec.ts src/server.spec.mjs
	npm --prefix web-console run build

test-run-history: ## 验证 M7.5 Run列表/详情/Step API、历史页面和用户隔离
	cd agent-service && uv run --frozen pytest -q tests/test_run_history.py tests/test_run_history_api.py
	./scripts/test-agent-persistence.sh -k run_history
	npm --prefix web-console test -- --run src/api/runHistoryClient.spec.ts src/components/RunHistoryPage.spec.ts src/App.spec.ts
	npm --prefix web-console run build

test-model-runtime: ## 验证 M7.6-A模型配置、结构化调用、稳定错误、重试和LLM Step观测
	cd agent-service && uv run --frozen pytest -q tests/test_model_settings.py tests/test_model_capabilities.py tests/test_model_client.py tests/test_model_invocation.py tests/test_llm_step_observability.py tests/test_observability.py tests/test_run_history.py tests/test_run_history_api.py tests/test_alembic.py
	./scripts/test-agent-persistence.sh -k "llm_step_observability or step_type_migration"
	npm --prefix web-console test -- --run src/api/runHistoryClient.spec.ts src/components/RunHistoryPage.spec.ts
	npm --prefix web-console run build

test-model-adapters: ## 验证 M7.6-B五个模型Protocol适配器和既有确定性门禁
	cd agent-service && uv run --frozen pytest -q tests/test_model_adapters.py tests/test_run_versioning.py tests/test_intent_router_prompt.py tests/test_action_decision.py tests/knowledge/test_reranking.py tests/knowledge/test_specification_qa_workflow.py tests/test_review_draft_generation.py

knowledge-ingest: ## 显式全量重建16份演示规范的Embedding索引
	$(COMPOSE) up -d postgres
	$(COMPOSE) build agent-service
	$(COMPOSE) run --rm --no-deps agent-service /service/.venv/bin/alembic upgrade head
	$(COMPOSE) run --rm --no-deps agent-service /service/.venv/bin/python -m app.cli.knowledge_ingest --knowledge-root /knowledge-base

test-knowledge-ingestion: ## 验证 M7.6-C全量入库、幂等重建、CLI退出码和索引就绪能力
	cd agent-service && uv run --frozen pytest -q tests/test_knowledge_ingestion.py tests/test_knowledge_index_capabilities.py
	./scripts/test-agent-persistence.sh -k "knowledge_ingestion or knowledge_index_capabilities"

test-agent-messages: ## 验证 M7.6-D统一消息、路由澄清、Run/Step/SSE和模型错误
	cd agent-service && uv run --frozen pytest -q tests/test_agent_messages.py tests/test_intent_router_prompt.py tests/test_run_history.py tests/test_run_history_api.py
	./scripts/test-agent-persistence.sh -k agent_messages

test-agent-read-skills: ## 验证 M7.6-E三个只读Skill生产分发、观测和统一HTTP闭环
	cd agent-service && uv run --frozen pytest -q tests/test_production_agent_skills.py tests/test_dynamic_diagnosis_workflow.py tests/knowledge/test_specification_qa_workflow.py
	./scripts/test-agent-persistence.sh -k agent_read_skills

test-workflow-schemas: ## 单独验证 M2.4 Workflow 状态与诊断 Schema
	cd agent-service && uv run --frozen pytest -q tests/test_workflow_schemas.py

test-workflow-nodes: ## 单独验证 M2.5 固定 Workflow 节点、合并与失败中断
	cd agent-service && uv run --frozen pytest -q tests/test_order_diagnosis_workflow.py

test-diagnosis-rules: ## 单独验证 M2.6 确定性诊断规则、信息完整性和优先级
	cd agent-service && uv run --frozen pytest -q tests/test_diagnosis_rules.py

test-diagnosis-generation: ## 单独验证 M2.7 规则文案、模型校验和失败回退
	cd agent-service && uv run --frozen pytest -q tests/test_diagnosis_generation.py tests/test_order_diagnosis_workflow.py

test-diagnosis-api: ## 在隔离 PostgreSQL 上验证 M2.8 诊断 API、Run终态和失败映射
	./scripts/test-agent-persistence.sh -k order_diagnosis_api

test-page-context: ## 验证 M3.1 页面上下文Schema、事实重校验和伪造拦截
	cd agent-service && uv run --frozen pytest -q tests/test_page_context.py tests/test_order_diagnosis_workflow.py
	./scripts/test-agent-persistence.sh -k order_diagnosis_api

test-session-context: ## 验证 M3.2 会话Schema、过期、清除和上下文继承
	cd agent-service && uv run --frozen pytest -q tests/test_session_context.py
	./scripts/test-agent-persistence.sh -k session

test-intent-routing: ## 验证 M3.3 意图、必填参数、Skill映射和UNKNOWN门禁
	cd agent-service && uv run --frozen pytest -q tests/test_intent_routing.py

test-router-prompt: ## 验证 M3.4 Prompt、上下文注入、Schema重试和UNKNOWN回退
	cd agent-service && uv run --frozen pytest -q tests/test_intent_router_prompt.py

eval-router: ## 验证 M3.7 固定路由数据集、评测指标、混淆矩阵和失败样本
	cd agent-service && uv run --frozen pytest -q tests/evaluation/test_router_eval.py

test-knowledge-docs: ## 验证 M4.1 规范目录、元数据、版本关系和演示文档
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_knowledge_documents.py

test-knowledge-models: ## 验证 M4.2 知识Schema、ORM模型和PostgreSQL迁移
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_knowledge_models.py tests/knowledge/test_knowledge_documents.py tests/test_alembic.py
	./scripts/test-agent-persistence.sh -k knowledge

test-knowledge-loading: ## 验证 M4.3 文档加载、分块、稳定ID和重复检测
	cd agent-service && uv run --frozen pytest -q tests/knowledge

test-knowledge-embedding: ## 验证 M4.4 Provider、批处理、重试、pgvector入库和重新索引
	cd agent-service && uv run --frozen pytest -q tests/knowledge
	./scripts/test-agent-persistence.sh -k knowledge

test-knowledge-keyword: ## 验证 M4.5 中文预处理、GIN全文检索和关键词分数
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_knowledge_search.py tests/knowledge/test_knowledge_models.py tests/test_alembic.py
	./scripts/test-agent-persistence.sh -k keyword

test-knowledge-vector: ## 验证 M4.6 Query Embedding、HNSW余弦检索、TopK和阈值
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_knowledge_search.py tests/knowledge/test_embedding_batching.py tests/knowledge/test_knowledge_models.py tests/test_alembic.py
	./scripts/test-agent-persistence.sh -k vector

test-knowledge-filters: ## 验证 M4.7 检索元数据、有效期、权限和误召回门禁
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_knowledge_search.py tests/knowledge/test_knowledge_models.py
	./scripts/test-agent-persistence.sh -k search_filters

test-knowledge-hybrid: ## 验证 M4.8 RRF融合、去重、片段合并和混合TopK
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_hybrid_search.py tests/knowledge/test_knowledge_search.py
	./scripts/test-agent-persistence.sh -k hybrid_search

test-knowledge-rerank: ## 验证 M4.9 模型重排、超时降级和低相关片段拦截
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_reranking.py tests/knowledge/test_hybrid_search.py

test-knowledge-citations: ## 验证 M4.10 引用身份、版本、原文和前端卡片
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_citations.py tests/knowledge/test_hybrid_search.py
	cd web-console && npm test -- --run src/components/KnowledgeCitationCard.spec.ts

test-specification-qa: ## 验证 M4.11 规范问答固定Workflow、路由Skill和安全回答
	cd agent-service && uv run --frozen pytest -q tests/knowledge/test_specification_qa_workflow.py tests/knowledge/test_citations.py

eval-rag: ## 验证 M4.12 固定评测集、四策略、Hit@5、MRR和失败样本
	cd agent-service && uv run --frozen pytest -q tests/evaluation/test_rag_eval.py tests/integration/rag

test-approval: ## 验证 M6 Approval生命周期、确认执行、安全边界、操作日志和前端契约
	cd agent-service && uv run --frozen pytest -q tests/test_approval_lifecycle.py tests/test_approval_schemas.py tests/test_review_draft_generation.py tests/test_write_tools.py tests/test_approval_confirmation.py tests/test_approval_confirmation_api.py tests/test_approval_security.py tests/test_operation_log.py tests/test_operation_log_api.py
	./scripts/test-agent-persistence.sh -k "approval or review_draft_store or execution or confirmation or operation_log"
	cd web-console && npm test -- --run src/components/ReviewApprovalCard.spec.ts src/api/agentClient.spec.ts

test-agent-e2e: ## 使用隔离 PostgreSQL 和真实 Java 验证诊断、写Tool及M6.6确认执行
	./scripts/test-agent-e2e.sh

quality: ## 运行 Python Ruff 和 mypy 严格质量检查
	cd agent-service && uv run --frozen ruff check .
	cd agent-service && uv run --frozen mypy app tests

agent-migrate: ## 执行 Agent 自有 SQLAlchemy 元数据的 Alembic 迁移
	$(COMPOSE) run --rm agent-service /service/.venv/bin/alembic upgrade head

test-business-domain: ## 在 PostgreSQL Testcontainers 上验证领域模型
	mvn --file business-service/pom.xml \
		-Dtest=BusinessStatusEnumTest,DomainModelValidationTest,DomainRepositoryIntegrationTest \
		test

test-business-data: ## 验证 M0.3 固定数据映射和业务状态组合
	mvn --file business-service/pom.xml \
		-Dtest=DemoDataIntegrityIntegrationTest,BusinessStateConsistencyValidatorTest \
		test

test-java-contract: ## 验证 M0.4 Java 只读查询接口契约
	mvn --file business-service/pom.xml \
		-Dtest=BusinessQueryApiIntegrationTest \
		test

test-java-write: ## 验证 M0.5 Java 写接口、权限、幂等、并发与操作日志
	mvn --file business-service/pom.xml \
		-Dtest=BusinessWriteApiIntegrationTest \
		test

test-java-errors: ## 验证 M0.6 统一响应、错误映射和 Trace ID
	mvn --file business-service/pom.xml \
		-Dtest=ApiExceptionHandlingIntegrationTest \
		test

test-java-faults: ## 验证 M0.7 只读故障模拟和默认关闭保护
	mvn --file business-service/pom.xml \
		-Dtest=DemoFaultSimulationIntegrationTest,DemoFaultDisabledIntegrationTest \
		test

test-web: ## 验证业务页面、诊断侧边栏、实时步骤和生产代理
	npm --prefix web-console test
	npm --prefix web-console run build

build-web: ## 构建含诊断侧边栏和实时步骤的前端生产资源
	npm --prefix web-console run build

dev: ## 构建并启动 PostgreSQL、Java、Python 和 Web
	$(COMPOSE) up --build

dev-business: ## 只启动 Java 服务及其依赖
	$(COMPOSE) up --build business-service

dev-agent: ## 只启动 Python 服务及其依赖
	$(COMPOSE) up --build agent-service

dev-web: ## 只启动 Web 服务及其依赖
	$(COMPOSE) up --build web-console

down: ## 停止本项目服务（保留数据卷）
	$(COMPOSE) down --remove-orphans

logs: ## 跟踪全部服务日志
	$(COMPOSE) logs --follow

ps: ## 查看服务状态
	$(COMPOSE) ps

reset-demo: ## 删除本地演示数据卷并重建 M0.3 固定业务数据
	./scripts/reset-demo
