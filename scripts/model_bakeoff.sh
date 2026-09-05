#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
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
PRE_SNAPSHOT_FILE=""
POST_SNAPSHOT=""
POST_SNAPSHOT_NAME=""
POST_SNAPSHOT_SHA256=""
E2E_WORKDIR=""
E2E_STATUS_PATH=""
E2E_MANIFEST_PATH=""
RECALL_EVIDENCE_PATH=""
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
is_safe_run_id() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$ ]]; }
sha256_file() { shasum -a 256 "$1" | awk '{print $1}'; }
is_safe_run_id "$ARM" || die "bake-off arm has an invalid safe format"
is_positive_int "$WORKER_CONCURRENCY" || die "NEOCORTEX_WORKER_CONCURRENCY must be a positive integer"
is_positive_number "$PER_CALL_TIMEOUT" || die "NEOCORTEX_LOCAL_MODEL_TIMEOUT_S must be a positive number"
case "${DOMAIN_ROUTING_ENABLED,,}" in
  true|1|yes) DOMAIN_ROUTING_ENABLED=true ;;
  false|0|no) DOMAIN_ROUTING_ENABLED=false ;;
  *) die "NEOCORTEX_DOMAIN_ROUTING_ENABLED must be true or false" ;;
esac
[[ "$CORPUS_SIZE" == "28" ]] || die "fixed corpus parser returned $CORPUS_SIZE episodes, expected 28"
is_safe_run_id "$RUN_ID" || die "NEOCORTEX_BAKEOFF_RUN_ID has an invalid safe format"

# The bake-off uses the admin dev-token identity for its MCP recall probe.
# Keep an explicit MCP override, but make the documented admin-only invocation
# complete without requiring a second undocumented credential.
export NEOCORTEX_MCP_TOKEN="${NEOCORTEX_MCP_TOKEN:-${NEOCORTEX_ADMIN_TOKEN:-}}"

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
poll_jobs() {
  local deadline state counts todo doing
  deadline=$(( $(date +%s) + POLL_TIMEOUT ))
  while :; do
    state=$(curl --fail --silent http://127.0.0.1:8001/admin/jobs/summary -H @- \
      <<<"Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}")
    if ! counts=$(printf '%s' "$state" | uv run python -c \
      'import json,sys; x=json.load(sys.stdin); keys=("todo","doing","succeeded","failed","cancelled","total"); assert isinstance(x,dict) and all(type(x.get(k)) is int and x[k] >= 0 for k in keys) and x["total"] > 0 and sum(x[k] for k in keys[:-1]) == x["total"]; print(" ".join(f"{k}={x[k]}" for k in keys) + f" failure_rate_ok={(x[\"failed\"] + x[\"cancelled\"]) / x[\"total\"] <= 0.10}")' \
      2>/dev/null); then
      echo 'job summary malformed or exceeds failure-rate gate; metrics NOT_MEASURED' >&2
      return 2
    fi
    todo="${counts#*todo=}"
    todo="${todo%% *}"
    doing="${counts#*doing=}"
    doing="${doing%% *}"
    local failure_rate_ok="${counts#*failure_rate_ok=}"
    failure_rate_ok="${failure_rate_ok%% *}"
    printf 'jobs status %s\n' "$counts"
    if [[ "$todo" == 0 && "$doing" == 0 ]]; then
      [[ "$failure_rate_ok" == True ]] || {
        echo 'job summary exceeds failure-rate gate; metrics NOT_MEASURED' >&2
        return 2
      }
      return 0
    fi
    if (( $(date +%s) >= deadline )); then
      echo 'job poll timed out; metrics NOT_MEASURED' >&2
      return 1
    fi
    sleep 5
  done
}
result_matches_child() {
  local result_path="$1"
  local test_script="$2"
  local child_run_id="$3"
  local exit_code="$4"
  uv run python -c \
    'import json, sys; data=json.load(open(sys.argv[1], encoding="utf-8")); assert isinstance(data, dict) and data.get("script") == sys.argv[2] and data.get("child_run_id") == sys.argv[3] and data.get("exit_code") == int(sys.argv[4])' \
    "$result_path" "$test_script" "$child_run_id" "$exit_code" >/dev/null 2>&1
}
run_e2e_with_test_tokens() {
  local index="$1"
  local test_script="$2"
  local child_run_id="${RUN_ID}.e2e.$(printf '%02d' "$index")"
  local result_path="$E2E_WORKDIR/result-$(printf '%02d' "$index").json"
  local stdout_path="$E2E_WORKDIR/stdout-$(printf '%02d' "$index")"
  local stderr_path="$E2E_WORKDIR/stderr-$(printf '%02d' "$index")"
  local status
  printf '+ e2e index=%s test=%q child_run_id=%s dev_tokens_file=dev_tokens_test.json\n' "$index" "$test_script" "$child_run_id"
  (( DRY_RUN )) && return 0
  if (
    # The corpus arm uses the role-based admin map.  E2E scripts intentionally
    # exercise Alice/Bob/Eve isolation and therefore require their test map.
    export NEOCORTEX_DEV_TOKENS_FILE="$ROOT/dev_tokens_test.json"
    export KEEP_POSTGRES_RUNNING=1
    export NEOCORTEX_E2E_RUN_ID="$child_run_id"
    export NEOCORTEX_E2E_RESULT_PATH="$result_path"
    unset NEOCORTEX_ADMIN_TOKEN NEOCORTEX_MCP_TOKEN NEOCORTEX_RECALL_TOKEN
    unset NEOCORTEX_TOKEN NEOCORTEX_DEV_TOKEN
    unset NEOCORTEX_ALICE_TOKEN NEOCORTEX_BOB_TOKEN NEOCORTEX_EVE_TOKEN
    "$ROOT/scripts/run_e2e.sh" "$ROOT/scripts/$test_script"
  ) >"$stdout_path" 2>"$stderr_path"; then
    status=0
  else
    status=$?
  fi
  # Raw E2E output is diagnostic only and never becomes evidence.
  rm -f "$stdout_path" "$stderr_path"
  if [[ -f "$result_path" ]] && ! result_matches_child "$result_path" "$test_script" "$child_run_id" "$status"; then
    rm -f "$result_path"
  fi
  if [[ ! -f "$result_path" ]]; then
    if [[ "$test_script" == e2e_plan15_scenarios_test.py || "$test_script" == e2e_plan17_validation.py ]]; then
      uv run python "$ROOT/scripts/e2e_manifest.py" write-missing-result \
        --path "$result_path" --script "$test_script" --child-run-id "$child_run_id" --exit-code "$status"
    else
      uv run python "$ROOT/scripts/e2e_manifest.py" write-exit-result \
        --path "$result_path" --script "$test_script" --child-run-id "$child_run_id" --exit-code "$status"
    fi
  fi
  printf '%s\t%s\t%s\t%s\n' "$test_script" "$child_run_id" "$status" "$result_path" >>"$E2E_STATUS_PATH"
  printf 'e2e completed index=%s child_run_id=%s exit_code=%s\n' "$index" "$child_run_id" "$status"
  return "$status"
}

