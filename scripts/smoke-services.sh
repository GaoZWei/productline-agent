#!/bin/sh
set -eu

command -v curl >/dev/null 2>&1 || {
    echo "curl is required for smoke tests" >&2
    exit 1
}

task_tmp_dir=$(mktemp -d)
agent_pid=""
business_pid=""
business_container=""
web_pid=""

cleanup() {
    for pid in "$agent_pid" "$business_pid" "$web_pid"; do
        if test -n "$pid"; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    if test -n "$business_container"; then
        docker rm --force "$business_container" >/dev/null 2>&1 || true
    fi
    rm -rf "$task_tmp_dir"
}
trap cleanup EXIT INT TERM

wait_for_health() {
    url=$1
    attempts=0
    until curl --fail --silent "$url" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if test "$attempts" -ge 30; then
            echo "health check failed: $url" >&2
            return 1
        fi
        sleep 0.1
    done
}

if command -v python3 >/dev/null 2>&1; then
    PORT=18000 python3 agent-service/app/main.py >"$task_tmp_dir/agent.log" 2>&1 &
    agent_pid=$!
    wait_for_health http://127.0.0.1:18000/health
    echo "agent-service smoke test passed"
else
    echo "python3 is required for agent-service smoke test" >&2
    exit 1
fi

if command -v javac >/dev/null 2>&1 \
    && command -v java >/dev/null 2>&1 \
    && javac -version >/dev/null 2>&1 \
    && java -version >/dev/null 2>&1; then
    mkdir -p "$task_tmp_dir/java"
    javac --release 21 -d "$task_tmp_dir/java" business-service/src/Main.java
    PORT=18080 java --add-modules jdk.httpserver -cp "$task_tmp_dir/java" Main \
        >"$task_tmp_dir/business.log" 2>&1 &
    business_pid=$!
    wait_for_health http://127.0.0.1:18080/health
    echo "business-service smoke test passed"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker build --quiet --tag remote-sensing-agent-business-smoke business-service >/dev/null
    business_container=$(docker run --detach --rm --publish 18080:8080 \
        remote-sensing-agent-business-smoke)
    wait_for_health http://127.0.0.1:18080/health
    echo "business-service Docker smoke test passed"
else
    echo "JDK 21 or a running Docker daemon is required for business-service smoke test" >&2
    exit 1
fi

if command -v node >/dev/null 2>&1; then
    PORT=15173 node web-console/server.mjs >"$task_tmp_dir/web.log" 2>&1 &
    web_pid=$!
    wait_for_health http://127.0.0.1:15173/health
    echo "web-console smoke test passed"
else
    echo "Node.js is required for web-console smoke test" >&2
    exit 1
fi
