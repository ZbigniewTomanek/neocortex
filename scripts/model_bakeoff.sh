#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARM=""
DRY_RUN=0
POLL_TIMEOUT="${BAKEOFF_POLL_TIMEOUT:-14400}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --arm) ARM="$2"; shift 2 ;;
    --poll-timeout) POLL_TIMEOUT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$ARM" ]] || ARM="${NEOCORTEX_BAKEOFF_ARM:-unnamed}"

run() { printf '+ '; printf '%q ' "$@"; printf '\n'; (( DRY_RUN )) || "$@"; }
run_shell() { printf '+ %s\n' "$1"; (( DRY_RUN )) || bash -c "$1"; }

run "$ROOT/scripts/manage.sh" start --fresh
if (( ! DRY_RUN )); then
  uv run python -c 'import asyncio; from neocortex.embedding_service import EmbeddingService; from neocortex.mcp_settings import MCPSettings; v=asyncio.run(EmbeddingService(model=MCPSettings().embedding_model).embed("bakeoff probe")); assert v is not None and len(v)==768, "EMBEDDINGS DEAD"; print("embeddings OK")'
  curl --fail --silent --show-error "http://127.0.0.1:8001/admin/graphs" -H "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN:-admin-token-neocortex}" | grep -q 'ncx_shared__' || { echo 'seed schemas missing' >&2; exit 1; }
fi
run uv run python "$ROOT/scripts/corpus_loader.py"
run_shell "deadline=\$(date +%s)+${POLL_TIMEOUT}; while :; do state=\$(curl --fail --silent http://127.0.0.1:8001/admin/jobs/summary -H 'Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN:-admin-token-neocortex}'); todo=\$(printf '%s' \"\$state\" | uv run python -c 'import json,sys; x=json.load(sys.stdin); print(x.get(\"todo\",0)+x.get(\"doing\",0))'); echo \"jobs outstanding: \$todo\"; [[ \"\$todo\" == 0 ]] && break; (( \$(date +%s) >= deadline )) && { echo 'job poll timed out; metrics not written' >&2; exit 1; }; sleep 5; done"
run uv run python "$ROOT/scripts/compute_metrics.py" --arm "$ARM" --phase corpus
run uv run python "$ROOT/scripts/recall_scorer.py"
run "$ROOT/scripts/manage.sh" snapshot save "$ARM"
for test in e2e_extraction_pipeline_test.py e2e_plan15_scenarios_test.py e2e_plan17_validation.py e2e_episodic_memory_test.py e2e_cognitive_recall_test.py; do
  run "$ROOT/scripts/run_e2e.sh" "$ROOT/scripts/$test"
done
run uv run python "$ROOT/scripts/compute_metrics.py" --arm "$ARM" --phase e2e --merge
