# Stage 6: Qwen Arm

**Goal**: Run the identical bake-off against `local:qwen3.8-27b` and produce the comparison numbers Stage 7's gate consumes.
**Dependencies**: Stage 5 DONE (needs the baseline and its resolved absolute thresholds).

---

## Steps

1. **Pin the configuration — one variable only.**
   - Details:
     ```
     NEOCORTEX_LOCAL_MODEL_BASE_URL=http://z-spark.tail215ba1.ts.net:4000/v1
     VLLM_API_KEY=<from ~/projects/my-telegram-bot/.env, never committed>

     NEOCORTEX_ONTOLOGY_MODEL=local:qwen3.8-27b            THINKING_EFFORT=medium
     NEOCORTEX_EXTRACTOR_MODEL=local:qwen3.8-27b           THINKING_EFFORT=low
     NEOCORTEX_LIBRARIAN_MODEL=local:qwen3.8-27b           THINKING_EFFORT=low
     NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=local:qwen3.8-27b   THINKING_EFFORT=medium
     ```
     **Keep the effort levels identical to the baseline arm.** The comparison this stage makes is
     model-vs-model. Effort tuning is Stage 8's job and mixing the two would make both
     uninterpretable. If Stage 2's probe showed a level that is outright non-functional for an
     agent, use the nearest working level and record the deviation prominently in the arm notes as
     a confound.
   - Source the key without committing it:
     `export VLLM_API_KEY=$(grep -E '^VLLM_API_KEY=' ~/projects/my-telegram-bot/.env | cut -d= -f2-)`.
     Note that shell-sourcing that `.env` directly yields nothing for these values.

2. **Pre-flight the endpoint.**
   - Details: before starting, confirm
     `curl -s $NEOCORTEX_LOCAL_MODEL_BASE_URL/models -H "Authorization: Bearer $VLLM_API_KEY"`
     returns exactly `qwen3.8-27b`. If the endpoint is down, this is an **external blocker**: mark
     the stage BLOCKED, record it, and do not retry in a loop (see the index's endpoint-specific
     triage).

3. **Confirm worker concurrency matches the baseline arm.**
   - Details: SGLang runs `max_running_requests=8` on a single shared GB10 with p50 23 tok/s
     single-stream decode. Each extraction is 3 sequential agents with tool budgets of 30 and 150, so
     4 workers can present far more than 8 concurrent requests once tool loops are in flight —
     `NEOCORTEX_WORKER_CONCURRENCY=2` is required here.
   - **Stage 5 already ran the baseline at 2 as well (D11), so this is no longer a difference between
     the arms — verify it rather than record it as a confound.** The earlier draft of this plan set 2
     here only, on the reasoning that concurrency "affects throughput and not quality". That reasoning
     was wrong: each ontology agent is seeded with a type snapshot taken when its job starts and types
     are created with `INSERT … ON CONFLICT DO NOTHING`, so concurrency changes how much of each
     other's committed ontology sibling extractions see — moving the active type counts, unused edge %,
     and reuse ratio that Tier 2 gates on. If for any reason the baseline arm ran at a different
     concurrency, **re-run the baseline** rather than recording an asymmetry on a gating axis.

4. **Run the arm.**
   - Details: `./scripts/model_bakeoff.sh --arm qwen38-27b`.
     Expect this to take substantially longer than the baseline — the plan's scoping decision is
     that latency is measured, not gated (D3).
   - **Budget the job-completion poll at ≥ 4 h, not the 1800 s an earlier draft suggested.** Stage 5
     budgets the *faster* hosted arm at 60–90 min for the same 28 episodes at the same concurrency, and
     `resources/probes.md` Probe 5 measured the Qwen extractor **alone** at 124.8 s at `low` — one of
     three sequential agents, at the cheapest effort, with the librarian's 150-call tool budget still
     ahead of it. Per Stage 4 step 5 the orchestrator **aborts without writing metrics** if the poll
     expires with work outstanding; do not "rescue" a timed-out run by computing metrics on the partial
     graph, because the result is indistinguishable from a genuine collapse.

