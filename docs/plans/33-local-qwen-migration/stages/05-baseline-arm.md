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
     NEOCORTEX_WORKER_CONCURRENCY=2
     ```
     Do **not** tune the models or efforts. The baseline is the status quo, not an optimised hosted
     arm — the question this plan answers is "can local Qwen replace what runs today", not "which
     model wins when both are tuned".
   - **`worker_concurrency=2` is deliberate and non-negotiable (D11)**, even though the hosted arm
     could run at the default 4. The Qwen arm must run at 2 to respect SGLang's
     `max_running_requests=8`, and concurrency is **not** a quality-neutral knob: each ontology agent
     is seeded with a type snapshot taken when its job starts, and types are created with
     `INSERT … ON CONFLICT DO NOTHING` (`db/adapter.py:550-560`, whose own comment reads "Concurrent
     insert won — fetch the existing row"). Fewer parallel jobs means each extraction sees more of its
     siblings' committed types, which moves the active type counts, unused edge %, and reuse ratio
     that Tier 2 gates on. Equal concurrency costs this arm wall-clock and buys a clean comparison.

2. **Run the arm twice (D12).**
   - Details: `./scripts/model_bakeoff.sh --arm baseline-gpt54mini` and then
     `--arm baseline-gpt54mini-run2`.
     Expect roughly 28 episodes × (3 extraction agents + routing). Plan 29 measured **59.3 s average
     extraction time over 42 extractions**, and Plan 32 recorded 37 extraction+routing jobs in ~450 s
     at 4 workers — at 2 workers budget ~60–90 minutes per run, plus the five e2e scripts.
   - Two runs exist to **measure run-to-run variance**, which this plan has never had and which every
     Tier 2 tolerance silently assumes. Nothing pins temperature or a seed on either arm (local runs at
     0.6), so a one-scenario delta on a 14-point gate may be pure sampling noise. Record the spread of
     every Tier 2 metric across the two runs; step 5 uses it. If the two runs disagree wildly on a
     metric, say so plainly — that metric is not gate-worthy at n=1 and should be recorded as Tier 3
     instead.
   - Use run 1 as the reported baseline; run 2 is the variance probe, not an average.

3. **Confirm the run is clean before trusting it.**
   - Details: check `GET /admin/jobs/summary` — `failed` should be near zero. Plan 23 recorded a
     **29% extraction failure rate** as a historical baseline; if this arm reproduces anything like
     that, the harness or the environment is broken, not the model. Investigate before recording.

4. **Record the numbers into the index.**
   - File: `docs/plans/33-local-qwen-migration/index.md`
   - Details: fill the "Baseline" column of both the Tier 1 and Tier 2 tables from
     `resources/metrics-baseline-gpt54mini.json`. Write `NOT MEASURED` for anything that could not
     be captured, and add a Backlog entry for each — never estimate.

5. **Derive the concrete Tier 2 thresholds, widened by the measured spread.**
   - Details: the index states Tier 2 targets relatively ("≥ baseline − 1", "within ±25%", "≥ baseline
     × 0.75"). Resolve them to **absolute numbers now**, before the Qwen arm runs, and write them
     into the index's target column as e.g. `≥ 11/14 (abs: ≥ 12 given baseline 13)`.
     Fixing the goalposts before seeing the Qwen result is what keeps Stage 7 honest.
   - **Any tolerance narrower than the two runs' observed spread must be widened to exceed it (D12)**,
     and the widening recorded with the two measurements that justified it. A gate that cannot
     distinguish a regression from a re-run is not measuring the model. This is the *only* sanctioned
     edit to a Target cell in the whole plan, it happens here — before any Qwen number exists — and
     Stage 7's "never edit a threshold" rule takes effect immediately after.
   - The three ontology-size rows (active node types, active edge types, unused edge %) are already
     relative-only in the index; do **not** reintroduce Plan 28's absolute ranges when resolving them.
     Plan 29 measured 6–32 / 0–22 / 46–100% against those exact targets and attributed the misses to
     corpus volume and seed-ontology size, not extraction quality.

6. **Snapshot and archive.**
   - Details: `./scripts/manage.sh snapshot save baseline-gpt54mini`. Copy
     `log/agent_actions.log` to `resources/logs-baseline-gpt54mini.log` — it holds the per-stage
     timings and token counts Tier 3 needs, and the next `--fresh` start will rotate it away.

---

## Verification

- [ ] `resources/metrics-baseline-gpt54mini.json` **and** `-run2.json` exist, and every Tier 1 and
      Tier 2 field is populated or explicitly `NOT MEASURED`.
- [ ] All 28 episodes ingested in both runs; episodes-consolidated ≥ 90%.
- [ ] Job failure rate recorded; if > 10%, the run is quarantined and re-run rather than accepted
      as a baseline.
- [ ] Both runs used `worker_concurrency=2`, and the metrics JSON records it.
- [ ] The per-metric spread between the two runs is written into the stage notes.
- [ ] Index Tier 1 and Tier 2 "Baseline" columns filled in.
- [ ] Tier 2 relative targets resolved to absolute numbers **in the index**, each ≥ the observed spread.
- [ ] `./scripts/manage.sh snapshot list` shows `baseline-gpt54mini`.
- [ ] `resources/logs-baseline-gpt54mini.log` archived (it carries the Tier 1c rejection events).

---

## Commit

`test(models): record GPT-5.4-mini baseline arm metrics`
