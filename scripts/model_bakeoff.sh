#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARM=""
DRY_RUN=0
RUN_ID="${NEOCORTEX_BAKEOFF_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
MODEL="${NEOCORTEX_ONTOLOGY_MODEL:-local:qwen3.8-flash-next}"
ENDPOINT="${NEOCORTEX_LOCAL_MODEL_BASE_URL:-http://127.0.0.1:24000/v1}"
CORPUS_PATH="docs/plans/18.5-e2e-revalidation/resources/episodes.md"
CORPUS_SIZE="$(uv run python "$ROOT/scripts/corpus_loader.py" --dry-run | wc -l | tr -d ' ')"
WORKER_CONCURRENCY="${NEOCORTEX_WORKER_CONCURRENCY:-2}"
PER_CALL_TIMEOUT="${NEOCORTEX_LOCAL_MODEL_TIMEOUT_S:-600}"
POLL_TIMEOUT_OVERRIDE="${BAKEOFF_POLL_TIMEOUT:-}"
POLL_TIMEOUT_ARG=""
POLL_TIMEOUT=""
TOKEN_ENV="NEOCORTEX_ADMIN_TOKEN"
MCP_TOKEN_ENV="NEOCORTEX_MCP_TOKEN"
TOKENS_FILE="${NEOCORTEX_DEV_TOKENS_FILE:-}"
PRE_SNAPSHOT=""
POST_SNAPSHOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --arm) ARM="$2"; shift 2 ;;
    --poll-timeout) POLL_TIMEOUT_ARG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$ARM" ]] || ARM="${NEOCORTEX_BAKEOFF_ARM:-unnamed}"
if [[ -n "$POLL_TIMEOUT_ARG" ]]; then
  POLL_TIMEOUT_OVERRIDE="$POLL_TIMEOUT_ARG"
fi

die() { echo "model bake-off: $*" >&2; exit 2; }
is_positive_int() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }
is_positive_number() { [[ "$1" =~ ^[1-9][0-9]*(\.[0-9]+)?$|^0\.[0-9]+$ ]]; }
is_positive_int "$WORKER_CONCURRENCY" || die "NEOCORTEX_WORKER_CONCURRENCY must be a positive integer"
is_positive_number "$PER_CALL_TIMEOUT" || die "NEOCORTEX_LOCAL_MODEL_TIMEOUT_S must be a positive number"
[[ "$CORPUS_SIZE" == "28" ]] || die "fixed corpus parser returned $CORPUS_SIZE episodes, expected 28"

if [[ -n "$POLL_TIMEOUT_OVERRIDE" ]]; then
  is_positive_int "$POLL_TIMEOUT_OVERRIDE" || die "BAKEOFF_POLL_TIMEOUT must be a positive integer"
  POLL_TIMEOUT="$POLL_TIMEOUT_OVERRIDE"
  POLL_TIMEOUT_SOURCE="explicit BAKEOFF_POLL_TIMEOUT"
else
  # Three model stages run serially per episode, with up to three attempts;
  # divide by worker concurrency and add a bounded startup allowance.
  PER_CALL_TIMEOUT_INT="${PER_CALL_TIMEOUT%.*}"
  [[ -n "$PER_CALL_TIMEOUT_INT" ]] || PER_CALL_TIMEOUT_INT=1
  (( PER_CALL_TIMEOUT_INT > 0 )) || PER_CALL_TIMEOUT_INT=1
  POLL_TIMEOUT=$((PER_CALL_TIMEOUT_INT * 3 * 3 * CORPUS_SIZE / WORKER_CONCURRENCY + 60))
  POLL_TIMEOUT_SOURCE="derived: per_call_timeout_s x 3 stages x 3 attempts x corpus_size / worker_concurrency + 60s"
fi

ADMIN_TOKEN_SET="no"
[[ -n "${NEOCORTEX_ADMIN_TOKEN:-}" ]] && ADMIN_TOKEN_SET="yes"
TOKENS_FILE_SET="no"
MCP_TOKEN_SET="no"
[[ -n "${NEOCORTEX_MCP_TOKEN:-}" ]] && MCP_TOKEN_SET="yes"
[[ -n "$TOKENS_FILE" ]] && TOKENS_FILE_SET="yes"

