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
DOMAIN_ROUTING_ENABLED="${NEOCORTEX_DOMAIN_ROUTING_ENABLED:-true}"
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
case "${DOMAIN_ROUTING_ENABLED,,}" in
  true|1|yes) DOMAIN_ROUTING_ENABLED=true ;;
  false|0|no) DOMAIN_ROUTING_ENABLED=false ;;
  *) die "NEOCORTEX_DOMAIN_ROUTING_ENABLED must be true or false" ;;
esac
[[ "$CORPUS_SIZE" == "28" ]] || die "fixed corpus parser returned $CORPUS_SIZE episodes, expected 28"

INITIAL_DOMAIN_COUNT=0
MAX_UNIQUE_ROUTED_DOMAINS=0
ROUTE_ATTEMPTS=0
EXTRACTION_ATTEMPTS="$(uv run python -c 'from neocortex.jobs.tasks import extract_episode; print(extract_episode.retry_strategy.max_attempts)')"
is_positive_int "$EXTRACTION_ATTEMPTS" || die "extract_episode retry count is not a positive integer"
MAX_ROUTE_INVOCATIONS=0
MAX_ROUTED_EXTRACTION_JOBS=0
ROUTE_CLASSIFIER_STAGE_INVOCATIONS=0
TOP_LEVEL_SEED_RESOLUTION_STAGE_INVOCATIONS=0
PERSONAL_EXTRACTION_STAGE_INVOCATIONS=0
ROUTED_EXTRACTION_STAGE_INVOCATIONS=0
ROUTED_SEED_STAGE_INVOCATIONS=0
OPERATIONAL_ACCEPTANCE_STAGE_INVOCATIONS=0
if [[ "$DOMAIN_ROUTING_ENABLED" == true ]]; then
  # The fresh run seeds the domains declared by the running application.  A
  # route invocation can add at most one proposed domain, and the router's
  # explicit cap bounds unique routed domains for that invocation.
  INITIAL_DOMAIN_COUNT="$(uv run python -c 'from neocortex.domains.models import SEED_DOMAINS; print(len(SEED_DOMAINS))')"
  is_positive_int "$INITIAL_DOMAIN_COUNT" || die "seed domain count is not a positive integer"
  MAX_UNIQUE_ROUTED_DOMAINS="$(uv run python -c 'from neocortex.domains.router import MAX_UNIQUE_ROUTED_DOMAINS; print(MAX_UNIQUE_ROUTED_DOMAINS)')"
  is_positive_int "$MAX_UNIQUE_ROUTED_DOMAINS" || die "max unique routed domain count is not a positive integer"
  (( MAX_UNIQUE_ROUTED_DOMAINS >= INITIAL_DOMAIN_COUNT )) \
    || die "max unique routed domain count is below the seeded-domain count"
  ROUTE_ATTEMPTS="$(uv run python -c 'from neocortex.jobs.tasks import route_episode; print(route_episode.retry_strategy.max_attempts)')"
  is_positive_int "$ROUTE_ATTEMPTS" || die "route_episode retry count is not a positive integer"
fi

MAX_ROUTE_INVOCATIONS=$((CORPUS_SIZE * ROUTE_ATTEMPTS))
MAX_ROUTED_EXTRACTION_JOBS=$((MAX_ROUTE_INVOCATIONS * MAX_UNIQUE_ROUTED_DOMAINS))
# The following counters are stage invocations used only for the operational
# acceptance deadline.  A route invocation can classify once and warm one
# proposed-domain seed at the top level.  Each routed extraction retry can
# also resolve one domain seed; counting that on every retry is conservative
# because cache hits may avoid the call.  Parent-seed recursion, internal
# PydanticAI retries, and non-model work remain outside this budget.
ROUTE_CLASSIFIER_STAGE_INVOCATIONS="$MAX_ROUTE_INVOCATIONS"
TOP_LEVEL_SEED_RESOLUTION_STAGE_INVOCATIONS="$MAX_ROUTE_INVOCATIONS"
PERSONAL_EXTRACTION_STAGE_INVOCATIONS=$((CORPUS_SIZE * EXTRACTION_ATTEMPTS * 3))
ROUTED_EXTRACTION_STAGE_INVOCATIONS=$((MAX_ROUTED_EXTRACTION_JOBS * EXTRACTION_ATTEMPTS * 3))
ROUTED_SEED_STAGE_INVOCATIONS=$((MAX_ROUTED_EXTRACTION_JOBS * EXTRACTION_ATTEMPTS))
if [[ "$DOMAIN_ROUTING_ENABLED" == true ]]; then
  OPERATIONAL_ACCEPTANCE_STAGE_INVOCATIONS=$((ROUTE_CLASSIFIER_STAGE_INVOCATIONS + TOP_LEVEL_SEED_RESOLUTION_STAGE_INVOCATIONS + PERSONAL_EXTRACTION_STAGE_INVOCATIONS + ROUTED_EXTRACTION_STAGE_INVOCATIONS + ROUTED_SEED_STAGE_INVOCATIONS))
