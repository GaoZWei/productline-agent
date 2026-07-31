SHELL := /bin/sh
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help config validate test smoke test-business-domain test-business-data test-java-contract dev dev-business dev-agent dev-web down logs ps reset-demo

help: ## 显示可用命令
	@awk 'BEGIN {FS = ":.*## "; printf "用法: make <target>\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

config: ## 展开并校验 Docker Compose 配置
	$(COMPOSE) config

validate: ## 检查 M0.1 必需目录、文件与 Compose 配置
	./scripts/check-foundation.sh
	$(COMPOSE) config --quiet

test: validate smoke test-business-domain test-business-data test-java-contract ## 运行当前阶段全部自动检查

smoke: ## 验证 Java、Python 和 Web 健康检查
	./scripts/smoke-services.sh

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
