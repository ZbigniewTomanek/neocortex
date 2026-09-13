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

## 2026-09-13 -- Stage 2 committed/reviewing; disjoint Stage 4 work starts

- Stage 2 commit `8932147` exists; all commit hooks pass. Final suite 1,404 passed / 7 skipped in 42.52 s (`validation/stage2-suite-coordinator-attempt2.txt`). Independent codex/gpt-5.6-sol/high post-review dispatched, one review only.
- Parallel exception: Stage4 assignment A1 has its own brief `briefs/stage4-instruments-brief.md`, limited to speed probe/fact scorer and their two unit files. It shares no file with Stage2's reviewed implementation/brief scope. Extraction prompt/merge changes wait for review completion.
- Stage5 offline implementation is frozen and remains uncommitted; live proof waits for the Stage4 baseline as planned. No live model call yet.

## 2026-09-13 -- Pre-measurement probe gaps promoted into Stage 4 A1

- Implementer traced `--classify --test-model`: `_classify` ignores use_test_model and builds a real AgentDomainClassifier, potentially contacting the hosted default during a mock run. Added probe-local scoped TestModel factory override and live-request denial to A1; no hosted/product classifier code changes.
- Raw unit summaries lack `critical_defects`, so Stage6's selected-level gate could not be measured from its own artifacts. A1 now records observed graph/validation defects and preserves explicit unknowns; no default clean row for an unlaunched unit.
- These are prerequisite instrument corrections before live calls, not a reason to rerun live measurements later. A1's file scope remains disjoint from Stage2 review.

## 2026-09-13 -- Review time bounded

- Stage2 reviewer proposed a further 20–30 minute axis pass after reading the scope. Coordinator bounded remaining work to five minutes to finish/refute existing concrete candidates and return one complete set, consistent with the owner's standing review/validation-trap constraint.
- No correctness finding is waived; unverified ideas must be dropped rather than assigned a severity. Review ledger is consumed only when the final set is on disk.
- Local settings validation now passes without editing .env; prior backlog5 malformed-setting condition is not reproduced on this machine.

## 2026-09-13 -- Stage 2 review spent, one fix accepted

- Complete review stored before triage in validation/stage2-review.md; ledger spent. One P2 BLOCKING F1, two candidates refuted.
- Coordinator reproduced F1: episodic cross-session heading followed by Stage3 is wrongly returned as scenario heading. Both literals verified in the child. Accepted as incorrect diagnostic evidence.
- Stage2 brief corrected in place; fix1 brief freezes scope to banner parser and its tests. One fix/no re-review. Dispatch waits for Stage4 A1 write-lock release.

## 2026-09-13 -- A1 releases write lock; Stage 2 fix starts

- Stage4 A1 returned its four-file implementation: 54 focused tests passed; formatter, lint and whole-tree type checks passed. No live calls. Frozen pending coordinator inspection and the remaining Stage4 assignments.
- Docker recheck confirms local PostgreSQL and tailscale healthy. Existing Stage1 commit resolves in git; no spent review reset on resume.
- Stage2 fix1 dispatched to codex/gpt-5.6-sol/high, limited to the reproduced F1 and its tests. No concurrent feature writer and no re-review.

## 2026-09-13 -- A1 coordinator gate and baseline environment

- Coordinator reran both instrument test files: 54 passed in 0.73 s (`validation/stage4-instruments-coordinator-attempt1.txt`) and inspected all four diffs.
- Before live use, a bounded read-only strong assignment checks whether timeout events would incorrectly disqualify a permitted single timeout; no new review round is being run.
- Stage4 live brief now explicitly unsets Google/Gemini keys for in-memory probes: existing resolve_embeddings otherwise enables hosted embeddings when ambient keys exist. The intended offline scoring path uses embeddings=none. Local model base URL is pinned; no environment file or hosted product code changes.

## 2026-09-13 -- A1 measurement correction queued before live use