else
  OPERATIONAL_ACCEPTANCE_STAGE_INVOCATIONS="$PERSONAL_EXTRACTION_STAGE_INVOCATIONS"
fi

if [[ -n "$POLL_TIMEOUT_OVERRIDE" ]]; then
  is_positive_int "$POLL_TIMEOUT_OVERRIDE" || die "BAKEOFF_POLL_TIMEOUT must be a positive integer"
  POLL_TIMEOUT="$POLL_TIMEOUT_OVERRIDE"
  POLL_TIMEOUT_SOURCE="explicit BAKEOFF_POLL_TIMEOUT"
else
  # This is an operational acceptance budget for stage invocations.  The
  # explicit router fan-out policy and registered job retry policies make it
  # useful for this bake-off, but it is not a theoretical per-request upper
  # bound: PydanticAI's internal retries and non-model work are excluded.
  # Exceeding this deadline is a NOT_MEASURED/stability failure.  Use awk for
  # ceil(): shell arithmetic would silently truncate fractional timeouts.
  if [[ "$DOMAIN_ROUTING_ENABLED" == true ]]; then
    POLL_TIMEOUT_SOURCE="operational acceptance budget derived from registered route/extract retries, explicit max unique routed domains, route classifier/top-level seed-resolution stages, three-stage extraction, corpus size, and worker concurrency; excludes parent-seed recursion, PydanticAI theoretical retries, and non-model work; overrun is NOT_MEASURED/stability failure; rounded up + 60s"
  else
    POLL_TIMEOUT_SOURCE="operational acceptance budget derived from registered extract retries, three-stage personal extraction, corpus size, and worker concurrency; excludes PydanticAI theoretical retries and non-model work; overrun is NOT_MEASURED/stability failure; rounded up + 60s (domain routing disabled)"
  fi
  POLL_TIMEOUT="$(awk -v timeout="$PER_CALL_TIMEOUT" \
    -v calls="$OPERATIONAL_ACCEPTANCE_STAGE_INVOCATIONS" \
    -v concurrency="$WORKER_CONCURRENCY" \
    'BEGIN { seconds = timeout * calls / concurrency + 60; whole = int(seconds); if (seconds > whole) whole++; print whole }')"
fi

ADMIN_TOKEN_SET="no"
[[ -n "${NEOCORTEX_ADMIN_TOKEN:-}" ]] && ADMIN_TOKEN_SET="yes"
TOKENS_FILE_SET="no"
MCP_TOKEN_SET="no"
[[ -n "${NEOCORTEX_MCP_TOKEN:-}" ]] && MCP_TOKEN_SET="yes"
[[ -n "$TOKENS_FILE" ]] && TOKENS_FILE_SET="yes"

