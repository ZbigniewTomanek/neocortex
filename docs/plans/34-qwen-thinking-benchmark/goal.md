# 34-qwen-thinking-benchmark, run contract

Authority: `docs/plans/34-qwen-thinking-benchmark` — [index.md](index.md) is the plan; the stage files
under `stages/` are the specifications; [decisions.md](decisions.md) D-1..D-8 are binding.
Goal ID: `none`
Started: 2026-09-11
Protocol: [PROTOCOL.md](PROTOCOL.md) · Status: [state.json](state.json) · Record: [journal.md](journal.md) · [backlog.md](backlog.md)

## Contract

Plan 33 ended with every Qwen agent on `HOLD` and the verdict unmeasurable: two E2E children failed on
hosted-tuned timers, one on an unverified formatter bug, the only real quality misses were one
numeric-fact merge defect, the integrity evidence existed only in a private audit log, and the thinking
sweep had never run because the client dropped every positive level before the request left the process
(fixed pre-run in `10dcbb5`, D-6).

When this run is done: the speed probe scores fact retention offline; skip events and a 20/20 graph
sample export privacy-safely; the five E2E children wait on readiness instead of fixed timers; explicit
numbers survive Qwen extraction and the one-shot merge; a measured answer exists to whether the local
endpoint honours `reasoning_effort` at all; one bounded sweep has picked a thinking level per agent by
the pre-committed rule in Stage 6; one tuned compact service arm has produced the rubric's evidence; and
`resources/decision.md` plus `resources/report.md` publish a truthful per-agent `MIGRATE`/`HOLD` with
every cell citing the artifact it was read from.

**Boundary.** The files in the plan's *Files That May Be Changed* section, plus this run record. Hosted
model prompts, tools, profiles, and settings do not change (index guardrail 9). `src/neocortex/admin/`
is out of scope (Stage 3). Plan 33's `state.json` is not touched; only its `backlog.md`, `journal.md`,
and `resources/` receive the handoff.

**A truthful `HOLD` is a successful outcome.** So is "the endpoint ignores `reasoning_effort`". The
plan exists to measure, not to reach `MIGRATE`. Never weaken a criterion to produce a verdict.

## Stages and gates

Full criteria live in each stage file's *Verification* section and in the index's *Success Criteria*
table. Every stage additionally carries the two run-wide gates below.

1. `Fact-retention scorer and probe extension` — `scripts/fact_retention.py`, `resources/fact-fixture.json`,
   per-agent thinking flags and `fact_score` rows in `scripts/qwen_speed_probe.py`.
   GATE: the two unit files pass **including the mutation test** (deleting one fixture fact lowers
   `facts_found` by exactly one; a stale-only graph yields `new_present=false`); the `--test-model`
   probe run writes one row per compact episode and per triplet, each with `fact_score`.
2. `Privacy-safe integrity evidence export` — `scripts/export_skip_events.py`,
   `scripts/export_graph_sample.py`, `resources/quality-sample-tuned.schema.json`, cap-drop counting,
   metrics consistency fields, `failure_step`/`exception_class` capture.
   GATE: the three unit files pass, including one fixture per **all three** E2E banner conventions and
   the refusal of an event carrying free text; the swift3 parsing report regenerates byte-identically
   (`NOT MEASURED` if the gitignored `backups/` snapshot is absent, not red).
3. `E2E harness reliability and recall formatter` — `scripts/e2e_common.py`, readiness-based waits in the
   children, recall formatter diagnosis.
   GATE: `tests/unit/test_e2e_common.py` passes and a helper that returns on the first poll turns it red;
   `git grep -n "JOB_WAIT_TIMEOUT = 120" scripts/` returns nothing and all five children import
   `e2e_common`. The formatter reproduction is REPORT, not GATE (it may legitimately not reproduce).
4. `Numeric-fact preservation in the Qwen path` — Qwen extractor prompt, `render_oneshot_items` and the
   host merge in `oneshot_librarian.py`, the live `off` baseline.
   GATE: the merge/extractor tests pass **after** the S05 test was recorded red on pre-fix code, and one
   test asserts the **rendered prompt text**, not only merged content; hosted identity holds.
   REPORT: `resources/sweep/off.json`. Live budget 20 min.
5. `Thinking-level identity probe` — `scripts/effort_level_probe.py`, `resources/effort-levels.json`.
   GATE: every level's `resolved_reasoning_effort`, read at the PydanticAI boundary, equals its own name
   (`off` → `"none"`); all 3 `off` rows show `reasoning_tokens == 0` **and** `output_tokens > 0` **and**
   `valid_output == true`; every planned request is a real row or an explicit `TIMEOUT`/`NOT MEASURED`.
   REPORT: medians, the pairwise alias matrix, `distinct_levels`, whether the cancellation rule fired.
   Live budget 20 min. A cancelled sweep is a published result, not a failure.
6. `Per-agent thinking-level sweep` — `resources/effort-sweep.json`, `resources/effort-sweep.md`,
   raw cells under `resources/sweep/`.
   GATE: every cell names a `raw_path` whose row count equals `episodes`, or is `TIMEOUT`/`NOT MEASURED`;
   each selected level's raw rows show no critical defect and `timeouts <= 1`. Live budget 4 h, hard.
