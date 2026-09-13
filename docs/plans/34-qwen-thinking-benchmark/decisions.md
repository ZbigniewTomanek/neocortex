# Decisions

Append-only. **<=15 lines per entry** -- detail goes in `resources/`.

```
### D-N: [Title]
**Date**: YYYY-MM-DD - **Stage**: N (or "planning")
**Options**: A) [...] B) [...]
**Chosen**: [Option]
**Rationale**: [Why -- 1-3 lines]
```

An amendment to a success criterion uses this shape instead:

```
### D-N: Amend [criterion name]
**Date**: YYYY-MM-DD - **Stage**: N - **Type**: AMENDMENT
**Original**: "[quote verbatim]"
**Replacement**: "[new criterion]"
**Evidence**: [what proved the criterion was the defect -- link the journal entry]
**Class**: measurement (amendable). [Why this is not a correctness criterion.]
```

---

### D-1: Sweep `off`, `low`, `medium`, `high`; exclude `xhigh`
**Date**: 2026-09-11 - **Stage**: planning
**Options**: A) all five levels B) four levels without `xhigh` C) `off`, `medium`, `high` only
**Chosen**: B (owner choice, 2026-09-11).
**Rationale**: Plan 33 D28 prefers the lowest passing effort and the owner ruled out multi-hour `xhigh`
runs. Stage 5 first checks which levels the endpoint distinguishes so aliases are not swept twice.

### D-2: Fix numeric-fact loss before the sweep
**Date**: 2026-09-11 - **Stage**: planning
**Options**: A) sweep on current code, fix later B) fix the Qwen extractor prompt and one-shot merge first
**Chosen**: B (owner choice, 2026-09-11).
**Rationale**: All three failing quality scenarios (Plan 15 S05/S11, Plan 17 S07) are one defect: the
newer scalar never reaches node content. Sweeping without the fix measures the merge bug, not thinking.

### D-3: Keep the Plan 33 absolute rubric as the ship gate
**Date**: 2026-09-11 - **Stage**: planning
**Options**: A) keep the rubric B) Plan 15/17 only C) report only
**Chosen**: A (owner choice, 2026-09-11). Five E2E exit 0, Plan 15 ≥ 11/14, Plan 17 ≥ 13/14 with 0 FAIL,
real 20/20 sample. Any `NOT MEASURED` input is `HOLD`.
**Rationale**: Comparable verdict with Plan 33; the rubric is a REPORT decision rule, so a `HOLD` still
lets Stage 8 finish `DONE`.

### D-4: Sweep on the in-memory probe, run services once
**Date**: 2026-09-11 - **Stage**: planning
**Options**: A) one full bake-off per level B) per-agent sweep in `qwen_speed_probe.py` with cached
upstream stages and an offline fact-retention scorer, then one tuned service arm
**Chosen**: B.
**Rationale**: A costs four to eight service runs of 40–90 minutes each with no per-agent attribution. B
gives one live measurement per cell in minutes, a fixed selection rule, and one service arm for the
rubric. Backend drift between in-memory and PostgreSQL (Plan 33 backlog 5) is accepted for level
selection and is covered by the service arm for the verdict.

### D-5: Every live measurement is bounded, detached, and run once
**Date**: 2026-09-11 - **Stage**: planning
**Chosen**: 300 s per-call timeout, per-stage wall budgets (20 min / 20 min / 4 h / 2 h per arm), `nohup`
with incremental JSON, `--test-model` before every live command, at most two service arms.
**Rationale**: The `.tmp/qwen-harness-tuning` run lost about 10 of 13 hours to unvalidated live probes,
one uncapped 3 h 18 min call, and full-matrix reruns. The `.tmp/qwen-swift` run finished in 4 h 22 min
with these rules.

### D-6: Relay every Qwen thinking level to the request
**Date**: 2026-09-11 - **Stage**: planning (pre-review)
**Options**: A) sweep as planned B) fix the client relay first, then sweep C) abandon the sweep
**Chosen**: B.
**Rationale**: `build_model` wires a plain `OpenAIProvider`, whose profile reports `supports_thinking=False`,
so `Model.prepare_request` dropped `thinking` and `_get_reasoning_effort` omitted the field. `low`, `medium`
and `high` put byte-identical requests on the wire; only `off` differed, via its explicit
`openai_reasoning_effort="none"`. Plan 33's `probe-results-{low,medium,high,xhigh}.json` confirm it (medians
196 / 229 / 224 / 180, every pair an alias). Stages 5-7 would have measured sampling noise and published a
false root cause. Fix: `build_model_settings` restates every level through `openai_reasoning_effort` using
PydanticAI's own `OPENAI_REASONING_EFFORT_MAP`, inside the existing Qwen-only branch, so hosted and
local-non-Qwen settings are unchanged (guardrail 9 holds). Two exact-equality tests that pinned the old
shape were updated and three request-level guards added. This fixes the client only; whether the server
honours `reasoning_effort` is Stage 5's positive control.

