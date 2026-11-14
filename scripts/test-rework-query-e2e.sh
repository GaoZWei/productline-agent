#!/usr/bin/env sh
set -eu

rework_query_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
rework_query_temp="$(mktemp -d)"
rework_query_container="productline-rework-query-test-$$"
rework_query_java_pid=""

cleanup() {
  if [ -n "${rework_query_java_pid}" ]; then
    kill "${rework_query_java_pid}" >/dev/null 2>&1 || true
    wait "${rework_query_java_pid}" >/dev/null 2>&1 || true
  fi
  docker rm --force --volumes "${rework_query_container}" >/dev/null 2>&1 || true
  rm -rf "${rework_query_temp}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 只创建本次独占的环回测试库，不读取.env、不继承开发库地址、不启动模型。
docker run --detach --pull=never --name "${rework_query_container}" \
  --env POSTGRES_DB=business_service_test_rework_query --env POSTGRES_USER=test \
  --env POSTGRES_PASSWORD=rework-query-e2e-only --publish 127.0.0.1::5432 \
  --tmpfs /var/lib/postgresql/data:rw postgres:16-alpine >"${rework_query_temp}/container"
rework_query_port="$(docker port "${rework_query_container}" 5432/tcp | sed -n 's/.*://p' | head -n 1)"
if [ -z "${rework_query_port}" ]; then echo "无法解析隔离PostgreSQL端口" >&2; exit 1; fi
rework_query_attempt=0
until docker exec "${rework_query_container}" pg_isready -U test -d business_service_test_rework_query >/dev/null 2>&1; do
  rework_query_attempt=$((rework_query_attempt + 1))
  if [ "${rework_query_attempt}" -ge 60 ]; then echo "隔离PostgreSQL未就绪" >&2; exit 1; fi
  sleep 1
done

if ! mvn -o --file "${rework_query_root}/business-service/pom.xml" -DskipTests package >"${rework_query_temp}/package.log" 2>&1; then
  tail -60 "${rework_query_temp}/package.log" >&2
  exit 1
fi
SPRING_DATASOURCE_URL="jdbc:postgresql://127.0.0.1:${rework_query_port}/business_service_test_rework_query" \
SPRING_DATASOURCE_USERNAME=test SPRING_DATASOURCE_PASSWORD=rework-query-e2e-only \
DEMO_FAULTS_ENABLED=false \
  java -jar "${rework_query_root}/business-service/target/business-service-0.1.0-SNAPSHOT.jar" \
  --server.address=127.0.0.1 --server.port=0 >"${rework_query_temp}/java.log" 2>&1 &
rework_query_java_pid=$!
rework_query_attempt=0
rework_query_business_port=""
while :; do
  rework_query_business_port="$(sed -n 's/.*Tomcat started on port \([0-9][0-9]*\).*/\1/p' "${rework_query_temp}/java.log" | head -n 1)"
  if [ -n "${rework_query_business_port}" ] && curl --fail --silent "http://127.0.0.1:${rework_query_business_port}/health" >/dev/null; then break; fi
  rework_query_attempt=$((rework_query_attempt + 1))
  if ! kill -0 "${rework_query_java_pid}" 2>/dev/null || [ "${rework_query_attempt}" -ge 60 ]; then
    tail -60 "${rework_query_temp}/java.log" >&2
    exit 1
  fi
  sleep 1
done

cd "${rework_query_root}/agent-service"
case "${1:-}" in
  ""|-*) set -- tests/e2e/test_rework_operation_query.py "$@" ;;
esac
AGENT_REWORK_QUERY_TEST_DATABASE_URL="postgresql://test:rework-query-e2e-only@127.0.0.1:${rework_query_port}/business_service_test_rework_query" \
AGENT_REWORK_QUERY_TEST_BUSINESS_URL="http://127.0.0.1:${rework_query_business_port}" \
  uv run --frozen pytest -q "$@"
