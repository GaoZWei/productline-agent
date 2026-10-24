#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir/.."

# 使用独立项目、随机端口和专属数据卷，绝不重置正在演示的Compose项目。
export COMPOSE_PROJECT_NAME="productline-demo-reset-test-$$"
export POSTGRES_DB=remote_sensing_agent
export POSTGRES_USER=agent
export POSTGRES_PASSWORD=demo-reset-test-only
export POSTGRES_PORT=0
export BUSINESS_SERVICE_PORT=0
export AGENT_SERVICE_PORT=0
export WEB_CONSOLE_PORT=0
export MODEL_NAME=
export MODEL_API_KEY=
export EMBEDDING_API_KEY=
reset_temp=$(mktemp -d)
failure_log=""

cleanup() {
    reset_status=$?
    if [ "$reset_status" -ne 0 ]; then
        if [ -n "$failure_log" ] && [ -f "$failure_log" ]; then
            sed -n '1,35p' "$failure_log" >&2
        fi
        echo "demo reset verification failed; logs retained at $reset_temp" >&2
    fi
    docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    if [ "$reset_status" -eq 0 ]; then
        rm -rf "$reset_temp"
    fi
}
trap cleanup EXIT INT TERM

run_sql() {
    docker compose exec -T postgres sh -c \
        'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "$1"
}

reset_once() {
    failure_log="$reset_temp/$1.log"
    ./scripts/reset-demo >"$failure_log" 2>&1
}

wait_health() {
    attempt=0
    until curl --fail --silent "$1" >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 45 ]; then
            echo "demo reset verification failed: service health timeout" >&2
            return 1
        fi
        sleep 1
    done
}

reset_once first
first_snapshot=$(sed -n 's/^snapshot=//p' "$reset_temp/first.log")
test -n "$first_snapshot"
business_port=$(docker compose port business-service 8080 | sed -n 's/.*://p' | head -n 1)
business_url="http://127.0.0.1:$business_port"
wait_health "$business_url/health"

# 通过Java真实写入制造一次已演示状态，验证重置可清除新增复核、返工、幂等和审计。
curl --fail --silent --show-error \
    -H 'Content-Type: application/json' -H 'X-User-Id: reviewer-001' \
    -H 'X-User-Role: REVIEWER' -H 'Idempotency-Key: demo-reset-review' \
    --data '{"issueId":"ISSUE-001","status":"REWORK_REQUIRED","reviewComment":"演示重置隔离验证","expectedVersion":0}' \
    "$business_url/api/tasks/TASK-003/review" >"$reset_temp/review.json"
curl --fail --silent --show-error \
    -H 'Content-Type: application/json' -H 'X-User-Id: reviewer-001' \
    -H 'X-User-Role: REVIEWER' -H 'Idempotency-Key: demo-reset-rework' \
    --data '{"sourceIssueId":"ISSUE-001","reason":"演示重置隔离验证","expectedVersion":1}' \
    "$business_url/api/tasks/TASK-003/rework" >"$reset_temp/rework.json"

written_counts=$(run_sql "SELECT concat_ws('|',
    (SELECT version FROM production_tasks WHERE task_id = 'TASK-003'),
    (SELECT COUNT(*) FROM review_records), (SELECT COUNT(*) FROM rework_tasks),
    (SELECT COUNT(*) FROM idempotency_records), (SELECT COUNT(*) FROM operation_logs));")
test "$written_counts" = '2|4|1|2|2'
run_sql 'CREATE TABLE demo_reset_probe (id integer PRIMARY KEY); INSERT INTO demo_reset_probe VALUES (1);' >/dev/null

reset_once second
second_snapshot=$(sed -n 's/^snapshot=//p' "$reset_temp/second.log")
test "$first_snapshot" = "$second_snapshot"
test "$(run_sql "SELECT to_regclass('public.demo_reset_probe') IS NULL;")" = t

# 补验当前Python迁移和页面恢复；关闭Provider，验证不发送真实模型请求。
failure_log="$reset_temp/build.log"
docker compose build --quiet agent-service web-console >"$reset_temp/build.log" 2>&1
failure_log="$reset_temp/migrate.log"
docker compose run --rm --no-deps agent-service \
    /service/.venv/bin/alembic upgrade head >"$reset_temp/migrate.log" 2>&1
test "$(run_sql 'SELECT version_num FROM agent_alembic_version;')" = 0014_review_source_run
test "$(run_sql 'SELECT COUNT(*) FROM agent_runs;')" = 0
test "$(run_sql 'SELECT COUNT(*) FROM approval_records;')" = 0
test "$(run_sql 'SELECT COUNT(*) FROM knowledge_chunks;')" = 0
failure_log="$reset_temp/up.log"
docker compose up -d agent-service web-console >"$reset_temp/up.log" 2>&1
web_port=$(docker compose port web-console 5173 | sed -n 's/.*://p' | head -n 1)
web_url="http://127.0.0.1:$web_port"
wait_health "$web_url/health"
wait_health "$web_url/agent-api/health"
wait_health "$web_url/business-api/health"

echo 'demo reset verification passed: two resets, Java writes cleared, Agent migration, three health endpoints'
echo "snapshot=$second_snapshot"
echo 'knowledge_chunks=0 (expected: real Embedding ingestion remains a separate step)'