7. `Tuned compact service run` — arm `qwen-flash-next-compact-tuned` and its evidence under Plan 33's
   `resources/`.
   GATE (the only one, per D-7): the arm ran and its artifacts exist — metrics, recall results, E2E
   manifest, `skip-events-*-tuned*.json`, `quality-sample-*-tuned*.json`. Stability, integrity, skip
   attribution, the 20/20 sample and the E2E outcomes are REPORT and feed Stage 8 as rubric inputs.
   Live budget 2 h per arm, at most two arms.
8. `Decision, report, and Plan 33 handoff` — `resources/decision.md`, `resources/report.md`
   (ASD-STE100), `.env.example`/`docs/development.md` only for a `MIGRATE`, Plan 33 handoff, LESSONS.
   GATE: every verdict cites an artifact path that exists in the repository, and no `MIGRATE` row has a
   `NOT MEASURED` input.

**Run-wide gates, every stage.**

- `uv run pytest tests/ -q` and `uv run ruff check .` pass. Baseline at `b47f6ba`: **1,288 passed,
  7 skipped**, ruff **All checks passed!** (measured 2026-09-11, `validation/baseline-*.txt`). No test
  weakened, skipped, or deleted.
- Hosted path identity: the hosted branches of `build_extractor_agent`, `build_ontology_agent`,
  `build_librarian_agent` and the `hosted` profile selection in `run_extraction` stay byte-identical to
  `8766e90`.

## Execution guardrails (from the index, binding)

1. No live model call on a code path that has not passed the same command with `--test-model` in this run.
2. Every live call has a timeout ≤ 300 s. A timeout is a recorded value, never a crash or a retry loop.
3. Each live measurement runs once. A rerun needs a root-caused code change recorded in `decisions.md`.
4. Live work runs detached under `.tmp/plan34/`, writes incremental JSON after every episode, and is
   polled at intervals of five minutes or more. The orchestrator never blocks on a live run.
5. On budget overrun: stop launching cells, write the partial file, mark the rest `NOT MEASURED`, continue.
6. Levels are `off`, `low`, `medium`, `high`. `xhigh` is out of scope (D-1, D28, owner steer).
7. At most two compact service arms in this plan.
8. Reviewer findings about evidence wording or report formatting go to `backlog.md`. Only findings about
   product correctness, privacy, or a false `PASS` block.
9. Hosted-model prompts, tools, profiles, and settings do not change.

## Evidence index

- `briefs/stage<n>-brief.md` — the frozen specification the implementer worked from.
- `validation/baseline-pytest.txt`, `validation/baseline-ruff.txt` — the pre-run suite and lint baseline.
- `validation/stage<n>-<gate>-<attempt>.txt` — one file per check per attempt, raw, never appended to.
- `validation/stage<n>-review.md` — the reviewer's complete finding set and the orchestrator's triage.
- `resources/fact-fixture.json`, `resources/effort-levels.json`, `resources/effort-sweep.{json,md}`,
  `resources/sweep/*.json`, `resources/quality-sample-tuned.schema.json`, `resources/decision.md`,
  `resources/report.md` — the plan's own measured artifacts.
- `docs/plans/33-local-qwen-migration/resources/*-tuned*` — Stage 7's service-arm evidence.

## Allowed actions

Granted by the owner on 2026-09-11. The settings message listed five items and the owner replied
"proceed", which took all five as proposed.

- **Live calls to the local Qwen endpoint** `http://127.0.0.1:24000/v1` with `LITELLM_API_KEY` read from
  the environment — never printed, logged, or committed. Stages 4–7, under the budgets above.
- **Stage 7 may wipe the local development PostgreSQL graph.** `model_bakeoff.sh` runs
  `manage.sh start --fresh`; it saves a pre-snapshot first and restores it on exit, but the wipe is real.
  `manage.sh snapshot save` is granted with it.
- **Commits on `plan/34-qwen-thinking-benchmark`** — one per stage plus fix rounds. No push, no PR, no tag.
- **Writing Stage 7 evidence into `docs/plans/33-local-qwen-migration/resources/`** and appending to that
  plan's `backlog.md` and `journal.md`. Plan 33's `state.json` stays untouched.
- **Replacing `PROTOCOL.md`** with the goal-execution-loop render; the previous file is kept as
  `PROTOCOL.previous.md`.
- **Stage 7 Gemini embedding calls**, including their API cost, for the bounded service
  benchmark using the existing key. Owner replied "proceed" on 2026-09-13 after
  the pending embedding approval was explicitly identified. No external embedding
  calls in the in-memory Stage4–6 probes.

Not granted, and stopping actions under PROTOCOL: pushing anywhere, tagging, deploying,
sending anything to a person, external service calls or spending beyond the Stage7
embedding grant, deleting data outside the local dev estate.

## Invariants

- No credential, token, or cookie is written beneath this directory, under `.tmp/plan34/`, or into any
  commit. `LITELLM_API_KEY` is read from the environment and never echoed.
- `NOT MEASURED` is never `PASS`. No status is a literal, a default, a band midpoint, or a row generated
  to satisfy a count. A shortfall is recorded as a shortfall, never padded.
- A live measurement runs once. Reruns need a root-caused change in `decisions.md`.
- Correctness criteria are never amended. Measurement criteria may be, only with the four-part evidence
  the previous protocol required, carried forward here: journal evidence that the criterion is the
  defect, a `decisions.md` entry quoting the original verbatim, the original struck in place, and the
  disposition in `state.json`.
- Review flags in `state.json` are permanent. Resuming this run never restores a spent one.
