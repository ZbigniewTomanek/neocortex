# Commands

## Environment

```bash
# Local endpoint (never commit the key — .env is gitignored, keep it that way)
export VLLM_API_KEY=$(grep -E '^VLLM_API_KEY=' ~/projects/my-telegram-bot/.env | cut -d= -f2-)
export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://z-spark.tail215ba1.ts.net:4000/v1

# Required regardless of arm — embeddings stay on Gemini and fail SILENTLY without this
export GOOGLE_API_KEY=...     # embedding_service.py returns None, recall degrades to text-only
export OPENAI_API_KEY=...     # needed for the hosted baseline arm
```

## Arm configuration

**Baseline arm** (Stage 5) — the status quo, unchanged:

```bash
NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_ONTOLOGY_THINKING_EFFORT=medium
NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_EXTRACTOR_THINKING_EFFORT=low
NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_LIBRARIAN_THINKING_EFFORT=low
NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT=medium
```

**Qwen arm** (Stage 6) — identical effort levels, one variable changed:

```bash
NEOCORTEX_ONTOLOGY_MODEL=local:qwen3.8-27b
NEOCORTEX_ONTOLOGY_THINKING_EFFORT=medium
NEOCORTEX_EXTRACTOR_MODEL=local:qwen3.8-27b
NEOCORTEX_EXTRACTOR_THINKING_EFFORT=low
NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-27b
NEOCORTEX_LIBRARIAN_THINKING_EFFORT=low
NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=local:qwen3.8-27b
NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT=medium
NEOCORTEX_WORKER_CONCURRENCY=2          # SGLang caps at max_running_requests=8
```

## Services

```bash
./scripts/manage.sh start --fresh        # wipe + recreate — the correct isolation between arms
./scripts/manage.sh start                # persist-by-default
./scripts/manage.sh status
./scripts/manage.sh stop                 # app only; PG keeps running
./scripts/manage.sh stop --all

./scripts/manage.sh snapshot save <name>
./scripts/manage.sh snapshot list
./scripts/manage.sh snapshot load <name>
```

## E2E gates

```bash
./scripts/run_e2e.sh scripts/e2e_extraction_pipeline_test.py    # Tier 1 binary smoke
./scripts/run_e2e.sh scripts/e2e_plan15_scenarios_test.py       # ≥11/14
./scripts/run_e2e.sh scripts/e2e_plan17_validation.py           # ≥13/14
./scripts/run_e2e.sh scripts/e2e_episodic_memory_test.py
./scripts/run_e2e.sh scripts/e2e_cognitive_recall_test.py

KEEP_RUNNING=1 ./scripts/run_e2e.sh scripts/<t>.py   # leave services up for post-hoc SQL
MAX_WAIT=120 ./scripts/run_e2e.sh scripts/<t>.py
```

`run_e2e.sh` forces `NEOCORTEX_DEV_TOKENS_FILE=dev_tokens_test.json` (alice/bob/eve) and does
`manage.sh start --fresh` in local mode — **it wipes the DB**. One test script per invocation, so
the five gates cannot share a graph; the Stage 4 orchestrator is what runs them against one arm.

## Job monitoring

```bash
curl localhost:8001/admin/jobs/summary -H "Authorization: Bearer admin-token"
# {"todo":2,"doing":1,"succeeded":15,"failed":0,"cancelled":0,"total":18}

curl "localhost:8001/admin/jobs?status=failed&all_agents=true&limit=1000" \
     -H "Authorization: Bearer admin-token"
curl localhost:8001/admin/jobs/42 -H "Authorization: Bearer admin-token"   # + event timeline
```

`JobInfo` carries `created_at` / `started_at` / `finished_at` / `attempts`, derived from
`procrastinate_events` — this is the Tier 3 latency source.

TUI: `uv run python -m neocortex.tui --token tui-dev`, then `j` for the job monitor.

## Metrics

```bash
uv run python scripts/corpus_loader.py --dry-run           # must parse exactly 28 episodes
uv run python scripts/compute_metrics.py --arm <name>
uv run python scripts/recall_scorer.py                     # M1–M4
./scripts/model_bakeoff.sh --arm <name>                    # full arm, unattended
./scripts/model_bakeoff.sh --dry-run
```

Ontology metrics SQL is **reused verbatim** from
`docs/plans/29-ontology-validation/resources/queries.md:29-71` ("Plan 28 Success Metrics —
All-in-One"). Do not retype it — the point is comparability with the numbers already recorded there.

## Probes

```bash
uv run python scripts/probe_local_model.py --effort medium
uv run python scripts/probe_local_model.py --effort xhigh --model local:qwen3.8-27b
```

## Tests

```bash
uv run pytest tests/ -v                    # ~832+ tests, mock DB, no Docker
uv run pytest tests/test_local_provider_routing.py -v
NEOCORTEX_MOCK_DB=true uv run python -m neocortex
```

There are no pytest markers registered, so "run only the tests that hit a real model" is not
expressible — the real-model surface is the standalone `scripts/e2e_*.py` files.

## Pre-flight assertions (skipping either silently corrupts an arm)

```bash
# 1. Embeddings live? embedding_service.py returns None without GOOGLE_API_KEY — no error raised.
uv run python -c "
import asyncio
from neocortex.embedding_service import EmbeddingService
from neocortex.mcp_settings import MCPSettings
e = EmbeddingService(MCPSettings())
v = asyncio.run(e.embed('probe'))
assert v is not None and len(v) == 768, 'EMBEDDINGS DEAD — arm would be invalid'
print('embeddings OK', len(v))
"

# 2. Seed schemas provisioned? Omitting this silently zeroes domain routing —
#    it is how Plan 18.5's M5 scored 0/28. See .claude/skills/neocortex/KNOWN_ISSUES.md.
curl localhost:8001/admin/graphs -H "Authorization: Bearer admin-token"
```

## Rollback

Config-only — no code revert needed. Restore the four hosted model strings and their pre-migration
effort levels (ontology `medium`, extractor `low`, librarian `low`, classifier `medium`), then:

```bash
./scripts/manage.sh snapshot load baseline-gpt54mini
```
