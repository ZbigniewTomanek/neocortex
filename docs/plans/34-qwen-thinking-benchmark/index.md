# Plan: Qwen Thinking-Level Benchmark

**Date**: 2026-09-11<br>
**Branch**: `plan/34-qwen-thinking-benchmark` (branch from `plan/33-local-qwen-migration` head `8766e90`)<br>
**Predecessors**: [Plan 33 — local Qwen migration](../33-local-qwen-migration/index.md) (Stage 6 `BLOCKED` on backlog 16, Stage 8 no-op, Stage 9 `PENDING`); run records `.tmp/qwen-swift/` and `.tmp/qwen-harness-tuning/` (gitignored); [post-mortem](../33-local-qwen-migration/briefs/postmortem-qwen-swift.md).<br>
**Goal**: Fix the harness defects that made Plan 33's quality verdict unmeasurable, then measure which Qwen thinking level each reasoning agent needs, in one bounded sweep, and issue a truthful per-agent `MIGRATE`/`HOLD` with the Plan 33 rubric.

Executed per [PROTOCOL.md](PROTOCOL.md). Status of record: [state.json](state.json).<br>
Runtime record: [journal.md](journal.md) · [decisions.md](decisions.md) · [backlog.md](backlog.md)

## Context

Target: `local:qwen3.8-flash-next` at `http://127.0.0.1:24000/v1`, credential in `LITELLM_API_KEY`
(never printed or committed). Plan 33's final compact run `20260911T001509Z-swift3` was fast and stable
(30/30 jobs, 2,397 s, 68 requests, 0 reasoning tokens) but every agent is `HOLD`. The causes are mixed
and the current process cannot separate them:

- **Two E2E children are hosted-tuned harness flakes.** `e2e_cognitive_recall_test.py` waits a fixed
  `JOB_WAIT_TIMEOUT = 120` s; `e2e_extraction_pipeline_test.py` hit `ConnectionResetError` in
  `step_setup_domain_routing` right after `manage.sh` restarted services. Both passed in run 2.
- **One child is an unverified formatter bug.** `e2e_episodic_memory_test.py` sees 3 episodes in recall
  results but `formatted_context == "(no episodes recalled)"` (`_format_recall_context` in
  `src/neocortex/tools/recall.py`). Never reproduced in isolation.
- **The only real quality misses are one defect class.** Plan 15 S05/S11 and Plan 17 S07 all check that a
  newer number (May 1, 0.62, 94.2) reaches node `content`. `QWEN_EXTRACTOR_PROMPT` caps descriptions at
  one sentence and pushes scalars into `properties`; the host default `_merge_content` in
  `oneshot_librarian.py` only appends text. The checks never read `properties`.
- **The integrity gap is an instrument gap.** `edge_skipped_missing_node` (16) and
  `edge_skipped_temporal_pair` (5) are already logged per event with `episode_id` and `correlation_id`,
  but only to the private audit log, which Stage 7 tooling refuses to read. No privacy-safe graph
  sampler exists; the snapshot is a raw `pg_dump`. Cap-triggered relation drops in
  `cap_extraction_entities` are not counted at all.
- **The thinking sweep never ran.** Plan 33 Stage 8 was gated on a `MIGRATE` verdict. The speed probe's
  `THINKING` map stops at `medium`; thinking is disabled with the boolean `false`, not the string
  `none`; the probe applies one level to all agents.

Two prior autonomous runs tell us how this work fails. The 13-hour run lost about 10 hours to live probes
launched before mock validation, one uncapped 3 h 18 min model call, and full-matrix reruns after each
fix. The 4-hour run succeeded by validating with `--test-model` first, caching upstream stages, bounding
every call, and running the service corpus only at the end. Owner steer, verbatim: "do not fall into the
review/validation trap" (2026-09-10); no "rabbithole of running lengthy tests on xhigh that take hours"
(2026-09-11). Plan 33 D28 stands: prefer the lowest effort that passes; never choose `xhigh` by default.

## Strategy

**Phase A — instruments before measurements (Stages 1–3, independent, any order).** An offline
fact-retention scorer inside the in-memory speed probe, so a thinking level can be judged in minutes
without services. Privacy-safe exports for per-event skips, temporal survival, and a 20/20 graph sample.
Readiness-based E2E waits and the recall formatter fix. No live model call in Phase A.

