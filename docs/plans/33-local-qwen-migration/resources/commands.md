# Flash Next execution commands

These commands are for the active local target. Never print or commit the value of `VLLM_API_KEY`.
The key is read from the environment supplied by the supervisor.

## Preflight

```bash
export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://127.0.0.1:24000/v1
test -n "${VLLM_API_KEY:-}" || { echo 'VLLM_API_KEY is required' >&2; exit 1; }
curl --fail --silent --show-error \
  "$NEOCORTEX_LOCAL_MODEL_BASE_URL/models" \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  | jq -e '[.data[].id] | length == 1 and .[0] == "qwen3.8-flash-next"'
```

Use the same header for `/chat/completions`. Do not put the header or key into a saved command log.

## Active local configuration

```bash
export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://127.0.0.1:24000/v1
export NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=VLLM_API_KEY
export NEOCORTEX_ONTOLOGY_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTOR_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=local:qwen3.8-flash-next
```

Set each `*_THINKING_EFFORT` from the measured probe or effort sweep. Keep worker concurrency
conservative for the local service. `OPENAI_API_KEY` is needed only for an optional hosted baseline;
`GOOGLE_API_KEY` is needed for embeddings even when the reasoning model is local.

## Services and snapshots

```bash
./scripts/manage.sh start
./scripts/manage.sh status
./scripts/manage.sh stop
./scripts/manage.sh snapshot save qwen-flash-next
./scripts/manage.sh snapshot list
./scripts/manage.sh snapshot load qwen-flash-next
```

Use `start --fresh` only with an explicit disposable environment. Snapshot the graph before a fresh
run. The local arm must not merge into a populated output directory.

## Probe and bake-off

```bash
uv run python scripts/corpus_loader.py --dry-run
uv run python scripts/probe_local_model.py --model local:qwen3.8-flash-next --effort medium --timeout 300
uv run python scripts/compute_metrics.py --arm qwen-flash-next
./scripts/model_bakeoff.sh --arm qwen-flash-next
./scripts/model_bakeoff.sh --dry-run
```

The harness must emit raw JSON with model id, effort, commit, input corpus, job ids, and source paths.
Scenario scripts that always exit zero require score-line parsing. A non-terminal job is not a quality
result.

## Monitoring and audit

```bash
curl --fail --silent localhost:8001/admin/jobs/summary \
  -H "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}" \
  | jq .
curl --fail --silent 'localhost:8001/admin/jobs?status=failed&all_agents=true&limit=1000' \
  -H "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}" \
  | jq .
```

Read `log/agent_actions.log` for model calls, tool calls, timing, token use, and rejection events.
Redact authorization headers before sharing evidence.

## Optional hosted comparison

Run only when an isolated hosted environment and `OPENAI_API_KEY` are available. Use the same corpus,
prompts, schema, concurrency, timeout, and instrumentation. Two complete runs are required before a
noise band can support a baseline-relative statement. If they cannot complete, record `NOT MEASURED`
and continue the local decision.

## Rollback

Use [rollback.md](rollback.md). It restores hosted model strings and the named baseline snapshot when
that snapshot exists. Rollback changes configuration and graph state; it does not require a code revert.
