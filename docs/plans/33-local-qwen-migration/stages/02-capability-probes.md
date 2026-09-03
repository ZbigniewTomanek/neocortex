# Stage 2: Real-Agent Flash Next Probes

**Goal**: Exercise ontology, extractor, librarian, and domain-classifier agents against the exact local model with real schemas, tools, and bounded calls.
**Dependencies**: Stage 1 DONE.

## Steps

1. Read `resources/probe-corpus.md` and `resources/commands.md`. Use the fixed factual, temporal,
   and adversarial episodes. Run `scripts/probe_local_model.py` at low, medium, high, and xhigh with
   the model `local:qwen3.8-flash-next`, the local endpoint, and a timeout of at least 300 seconds.
   Use bounded concurrency below the service limit. Keep the key in `$VLLM_API_KEY` only.
2. Ensure the probe calls the real agent builders and records one JSON record per attempt: success or
   timeout, exception class, raw validation output, wall clock, prompt/completion/reasoning tokens,
   tool names and order, retries, and normalization rejections. N≥5 per agent/effort is preferred;
   record any shortfall as `NOT MEASURED`.
3. Exercise ontology and librarian tools against an isolated repository/schema. If a production DB is
   unavailable, run the PydanticAI surface with `InMemoryRepository` and label backend coverage in the
   findings; do not call this a PostgreSQL quality pass.
4. Reproduce and classify the observed HTTP 400 (`System message must be at the beginning`) separately
   from model refusal, timeout, invalid structured output, malformed tool arguments, and empty content.
   Check whether PydanticAI sends multiple system messages for ontology and extractor.
5. Fix a stale probe import only if present: `load_probe_corpus` and `load_corpus` must resolve to the
   same corpus loader contract. Delegate a narrow fix to a GPT-5.6-Luna xhigh subagent and add an
   import-level regression test; do not alter the corpus to improve results.
6. Write `resources/probe-findings.md` with per-agent/effort pass rates, failure examples, tool
   budgets, token and timing distributions, and a provisional `READY`, `NEEDS HARDENING`, or
   `BLOCKED` finding. These findings scope Stage 3; they do not decide migration quality.

## Verification

- [ ] GATE `uv run python scripts/probe_local_model.py --model local:qwen3.8-flash-next --effort medium` — emits records for all four agent surfaces; missing records, unbounded calls, or fabricated results make this red.
- [ ] GATE probe output schema — each record in `resources/probe-results-*.json` has an input episode, effort, model id, outcome, and measured provenance; a default or copied result makes this red.
- [ ] REPORT four-effort sweep — record pass/timeout/tool/rejection distributions and exact HTTP errors in `journal.md` and `resources/probe-findings.md`.

## Commit

`test(models): probe local Flash Next agent capabilities`