**Phase B — remove the known defect, then identify the levels (Stages 4–5).** Keep scalar facts through
Qwen extraction and merge, verified deterministically, then one bounded live `off` baseline. A 20-minute
level-identity probe proves `off` is really off and finds which of `low/medium/high` the endpoint actually
distinguishes, so the sweep never pays for an alias.

**Phase C — one sweep, one service run, one decision (Stages 6–8).** Per-agent sweep in the probe with
cached upstream stages, sequential extractor → librarian → ontology → classifier, hard 4 h budget,
detached, incremental output. Then one compact service arm with the selected levels (a second only after a
root-caused fix), the Plan 33 rubric applied per agent, and an ASD-STE100 report plus handoff to Plan 33
Stage 9.

### Execution guardrails (binding for every stage)

1. No live model call on a code path that has not passed the same command with `--test-model` in this run.
2. Every live call has a timeout ≤ 300 s (`--per-call-timeout` / `NEOCORTEX_LOCAL_MODEL_TIMEOUT_S`). A
   timeout is a recorded value, never a crash and never a retry loop.
3. Each live measurement runs once. A rerun requires a root-caused code change recorded in `decisions.md`.
4. Live work runs detached (`nohup … &`, log under `.tmp/plan34/`), writes incremental JSON after every
   episode, and is polled at ≥ 5-minute intervals. The coordinator never blocks on a live run.
5. Live budget per stage is in the criteria table. On overrun: stop launching cells, write the partial
   file, mark the rest `NOT MEASURED`, continue.
6. Levels are `off`, `low`, `medium`, `high`. `xhigh` is out of scope (D28; owner steer).
7. At most two compact service arms in this plan.
8. Reviewer findings about evidence wording or report formatting go to `backlog.md`; only findings about
   product correctness, privacy, or a false `PASS` block.
9. Hosted-model prompts, tools, profiles, and settings do not change.

## Success Criteria

GATE blocks its owning stage. REPORT is measured, written to `journal.md`, and never blocks. `NOT
MEASURED` is not `PASS`: it blocks a GATE and is published for a REPORT. Every measured GATE names the
artifact its value is read from and the defect that turns it red.

| Metric | Baseline | Target | Kind | If missed | If unmeasurable |
|--------|----------|--------|------|-----------|-----------------|
| Every GATE value is derived from a measurement of this run's own inputs | n/a | no status is a literal, a default, a band midpoint, or a row generated to satisfy a count | GATE | block stage | REPORT `NOT MEASURED` and block |
| Regression suite and lint | 1,283 passed / 7 skipped at `8766e90` | `uv run pytest tests/ -q` and `uv run ruff check .` pass; no test weakened, skipped, or deleted | GATE | block owning stage | n/a |
| Hosted path identity | hosted prompt/profile tests green | the hosted branches of `build_extractor_agent`, `build_ontology_agent`, `build_librarian_agent` and the `hosted` profile selection in `run_extraction` are byte-identical to `8766e90`, and the hosted tests named in Stage 4 pass | GATE | block owning stage | n/a |
| Fact-retention scorer sensitivity | no scorer | deleting one fixture fact from a canned graph lowers `facts_found` by exactly one, and a canned graph with only the stale value yields `new_present=false` (Stage 1 mutation tests) | GATE | block Stage 1 | n/a |
| Thinking `off` is really off | 0 reasoning tokens in swift3 aggregate | `reasoning_tokens == 0` with `output_tokens > 0` and valid output on 3/3 identity requests, read from `resources/effort-levels.json`; a nonzero count or leaked `<think>` marker turns it red, and a zero-output row is an instrument failure, not a pass | GATE | block Stage 5, diagnose `build_model_settings` | REPORT `NOT MEASURED` and block |
| Sweep completeness and provenance | no sweep | every planned cell in `resources/effort-sweep.json` links a raw probe JSON under `resources/sweep/` with the expected episode count, or is an explicit `TIMEOUT`/`NOT MEASURED` row; a copied or default row turns it red | GATE | block Stage 6 | REPORT `NOT MEASURED` and block |
| Terminal stability of the tuned arm | 30/30 in swift3 | all submitted jobs terminal; `(failed+cancelled)/total ≤ 0.10` read from the run's captured `/admin/jobs/summary` in `metrics-qwen-flash-next-compact-tuned.json` | GATE | block Stage 7, root-cause | REPORT `NOT MEASURED` and block |
| Critical integrity defects | 0 in swift3 | zero stored reasoning markers, invalid type names, garbage types, or source leaks in the metrics integrity scan | GATE | block Stage 7 | REPORT `NOT MEASURED` and block |
| Skip-event attribution (Plan 33 backlog 16) | 16 + 5 aggregate only | per `reason_code`, exported safe event count == aggregate counter, and every `temporal_pair` conflict has `survived == true` in `skip-events-*.json`; a count mismatch or a lost `SUPERSEDES`/`CORRECTS` edge turns it red | GATE | block Stage 7 | REPORT `NOT MEASURED` and block |
| Fixed graph sample | `NOT MEASURED` in Plan 33 | 20 real nodes and 20 real edges from the tuned arm's post-run graph in `quality-sample-*-tuned*.json`, all `type_valid` and `endpoints_exist` true; fewer than 20 real rows is a shortfall, never padded | GATE | block Stage 7 | REPORT `NOT MEASURED` and block |
| Absolute quality rubric (ship gate, per agent) | 0/5 E2E; Plan 15 9/14; Plan 17 12/14 + 1 FAIL | `MIGRATE` only when all five E2E children exit 0, Plan 15 ≥ 11/14 `PASS`, Plan 17 ≥ 13/14 `ACCEPTABLE` with 0 `FAIL`, and the sample gate is green. Any `NOT MEASURED` input means `HOLD`. | REPORT | publish `HOLD` per agent and continue | publish `NOT MEASURED`; never `MIGRATE` |
| Fact retention per level | not measured | per cell: compact `facts_found/facts_total`, triplet `new_present`/`old_absent`/`temporal_edge_present` | REPORT | publish and continue | publish `NOT MEASURED` |
| Level identity and aliasing | unknown | median reasoning tokens per level; levels within 20% with overlapping ranges are one alias and the sweep runs the distinct set only | REPORT | publish and continue | publish `NOT MEASURED`, sweep all four |
| Live model time per stage | Stage 4 ≤ 20 min · Stage 5 ≤ 20 min · Stage 6 ≤ 4 h · Stage 7 ≤ 2 h per arm | measured wall time under budget | REPORT | publish overrun, stop launching, open backlog | n/a |
| Tuned arm cost | swift3: 2,397 s, 68 requests, 0 reasoning tokens | wall time, requests, reasoning/completion tokens, p50/p95 per agent; latency never blocks | REPORT | publish and continue | publish `NOT MEASURED` |

