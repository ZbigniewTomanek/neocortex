# Commands and budgets

Never print, log, or commit the value of `LITELLM_API_KEY`. Run each live command in the orchestrator's
managed asynchronous session. A plain foreground shell is not a managed session. Live commands write
incremental output under `.tmp/plan34/` (gitignored).

## Preflight (before any live stage)

```bash
export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://127.0.0.1:24000/v1
export NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY
test -n "${LITELLM_API_KEY:-}" || { echo 'LITELLM_API_KEY is required' >&2; exit 1; }
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
  "$NEOCORTEX_LOCAL_MODEL_BASE_URL/models" \
  -H @- <<<"Authorization: Bearer ${LITELLM_API_KEY}" \
  | jq -e '[.data[].id] | length == 1 and .[0] == "qwen3.8-flash-next"'
uv run python -c "from neocortex.mcp_settings import MCPSettings; MCPSettings(); print('settings ok')"
mkdir -p .tmp/plan34/sweep .tmp/plan34/cache
```

If the settings one-liner fails on `extraction_enabled`, the local `.env` has a trailing backslash on
`NEOCORTEX_EXTRACTION_ENABLED` (Plan 33 backlog B1). Fix the untracked `.env`. Do not commit it.

## Effort sweep (Stage 6)

Use the finalized identity and the original `off` baseline. Do not run either measurement again.
Use the same live cache directory for all cells.

```bash
IDENTITY=docs/plans/34-qwen-thinking-benchmark/resources/effort-levels.json
BASELINE=docs/plans/34-qwen-thinking-benchmark/resources/sweep/off.json
SWEEP=docs/plans/34-qwen-thinking-benchmark/resources/sweep
MOCK=.tmp/plan34/stage6-test
mkdir -p "$MOCK/cache" "$MOCK/sweep"

env -u GOOGLE_API_KEY -u GEMINI_API_KEY uv run python scripts/effort_level_probe.py \
  --test-model --output "$MOCK/effort-levels.json"
env -u GOOGLE_API_KEY -u GEMINI_API_KEY uv run python scripts/qwen_speed_probe.py \
  --test-model --corpus both \
  --fixture docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json \
  --thinking off --per-call-timeout 300 --episode-timeout 600 --max-wall-seconds 1200 \
  --cache-dir "$MOCK/cache" --output "$MOCK/off.json"
env -u GOOGLE_API_KEY -u GEMINI_API_KEY \
  uv run python docs/plans/34-qwen-thinking-benchmark/validation/effort_sweep_runner.py \
  --test-model --output-dir "$MOCK/sweep" \
  --identity-json "$MOCK/effort-levels.json" --baseline-json "$MOCK/off.json" \
  --cache-dir "$MOCK/cache" --max-wall-seconds 14400

env -u GOOGLE_API_KEY -u GEMINI_API_KEY \
  uv run python docs/plans/34-qwen-thinking-benchmark/validation/effort_sweep_runner.py \
  --output-dir "$SWEEP" \
  --identity-json "$IDENTITY" --baseline-json "$BASELINE" \
  --cache-dir .tmp/plan34/cache \
  --max-wall-seconds 14400 \
  > .tmp/plan34/stage6-runner.log 2>&1
```

Poll `resources/effort-sweep.json` and the managed session at intervals of five minutes or more. Do not
restart the runner only because a quality score is low. A rerun requires a recorded root-cause change.

Level to setting mapping: `off` → `false` (boolean), `low`/`medium`/`high` → the same string. There is
no `none` literal in `ThinkingLevel`. `qwen_speed_probe.py --thinking off` performs the mapping.

## Tuned compact arm (Stage 7)