- Strong diagnosis demonstrated normalizer drift (DishGreg/Functiondefault/FUNCTIONDEFAULT wrongly accepted) and expected timeouts wrongly labeled critical failures. Coordinator traced public normalization rejection and independently reproduced timeout -> [agent_run_failure].
- Accepted both as measurement correctness defects. Two-file gate correction brief written; dispatch waits for Stage2 fix to finish. This is a pre-review gate fix, not a new review round.
- The correction must preserve independent real defects during timeout; no blanket clean result. A2's final suite will cover the corrected tree.

## 2026-09-13 -- Stage 2 fix1 accepted

- F1 correction inspected against the complete finding: child-aware parsing reports the later episodic Stage3, preserves Plan15/17 scenario priority. Coordinator reproduced exact corrected tuple; no rereview.
- Focused 84 passed in 6.27 s; full suite 1,413 passed / 7 skipped in 43.48 s; all scoped hooks pass. Raw evidence in validation/stage2-fix1-*-attempt1.txt.
- Repair budget consumed (one round); implementation and single fix are complete. Stage4 A1 remains frozen, Stage5 offline files remain untouched; only Stage2 files and coordinator run records are staged for the fix commit.

## 2026-09-13 -- Stage 2 DONE; Stage 4 resumes

- Fix commit d639284 created with all hooks passing; Stage2 DONE with commits 8932147 and d639284. Review and repair flags remain spent.
- Dispatch Stage4's bounded A1 gate correction as the sole writer. A2 follows sequentially; no further Stage2 review or work.

## 2026-09-13 -- Stage 3 formatter diagnosis prepared

- Read-only codex/gpt-5.6-sol/high assignment ran in parallel with Stage4 writes. Existing recall-session tests: 14 passed in 0.44 s. Direct InMemory recall returned one episode, source_kind=episode, valid JSON context, not the placeholder.
- No defect reproduced; no product fix justified. Stage3 brief carries this REPORT-only limitation to avoid speculative formatter changes.
- Live diagnosis needs PostgreSQL-backed results' safe source kinds/counts/ids and placeholder boolean after terminal extraction, tied to revision/run identity. Source text is not required.
- Prepared a draft Stage8 brief using the mandated simple-english rules; no verdict or report value is invented before live evidence.

## 2026-09-13 -- Stage 4 A1 accepted; scalar assignment A2 starts

- Inspected gatefix1: public normalizers replace copied rules; APITimeoutError becomes timeout; timeout-caused failure events no longer become critical defects. Independent stored marker remains critical during timeout.
- Focused 63 tests pass with real delayed TestModel/provider-timeout regressions; scoped hooks pass. Coordinator rerun evidence: validation/stage4-instruments-gatefix1-coordinator-attempt1.txt.
- A1 writer released. Dispatch A2 under briefs/stage4-scalars-brief.md, codex/gpt-5.6-sol/high, sole writer. S05 must run red before product edits. Full-suite and exact mock baseline follow the scalar changes; live remains undispatched.

## 2026-09-13 -- Stage 7 external embedding authority clarified

- Read-only preflight found model_bakeoff.sh requires GOOGLE_API_KEY and makes a real Gemini embedding health request. Saved allowed actions cover local Qwen calls and exclude spending money/external service calls.
- Asked owner asynchronously for Stage7-only embedding approval before that stage. No external call issued. Stage7 brief explicitly prevents launch pending the answer; independent offline/local work can continue.

## 2026-09-13 -- Stage 4 scalar regression is red before the fix

- A2 saved validation/stage4-s05-red-attempt1.txt before product edits. S05 fails `assert "April 15" not in merged.content` because content contains both the old April15 sentence and new May1 sentence.
- The stored property already has May1, demonstrating the content/property mismatch rather than a missing property update. Coordinator read the failing output. A2 now implements the bounded merge/rendering correction.

## 2026-09-13 -- Scalar gate catches cross-property rewriting

- Coordinator inspected A2's four-file diff and exact mock JSON: 11/11 synthetic units ok, embeddings none, expected fact/triplet observations present. Synthetic quality is not live quality.
- Direct deterministic call with old retries15/timeout16 and new retries16/timeout17 returned `Retries 17, timeout 17.` Sequential value replacement rewrote the valid new retries value through the other property's old value.
- Accepted as scalar data corruption within the declared merge contract. A2 brief corrected with this exact regression and a non-cascading policy that preserves incoming text. Strong implementer retains sole writer for the gate correction; no review or live run consumed.

