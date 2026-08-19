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

**Baseline arm** (Stage 5) — the status quo models, run **twice** for variance (D12):

```bash
NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_ONTOLOGY_THINKING_EFFORT=medium
NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_EXTRACTOR_THINKING_EFFORT=low
NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_LIBRARIAN_THINKING_EFFORT=low
NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT=medium
NEOCORTEX_WORKER_CONCURRENCY=2          # D11 — must match the Qwen arm, not the default 4
```

**Qwen arm** (Stage 6) — identical effort levels and concurrency, model strings the only change:

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

**Isolation arms** (Stage 6b, only if the joint arm missed a Tier 2 metric) — one agent local, the
other three hosted, everything else identical. E.g. librarian-only:

```bash
NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-27b
NEOCORTEX_LIBRARIAN_THINKING_EFFORT=low
NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_ONTOLOGY_THINKING_EFFORT=medium
NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_EXTRACTOR_THINKING_EFFORT=low
NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini
NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT=medium
NEOCORTEX_WORKER_CONCURRENCY=2
```

All of these env names resolve through `env_prefix = "NEOCORTEX_"` on `MCPSettings`; there are no
aliases, so the field name is the variable name.

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

`run_e2e.sh` defaults `NEOCORTEX_DEV_TOKENS_FILE=dev_tokens_test.json` (alice/bob/eve, local mode only)
and does `manage.sh start --fresh` at line 122 — **it wipes the DB** (`docker compose down -v`). One
test script per invocation (enforced at line 90), so the five gates cannot share a graph.
`MAX_WAIT` defaults to **60**.

**Consequence for the Stage 4 orchestrator**: compute and snapshot every graph-derived metric against
the 28-episode corpus **before** the first e2e script runs. The five scripts each build their own
graph; their only contribution is a score line. Running `compute_metrics.py` after them would measure
whatever the last script left behind.

Two of the five are **not** exit-code gated — `e2e_plan15_scenarios_test.py` and
`e2e_plan17_validation.py` wrap every scenario in `try/except` and never call `sys.exit`, so they exit 0
at any score. Parse their printed `Acceptable (PASS only): X/14` line. The other three
(`e2e_extraction_pipeline_test.py`, `e2e_episodic_memory_test.py`, `e2e_cognitive_recall_test.py`) fail
via uncaught `assert` and are genuinely exit-code gated.

To bring the stack up **without** wiping — which is what the Stage 2 probes need — use
`./scripts/manage.sh start` (persist-by-default), not `run_e2e.sh`.

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

# Harness self-check (Stage 4): restore the Plan 29-era graph first, or the numbers cannot match.
./scripts/manage.sh snapshot save pre-plan33-current        # keep the live graph
./scripts/manage.sh snapshot load pre-plan30-20260407-201234
uv run python scripts/compute_metrics.py --arm plan29-replay
```

Ontology metrics SQL is reused from
`docs/plans/29-ontology-validation/resources/queries.md:29-71` ("Plan 28 Success Metrics —
All-in-One") for comparability with the numbers already recorded there. Three things to know before
relying on it:

- it returns **5** columns, not the 6 its own header claims — **no instance-level types** (Plan 29
  computed that one by human review; Stage 4 step 3b defines an automatable rule instead);
- `{schema}` is a textual placeholder — substitute per schema, there is no bound parameter;
- its `garbage_types` regex is a frozen pre-Qwen copy of `_TOOL_CALL_ARTIFACT`. Interpolate
  `_TOOL_CALL_ARTIFACT.pattern` from `neocortex.normalization` instead, or the metric is blind to the
  shapes Stage 3 step 6 adds.

## Probes

```bash
uv run python scripts/probe_local_model.py --effort medium
uv run python scripts/probe_local_model.py --effort xhigh --model local:qwen3.8-27b
```

## Tests

```bash
uv run pytest tests/ -v                    # 916 tests collected (2026-08-19), mock DB, no Docker
uv run pytest tests/test_local_provider_routing.py -v
uv run pytest tests/mcp/test_fuzzy_dedup.py -v   # holds the 3 real librarian prompt assertions
NEOCORTEX_MOCK_DB=true uv run python -m neocortex
```

`tests/test_agents.py` tests `src/pydantic_agents_playground`, **not** `neocortex.extraction.agents` —
it is not affected by Stage 3's prompt changes.

There are no pytest markers registered, so "run only the tests that hit a real model" is not
expressible — the real-model surface is the standalone `scripts/e2e_*.py` files.

## Pre-flight assertions (skipping either silently corrupts an arm)

```bash
# 1. Embeddings live? embedding_service.py returns None without GOOGLE_API_KEY — no error raised.
#    NOTE the constructor is EmbeddingService(model: str | None = None, dimensions: int = 768).
#    Passing MCPSettings() positionally binds it to self._model, the Gemini SDK rejects it, and
#    embed()'s bare `except Exception: return None` swallows the error — so the assert below would
#    report "EMBEDDINGS DEAD" even when embeddings are healthy. Match services.py:112 instead.
uv run python -c "
import asyncio
from neocortex.embedding_service import EmbeddingService
from neocortex.mcp_settings import MCPSettings
e = EmbeddingService(model=MCPSettings().embedding_model)
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