## Files That May Be Changed

- `scripts/qwen_speed_probe.py`, new `scripts/fact_retention.py`, `scripts/effort_level_probe.py`,
  `scripts/export_skip_events.py`, `scripts/export_graph_sample.py`, `scripts/e2e_common.py` — harness.
- `scripts/e2e_*.py`, `scripts/run_e2e.sh`, `scripts/model_bakeoff.sh`, `scripts/compute_metrics.py`,
  `scripts/e2e_manifest.py`, `scripts/generate_qwen_parsing_report.py` — E2E reliability and evidence.
- `src/neocortex/extraction/agents.py` (Qwen prompt, cap counter), `oneshot_librarian.py` (merge),
  `pipeline.py` (event fields), `src/neocortex/tools/recall.py` (formatter) — Qwen path and one bug fix.
- `tests/` — new and updated tests only; no assertion weakened.
- `.env.example`, `docs/development.md` — Qwen effort defaults and local setup text; never secrets.
- `docs/plans/34-qwen-thinking-benchmark/` — this plan; `docs/plans/33-local-qwen-migration/backlog.md`
  and `journal.md` — handoff entries only; `docs/plans/LESSONS.md`.

## Stages

Routing table only. Status, notes, and commits live in `state.json` and nowhere else.

| # | Stage |
|---|-------|
| 1 | [Fact-retention scorer and probe extension](stages/01-fact-retention-scorer.md) |
| 2 | [Privacy-safe integrity evidence export](stages/02-integrity-evidence-export.md) |
| 3 | [E2E harness reliability and recall formatter](stages/03-e2e-harness-reliability.md) |
| 4 | [Numeric-fact preservation in the Qwen path](stages/04-numeric-fact-preservation.md) |
| 5 | [Thinking-level identity probe](stages/05-effort-level-identity.md) |
| 6 | [Per-agent thinking-level sweep](stages/06-per-agent-effort-sweep.md) |
| 7 | [Tuned compact service run](stages/07-combined-compact-run.md) |
| 8 | [Decision, report, and Plan 33 handoff](stages/08-decision-and-handoff.md) |
