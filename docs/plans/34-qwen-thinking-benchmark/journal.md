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
