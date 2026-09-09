# Flash Next execution commands

These commands are for the active local target. Never print or commit the value of the configured
credential. The key is read from the environment supplied by the supervisor.

## Preflight

```bash
export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://127.0.0.1:24000/v1
export NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json
export NEOCORTEX_ADMIN_TOKEN=admin-token
export NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY
test -n "${LITELLM_API_KEY:-}" || { echo 'LITELLM_API_KEY is required' >&2; exit 1; }
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
  "$NEOCORTEX_LOCAL_MODEL_BASE_URL/models" \
  -H @- <<<"Authorization: Bearer ${LITELLM_API_KEY}" \
  | jq -e '[.data[].id] | length == 1 and .[0] == "qwen3.8-flash-next"'
```

Use the same header for `/chat/completions`. Do not put the header or key into a saved command log.

## Active local configuration

```bash
export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://127.0.0.1:24000/v1
export NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY
export NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json
export NEOCORTEX_ADMIN_TOKEN=admin-token
export NEOCORTEX_ONTOLOGY_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTOR_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=local:qwen3.8-flash-next
export NEOCORTEX_EXTRACTION_ENABLED=true
export NEOCORTEX_DOMAIN_ROUTING_ENABLED=true
export NEOCORTEX_ONTOLOGY_THINKING_EFFORT=low
export NEOCORTEX_EXTRACTOR_THINKING_EFFORT=low
export NEOCORTEX_LIBRARIAN_THINKING_EFFORT=low
export NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT=low
export NEOCORTEX_WORKER_CONCURRENCY=2
export NEOCORTEX_LOCAL_MODEL_TIMEOUT_S=600
export NEOCORTEX_BAKEOFF_CORPUS_PROFILE=compact
```

The initial compact arm retains low effort for all four reasoning roles and concurrency 2.
Later effort changes require the measured sweep. `OPENAI_API_KEY` is needed only for an optional hosted baseline;
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
uv run python scripts/corpus_loader.py --corpus-profile compact --dry-run
./scripts/model_bakeoff.sh --arm qwen-flash-next-compact --corpus-profile compact --dry-run
export NEOCORTEX_BAKEOFF_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-compact"
./scripts/model_bakeoff.sh --arm qwen-flash-next-compact --corpus-profile compact
```

Generate a new run ID for every real arm. Do not reuse the old unstarted full-profile run ID.
The active input is [compact revision 1](compact-corpus-design.md); the harness defaults to
`full` outside these explicit commands. Quality reports use `metrics-qwen-flash-next-compact.json`
and `qwen-parsing-report-compact.schema.json`.

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
