# Journal

Append-only. Newest entries at the bottom. Never rewrite an earlier entry.

One entry per invocation, in this shape:

```
## YYYY-MM-DD HH:MM -- Stage N: [Name] -- DONE
**Did**: [1-3 lines]
**Verification**: GATE lines passed. REPORT values: [metric]=[value]
**Provenance**: [per measured GATE: the input the value was read from, and the defect that would
turn it red] - [or `NOT MEASURED` for any that could not be produced from this run's own inputs]
**Problems**: [symptom -> root cause -> resolution -> inline/subagent] or "none"
**Commit**: `abc1234`
```

---
## 2026-09-11 14:45 -- Pre-review: plan revised before execution

**Did**: Ran `/plan-pre-review` against this plan. Eleven findings confirmed, seven refuted. Fixed the one
P0 in product code and revised the plan for the rest. No stage has started; `state.json` is unchanged.

**Product fix (D-6)**: `build_model_settings` now restates every Qwen thinking level through
`openai_reasoning_effort`. Before this, `low`/`medium`/`high` reached the server as byte-identical requests,
so Stages 5-7 would have measured sampling noise. Verified at the PydanticAI boundary: each level now
resolves to its own name, `off` still resolves to `"none"` with the nothink `extra_body`, and hosted and
local-non-Qwen settings are byte-identical to before. Suite 1,288 passed / 7 skipped; `ruff check .` clean
after excluding the untracked-by-the-type-checker `test_agents/` sample tree, which had 34 pre-existing
errors and made every stage's lint GATE red at baseline.

**Plan revisions**: Stage 2 - gate command named no subcommand and could not run; graph-sample fields
cannot validate against Plan 33's `additionalProperties: false` schema, so a new schema is written instead;
`failure_step` now covers all three banner conventions; `relation_type` is not on the skip events. Stage 3 -
the compound GATE demanded a formatter reproduction that step 4 explicitly allows to fail, which would have
left Stages 7 and 8 unreachable, so it is split into a GATE and a REPORT; `wait_for_jobs` keeps the
children's baseline-scoped PostgreSQL query because `/admin/jobs/summary` cannot express "jobs after this
baseline". Stage 4 - the merge fix now names `render_oneshot_items`, the function that actually builds the
model-facing text, and requires a test that asserts the rendered prompt. Stage 5 - added the positive
control, a deterministic reduction for the non-transitive alias rule, and a cancellation rule. Stage 6 -
per-agent `off` cells (D-8) and a selection rule that ranks triplet passes first. Stage 7 - evidence lines
demoted to REPORT (D-7).

**Verification**: `uv run pytest tests/ -q` 1,288 passed / 7 skipped. `uv run ruff check .` clean.
**Provenance**: the P0 was read from `model_factory.py:104` plus PydanticAI's `prepare_request` and
`_get_reasoning_effort`, executed directly rather than inferred, and corroborated by Plan 33's committed
`probe-results-{low,medium,high,xhigh}.json`. The lint baseline was read from `ruff check .` on a clean
tree at `04e40d1`. The regression baseline 1,283 in the criteria table was stale; the tree measured 1,285
before this change.
**Problems**: none blocking. Whether the server honours `reasoning_effort` is still unmeasured by design.
**Commits**: `10dcbb5` (thinking-level relay), `b47f6ba` (ruff exclude), plus this plan revision.

## 2026-09-11, run started

- Run directory created by `init_run.sh`. Preset `custom` (review-each-stage-after, one-review-one-fix, never-stop).
- Roles: orchestrator `current-session` (coordinator), implementer `claude/opus` effort `high` (strong), reviewer `claude/opus` effort `high` (strong), helper `claude/sonnet` effort `medium` (light).
- Stages: Fact-retention scorer and probe extension, Privacy-safe integrity evidence export, E2E harness reliability and recall formatter, Numeric-fact preservation in the Qwen path, Thinking-level identity probe, Per-agent thinking-level sweep, Tuned compact service run, Decision, report, and Plan 33 handoff.
- Owner's reply to the settings message: "<quote it word for word>"
- Defaults taken: <list the settings the owner did not name>.
- Gate commands verified at baseline: <command> gives <output>.

