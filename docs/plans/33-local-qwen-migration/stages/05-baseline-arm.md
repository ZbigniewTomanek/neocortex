# Stage 5: Baseline Arm — GPT-5.4-mini

**Goal**: Measure the current hosted configuration on the hardened prompts, producing the reference numbers every Tier 2 target is scored against.
**Dependencies**: Stages 3 and 4 DONE.

---

## Why this arm is not optional

NeoCortex has never measured itself end-to-end with a script. The numbers scattered through
Plans 18.5, 22, 23, and 29 were produced by hand, on different corpora, at different times, on
**Gemini Flash** — not on the `openai-responses:gpt-5.4-mini` that runs today. Commit `e74b441`
switched models with **no before/after quality measurement attached**. So there is no usable
prior baseline: it has to be measured now, on this corpus, with these prompts.

---

## Steps

1. **Pin the configuration.**
   - Details: all four agents on the current hosted defaults, unchanged:
     ```
     NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini          THINKING_EFFORT=medium
     NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini         THINKING_EFFORT=low
     NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini         THINKING_EFFORT=low
     NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini THINKING_EFFORT=medium
     ```
     Do **not** tune these. The baseline is the status quo, not an optimised hosted arm — the
     question this plan answers is "can local Qwen replace what runs today", not "which model wins
     when both are tuned".

2. **Run the arm.**
   - Details: `./scripts/model_bakeoff.sh --arm baseline-gpt54mini`.
     Expect roughly 28 episodes × (3 extraction agents + routing). Plan 29 measured **59.3 s average
     extraction time over 42 extractions**, and Plan 32 recorded 37 extraction+routing jobs in ~450 s
     at `worker_concurrency=4`, so budget ~30–45 minutes plus the five e2e scripts.

3. **Confirm the run is clean before trusting it.**
   - Details: check `GET /admin/jobs/summary` — `failed` should be near zero. Plan 23 recorded a
     **29% extraction failure rate** as a historical baseline; if this arm reproduces anything like
     that, the harness or the environment is broken, not the model. Investigate before recording.

4. **Record the numbers into the index.**
   - File: `docs/plans/33-local-qwen-migration/index.md`
   - Details: fill the "Baseline" column of both the Tier 1 and Tier 2 tables from
     `resources/metrics-baseline-gpt54mini.json`. Write `NOT MEASURED` for anything that could not
     be captured, and add a Backlog entry for each — never estimate.

5. **Derive the concrete Tier 2 thresholds.**
   - Details: the index states Tier 2 targets relatively ("≥ baseline − 1", "within ±25%", "≥ baseline
     × 0.75"). Resolve them to **absolute numbers now**, before the Qwen arm runs, and write them
     into the index's target column as e.g. `≥ 11/14 (abs: ≥ 12 given baseline 13)`.
     Fixing the goalposts before seeing the Qwen result is what keeps Stage 7 honest.

6. **Snapshot and archive.**
   - Details: `./scripts/manage.sh snapshot save baseline-gpt54mini`. Copy
     `log/agent_actions.log` to `resources/logs-baseline-gpt54mini.log` — it holds the per-stage
     timings and token counts Tier 3 needs, and the next `--fresh` start will rotate it away.

---

## Verification

- [ ] `resources/metrics-baseline-gpt54mini.json` exists and every Tier 1 and Tier 2 field is
      populated or explicitly `NOT MEASURED`.
- [ ] All 28 episodes ingested; episodes-consolidated ≥ 90%.
- [ ] Job failure rate recorded; if > 10%, the run is quarantined and re-run rather than accepted
      as a baseline.
- [ ] Index Tier 1 and Tier 2 "Baseline" columns filled in.
- [ ] Tier 2 relative targets resolved to absolute numbers **in the index**.
- [ ] `./scripts/manage.sh snapshot list` shows `baseline-gpt54mini`.
- [ ] `resources/logs-baseline-gpt54mini.log` archived.

---

## Commit

`test(models): record GPT-5.4-mini baseline arm metrics`
