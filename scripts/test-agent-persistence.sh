#!/usr/bin/env sh
set -eu

test_container="productline-agent-m21-test-$$"
test_database="remote_sensing_agent"
test_user="agent"
test_password="agent-test-only"

cleanup() {
  docker rm --force "${test_container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run --detach --rm \
  --name "${test_container}" \
  --env POSTGRES_DB="${test_database}" \
  --env POSTGRES_USER="${test_user}" \
  --env POSTGRES_PASSWORD="${test_password}" \
  --publish 127.0.0.1::5432 \
  --tmpfs /var/lib/postgresql/data \
  pgvector/pgvector:pg16 >/dev/null

attempt=0
until docker exec "${test_container}" pg_isready \
  --username "${test_user}" --dbname "${test_database}" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge 30 ]; then
    echo "M2.1 测试 PostgreSQL 未在预期时间内就绪" >&2
    exit 1
  fi
  sleep 1
done

test_port=$(docker port "${test_container}" 5432/tcp | sed -n 's/.*://p' | head -n 1)
if [ -z "${test_port}" ]; then
  echo "无法解析 M2.1 测试 PostgreSQL 端口" >&2
  exit 1
fi

cd "$(dirname "$0")/../agent-service"
AGENT_PERSISTENCE_TEST_DATABASE_URL="postgresql://${test_user}:${test_password}@localhost:${test_port}/${test_database}" \
  uv run --frozen pytest -q tests/test_agent_persistence.py tests/test_alembic.py "$@"