## 2026-09-11 15:36 -- Run armed: goal-execution-loop settings

**Did**: Sent the five-part settings message. Owner replied, verbatim: **"proceed"**. That took every
proposed value, including the one part whose documented default is no.

**Settings**: preset `custom` = `review-each-stage-after` + `one-review-one-fix` + `never-stop`. Not the
`thorough` default: the owner's 2026-09-10 steer ("do not fall into the review/validation trap") and the
plan's own pre-existing unattended protocol both argue for one review and one fix per stage. Roles:
orchestrator `current-session`; implementer `claude/opus` effort high; reviewer `claude/opus` effort
high; helper `claude/sonnet` effort medium — all shipped agent definitions on this harness, no external
commands. Groups A=1,2,3 B=4,5 C=6 D=7 E=8 (informational under `never-stop`).

**Defaults taken unchanged**: the role models and efforts (tier defaults for a Claude Code
orchestrator), the run directory (the plan directory).
**Owner-specific, not a default**: the three mode values, the stage groups, the five granted actions,
and replacing `PROTOCOL.md`.

**PROTOCOL replacement**: the previous file — task-planning's autonomous protocol — is kept at
`PROTOCOL.previous.md`. It says nothing about briefs, implementer/reviewer roles, or the review ledger
this run needs. Its load-bearing substance is carried into `goal.md` as run invariants: the amendment
rule with its four-part evidence requirement, `NOT MEASURED` is never `PASS`, and never generating an
artifact to satisfy a declared count.

**Baseline, measured before stage 1** (both commands from the plan's `resources/commands.md`, run on a
clean tree at `b47f6ba` + the untracked `.agents/`):
- `uv run pytest tests/ -q` -> **1,288 passed, 7 skipped** in 46.19 s, exit 0 -> `validation/baseline-pytest.txt`
- `uv run ruff check .` -> **All checks passed!**, exit 0 -> `validation/baseline-ruff.txt`
Both match the figure the plan's criteria table names, so no plan defect to fix before stage 1.

**Environment checked**: local Qwen endpoint `http://127.0.0.1:24000/v1/models` answers HTTP 401
unauthenticated, so the server is alive; `LITELLM_API_KEY` is present in the environment and is never
echoed, logged, or committed. `neocortex-postgres` is up and healthy.

**Verification**: n/a (setup). **Provenance**: baseline values read from the two files above.
**Problems**: none. **Commit**: pending with stage 1.

## 2026-09-11 16:05 -- Stage 1: Fact-retention scorer and probe extension -- DONE

**Did**: Added `scripts/fact_retention.py` (offline scorer), the committed `resources/fact-fixture.json`
(8 compact episodes, 3 supersession triplets, the E18->E20->E26 chain), per-agent thinking flags plus
`--corpus`, `--fixture`, `--per-call-timeout`, `--max-wall-seconds` and incremental output in
`scripts/qwen_speed_probe.py`, and one read-only `graph_snapshot()` on `InMemoryRepository`.
Implementer `claude/opus` effort high.

**Verification -- every gate re-run by the orchestrator, not read from the implementer's report**:
- GATE G1 `pytest tests/unit/test_fact_retention.py tests/unit/test_qwen_speed_probe.py -q` -> **47 passed**
  (`validation/stage1-unit-3.txt`; my own re-run agreed).
- GATE G2 the `--test-model --corpus both` probe run -> exit 0, **11/11 units**. I re-ran it to a separate
  output (`.tmp/plan34/stage1-verify.json`) and read the JSON directly: rows
  `E02,E04,E05,E10,E18,E20,E26,E27,S05,S11,S07`; every row carries `fact_score`; the three triplets carry
  a `supersession` dict and `fact_score: null`; `run.thinking_extractor == "high"` while the other three
  agents read `"off"`, so the per-agent wiring reaches the config.
