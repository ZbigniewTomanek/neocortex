# Stage 8: Decision, report, and Plan 33 handoff

**Goal**: Apply the Plan 33 rubric per agent, publish the ASD-STE100 technical report, set the validated Qwen defaults where a `MIGRATE` exists, and hand the result to Plan 33 Stage 9.
**Dependencies**: 7

No live model call.

---

## Steps

1. Decision table.
   - Where: new `resources/decision.md`.
   - Details: one row per agent (ontology, extractor, librarian, domain classifier) with the selected level
     from `resources/effort-sweep.json`, the five E2E exit codes, Plan 15 and Plan 17 scores, the sample
     result, the skip-attribution result, and the verdict. These arrive as Stage 7 REPORT values (D-7), so
     this stage always runs and always publishes: `MIGRATE` requires every rubric input measured and
     passing; any failed or `NOT MEASURED` input is `HOLD`. Each cell cites the artifact path it was read
     from. If Stage 5's cancellation rule fired, say plainly that the endpoint ignores `reasoning_effort`,
     that `off` is therefore the only supportable setting, and that no per-agent level was selectable.

2. Defaults and rollback (only for agents with `MIGRATE`).
   - Where: the local Qwen block in `.env.example`; the local-model section of `docs/development.md`;
     `resources/commands.md` in this plan.
   - Details: document `NEOCORTEX_<AGENT>_THINKING_EFFORT` values (boolean `false` for off) and the model
     ids as the validated local configuration; rollback is the hosted configuration already documented.
     Do not change `MCPSettings` defaults, which serve hosted models too.

3. Technical report.
   - Where: new `resources/report.md`, written with the `simple-english` skill rules (ASD-STE100).
   - Details: what was measured, which levels the endpoint distinguishes, the per-agent results, the root
     causes fixed in Stages 3–4, what remains, and the next action. Numbers cite their artifact.

4. Plan 33 handoff.
   - Where: `docs/plans/33-local-qwen-migration/backlog.md` item 16 and `journal.md`.
   - Details: set item 16 to `RESOLVED` with the skip-events and sample paths if the Stage 7 evidence was
     green, otherwise `DEFERRED → 34` with the reason. Append one journal entry in Plan 33 naming this
     plan's decision file so Stage 9 can consume it. Do not change Plan 33 `state.json` statuses.

5. Lessons.
   - Where: `docs/plans/LESSONS.md`.
   - Details: add one line per durable fact learned in this run (level aliasing result, what the merge
     fix needed, any harness gotcha), linking this plan.

---

## Verification

- [ ] GATE decision provenance — every verdict in `resources/decision.md` cites an artifact path that exists in the repository and a `MIGRATE` row has no `NOT MEASURED` input; a verdict without a path, or a `MIGRATE` over a missing measurement, turns it red.
- [ ] REPORT `uv run pytest tests/ -q` and `uv run ruff check .` — documentation-only stage; record the result.
- [ ] REPORT the per-agent verdicts and the report path — record in `journal.md`.

---

## Commit

`docs(plan): record Qwen thinking benchmark decision`
