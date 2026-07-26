#!/bin/sh
set -eu

required_directories="
agent-service
business-service
web-console
docs
"

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
business-service/src/Main.java
web-console/Dockerfile
web-console/server.mjs
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

for variable in \
    POSTGRES_DB \
    POSTGRES_USER \
    POSTGRES_PASSWORD \
    BUSINESS_SERVICE_PORT \
    AGENT_SERVICE_PORT \
    WEB_CONSOLE_PORT \
    MODEL_PROVIDER \
    MODEL_API_KEY; do
    grep -q "^${variable}=" .env.example || {
        echo "missing environment example: $variable" >&2
        exit 1
    }
done

echo "M0.1 foundation checks passed"