- GATE G3 `pytest tests/ -q` -> **1,322 passed, 7 skipped** (baseline 1,288/7; +34 new, none removed).
  `git diff --numstat tests/unit/test_qwen_speed_probe.py` is `314 0` -- **zero deleted lines**, so no
  existing assertion was weakened.
- GATE G4 `ruff check .` -> `All checks passed!`.

**Provenance**: G1's value is read from the pytest summary line; the defect that turns it red is a scorer
that returns full marks regardless of input, which
`test_removing_one_fact_lowers_facts_found_by_exactly_one` catches -- it builds the E04 graph twice, once
with `Libpostal` removed (guarded by `assert text.count("Libpostal") == 1`), and requires `facts_found` to
drop by **exactly** one and `missing_keys == [5]`. G2's value is read from the summary JSON I generated
myself. G3's baseline comes from `validation/baseline-pytest.txt`.

**REPORT -- wall time**: the `--test-model` run self-reports **0.15 s**; the gate command wall time is
about 1 s. **Zero live model calls in this stage**, as designed.

**`fact_score` is 0 for every compact episode, and that is the correct reading.** TestModel emits stub
extractor output: the probe's own stage rows show `ents 0 rels 0` and every summary shows
`nodes_after: 0`. An empty graph can retain no fact. G2 proves the plumbing, not quality; Stage 6 is the
first real reading. The scorer's discrimination is proven by the hand-built mutation test alone.

**Problems and triage**:
- *E10 carries 5 facts, below the brief's 6-10 floor.* Not a drop: the fixture spec's own candidate table
  lists only five for E10 and all five verified. Accepted as an honest shortfall rather than padded --
  `goal.md` forbids generating a row to satisfy a count, and the spec is the binding reference. Effect is
  confined to Stage 6's `Sigma facts_found` tie-break, where E10 contributes at most 5. The implementer
  verified five further real substrings exist if a future run wants them.
- *`Precision, Recall, F1` does occur verbatim in E02*; my brief guessed it might not. Kept. All 56 spec
  candidates verified; none dropped.
- *Cache-key change (D-10) makes Plan 33's 29 warm entries under `.tmp/qwen-swift/cache/` unreachable.*
  No loss: `resources/commands.md` points Stages 4 and 6 at `.tmp/plan34/cache`, which starts empty
  either way. No compatibility branch added (PROTOCOL forbids shims absent an explicit ask).
- *Two additions beyond the brief's letter, both accepted.* A wall-budget-truncated run writes
  `chain: {"status": "NOT MEASURED", "reason": "wall_budget"}` rather than a count over a partly-built
  graph; and `main` returns 1 on an empty unit set so "zero units, all green" cannot read as success.
  Both apply the `NOT MEASURED is never PASS` invariant; keeping them.

**Not measured, by design**: `fact_score` over a real model's graph; `temporal_edge_present == true` on a
pipeline-built graph; `--classify` under the new per-agent wiring (`AgentDomainClassifier` has no
TestModel path -- unchanged from before this stage); that `--per-call-timeout` actually bounds a live
HTTP call (Stage 5 measures it).

**Commit**: see `state.json`.

## 2026-09-11 16:35 -- Stage 1 review spent; run paused and serialized for resume

**Did**: Received the Stage 1 post-review, wrote the complete finding set to
`validation/stage1-review.md`, triaged all 8 findings into `backlog.md` items 6-12, and stopped the run
at the owner's request ("we'll have no time for the fixes, let's serialize the state in the plan files so
it can be resumed"). No fix round was opened.