### D-7: Stage 7 evidence lines are REPORT, not GATE
**Date**: 2026-09-11 - **Stage**: planning (pre-review)
**Options**: A) keep four blocking GATEs B) demote to REPORT, keep one artifact-existence GATE
**Chosen**: B.
**Rationale**: PROTOCOL makes a stage with an unmet gate and an essential deferral `BLOCKED`, and `state.json`
wires Stage 8 `depends_on: [7]`, so a red evidence gate left Stage 8 permanently `PENDING` — no decision
table, no report, no handoff. Red is the expected case (swift3: 0/5 E2E, failing supersession), and D-3
already intends a `HOLD` to be publishable. The rubric in Stage 8 treats any failed or `NOT MEASURED` input
as `HOLD`, so demoting loses no rigour and restores the deliverable. One GATE remains: the arm ran and its
artifacts exist, because Stage 8 cannot compute a verdict from nothing.

### D-8: Every agent gets its own `off` cell at its pinned upstream configuration
**Date**: 2026-09-11 - **Stage**: planning (pre-review)
**Options**: A) reuse Stage 4's all-off baseline for all four agents B) one `off` cell per agent
**Chosen**: B.
**Rationale**: Stage 4's baseline ran every agent at `off`, so it is a valid `off` row for the extractor only.
Steps 2-4 pin upstream agents at `L_ext`/`L_lib`, and the classifier never ran in Stage 4 at all, so three of
four agents had no `off` row and the selection rule could never choose `off` — against D28. Four extra cells,
the cheapest in the sweep. The selection rule now ranks triplet passes first (the defect class `facts_found`
cannot see, because the scorer also matches `properties`), then `facts_found`, then explicitly prefers the
lowest level within the tie band.

### D-9: `--corpus` gains an `episodes` default instead of changing `--episodes`
**Date**: 2026-09-11 - **Stage**: 1
**Options**: A) `--corpus {compact,supersession,both}` as the plan writes it, with `--episodes` defaulting
to all eight B) add a fourth value `episodes` and make it the default
**Chosen**: B.
**Rationale**: `test_cli_defaults` pins `--episodes` to `["E04","E05"]`. Option A would have to change
that assertion to make the stage pass, which the protocol forbids. `--corpus episodes` (default) keeps
every existing invocation and the test byte-identical; `compact` and `both` select all eight keys, which
is what Stage 4's and Stage 6's commands need (Stage 6 counts 14 model runs = 8 compact + 3 triplets x 2).

### D-10: The extraction cache key covers the ontology and extractor levels, not the librarian's
**Date**: 2026-09-11 - **Stage**: 1
**Options**: A) all four per-agent levels in the key, as "each agent's level" reads literally
B) only the levels that produce the cached artifact
**Chosen**: B.
**Rationale**: The cache holds an `ExtractionResult` plus its ontology snapshot — artifacts the librarian
never influences. Option A breaks Stage 6 step 2, whose design is a librarian sweep reusing one
extraction cached at the pinned `L_ext`: a single-valued `--cache-thinking` cannot express a per-agent
key, so every librarian cell would miss the cache and re-run extraction, multiplying the 4 h budget.
Option B satisfies the stage's stated requirement — "a librarian-only rerun cannot silently reuse an
extraction produced at another extractor level" — because the extractor level is in the key. The
invariant is asserted in `test_cache_key_is_setup_specific` rather than left to the docstring.

### D-11: A triplet row's `fact_score` is `null`, not a zero-valued score
**Date**: 2026-09-11 - **Stage**: 1
**Options**: A) emit `{"facts_total": 0, "facts_found": 0}` for supersession rows so every row has a
numeric score B) emit `null`
**Chosen**: B.
**Rationale**: The fixture defines no `facts[]` for triplets. A `0/0` row serializes as a measured
full-marks score and would inflate any later aggregate; `null` says "not scored here", and the triplet's
real measurement is its `supersession` object. Stage 1's gate reads the presence of the `fact_score` key,
which `null` satisfies. Consistent with the `goal.md` invariant against rows generated to satisfy a count.