## 2026-09-13 -- Stage 4 deterministic implementation accepted

- A2 corrected simultaneous replacements; coordinator's exact retries15/timeout16 -> retries16/timeout17 call now returns `Retries 16, timeout 17.` All eight Stage4 source/test diffs inspected.
- Focused 118 passed, hosted 14 passed, full suite 1,429 passed / 7 skipped, scoped hooks and lint passed. Required S05 red evidence remains separate. Hosted extractor/librarian prompt AST hashes match 8766e90; other hosted branches unchanged by Stage4.
- Exact TestModel baseline: 11/11 units ok in 0.08 s, embeddings none. Eight synthetic fact scores 0/56; triplets have new_present=false and old_absent=true. This proves the instrument, not model quality. Coordinator runs the final same-command mock with its own durable JSON.
- Promoted backlog6/7/8/10/11 resolved; Stage1 stays DONE. Formatter non-reproduction and hook observation limits recorded as backlog13/14.
- Commit/review precede live proof per protocol. Stage3 can write during committed Stage4 review because their source scopes are disjoint; neither stage may change the other's files.

## 2026-09-13 -- Stage 4 committed/reviewing; Stage 3 writes

- Stage4 implementation commit 2f199a3 exists. Commit hook added only the missing final newline to the mock JSON, then all hooks passed; numeric/artifact values unchanged.
- Single independent codex/gpt-5.6-sol/high post-review dispatched with a ten-minute scope budget. Live baseline remains deferred until findings are triaged/fixed.
- Stage3 starts on codex/gpt-5.6-sol/high under its existing brief while review reads committed Stage4. Source scopes do not intersect; no second feature writer. This is the protocol's committed-review exception.

## 2026-09-13 -- Owner proceeds and grants Stage7 embeddings

- Owner: "proceed", after the status response explicitly named the pending Stage7 Gemini embedding approval. Coordinator announced the bounded interpretation and recorded it in goal.md and the Stage7 brief.
- Authorized: Gemini embedding calls and their API cost for the bounded Stage7 service benchmark, existing key only. No hosted reasoning calls or in-memory-probe embeddings. All other limits and review budgets unchanged.
- Existing Stage3 writer and Stage4 reviewer remain active; no duplicate dispatch or spent-ledger reset.

## 2026-09-13 -- Stage4 review spent; two findings accepted

- Complete review saved before triage in validation/stage4-review.md; ledger spent. F1 display projection omits ninth conflict key; F2 value-only replacement corrupts unchanged same-valued facts or leaves stale ambiguous values.
- Coordinator independently reproduced all three concrete examples and accepted F1/F2. New fix1 brief is self-contained and corrects the scalar brief. One fix, no re-review; no hosted/model-authored scope expansion.
- Stage3 asked to pause after its current atomic edit and preserve its work. Stage4 fix waits for its write-lock release; no concurrent feature writer.

## 2026-09-13 -- Stage3 checkpoint; Stage4 fix1 starts

- Stage3 released lock with e2e_common and its tests saved (9 passed/0.02s), plus cognitive, episodic and weight child integrations. Formatter reproduction green (1 passed/0.43s), no product change or retained never-red test.
- Remaining Stage3: Plan15/17, content-update, extraction child; shell readiness; final gates. Failed combined Plan15/17 patch was atomic and left both unchanged.
- Dispatch Stage4 fix1 under its frozen brief, sole codex/gpt-5.6-sol/high writer. Resume Stage3 checkpoint afterward.

## 2026-09-13 -- Stage4 fix verification, same F2 round

- Initial fix1 passes all reviewed examples, 122 focused/14 hosted, full1442/7 and fresh mock11/11. Full lint identifies only paused Stage3's Mapping import; Stage4 owner does not edit it.
- Coordinator's F2 fallback check finds one unlabeled occurrence shared by two changed properties is arbitrarily rewritten to the first new value. This contradicts the claimed conservative fallback; exact input added to fix brief.
- Same F2 verification correction dispatched, no new finding/review/repair round. Require unique property ownership for unlabeled fallback. Final full suite waits until the sequential Stage3 import correction.