**Review outcome**: PASS, 8 findings, **none blocking**. Reviewer gate dispositions agree with my own
independent re-runs: G1 47 passed, G2 11/11 rows with `fact_score`, G3 1,322 passed / 7 skipped, G4
clean, hosted-path identity untouched (`0101ce4` changes nothing under `src/neocortex/extraction/`).
The reviewer confirmed the two properties the whole plan rests on: the supersession haystack really is
anchor-`content`-only, so the probe cannot pass where the E2E child fails (exact for S05 and S07,
approximate for S11 -- backlog 10); and the mutation test is load-bearing, so a constant-full-marks
scorer fails the suite. Zero deleted lines in `tests/`.

**Triage**: `one-review-one-fix`, review spent, no fix round run. Stage 1 stays `DONE` at `0101ce4`;
none of the 8 findings blocks a Stage 1 gate, and under `goal.md` guardrail 8 none is a
product-correctness, privacy, or false-`PASS` issue in Stage 1's own deliverable. No finding was
dismissed -- all 8 are in the backlog with their evidence and their fix.

**The one item a resuming session must act on before Stage 6** is backlog 6 (review F1): the Stage 6
step-2 librarian command, exactly as the stage file writes it today, computes a different cache key from
the one step 1 writes (`E04-957d37180cb3` vs `E04-04c212aba9cf`, both verified), and the miss raises out
of `run_text` -> `run_unit` -> `main` because `load_cached_extraction` sits outside the `try`. The cell
would produce a traceback and **no output file at all** -- not the `NOT MEASURED` row the protocol
requires. Two fixes, both needed, both written out in the backlog entry.

**Verification**: gates re-run by the orchestrator, recorded in the previous entry. Nothing new was run.
**Provenance**: every finding cites a file and line the reviewer read; F1's key hashes were computed by
the reviewer and the crash reproduced live.
**Problems**: none blocking.

---

## RESUME HERE

State of record is `state.json`. Read `goal.md`, then `PROTOCOL.md`, then this entry.

**Stage 1** -- `DONE`, commit `0101ce4`, review spent, 8 findings in `backlog.md` 6-12. Nothing to redo.

**Stage 2** -- `IN_PROGRESS`, `step: WRITING`. A `claude/opus` implementer was dispatched against
`briefs/stage2-brief.md` and was still running when the session ended. It leaves **uncommitted and
ungated** work in the tree. At the time of this commit `git status` showed:
`M scripts/compute_metrics.py`, `M src/neocortex/extraction/agents.py`,
`M src/neocortex/extraction/pipeline.py`, `?? scripts/export_skip_events.py`,
`?? scripts/export_graph_sample.py` -- and more may have landed after. No `validation/stage2-*` evidence
existed yet, so **no gate has been run on any of it**.

To resume Stage 2: inspect `git status` and `git diff` against `briefs/stage2-brief.md`; if the work is
complete, run the brief's four gates yourself and save the raw output to the evidence paths the gate
table names, then commit with the stage's message; if it is partial, either finish it with a fresh
implementer given the same brief plus the diff, or `git checkout --` the tracked files and delete the two
new scripts to start clean. Do not commit it ungated.

**Stage 3** -- `PENDING`. `briefs/stage3-brief.md` is written, reviewed against a full inventory, and
ready to dispatch. It could not start in parallel with Stage 2 because both briefs touch
`scripts/model_bakeoff.sh`, which the one-writer rule forbids.

**Stages 4-8** -- `PENDING`, no brief yet. Stage 4 is the first live model call in the plan.

**Not yet started, and load-bearing**: no live model call has been made in this run. The plan's central
question -- whether the local endpoint honours `reasoning_effort` at all -- is Stage 5 and is still
`NOT MEASURED`.

## 2026-09-13 -- Run resumed on Codex

