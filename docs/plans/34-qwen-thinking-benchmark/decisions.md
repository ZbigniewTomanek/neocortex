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