print_configuration() {
  local endpoint_identity
  endpoint_identity="$(redact_endpoint "$ENDPOINT")"
  printf '%s\n' \
    "bakeoff_run_id=$RUN_ID" \
    "arm=$ARM" \
    "model=$MODEL" \
    "endpoint=$endpoint_identity" \
    "effort_ontology=${NEOCORTEX_ONTOLOGY_THINKING_EFFORT:-low}" \
    "effort_extractor=${NEOCORTEX_EXTRACTOR_THINKING_EFFORT:-low}" \
    "effort_librarian=${NEOCORTEX_LIBRARIAN_THINKING_EFFORT:-low}" \
    "worker_concurrency=$WORKER_CONCURRENCY" \
    "domain_routing_enabled=$DOMAIN_ROUTING_ENABLED" \
    "initial_domain_count=$INITIAL_DOMAIN_COUNT" \
    "max_unique_routed_domains=$MAX_UNIQUE_ROUTED_DOMAINS" \
    "route_attempts=$ROUTE_ATTEMPTS" \
    "extraction_attempts=$EXTRACTION_ATTEMPTS" \
    "max_route_invocations=$MAX_ROUTE_INVOCATIONS" \
    "max_routed_extraction_jobs=$MAX_ROUTED_EXTRACTION_JOBS" \
    "route_classifier_stage_invocations_max=$ROUTE_CLASSIFIER_STAGE_INVOCATIONS" \
    "top_level_seed_resolution_stage_invocations_max=$TOP_LEVEL_SEED_RESOLUTION_STAGE_INVOCATIONS" \
    "personal_extraction_stage_invocations_max=$PERSONAL_EXTRACTION_STAGE_INVOCATIONS" \
    "routed_extraction_stage_invocations_max=$ROUTED_EXTRACTION_STAGE_INVOCATIONS" \
    "routed_seed_stage_invocations_max=$ROUTED_SEED_STAGE_INVOCATIONS" \
    "operational_acceptance_stage_invocations=$OPERATIONAL_ACCEPTANCE_STAGE_INVOCATIONS" \
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

redact_endpoint() {
  local endpoint="$1"
  # Preserve the endpoint identity (scheme, host, port, and base path) while
  # removing URL userinfo and query/fragment values that can carry credentials.
  if [[ "$endpoint" =~ ^([[:alpha:]][[:alnum:]+.-]*://)([^/?#]+)([^?#]*) ]]; then
    local scheme="${BASH_REMATCH[1]}"
    local authority="${BASH_REMATCH[2]}"
    local path="${BASH_REMATCH[3]}"
    authority="${authority##*@}"
    printf '%s%s%s\n' "$scheme" "$authority" "$path"
  else
    endpoint="${endpoint%%\?*}"
    endpoint="${endpoint%%#*}"
    printf '%s\n' "$endpoint"
  fi
}

run() { printf '+ '; printf '%q ' "$@"; printf '\n'; (( DRY_RUN )) || "$@"; }
run_shell() { printf '+ %s\n' "$1"; (( DRY_RUN )) || bash -c "$1"; }

RESTORE_FAILURE_STATUS=3
restore_preserved_snapshot() {
  local exit_code=$?
  if [[ -n "$PRE_SNAPSHOT" && "$DRY_RUN" -eq 0 ]]; then
    if ! "$ROOT/scripts/manage.sh" snapshot load "$PRE_SNAPSHOT" >/dev/null 2>&1; then
      local restore_status="$RESTORE_FAILURE_STATUS"
      # Keep the restoration outcome distinguishable even if the command that
      # triggered EXIT happened to return the reserved status already.
      (( exit_code == restore_status )) && restore_status=4
      echo "model bake-off: failed to restore preserved snapshot $PRE_SNAPSHOT" >&2
      echo "model bake-off: restoration failure status=$restore_status (original status=$exit_code)" >&2
      exit "$restore_status"
    fi
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
  # Feed the credential through stdin.  Passing it via jq --arg would expose
  # it in argv to process observers.
  jq -e --rawfile token /dev/stdin 'type == "object" and has(($token | rtrimstr("\n")))' "$TOKENS_FILE" \
    <<<"$NEOCORTEX_ADMIN_TOKEN" >/dev/null \
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
export NEOCORTEX_DOMAIN_ROUTING_ENABLED="$DOMAIN_ROUTING_ENABLED"

if (( ! DRY_RUN )); then
  # A fresh start destroys the PostgreSQL volume.  If PostgreSQL is stopped,
  # first start it non-destructively so a recoverable snapshot can be made.
  if ! docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
    pg_isready -U neocortex -d neocortex >/dev/null 2>&1; then
    echo "model bake-off: PostgreSQL is stopped; starting non-destructively before snapshot" >&2
    run "$ROOT/scripts/manage.sh" start
  fi
  docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
    pg_isready -U neocortex -d neocortex >/dev/null 2>&1 \
    || die "PostgreSQL is not ready; refusing destructive start --fresh without a recovery snapshot"
  PRE_SNAPSHOT_NAME="${ARM}-pre-${RUN_ID}"
  run "$ROOT/scripts/manage.sh" snapshot save "$PRE_SNAPSHOT_NAME"
  PRE_SNAPSHOT_FILE="$(find "$ROOT/backups" -maxdepth 1 -type f -name "$PRE_SNAPSHOT_NAME-*.tar.gz" -print 2>/dev/null | sort | tail -1)"
  [[ -n "$PRE_SNAPSHOT_FILE" && -s "$PRE_SNAPSHOT_FILE" ]] \
    || die "pre-run snapshot archive is missing; refusing destructive start --fresh"
  tar -tzf "$PRE_SNAPSHOT_FILE" >/dev/null 2>&1 \
    || die "pre-run snapshot archive is invalid; refusing destructive start --fresh"
  PRE_SNAPSHOT="$PRE_SNAPSHOT_NAME"
fi

run "$ROOT/scripts/manage.sh" start --fresh
if (( ! DRY_RUN )); then
  uv run python -c 'import asyncio, os; from neocortex.embedding_service import EmbeddingService; from neocortex.mcp_settings import MCPSettings; assert os.environ.get("GOOGLE_API_KEY"), "GOOGLE_API_KEY is required; embedding health NOT MEASURED"; v=asyncio.run(EmbeddingService(model=MCPSettings().embedding_model).embed("bakeoff probe")); assert v is not None and len(v)==768, "EMBEDDINGS DEAD"; print("embeddings OK")'
  curl --fail --silent --show-error "http://127.0.0.1:8001/admin/graphs" -H @- \
    <<<"Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}" \
    | grep -q 'ncx_shared__' || { echo 'seed schemas missing' >&2; exit 1; }
  run uv run python "$ROOT/scripts/auth_self_check.py"
fi
run uv run python "$ROOT/scripts/corpus_loader.py"
run_shell 'deadline=$(date +%s)+'"$POLL_TIMEOUT"'; while :; do state=$(curl --fail --silent http://127.0.0.1:8001/admin/jobs/summary -H @- <<< "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}"); todo=$(printf "%s" "$state" | uv run python -c '\''import json,sys; x=json.load(sys.stdin); print(x.get("todo",0)+x.get("doing",0))'\''); echo "jobs outstanding: $todo"; [[ "$todo" == 0 ]] && break; (( $(date +%s) >= deadline )) && { echo "job poll timed out; metrics not written (NOT_MEASURED)" >&2; exit 1; }; sleep 5; done'
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