```bash
ARM=qwen-flash-next-compact-tuned
SWEEP=docs/plans/34-qwen-thinking-benchmark/resources/effort-sweep.json
test -n "${NEOCORTEX_ADMIN_TOKEN:-}" || { echo 'NEOCORTEX_ADMIN_TOKEN is required' >&2; exit 1; }
test -n "${GOOGLE_API_KEY:-}" || { echo 'GOOGLE_API_KEY is required' >&2; exit 1; }
jq -e '.run.complete == true and
  ([.selections.ontology, .selections.extractor, .selections.librarian, .selections.classifier]
   | all(.status == "SELECTED" and (.level | IN("off", "low", "medium", "high"))))' "$SWEEP" >/dev/null
L_ONT="$(jq -r '.selections.ontology.level' "$SWEEP")"
L_EXT="$(jq -r '.selections.extractor.level' "$SWEEP")"
L_LIB="$(jq -r '.selections.librarian.level' "$SWEEP")"
L_CLS="$(jq -r '.selections.classifier.level' "$SWEEP")"
level_setting() { case "$1" in off) printf 'false\n' ;; low|medium|high) printf '%s\n' "$1" ;; *) return 2 ;; esac; }

unset DOCKER_HOST
export DOCKER_CONTEXT=desktop-linux
export NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json
export NEOCORTEX_ONTOLOGY_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTOR_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTION_ENABLED=true
export NEOCORTEX_DOMAIN_ROUTING_ENABLED=true
export NEOCORTEX_ONTOLOGY_THINKING_EFFORT="$(level_setting "$L_ONT")"
export NEOCORTEX_EXTRACTOR_THINKING_EFFORT="$(level_setting "$L_EXT")"
export NEOCORTEX_LIBRARIAN_THINKING_EFFORT="$(level_setting "$L_LIB")"
export NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT="$(level_setting "$L_CLS")"
export NEOCORTEX_WORKER_CONCURRENCY=2
export NEOCORTEX_LOCAL_MODEL_TIMEOUT_S=300
export NEOCORTEX_BAKEOFF_CORPUS_PROFILE=compact
RUN="$(date -u +%Y%m%dT%H%M%SZ)-tuned1"
export NEOCORTEX_BAKEOFF_RUN_ID="$RUN"
STATUS=".tmp/plan34/stage7-${RUN}-supervisor.json"
LOG=".tmp/plan34/stage7-${RUN}.log"

./scripts/model_bakeoff.sh --arm "$ARM" --corpus-profile compact --dry-run
uv run python docs/plans/34-qwen-thinking-benchmark/validation/stage7_arm_supervisor.py \
  --status "$STATUS" --run-id "$RUN" --arm "$ARM" \
  --workload-seconds 6600 --total-seconds 7200 -- \
  ./scripts/model_bakeoff.sh --arm "$ARM" --corpus-profile compact \
  > "$LOG" 2>&1
```

Run the supervisor command in a managed asynchronous session. The explicit `DOCKER_CONTEXT` does not
change the global Docker configuration. Poll the status file and job summary at intervals of five
minutes or more.

The harness saves the existing graph before the fresh reset. It restores that snapshot when the arm
exits. The harness exports skip events and the graph sample before the first E2E child resets services.
It merges consistency metrics before the manifest digest. It generates the report after the final
manifest and recall evidence exist.

```bash
jq '{status,run_id,arm,timed_out,workload_wall_seconds,total_wall_seconds,cleanup_reserve_exceeded}' "$STATUS"
```

## Live budgets

| Stage | Budget | On overrun |
|-------|--------|-----------|
| 4 | 20 min | write partial `off.json`, mark rest `TIMEOUT`, continue |
| 5 | 20 min | mark remaining requests `NOT MEASURED`, continue |
| 6 | 4 h total | stop launching cells, select among measured, continue |
| 7 | 2 h per arm, ≤ 2 arms | record last summary, arm is `NOT MEASURED`, continue to Stage 8 with `HOLD` |

## Reference commands

```bash
uv run pytest tests/ -q                 # full regression suite (no Docker)
uv run ruff check .                     # lint
./scripts/manage.sh status              # services
./scripts/manage.sh snapshot list       # graph snapshots
```
