#!/usr/bin/env sh
set -eu

e2e_project="productline-agent-m210-test-$$"
e2e_database="remote_sensing_agent"
e2e_user="agent"
e2e_password="agent-e2e-only"

export COMPOSE_PROJECT_NAME="${e2e_project}"
export POSTGRES_DB="${e2e_database}"
export POSTGRES_USER="${e2e_user}"
export POSTGRES_PASSWORD="${e2e_password}"
export POSTGRES_PORT=0
export BUSINESS_SERVICE_PORT=0
export DEMO_FAULTS_ENABLED=true
export DEMO_FAULT_TIMEOUT_DELAY_MS=500

cleanup() {
  docker compose down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker compose up --build --detach business-service

postgres_port="$(docker compose port postgres 5432 | sed -n 's/.*://p' | head -n 1)"
business_port="$(docker compose port business-service 8080 | sed -n 's/.*://p' | head -n 1)"
if [ -z "${postgres_port}" ] || [ -z "${business_port}" ]; then
  echo "无法解析 M2.10 E2E 服务端口" >&2
  exit 1
fi

attempt=0
until curl --fail --silent "http://127.0.0.1:${business_port}/health" >/dev/null; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge 60 ]; then
    echo "M2.10 business-service 未在预期时间内就绪" >&2
    docker compose logs business-service >&2
    exit 1
  fi
  sleep 1
done

cd "$(dirname "$0")/../agent-service"
AGENT_E2E_DATABASE_URL="postgresql://${e2e_user}:${e2e_password}@127.0.0.1:${postgres_port}/${e2e_database}" \
AGENT_E2E_BUSINESS_URL="http://127.0.0.1:${business_port}" \
  uv run --frozen pytest \
    tests/e2e/test_order_diagnosis.py \
    tests/e2e/test_write_tools.py \
    tests/e2e/test_approval_confirmation.py \
    -q "$@"
