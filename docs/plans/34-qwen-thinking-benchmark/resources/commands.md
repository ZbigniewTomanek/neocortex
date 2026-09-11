# Commands and budgets

Never print, log, or commit the value of `LITELLM_API_KEY`. Every live command below runs detached and
writes incremental output under `.tmp/plan34/` (gitignored). Finished evidence is copied into this
plan's `resources/` or Plan 33's `resources/`.

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
`NEOCORTEX_EXTRACTION_ENABLED` (Plan 33 backlog B1). Fix the untracked `.env`; do not commit it.

## Probe pattern (Stages 4–6)

Always the same command with `--test-model` first. `--max-wall-seconds` below is the Stage 6 per-cell
value; Stage 4's `off` baseline uses `1200` to stay inside its 20-minute budget. Then:

```bash
nohup uv run python scripts/qwen_speed_probe.py \
  --corpus both \
  --fixture docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json \
  --thinking off --thinking-extractor "${LEVEL}" \
  --per-call-timeout 300 --episode-timeout 600 --max-wall-seconds 3600 \
  --cache-dir .tmp/plan34/cache \
  --output ".tmp/plan34/sweep/extractor-${LEVEL}.json" \
  > ".tmp/plan34/sweep/extractor-${LEVEL}.log" 2>&1 &
echo $! > ".tmp/plan34/sweep/extractor-${LEVEL}.pid"
```

Poll: `jq '.episodes | length' .tmp/plan34/sweep/extractor-${LEVEL}.json` at intervals of five minutes
or more. When the PID exits, copy the JSON to `docs/plans/34-qwen-thinking-benchmark/resources/sweep/`.

Level to setting mapping: `off` → `false` (boolean), `low`/`medium`/`high` → the same string. There is
no `none` literal in `ThinkingLevel`; `qwen_speed_probe.py --thinking off` performs the mapping.

## Identity probe (Stage 5)

```bash
uv run python scripts/effort_level_probe.py --test-model
nohup uv run python scripts/effort_level_probe.py --levels off,low,medium,high --repeats 3 \
  --per-call-timeout 300 --max-wall-seconds 1200 \
  --output docs/plans/34-qwen-thinking-benchmark/resources/effort-levels.json \
  > .tmp/plan34/effort-levels.log 2>&1 &
```

## Tuned compact arm (Stage 7)

```bash
export NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json
export NEOCORTEX_ADMIN_TOKEN=admin-token
export NEOCORTEX_ONTOLOGY_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTOR_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTION_ENABLED=true
export NEOCORTEX_DOMAIN_ROUTING_ENABLED=true
# Selected levels from resources/effort-sweep.json; "off" is the boolean false.
export NEOCORTEX_ONTOLOGY_THINKING_EFFORT="${L_ONT}"
export NEOCORTEX_EXTRACTOR_THINKING_EFFORT="${L_EXT}"
export NEOCORTEX_LIBRARIAN_THINKING_EFFORT="${L_LIB}"
export NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT="${L_CLS}"
export NEOCORTEX_WORKER_CONCURRENCY=2
export NEOCORTEX_LOCAL_MODEL_TIMEOUT_S=300
export NEOCORTEX_BAKEOFF_CORPUS_PROFILE=compact
export NEOCORTEX_BAKEOFF_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-tuned1"
./scripts/manage.sh snapshot save pre-plan34-tuned1
./scripts/model_bakeoff.sh --arm qwen-flash-next-compact-tuned --corpus-profile compact --dry-run
nohup ./scripts/model_bakeoff.sh --arm qwen-flash-next-compact-tuned --corpus-profile compact \
  > .tmp/plan34/arm-tuned1.log 2>&1 &
```

Poll `curl -s -H "Authorization: Bearer $NEOCORTEX_ADMIN_TOKEN" http://127.0.0.1:8001/admin/jobs/summary`
at intervals of five minutes or more. `GOOGLE_API_KEY` is still needed for embeddings.

After the arm:

```bash
RUN="$NEOCORTEX_BAKEOFF_RUN_ID"; ARM=qwen-flash-next-compact-tuned
OUT=docs/plans/33-local-qwen-migration/resources
uv run python scripts/export_skip_events.py --run-id "$RUN" --arm "$ARM" --output "$OUT/skip-events-$ARM-$RUN.json"
uv run python scripts/export_graph_sample.py --run-id "$RUN" --arm "$ARM" --check-temporal "$OUT/skip-events-$ARM-$RUN.json" --sample 20 --output "$OUT/quality-sample-$ARM-$RUN.json"
uv run python scripts/compute_metrics.py --arm "$ARM" --phase e2e --run-id "$RUN" --skip-events "$OUT/skip-events-$ARM-$RUN.json" --merge
uv run python scripts/generate_qwen_parsing_report.py generate \
  --plan-dir docs/plans/33-local-qwen-migration --output-dir "$OUT" --run-id "$RUN" --arm "$ARM"
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