resolve_saved_snapshot() {
  local name="$1"
  local snapshot_path
  [[ -n "${NEOCORTEX_SNAPSHOT_PATH_FILE:-}" && -s "$NEOCORTEX_SNAPSHOT_PATH_FILE" ]] \
    || die "snapshot path receipt is missing for $name"
  snapshot_path="$(<"$NEOCORTEX_SNAPSHOT_PATH_FILE")"
  case "$snapshot_path" in
    "$ROOT/backups/${name}-"*.tar.gz) ;;
    *) die "snapshot path receipt is not the exact run-named archive for $name" ;;
  esac
  [[ -f "$snapshot_path" && -s "$snapshot_path" ]] || die "snapshot archive is missing for $name"
  tar -tzf "$snapshot_path" >/dev/null 2>&1 || die "snapshot archive is invalid for $name"
  local metadata
  metadata="$(tar -xOzf "$snapshot_path" ./snapshot.json 2>/dev/null)" \
    || die "snapshot metadata is missing for $name"
  printf '%s' "$metadata" | uv run python -c \
    'import json, sys; expected=sys.argv[1]; data=json.load(sys.stdin); assert data.get("name") == expected' "$name" \
    || die "snapshot metadata name is inconsistent for $name"
  printf '%s\n' "$snapshot_path"
}