### D-12: The two new JSON Schemas live in this plan's `resources/`, not Plan 33's
**Date**: 2026-09-11 - **Stage**: 2
**Options**: A) ship `skip-events.schema.json` beside the existing report schemas in
`docs/plans/33-local-qwen-migration/resources/` as the stage text says B) both new schemas in
`docs/plans/34-qwen-thinking-benchmark/resources/`
**Chosen**: B.
**Rationale**: Stage 2's own gate G2 proves Plan 33's `resources/` is byte-unchanged, and the stage
already routes `quality-sample-tuned.schema.json` to this plan's `resources/`. Splitting the two schemas
across directories would leave one of them in a tree the stage is simultaneously proving frozen. Stage 7
still writes its *evidence* into Plan 33's `resources/`, which is what the owner granted.

### D-13: The cap-drop audit event carries counts only, never endpoint names
**Date**: 2026-09-11 - **Stage**: 2
**Options**: A) log the dropped relations "with their endpoints" as the stage text says
B) log integer counts; return the endpoint pairs from a pure function for tests only
**Chosen**: B.
**Rationale**: At cap time no node ids exist yet, so the only available endpoints are entity *names* —
graph text. `log/agent_actions.log` is privacy-scanned and every other skip event carries integer ids
only; writing names there would create the leak Stage 2 exists to prevent. `count_capped_relations`
returns the pairs so the drop is still unit-testable, and `extractor_cardinality_capped` gains
`relations_dropped_by_cap`, `relations_before`, `relations_after`. Also chosen over changing
`cap_extraction_entities`'s return type, which would churn its existing tests and the identity check at
`pipeline.py:483` for no gain.

### D-14: Stage 3's structural gate checks all seven children, not the `= 120` literal
**Date**: 2026-09-11 - **Stage**: 3 - **Type**: strengthened gate, not an amendment
**Original gate**: "`git grep -n \"JOB_WAIT_TIMEOUT = 120\" scripts/` returns nothing, and each of the five
children imports `e2e_common`"
**As written in the brief**: `git grep -n "JOB_WAIT_TIMEOUT" scripts/` returns nothing, and all **seven**
files import `e2e_common`.
**Evidence**: only `e2e_cognitive_recall_test.py:70` and `e2e_weight_stability_test.py:75` carry the
literal `120`. The other five carry 300 or 600 (`e2e_extraction_pipeline_test.py:83`,
`e2e_episodic_memory_test.py:48`, `e2e_plan15_scenarios_test.py:57`, `e2e_plan17_validation.py:48`,
`e2e_content_update_test.py:47`). The original grep therefore goes green after changing two of seven
files, while five children keep a hosted-tuned constant.
**Rationale**: this tightens a gate rather than relaxing one, so the four-part amendment rule does not
apply. A gate that cannot fail on the defect it names is not a gate (PROTOCOL, Gates).

### D-15: `failure_step` prefers the scenario docstring over the phase banner
**Date**: 2026-09-11 - **Stage**: 2
**Options**: A) last banner printed wins, as the stage implies B) precedence: scenario docstring first,
then `=== Step`/`=== Stage`/`PHASE`
**Chosen**: B.
**Rationale**: inventory found a fourth convention the stage text does not mention —
`e2e_plan15_scenarios_test.py:852-855` and `e2e_plan17_validation.py` print `PHASE X:` banners **as well
as** `--- docstring ---` ones (`:951`, `:959`). Under "last wins", the two children whose failures the
rubric most needs attributed would resolve to a coarse phase name. The docstring localizes the failure to
one scenario. The matched convention is recorded as `failure_step_kind` so a coarse attribution is
visible as coarse.

### D-16: Keep live probes in managed asynchronous command sessions
**Date**: 2026-09-13 - **Stage**: 4
**Root cause**: the command runner kills shell-background children at command exit.
Two harmless `nohup ... &` experiments reproduced this; `disown` was unavailable.
The first baseline left an empty log and no JSON. Completed inference and zero calls
are both unproven: its measurement is NOT MEASURED, not a model failure.
**Change**: replace the shell-background launch with a foreground command retained
by the runner's asynchronous session. A harmless test survived intervening calls.
This is the detached execution mechanism for this harness, not a model-code change.
**Rerun boundary**: one corrected launch, distinct attempt2 paths, only the remaining
time before the original 13:39:43 UTC deadline. No reset of the 20-minute budget.
