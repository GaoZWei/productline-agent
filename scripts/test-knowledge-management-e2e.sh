#!/usr/bin/env sh
set -eu

kb02_project="productline-agent-kb02-test-$$"
kb02_temp="$(mktemp -d)"
kb02_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"

# 测试只使用这里的固定演示配置，不读取本机.env或继承模型凭据。
export MODEL_NAME= MODEL_BASE_URL= MODEL_API_KEY= EMBEDDING_API_KEY=
export POSTGRES_DB=knowledge_management_test POSTGRES_USER=agent POSTGRES_PASSWORD=kb02-e2e-only
export POSTGRES_PORT=127.0.0.1:0 BUSINESS_SERVICE_PORT=127.0.0.1:0 AGENT_SERVICE_PORT=127.0.0.1:0

cat >"${kb02_temp}/compose.env" <<'ENV'
MODEL_NAME=
MODEL_BASE_URL=
MODEL_API_KEY=
EMBEDDING_API_KEY=
ENV

kb02_compose() {
  docker compose --file "${kb02_root}/docker-compose.yml" --project-name "${kb02_project}" \
    --env-file "${kb02_temp}/compose.env" "$@"
}

cleanup() {
  kb02_compose down --volumes --remove-orphans --rmi local >"${kb02_temp}/cleanup.log" 2>&1 || true
  rm -rf "${kb02_temp}"
}
trap cleanup EXIT INT TERM

echo "KB-02: 构建并启动隔离Java/PostgreSQL"
if ! kb02_compose up --build --detach business-service >"${kb02_temp}/java.log" 2>&1; then
  tail -n 60 "${kb02_temp}/java.log" >&2
  exit 1
fi
echo "KB-02: 构建Agent并迁移隔离知识库"
if ! kb02_compose build agent-service >"${kb02_temp}/agent-build.log" 2>&1; then
  tail -n 60 "${kb02_temp}/agent-build.log" >&2
  exit 1
fi
if ! kb02_compose run --rm --no-deps agent-service /service/.venv/bin/alembic upgrade head \
  >"${kb02_temp}/migration.log" 2>&1; then
  tail -n 60 "${kb02_temp}/migration.log" >&2
  exit 1
fi
kb02_compose up --detach agent-service >"${kb02_temp}/agent-up.log" 2>&1

kb02_postgres_port="$(kb02_compose port postgres 5432 | sed -n 's/.*://p' | head -n 1)"
kb02_business_port="$(kb02_compose port business-service 8080 | sed -n 's/.*://p' | head -n 1)"
kb02_agent_port="$(kb02_compose port agent-service 8000 | sed -n 's/.*://p' | head -n 1)"
if [ -z "${kb02_postgres_port}" ] || [ -z "${kb02_business_port}" ] || [ -z "${kb02_agent_port}" ]; then
  echo "无法解析KB-02隔离服务端口" >&2
  exit 1
fi

echo "KB-02: 真实HTTP授权、资料管理及Agent进程重启验收"
cd "$(dirname "$0")/../agent-service"
KB02_E2E_PROJECT="${kb02_project}" \
KB02_E2E_ENV_FILE="${kb02_temp}/compose.env" \
KB02_E2E_AGENT_URL="http://127.0.0.1:${kb02_agent_port}" \
KB02_E2E_BUSINESS_URL="http://127.0.0.1:${kb02_business_port}" \
KB02_E2E_DATABASE_URL="postgresql://agent:kb02-e2e-only@127.0.0.1:${kb02_postgres_port}/knowledge_management_test" \
  uv run --frozen pytest -q --tb=short tests/e2e/test_knowledge_management.py "$@"
