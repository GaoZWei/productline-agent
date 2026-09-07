#!/usr/bin/env sh
set -eu

e2e_project="productline-agent-m76g-test-$$"
e2e_database="remote_sensing_agent"
e2e_user="agent"
e2e_password="agent-page-e2e-only"
e2e_temp="$(mktemp -d)"

export COMPOSE_PROJECT_NAME="${e2e_project}"
export POSTGRES_DB="${e2e_database}"
export POSTGRES_USER="${e2e_user}"
export POSTGRES_PASSWORD="${e2e_password}"
export POSTGRES_PORT=0
export BUSINESS_SERVICE_PORT=0
export AGENT_SERVICE_PORT=0
export WEB_CONSOLE_PORT=0
export MODEL_NAME=
export MODEL_BASE_URL=
export MODEL_API_KEY=
export EMBEDDING_API_KEY=

cleanup() {
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${e2e_temp}"
}
trap cleanup EXIT INT TERM

docker compose up --build --detach business-service
docker compose build agent-service web-console
docker compose run --rm --no-deps agent-service \
  /service/.venv/bin/alembic upgrade head
docker compose up --detach agent-service web-console

web_port="$(docker compose port web-console 5173 | sed -n 's/.*://p' | head -n 1)"
if [ -z "${web_port}" ]; then
  echo "无法解析 M7.6-G Web 服务端口" >&2
  exit 1
fi
web_url="http://127.0.0.1:${web_port}"

attempt=0
until curl --fail --silent "${web_url}/health" >"${e2e_temp}/web-health.json"; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge 90 ]; then
    echo "M7.6-G web-console 未在预期时间内就绪" >&2
    docker compose logs web-console agent-service business-service >&2
    exit 1
  fi
  sleep 1
done

attempt=0
until curl --fail --silent "${web_url}/agent-api/health" \
  >"${e2e_temp}/agent-health.json"; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge 60 ]; then
    echo "M7.6-G agent-service 代理链路未在预期时间内就绪" >&2
    docker compose logs agent-service >&2
    exit 1
  fi
  sleep 1
done

attempt=0
until curl --fail --silent "${web_url}/business-api/health" \
  >"${e2e_temp}/business-health.json"; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge 60 ]; then
    echo "M7.6-G business-service 代理链路未在预期时间内就绪" >&2
    docker compose logs business-service >&2
    exit 1
  fi
  sleep 1
done

curl --fail-with-body --silent --show-error "${web_url}/" >"${e2e_temp}/index.html"
curl --fail-with-body --silent --show-error "${web_url}/business-api/api/orders/ORDER-003" \
  >"${e2e_temp}/order.json"
curl --fail-with-body --silent --show-error "${web_url}/agent-api/api/agent/capabilities" \
  >"${e2e_temp}/capabilities.json"

curl --fail-with-body --silent --show-error \
  --request POST \
  --header "Content-Type: application/json" \
  --header "X-User-Id: reviewer-001" \
  --header "X-User-Role: REVIEWER" \
  --data '{"order_id":"ORDER-003","user_message":"这个订单为什么还没有交付？","page_context":{"current_system":"production-system","current_page":"order-detail","order_id":"ORDER-003","task_id":null,"issue_id":null,"batch_id":null,"product_type":"DOM","satellite_type":null,"user_role":"REVIEWER"}}' \
  "${web_url}/agent-api/api/agent/order-diagnosis" \
  >"${e2e_temp}/fixed-diagnosis.json"

unified_status="$(curl --silent \
  --output "${e2e_temp}/unified-error.json" \
  --write-out '%{http_code}' \
  --request POST \
  --header "Content-Type: application/json" \
  --header "X-User-Id: reviewer-001" \
  --header "X-User-Role: REVIEWER" \
  --data '{"message":"查询 ORDER-003 当前状态"}' \
  "${web_url}/agent-api/api/agent/messages")"

rg --quiet '遥感数据产线' "${e2e_temp}/index.html"
rg --quiet '"orderId":"ORDER-003"' "${e2e_temp}/order.json"
rg --quiet '"message_api_enabled":true' "${e2e_temp}/capabilities.json"
rg --quiet '"configured":false' "${e2e_temp}/capabilities.json"
rg --quiet '"blocking_stage":"QUALITY_REVIEW"' "${e2e_temp}/fixed-diagnosis.json"
test "${unified_status}" = "503"
rg --quiet '"code":"MODEL_NOT_CONFIGURED"' "${e2e_temp}/unified-error.json"

echo "M7.6-G Docker页面烟测通过：静态页、Java代理、Agent能力、固定诊断及模型失败语义均符合预期"