- Owner: "use goal-execution-loop skill to act as a coordinator to finish docs/plans/34-qwen-thinking-benchmark/index.md".
- Existing modes, groups, permissions and PROTOCOL retained; no owner gate is due. Stage 1 commit `0101ce4` exists.
- Harness adaptation: resumed assignments use the skill's Codex tiers (`codex/gpt-5.6-sol`, high, implementer/reviewer; `codex/gpt-5.6-luna`, medium, helper). Historical role records remain intact; each stage records actual agents.
- Stage 2 resumes from WRITING with existing changes preserved. Some attempt-1 evidence landed after the pause; new attempts must use fresh filenames. Untracked `.agents/` is user material, excluded from commits.
- Stage 2 brief header updated for actual roles. No feature code changed by coordinator.

## 2026-09-13 -- Preparation for remaining stages

- Stage 3 brief header uses actual Codex strong-tier roles; deliverables unchanged.
- Backlog 6's documented command correction applied to Stage 6 step 2: pin the ontology and extractor levels when reading the extraction cache. Its runtime error handling remains required implementation work before the sweep.
- Backlog 7 and 8 are promoted into pre-sweep instrumentation repairs: fixture cache provenance and cross-node fact matching affect the evidence to be published. Backlog 10's wording correction will accompany those changes. No live measurement may precede these repairs.
- Custom goal agent types are unavailable in this session; explicit strong/light model overrides and flat, no-delegation prompts enforce the same role contract.

## 2026-09-13 -- Stage 4/5 briefs prepared

- Stage 4 brief separates deterministic implementation from live launch; Stage 5 does the same. Only one implementation writer runs at a time.
- Stage 4 resolves contradictory prose in favor of its unchanged S05 gate: content must contain May 1 and omit April 15. The illustrative "previously Y" wording cannot reintroduce the stale date. No criterion is relaxed.
- Stage 2 implementation inspection found possible false comparisons against missing audit counters, a still-hardcoded effort in the parametrized report, and a same-directory temporal annotation command that refuses its own input. These were sent to the active implementer before gating; no review budget has been consumed.

## 2026-09-13 -- Stage 2 brief corrected for tuned evidence

- Implementer confirmed frozen historical schema has effort `const: false`. Added a separate tuned report schema to Stage 2 scope; exact four-agent effort mapping and suffixed output files preserve historical evidence.
- Clarified atomic annotation of this run's skip file for the documented same-directory command. Cross-schema numeric-id ambiguity must remain unresolved rather than a false survived=true.
- Read-only local endpoint check (10 s) returned curl exit 28, HTTP 000. No inference request was issued; live readiness remains unmeasured.

## 2026-09-13 -- Stage 7 lifecycle prerequisite identified

- `model_bakeoff.sh` captures corpus metrics before children, each child restarts services, and EXIT restores PRE_SNAPSHOT (`restore_preserved_snapshot`). Therefore the plan's after-arm live graph export would sample the restored graph, not this run's corpus.
- Stage 7 must collect skip/sample evidence while the corpus graph still exists, before the first child restart; then build the final report after the manifest exists. Updating metrics after manifest creation also changes its pinned digest, so all corpus metric augmentation must precede manifest construction or require explicit manifest regeneration.
- This is required harness integration within the plan's allowed `scripts/model_bakeoff.sh` scope, to be included in Stage 7 brief and tested before any service arm. No live call or product edit made here.

## 2026-09-13 -- Stage 2 blocked on PostgreSQL; independent Stage 5 starts

- Stage 2 implementation finished, no commit or review yet because full-suite gate is red: 1,355 passed / 7 skipped / 31 setup errors, all PostgreSQL connection resets (`validation/stage2-suite-2.txt`).
- Coordinator reproduced one setup error at localhost:5432 (`stage2-postgres-coordinator-attempt1.txt`), independently measured 138 focused tests passing (`stage2-unit-coordinator-attempt1.txt`), lint clean, and historical generation exit 0 with no Plan 33 resource diff. All evidence under validation/.
- Stage 2 changes remain uncommitted and frozen pending environment recovery; review.used remains false. No tests skipped, weakened or deleted.
- Docker owns the local model listener, but its container listing hangs and was interrupted; local endpoint check times out. Owner clarification requested asynchronously while offline work continues.
- Stage 5 depends only on accepted Stage 1 and writes new files disjoint from frozen Stage 2. Dispatch its offline assignment on codex/gpt-5.6-sol/high. Stage 3/4 overlap Stage 2 files and wait until its commit or a deliberate isolation decision.