resolve_canonical_tokens_file() {
  local requested="${TOKENS_FILE:-}"
  [[ -n "$requested" ]] || die "NEOCORTEX_DEV_TOKENS_FILE must be the repository-root dev_tokens.json"
  local candidate="$requested"
  if [[ "$candidate" != /* ]]; then
    candidate="$ROOT/$candidate"
  fi
  local parent
  parent="$(cd -- "$(dirname -- "$candidate")" 2>/dev/null && pwd -P)" \
    || die "NEOCORTEX_DEV_TOKENS_FILE parent cannot be resolved"
  candidate="$parent/$(basename -- "$candidate")"
  [[ "$candidate" == "$ROOT/dev_tokens.json" ]] \
    || die "NEOCORTEX_DEV_TOKENS_FILE must resolve to the repository-root dev_tokens.json"
  [[ ! -L "$candidate" ]] || die "NEOCORTEX_DEV_TOKENS_FILE must not be a symlink"
  TOKENS_FILE="$candidate"
}

quarantine_canonical_metrics() {
  local canonical="$ROOT/docs/plans/33-local-qwen-migration/resources/metrics-${ARM}.json"
  [[ ! -e "$canonical" ]] && return 0
  [[ -f "$canonical" && ! -L "$canonical" ]] \
    || die "canonical metrics path is not a regular file; refusing to quarantine it"
  local stale="$canonical.stale"
  if [[ -e "$stale" ]]; then
    stale="$canonical.stale-${RUN_ID}-$$"
  fi
  [[ ! -e "$stale" ]] || die "stale metrics diagnostic path already exists; refusing to overwrite it"
  mv -- "$canonical" "$stale" \
    || die "failed to quarantine the previous canonical metrics artifact"
  printf 'quarantined stale canonical metrics arm=%s diagnostic=%s\n' "$ARM" "${stale#"$ROOT/"}"
}

RESTORE_FAILURE_STATUS=3
cleanup_e2e_workdir() {
  if [[ -n "$E2E_WORKDIR" && -d "$E2E_WORKDIR" ]]; then
    rm -rf "$E2E_WORKDIR"
  fi
}
restore_preserved_snapshot() {
  local exit_code=$?
  if [[ -n "$PRE_SNAPSHOT" && "$DRY_RUN" -eq 0 ]]; then
    local snapshot_load_name="$PRE_SNAPSHOT"
    if [[ -n "$PRE_SNAPSHOT_FILE" ]]; then
      snapshot_load_name="${PRE_SNAPSHOT_FILE##*/}"
      snapshot_load_name="${snapshot_load_name%.tar.gz}"
    fi
    if ! "$ROOT/scripts/manage.sh" snapshot load "$snapshot_load_name" >/dev/null 2>&1; then
      local restore_status="$RESTORE_FAILURE_STATUS"
      # Keep the restoration outcome distinguishable even if the command that
      # triggered EXIT happened to return the reserved status already.
      (( exit_code == restore_status )) && restore_status=4
      echo "model bake-off: failed to restore preserved snapshot $PRE_SNAPSHOT" >&2
      echo "model bake-off: restoration failure status=$restore_status (original status=$exit_code)" >&2
      cleanup_e2e_workdir
      exit "$restore_status"
    fi
  fi
  cleanup_e2e_workdir
  exit "$exit_code"
}
trap restore_preserved_snapshot EXIT

if (( DRY_RUN )); then
  print_configuration
else
  resolve_canonical_tokens_file
  [[ -n "${NEOCORTEX_ADMIN_TOKEN:-}" ]] || die "NEOCORTEX_ADMIN_TOKEN is required (value is never logged)"
  [[ "$NEOCORTEX_ADMIN_TOKEN" == "admin-token" ]] \
    || die "NEOCORTEX_ADMIN_TOKEN must be the configured admin-token identity"
  [[ -f "$TOKENS_FILE" ]] || die "dev-token file does not exist: $TOKENS_FILE"
  command -v jq >/dev/null 2>&1 || die "jq is required to validate the dev-token map"
  # Feed the credential through stdin.  Passing it via jq --arg would expose
  # it in argv to process observers.
  jq -e --rawfile token /dev/stdin 'type == "object" and has(($token | rtrimstr("\n")))' "$TOKENS_FILE" \
    <<<"$NEOCORTEX_ADMIN_TOKEN" >/dev/null \
    || die "NEOCORTEX_ADMIN_TOKEN is not present in NEOCORTEX_DEV_TOKENS_FILE"
  [[ -n "${GOOGLE_API_KEY:-}" ]] || die "GOOGLE_API_KEY is required for embedding health; recall metrics are NOT MEASURED"
  E2E_WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/neocortex-bakeoff.XXXXXX")"
  E2E_STATUS_PATH="$E2E_WORKDIR/status.tsv"
  E2E_MANIFEST_PATH="$ROOT/docs/plans/33-local-qwen-migration/resources/e2e-manifest-${ARM}-${RUN_ID}.json"
  RECALL_EVIDENCE_PATH="$ROOT/docs/plans/33-local-qwen-migration/resources/recall-results-${ARM}-${RUN_ID}.json"
  export NEOCORTEX_SNAPSHOT_PATH_FILE="$E2E_WORKDIR/snapshot-path"
  quarantine_canonical_metrics
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
  PRE_SNAPSHOT_FILE="$(resolve_saved_snapshot "$PRE_SNAPSHOT_NAME")"
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
run poll_jobs
POST_SNAPSHOT_NAME="${ARM}-${RUN_ID}"
run "$ROOT/scripts/manage.sh" snapshot save "$POST_SNAPSHOT_NAME"
if (( DRY_RUN )); then
  POST_SNAPSHOT="$ROOT/backups/${POST_SNAPSHOT_NAME}-DRY-RUN.tar.gz"
else
  POST_SNAPSHOT="$(resolve_saved_snapshot "$POST_SNAPSHOT_NAME")"
  POST_SNAPSHOT_SHA256="$(sha256_file "$POST_SNAPSHOT")"
fi
run uv run python "$ROOT/scripts/compute_metrics.py" --arm "$ARM" --phase corpus --snapshot-path "$POST_SNAPSHOT" --snapshot-sha256 "$POST_SNAPSHOT_SHA256" --run-id "$RUN_ID"
if (( DRY_RUN )); then
  run uv run python "$ROOT/scripts/recall_scorer.py" --output "docs/plans/33-local-qwen-migration/resources/recall-results-${ARM}-${RUN_ID}.json"
  index=0
  for test in e2e_extraction_pipeline_test.py e2e_plan15_scenarios_test.py e2e_plan17_validation.py e2e_episodic_memory_test.py e2e_cognitive_recall_test.py; do
    index=$((index + 1))
    run_e2e_with_test_tokens "$index" "$test"
  done
  run uv run python "$ROOT/scripts/e2e_manifest.py" build --arm "$ARM" --run-id "$RUN_ID"
  run uv run python "$ROOT/scripts/e2e_manifest.py" merge --run-id "$RUN_ID"
else
RECALL_STATUS=0
if uv run python "$ROOT/scripts/recall_scorer.py" --output "$RECALL_EVIDENCE_PATH" \
  >"$E2E_WORKDIR/recall.stdout" 2>"$E2E_WORKDIR/recall.stderr"; then
  RECALL_STATUS=0
else
  RECALL_STATUS=$?
  uv run python "$ROOT/scripts/e2e_manifest.py" write-not-measured-recall \
    --path "$RECALL_EVIDENCE_PATH" --run-id "$RUN_ID" --reason "recall_scorer_exit_${RECALL_STATUS}"
fi
rm -f "$E2E_WORKDIR/recall.stdout" "$E2E_WORKDIR/recall.stderr"
if (( RECALL_STATUS != 0 )); then
  printf 'recall completed run_id=%s status=NOT_MEASURED exit_code=%s\n' "$RUN_ID" "$RECALL_STATUS"
else
  printf 'recall completed run_id=%s status=MEASURED exit_code=0\n' "$RUN_ID"
fi
E2E_FAILURE_STATUS=0
index=0
for test in e2e_extraction_pipeline_test.py e2e_plan15_scenarios_test.py e2e_plan17_validation.py e2e_episodic_memory_test.py e2e_cognitive_recall_test.py; do
  index=$((index + 1))
  if run_e2e_with_test_tokens "$index" "$test"; then
    :
  else
    e2e_status=$?
    if (( E2E_FAILURE_STATUS == 0 )); then
      E2E_FAILURE_STATUS="$e2e_status"
    fi
    printf 'e2e failure recorded index=%s exit_code=%s\n' "$index" "$e2e_status"
  fi
done
run uv run python "$ROOT/scripts/e2e_manifest.py" build \
  --arm "$ARM" --run-id "$RUN_ID" \
  --metrics-path "$ROOT/docs/plans/33-local-qwen-migration/resources/metrics-${ARM}.json" \
  --snapshot-path "$POST_SNAPSHOT" --snapshot-sha256 "$POST_SNAPSHOT_SHA256" \
  --recall-path "$RECALL_EVIDENCE_PATH" --statuses-path "$E2E_STATUS_PATH" --output-path "$E2E_MANIFEST_PATH"
run uv run python "$ROOT/scripts/e2e_manifest.py" merge \
  --manifest-path "$E2E_MANIFEST_PATH" \
  --metrics-path "$ROOT/docs/plans/33-local-qwen-migration/resources/metrics-${ARM}.json" \
  --run-id "$RUN_ID" --snapshot-path "$POST_SNAPSHOT" --snapshot-sha256 "$POST_SNAPSHOT_SHA256"
if (( E2E_FAILURE_STATUS != 0 )); then
  exit "$E2E_FAILURE_STATUS"
fi
if (( RECALL_STATUS != 0 )); then
  exit "$RECALL_STATUS"
fi
fi