5. **Watch for the four predicted failure modes and count each one.**
   - Details:
     - **Silent refusal** — run succeeds, zero tool calls, prose output containing
       *"I can't verify"* / *"I have no record"*. This is the mode the 2026-08-19 probe hit and
       Stage 3 targeted; it is invisible to an exception counter because nothing throws.
     - **Terminal structured output dropped after a long tool loop** — the predicted librarian
       failure (9 tools, 150-call budget).
     - **Tool-budget exhaustion** — `UsageLimitExceeded` against the 30 / 150 limits.
     - **Leaked template markers** — `</think>`, `<tool_call>`, `<function=` in stored node names,
       type names, or content. Bot Plan 26 observed a stray `</think>` at `reasoning_effort=none`.
       **Read Tier 1c (rejection rate) as the primary signal here, not the stored-artifact scan.**
       After Stage 3 step 6, a leaked marker in a *type name* is rejected before it can be stored —
       `normalize_node_type` raises, `get_or_create_node_type` returns `None`, and
       `pipeline.py:448` drops the entity with a warning — so the stored-artifact and leak-scan rows
       will read 0 whether the model is clean or leaking constantly. A rejection rate materially
       above the baseline's *is* the leakage finding, and the rejected names in the metrics JSON are
       the evidence. The leak scan still matters for node **content** and node **names**, which the
       regex never guarded.

6. **Record everything into the index.**
   - File: `docs/plans/33-local-qwen-migration/index.md`
   - Details: fill the "Qwen" column of the Tier 1 and Tier 2 tables. Record Tier 3 (latency,
     tokens, tool calls, retries) in `resources/` and summarise in the stage notes.
     **A regression is a valid result — record it plainly.** Do not adjust a threshold, retry with
     a different effort level, or tweak a prompt to improve the number. If something clearly went
     wrong mechanically (endpoint flapped mid-run, jobs failed on connection errors), quarantine
     the run and repeat it rather than reporting a polluted result.

7. **Snapshot and archive.**
   - Details: `./scripts/manage.sh snapshot save qwen38-27b`, and copy `log/agent_actions.log` to
     `resources/logs-qwen38-27b.log`. Both arms' graphs must remain restorable so any disputed
     number in Stage 7 can be re-derived instead of re-run.

---

## Verification

- [ ] `resources/metrics-qwen38-27b.json` exists with every Tier 1 and Tier 2 field populated or
      explicitly `NOT MEASURED`.
- [ ] The metrics JSON records the resolved model strings, effort levels, and worker concurrency,
      so the arm can never be misattributed.
- [ ] `worker_concurrency` in this arm's metrics JSON **equals** the baseline arm's (both 2).
- [ ] Counts for all four predicted failure modes are recorded, including zeros.
- [ ] Tier 1c rejection rate recorded for this arm alongside the baseline's, with the rejected type
      names listed. A stored-artifact count of 0 is **not** sufficient evidence of no leakage.
- [ ] The job poll reached `todo+doing == 0` — the arm was not metriced on a partial graph.
- [ ] Index Tier 1 and Tier 2 "Qwen" columns filled in.
- [ ] Both snapshots exist: `./scripts/manage.sh snapshot list` shows `baseline-gpt54mini` **and**
      `qwen38-27b`.
- [ ] Any residual deviation from the baseline arm's procedure (effort level, retries) is written into
      the stage notes as an explicit confound.
- [ ] **Set Stage 6b's disposition**: if every Tier 1 and Tier 2 threshold cleared, mark 6b SKIPPED
      with a note; otherwise list the missed Tier 2 metrics in the tracker note so 6b knows its scope.

---

## Commit

`test(models): record local Qwen3.8-27B arm metrics`