print_configuration() {
  printf '%s\n' \
    "bakeoff_run_id=$RUN_ID" \
    "arm=$ARM" \
    "model=$MODEL" \
    "endpoint=$ENDPOINT" \
    "effort_ontology=${NEOCORTEX_ONTOLOGY_THINKING_EFFORT:-low}" \
    "effort_extractor=${NEOCORTEX_EXTRACTOR_THINKING_EFFORT:-low}" \
    "effort_librarian=${NEOCORTEX_LIBRARIAN_THINKING_EFFORT:-low}" \
    "worker_concurrency=$WORKER_CONCURRENCY" \
    "per_call_timeout_s=$PER_CALL_TIMEOUT" \
    "corpus_size=$CORPUS_SIZE" \
    "poll_timeout_s=$POLL_TIMEOUT" \
    "poll_timeout_source=$POLL_TIMEOUT_SOURCE" \
    "corpus_path=$CORPUS_PATH" \
    "metrics_path=docs/plans/33-local-qwen-migration/resources/metrics-$ARM.json" \
    "audit_log=log/agent_actions.log" \
    "admin_token_env=$TOKEN_ENV configured=$ADMIN_TOKEN_SET" \
    "mcp_token_env=$MCP_TOKEN_ENV configured=$MCP_TOKEN_SET" \
    "dev_tokens_file=$TOKENS_FILE configured=$TOKENS_FILE_SET" \
    "mcp_auth_mode=dev_token"
}

run() { printf '+ '; printf '%q ' "$@"; printf '\n'; (( DRY_RUN )) || "$@"; }
run_shell() { printf '+ %s\n' "$1"; (( DRY_RUN )) || bash -c "$1"; }

restore_preserved_snapshot() {
  local exit_code=$?
  if [[ -n "$PRE_SNAPSHOT" && "$DRY_RUN" -eq 0 ]]; then
    "$ROOT/scripts/manage.sh" snapshot load "$PRE_SNAPSHOT" >/dev/null 2>&1 \
      || echo "model bake-off: failed to restore preserved snapshot $PRE_SNAPSHOT" >&2
  fi
  exit "$exit_code"
}
trap restore_preserved_snapshot EXIT

if (( DRY_RUN )); then
  print_configuration
else
  [[ -n "${NEOCORTEX_ADMIN_TOKEN:-}" ]] || die "NEOCORTEX_ADMIN_TOKEN is required (value is never logged)"
  [[ -n "${NEOCORTEX_MCP_TOKEN:-}" ]] || die "NEOCORTEX_MCP_TOKEN is required (value is never logged)"
  [[ -n "$TOKENS_FILE" ]] || die "NEOCORTEX_DEV_TOKENS_FILE is required"
  [[ -f "$TOKENS_FILE" ]] || die "dev-token file does not exist: $TOKENS_FILE"
  command -v jq >/dev/null 2>&1 || die "jq is required to validate the dev-token map"
  jq -e --arg token "$NEOCORTEX_ADMIN_TOKEN" 'type == "object" and has($token)' "$TOKENS_FILE" >/dev/null \
    || die "NEOCORTEX_ADMIN_TOKEN is not present in NEOCORTEX_DEV_TOKENS_FILE"
  [[ -n "${GOOGLE_API_KEY:-}" ]] || die "GOOGLE_API_KEY is required for embedding health; recall metrics are NOT MEASURED"
fi

export NEOCORTEX_BAKEOFF_RUN_ID="$RUN_ID"
export NEOCORTEX_LOCAL_MODEL_BASE_URL="$ENDPOINT"
export NEOCORTEX_LOCAL_MODEL_API_KEY_ENV="${NEOCORTEX_LOCAL_MODEL_API_KEY_ENV:-LITELLM_API_KEY}"
export NEOCORTEX_AUTH_MODE=dev_token
export NEOCORTEX_EXTRACTION_ENABLED=true
if [[ -n "$TOKENS_FILE" ]]; then
  export NEOCORTEX_DEV_TOKENS_FILE="$TOKENS_FILE"
