# Stage 5: Optional Hosted Baseline Comparison

**Goal**: Measure a same-prompt hosted reference when it is available, without making it a prerequisite for the local stability decision.
**Dependencies**: Stage 4 DONE.

## Steps

1. Check whether an isolated environment and `OPENAI_API_KEY` can run the current hosted defaults.
   If not, record `NOT MEASURED` in `journal.md`, leave the baseline artefact absent, and mark this
   optional stage `DONE` with a backlog reference. Do not mark a missing baseline as local failure.
2. If available, run two complete hosted arms with the same corpus, prompts, schema, concurrency,
   timeout, and instrumentation as Stage 6. Use `openai-responses:gpt-5.4-mini` only for this
   comparison. Save a snapshot for each arm and preserve the pre-run graph.
3. Require terminal jobs and complete metrics before deriving any tolerance. Compute run-to-run spread
   from the two raw outputs. A baseline value without two complete runs is historical context, not a
   gate threshold. Do not edit the Success Criteria target during this stage.
4. Write `resources/baseline-comparison.md` with inputs, missing signals, distributions, and any
   tolerance proposal. A dedicated GPT-5.6-Luna xhigh subagent audits that values came from files/API
   responses, not literals or the implementation's own output.

## Verification

- [ ] GATE baseline disposition — `resources/baseline-comparison.md` states either two complete runs with raw artefacts or `NOT MEASURED` with the exact external blocker; a single partial run makes this red.
- [ ] GATE same-input check — both arms, when present, use the Stage 3 prompt/schema/corpus and equal concurrency; a changed input or target copied into results makes this red.
- [ ] REPORT hosted latency, token, quality, and variance distributions — record values with run identifiers and caveats in `journal.md`; continue regardless of latency.

## Commit

`docs(plan): record optional hosted baseline evidence`
