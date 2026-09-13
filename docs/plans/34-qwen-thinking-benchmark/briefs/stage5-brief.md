# Stage 5 brief — thinking-level identity

Implementer: `codex/gpt-5.6-sol`, effort high, strong tier.
Reviewer: `codex/gpt-5.6-sol`, effort high, strong tier.
Authority: `stages/05-effort-level-identity.md`, `goal.md`, `PROTOCOL.md`.

## Scope and implementation

New `scripts/effort_level_probe.py`, `tests/unit/test_effort_level_probe.py`, and
Stage 5 artifacts under this run's validation/resources directories. Reuse endpoint
resolution and AgentInferenceConfig patterns from `scripts/qwen_speed_probe.py`.
Do not change model_factory unless the boundary gate is demonstrably red and the
coordinator dispatches a diagnosis/fix. Hosted behavior stays identical.

Build the real Qwen extractor agent for each of off/low/medium/high and issue three
identical requests using E04 from the compact corpus. Measure isolated extractor
requests, not full-pipeline runs. Read the stage specification for exact fields and
alias reduction. Record the effective request effort after `prepare_request` and
`_get_reasoning_effort`, not merely the input settings. `off` maps to boolean False
and wire effort "none". Preserve evidence of the thinking-off template flag.

Each row records real usage including reasoning and output tokens, valid output,
elapsed time, timeout and explicit error/status when applicable. Missing usage is
NOT MEASURED, never synthetic zero. Detect leaked reasoning markers without persisting
model text. Do not serialize exception messages, prompts, entity names or credentials.
Every planned request has a row; unlaunched requests are NOT MEASURED. Incrementally
write JSON atomically after each request; always finalize partial results on budget exit.
Maximum twelve live requests, 300 s per call, 1200 s total. Do not retry timed-out rows.

Implement the stage's deterministic pairwise alias relation and ascending reduction.
Cancellation requires measured, valid inputs; missing rows cannot prove the endpoint
ignores effort. Record the matrix, medians/ranges, kept levels, cancellation and why.
Support --levels off,low,medium,high, --repeats 3, --per-call-timeout 300,
--max-wall-seconds 1200, --output PATH and --test-model. Emit Markdown beside JSON.

## Deterministic checks before live work

- Unit cases required by the stage, including non-transitive aliases, cancellation,
  every wire effort, and twelve test-model rows. Add missing usage/budget cases that
  prevent a false off-PASS or false cancellation.
- `uv run pytest tests/unit/test_effort_level_probe.py -q`.
- `uv run python scripts/effort_level_probe.py --test-model --levels off,low,medium,high --repeats 3 --per-call-timeout 300 --max-wall-seconds 1200 --output docs/plans/34-qwen-thinking-benchmark/validation/stage5-testmodel.json`.
- `uv run pytest tests/ -q` and `uv run ruff check .`.
- Save each raw attempt separately as `validation/stage5-<check>-attempt<n>.txt`.

TestModel verifies instrumentation paths only; its synthetic token counts are not
evidence about the endpoint. Report the deterministic implementation before any live
call. Coordinator will inspect and gate it, then dispatch live work separately.

## Bounded live assignment (not yet dispatched)

Use the same validated CLI without --test-model, with output under `.tmp/plan34/`,
launched detached. Poll no more often than every five minutes; copy final JSON and
Markdown to `resources/effort-levels.{json,md}`. Report each gate using the actual rows,
compare measured medians with Plan 33's committed identity probe artifacts, and mark
any incomplete criterion NOT MEASURED. No rerun without a root-caused change recorded
by coordinator. No commits or edits to run records, briefs, or review files.