fi
export NEOCORTEX_ONTOLOGY_MODEL="$MODEL"
export NEOCORTEX_EXTRACTOR_MODEL="${NEOCORTEX_EXTRACTOR_MODEL:-$MODEL}"
export NEOCORTEX_LIBRARIAN_MODEL="${NEOCORTEX_LIBRARIAN_MODEL:-$MODEL}"
export NEOCORTEX_DOMAIN_CLASSIFIER_MODEL="${NEOCORTEX_DOMAIN_CLASSIFIER_MODEL:-$MODEL}"
export NEOCORTEX_WORKER_CONCURRENCY="$WORKER_CONCURRENCY"
export NEOCORTEX_LOCAL_MODEL_TIMEOUT_S="$PER_CALL_TIMEOUT"

if (( ! DRY_RUN )) && docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  pg_isready -U neocortex -d neocortex >/dev/null 2>&1; then
  PRE_SNAPSHOT="${ARM}-pre-${RUN_ID}"
  run "$ROOT/scripts/manage.sh" snapshot save "$PRE_SNAPSHOT"
fi

run "$ROOT/scripts/manage.sh" start --fresh
if (( ! DRY_RUN )); then
  uv run python -c 'import asyncio, os; from neocortex.embedding_service import EmbeddingService; from neocortex.mcp_settings import MCPSettings; assert os.environ.get("GOOGLE_API_KEY"), "GOOGLE_API_KEY is required; embedding health NOT MEASURED"; v=asyncio.run(EmbeddingService(model=MCPSettings().embedding_model).embed("bakeoff probe")); assert v is not None and len(v)==768, "EMBEDDINGS DEAD"; print("embeddings OK")'
  curl --fail --silent --show-error "http://127.0.0.1:8001/admin/graphs" -H "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}" | grep -q 'ncx_shared__' || { echo 'seed schemas missing' >&2; exit 1; }
  run uv run python "$ROOT/scripts/auth_self_check.py"
fi
run uv run python "$ROOT/scripts/corpus_loader.py"
run_shell 'deadline=$(date +%s)+'"$POLL_TIMEOUT"'; while :; do state=$(curl --fail --silent http://127.0.0.1:8001/admin/jobs/summary -H "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}"); todo=$(printf "%s" "$state" | uv run python -c '\''import json,sys; x=json.load(sys.stdin); print(x.get("todo",0)+x.get("doing",0))'\''); echo "jobs outstanding: $todo"; [[ "$todo" == 0 ]] && break; (( $(date +%s) >= deadline )) && { echo "job poll timed out; metrics not written (NOT_MEASURED)" >&2; exit 1; }; sleep 5; done'
run "$ROOT/scripts/manage.sh" snapshot save "$ARM"
if (( DRY_RUN )); then
  POST_SNAPSHOT="$ROOT/backups/${ARM}-${RUN_ID}.tar.gz"
else
  POST_SNAPSHOT="$(find "$ROOT/backups" -maxdepth 1 -type f -name "$ARM-*.tar.gz" -print | sort | tail -1)"
  [[ -n "$POST_SNAPSHOT" ]] || die "post-run snapshot was not created"
fi
run uv run python "$ROOT/scripts/compute_metrics.py" --arm "$ARM" --phase corpus --snapshot-path "$POST_SNAPSHOT" --run-id "$RUN_ID"
run uv run python "$ROOT/scripts/recall_scorer.py"
for test in e2e_extraction_pipeline_test.py e2e_plan15_scenarios_test.py e2e_plan17_validation.py e2e_episodic_memory_test.py e2e_cognitive_recall_test.py; do
  run "$ROOT/scripts/run_e2e.sh" "$ROOT/scripts/$test"
done
run uv run python "$ROOT/scripts/compute_metrics.py" --arm "$ARM" --phase e2e --merge --snapshot-path "$POST_SNAPSHOT" --run-id "$RUN_ID"
