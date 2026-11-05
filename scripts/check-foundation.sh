#!/bin/sh
set -eu
# Monorepo 必需目录
required_directories="
agent-service
business-service
agent-frontend
docs
"
# Monorepo 必需配置和启动文件
required_files="
.editorconfig
.env.example
.gitignore
README.md
Makefile
docker-compose.yml
agent-service/Dockerfile
agent-service/app/main.py
business-service/Dockerfile
business-service/pom.xml
business-service/src/main/java/com/productline/business/BusinessServiceApplication.java
business-service/src/main/resources/db/migration/V1__create_business_domain.sql
docs/README.md
docs/api/API_CONTRACT.md
docs/architecture/DOMAIN_MODEL.md
agent-frontend/Dockerfile
agent-frontend/server.mjs
"

for directory in $required_directories; do
    test -d "$directory" || {
        echo "missing required directory: $directory" >&2
        exit 1
    }
done

for file in $required_files; do
    test -s "$file" || {
        echo "missing or empty required file: $file" >&2
        exit 1
    }
done
# .env.example 必须包含的环境变量
for variable in \
    POSTGRES_DB \
    POSTGRES_USER \
    POSTGRES_PASSWORD \
    BUSINESS_SERVICE_PORT \
    SPRING_DATASOURCE_URL \
    SPRING_DATASOURCE_USERNAME \
    SPRING_DATASOURCE_PASSWORD \
    AGENT_SERVICE_PORT \
    AGENT_FRONTEND_PORT \
    MODEL_PROVIDER \
    MODEL_API_KEY; do
    grep -q "^${variable}=" .env.example || {
        echo "missing environment example: $variable" >&2
        exit 1
    }
done

echo "M0.1 foundation checks passed"
