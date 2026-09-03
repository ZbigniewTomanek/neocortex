# Stage 8: Thinking-Effort Tuning

**Goal**: Select the best effort level for each agent that passed, while measuring aliases and reporting cost without using latency as a gate.
**Dependencies**: Stage 7 DONE with at least one `MIGRATE` verdict.

## Steps

1. If Stage 7 produced no `MIGRATE`, record `SKIPPED` and explain why in `journal.md`; do not tune an
   agent that has no validated migration path.
2. For each migratable agent, sweep `low`, `medium`, `high`, and `xhigh` against an identical prompt
   and representative fixture at N≥5 where the endpoint permits. Keep all other agents at their
   Stage 6 settings. Use at least 300 seconds per extractor call and record timeouts explicitly.
3. Record pass/validity rate, reasoning tokens, completion tokens, tool calls, rejection rate, and
   critical integrity defects. Any level that produces a critical defect is disqualified for that
   agent, regardless of its average score.
4. Compare reasoning-token distributions for `high` with `medium` and `xhigh`. The available chat
   template may alias unsupported effort values; configure the actual observed level and document the
   alias rather than claiming a distinct setting.
5. Run one combined full local arm with the selected efforts. Confirm integrity and quality do not
   regress the Stage 6 configuration. Choose on quality; use lower token cost only as a tie-break.
6. Write `resources/effort-sweep.json` and record p50/p95 timing and token cost in `journal.md`. A
   dedicated GPT-5.6-Luna xhigh subagent audits that sweep values came from raw run inputs.

## Verification

- [ ] GATE effort safety — every chosen level has raw records and no critical integrity defect; an unmeasured or fabricated winner makes this red.
- [ ] GATE combined tuned arm — `resources/metrics-qwen-flash-next-tuned.json` comes from a fresh run and satisfies Stage 6 integrity checks; a copied metric or regression makes this red.
- [ ] REPORT effort distributions and alias finding — record model id, effort, token counts, timings, tool/rejection counts, and `NOT MEASURED` signals in `journal.md`.

## Commit

`perf(models): tune Flash Next thinking effort`