## 2026-09-13 -- F2 attribution verification and checkpoint lint

- Stage3 owner moved Mapping to collections.abc, helper9 tests and scoped ruff pass, then released lock. No broader Stage3 edits.
- F2 verification continues within the same fix: mixed int/string owners are identical in text, and generic threshold suffix matching still changes Retry threshold15 when only error_threshold changes. Coordinator reproduced the latter as Retry threshold16/Error threshold16.
- Tightened fix brief to string-based owner identity, full property labels and direct label/value association. These enforce the original unchanged-fact guarantee; no new review round, live call, or expanded feature scope.

## 2026-09-13 -- Stage4 single fix accepted on final evidence

- Complete fix diff inspected against F1/F2; reproduced corrected ninth-property, unchanged-team-size, two-property update and ambiguous-owner values. Conservative ambiguous text remains, with incoming description appended; no false attribution.
- Coordinator final focused125 pass/0.92s, full1445 pass/7 skipped/44.18s, whole-tree lint pass. Exact fresh mock11/11 ok, no critical defects, embeddings none, 0.08s. Evidence uses new stage4-fix1-*-coordinator-attempt1 files.
- Review and one repair consumed. No re-review. Stage3 checkpoint import lint corrected by its owner; unrelated source files stay unstaged for Stage4 fix commit.

## 2026-09-13 -- Stage4 fix committed; first live baseline launched

- Fix commit639b0d6 exists, hooks pass after final-newline-only normalization of mock JSON. Stage4 source is frozen; no re-review.
- First live inference launch: 13:19:43 UTC, PID88591, nohup under .tmp/plan34/sweep/off.log, incremental off.json. Exact tested command: corpus both, fixture, all thinking off, per-call300s, episode600s, max-wall1200s, live cache .tmp/plan34/cache.
- Endpoint model listing passes. Google/Gemini keys unset in probe process, embeddings none by construction. No prior off.json/log existed; no measurement overwritten. Next poll no earlier than13:24:43 UTC.
- Stage3 resumes as sole source writer. Coordinator's Stage4 live gate reads only frozen probe/extraction files and writes its separate measurement outputs; no Stage3 scope file is used by this in-memory run. No concurrent feature writer.

## 2026-09-13 -- First baseline poll has no measurement

- At13:25:16 UTC (more than five minutes after launch), PID88591 is absent, off.json does not exist, and off.log is empty. No completed inference or episode can be established from this attempt. NOT MEASURED, not a model failure or a zero-call claim.
- Strong bounded read-only launch-lifecycle diagnosis dispatched using harmless subprocess tests only; no model relaunch authorized. Stage3 source writer continues independently.
- Original Stage4 budget starts13:19:43 UTC and expires13:39:43 UTC; no silent reset. Any corrected launch needs the root cause and decision recorded first.

## 2026-09-13 -- Stage3 gate corrections

- Coordinator inspection found Plan15/17 all-failed handlers omitted the original routing-idle condition. Require route_active==0 before returning; other assertions unchanged.
- Full-suite attempt1: two cleanup-fixture failures, 1443 passed/7 skipped. New real readiness checks reached localhost because the fixture fakes manage.sh/uv but not curl, adding two60s waits.
- Coordinator inspected the fixture and authorizes a bounded test-scope extension: fake curl, preserve cleanup assertions, assert health calls precede fake test execution. Stage3 brief corrected; no production readiness bypass. Count as pre-review gatefix1.

## 2026-09-13 -- Baseline launch diagnosis and bounded correction

- Strong read-only diagnosis reproduced command-boundary cleanup on two harmless nohup jobs. Managed asynchronous sessions survive; launchd was rejected because its default can restart jobs.
- D-16 records the execution-method correction before any new inference. Original attempt remains NOT MEASURED; no claim of zero requests. Attempt2 uses separate paths and only time remaining before13:39:43 UTC.
- Stage3 implementer released the lock: final suite1445 passed/7 skipped, helper9 passed, lint and scoped hooks pass. Coordinator inspection and commit/review follow; no source writer active.