## 2026-09-13 -- Endpoint recovery, PostgreSQL still unavailable

- Authenticated bounded `/v1/models` check now returns exactly the required `qwen3.8-flash-next` model (jq true, exit 0); no inference request made.
- PostgreSQL representative gate still fails with the same connection reset (`validation/stage2-postgres-coordinator-attempt2.txt`). Docker listing with explicit desktop-linux context also hangs and was interrupted.
- Strong implementer reassigned to a bounded read-only environment diagnosis; no restart or environment mutation authorized or performed. Stage 5 offline writer continues independently.

## 2026-09-13 -- Owner restarted Docker; database recovered

- Owner: "restarted". Docker Desktop local context now responds; existing `neocortex-postgres` was stopped. Coordinator ran `docker --context desktop-linux compose up -d postgres`, preserving its volume.
- `pg_isready` accepts connections and the previously failing scoped-connection test passes (1 passed; `validation/stage2-postgres-coordinator-attempt3.txt`). Full gate will rerun after current Stage 5 files freeze.
- Docker commands for this run explicitly select desktop-linux because DOCKER_HOST overrides the default context. No unrelated container changed; no graph reset or live inference occurred.

## 2026-09-13 -- Stage 2 gates green; Stage 5 offline gates green

- Coordinator full suite: 1,404 passed / 7 skipped in 42.09 s (`validation/stage2-suite-coordinator-attempt1.txt`), including frozen Stage 5's 18 new tests. PostgreSQL blocker resolved. Lint clean (`validation/stage5-ruff-coordinator-attempt1.txt`).
- Stage 2 focused 138 passed, default historical generation byte-identical; diff inspected. Stage 2 implementation ready for commit and its one post-review.
- Coordinator Stage 5 exact TestModel run: 12 valid output rows, boundary none/low/medium/high as requested, no timeout. JSON `validation/stage5-testmodel-coordinator.json` read directly. Synthetic reasoning usage absent => NOT MEASURED and cancellation null, correctly.
- Stage 5 instrument corrections before gating: one request per row enforced with UsageLimits; mock exit requires correct boundaries and valid output instead of counting preallocated rows. No live run yet; regression evidence shared because both frozen code sets were checked together, no duplicate full-suite run.

## 2026-09-13 -- Commit hook gate fix

- Stage 2 commit attempt rejected by black (three formatted files) and ty (new exporter/metrics/report typing diagnostics plus Stage 5 test scripts import). No commit created; hooks were not bypassed.
- Stage 2 implementer dispatched for one bounded type-correction gate fix, preserving formatter output. Stage 5 writer has finished, so no concurrent writer.
- Coordinator small-change exception: one line adds the repository's existing `ty: ignore[unresolved-import]` convention to Stage 5's scripts import; runtime code unchanged. No broad suppression or configuration change.

## 2026-09-13 -- Hook gate fix complete

- Stage 2 typed dictionary narrowing and fixed tuple construction corrected; sequential Stage 5 nested settings narrowing also corrected by the same strong implementer after Stage 2 froze.
- Whole-tree ty passes; 156 combined focused tests pass; scoped pre-commit hooks pass including black/ruff/flake8/ty (`validation/stage2-stage5-precommit-gatefix1-attempt2.txt`).
- An initial all-files hook attempt exposed existing test_agents baseline issues; its formatter changes to previously clean unrelated files were restored. No unrelated changes retained, no hook bypass.
- Final regression rerun checks the actual formatted/type-corrected tree before commit. Review ledger remains unspent; gateFixes=1 for Stage 2.
