#!/usr/bin/env bash
# Unified E2E test runner for NeoCortex.
#
# Starts PostgreSQL + MCP server + ingestion server, waits for readiness,
# runs the given test script, and tears everything down on exit.
#
# Usage:
#   ./scripts/run_e2e.sh scripts/e2e_mcp_test.py
#   ./scripts/run_e2e.sh scripts/e2e_embedding_test.py
#   ./scripts/run_e2e.sh --docker scripts/e2e_ingestion_test.py
#
# Environment overrides:
#   NEOCORTEX_BASE_URL            (default: http://127.0.0.1:8000)
#   NEOCORTEX_INGESTION_BASE_URL  (default: http://127.0.0.1:8001)
#   KEEP_RUNNING=1                keep services up after test (skip teardown)
#   MAX_WAIT=60                   seconds to wait for readiness

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

MCP_BASE_URL="${NEOCORTEX_BASE_URL:-http://127.0.0.1:8000}"
INGESTION_BASE_URL="${NEOCORTEX_INGESTION_BASE_URL:-http://127.0.0.1:8001}"
MAX_WAIT="${MAX_WAIT:-60}"
MODE="local"
TEST_SCRIPT=""

# --- helpers ---------------------------------------------------------------

log()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [--docker] <test_script.py>

  --docker    Run everything via docker compose (default: local mode)
  <test_script.py>  Path to the Python e2e test to run (relative to project root)

Examples:
  $(basename "$0") scripts/e2e_mcp_test.py
  $(basename "$0") --docker scripts/e2e_ingestion_test.py
EOF
    exit 1
}

cleanup() {
    local exit_code=$?
    if [[ "${KEEP_RUNNING:-}" == "1" ]]; then
        ok "KEEP_RUNNING=1 — leaving services up."
        return
    fi

    log "Cleaning up..."

    if [[ "$MODE" == "docker" ]]; then
        docker compose -f "$PROJECT_DIR/docker-compose.yml" down --timeout 5 2>/dev/null || true
        log "Stopped docker compose services."
    else
        if [[ "${KEEP_POSTGRES_RUNNING:-}" == "1" ]]; then
            "$SCRIPT_DIR/manage.sh" stop
        else
            "$SCRIPT_DIR/manage.sh" stop --all
        fi
    fi

    exit "$exit_code"
}

wait_for_healthy() {
    local url="$1" max="$2" elapsed=0
    log "Waiting for $url (up to ${max}s)..."
    while (( elapsed < max )); do
        if curl -sf "$url" >/dev/null 2>&1; then
            ok "Healthy: $url (${elapsed}s)."
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    fail "Service at $url did not become healthy within ${max}s."
}

# --- parse args ------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker) MODE="docker"; shift ;;
        -h|--help) usage ;;
        -*)  fail "Unknown option: $1" ;;
        *)
            [[ -z "$TEST_SCRIPT" ]] || fail "Only one test script allowed, got extra: $1"
            TEST_SCRIPT="$1"; shift ;;
    esac
done

[[ -n "$TEST_SCRIPT" ]] || fail "No test script specified. Run with --help for usage."

# --- main ------------------------------------------------------------------

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$PROJECT_DIR"

# Resolve test script path relative to project root
if [[ ! -f "$TEST_SCRIPT" ]]; then
    fail "Test script not found: $TEST_SCRIPT"
fi

log "Mode: $MODE | Test: $TEST_SCRIPT"

if [[ "$MODE" == "docker" ]]; then
    # ---------- Docker mode: everything via docker compose ------------------
    # Use test tokens (alice/bob/eve personas) for e2e isolation tests
    export DEV_TOKENS_FILE="${DEV_TOKENS_FILE:-dev_tokens_test.json}"
    log "Starting all services via docker compose..."
    docker compose up -d --build 2>&1 || true
    wait_for_healthy "$MCP_BASE_URL/health" "$MAX_WAIT"
    wait_for_healthy "$INGESTION_BASE_URL/health" "$MAX_WAIT"
else
    # ---------- Local mode: delegate to manage.sh ---------------------------
    # Use test tokens (alice/bob/eve personas) for e2e isolation tests
    export NEOCORTEX_DEV_TOKENS_FILE="${NEOCORTEX_DEV_TOKENS_FILE:-dev_tokens_test.json}"
    "$SCRIPT_DIR/manage.sh" start --fresh
    wait_for_healthy "$MCP_BASE_URL/health" "$MAX_WAIT"
    wait_for_healthy "$INGESTION_BASE_URL/health" "$MAX_WAIT"
fi

# Ensure .env is sourced for test scripts (GOOGLE_API_KEY, etc.)
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a; source "$PROJECT_DIR/.env"; set +a
fi

log "Running E2E test: $TEST_SCRIPT"
uv run python "$TEST_SCRIPT"

ok "E2E TEST PASSED: $TEST_SCRIPT"
