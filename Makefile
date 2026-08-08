SHELL := /bin/sh
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help config validate test smoke test-agent-foundation test-agent-client test-agent-errors test-agent-tool-protocol test-tools quality agent-migrate test-business-domain test-business-data test-java-contract test-java-write test-java-errors test-java-faults test-web build-web dev dev-business dev-agent dev-web down logs ps reset-demo

help: ## 显示可用命令
	@awk 'BEGIN {FS = ":.*## "; printf "用法: make <target>\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

config: ## 展开并校验 Docker Compose 配置
	$(COMPOSE) config

validate: ## 检查 M0.1 必需目录、文件与 Compose 配置
	./scripts/check-foundation.sh
	$(COMPOSE) config --quiet

test: validate smoke test-agent-foundation test-agent-client test-agent-errors test-tools test-business-domain test-business-data test-java-contract test-java-write test-java-errors test-java-faults test-web ## 运行当前阶段全部自动检查

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

test-tools: test-agent-tool-protocol ## 验证 M1.4 基础协议和 M1.5 七个只读 Tool
	cd agent-service && uv run --frozen pytest -q tests/integration/tools

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

test-web: ## 验证 M0.8 API 契约、状态切换、页面组件和生产服务
	npm --prefix web-console test
	npm --prefix web-console run build

build-web: ## 构建 M0.8 前端生产资源
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
