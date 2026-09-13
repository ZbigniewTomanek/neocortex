# Stage 4 brief — scalar retention and measurement readiness

Implementer: `codex/gpt-5.6-sol`, effort high, strong tier.
Reviewer: `codex/gpt-5.6-sol`, effort high, strong tier.
Authority: `stages/04-numeric-fact-preservation.md`, `goal.md`, `PROTOCOL.md`.

## Assignment A: deterministic implementation

Implement Stage 4 steps 1–3 exactly, preserving hosted branches. Scope:
`src/neocortex/extraction/agents.py` (Qwen prompt only),
`src/neocortex/extraction/oneshot_librarian.py`, `tests/test_oneshot_librarian.py`,
`tests/test_qwen_extractor.py`. Existing Stage 2 cap counters stay intact.

Keep scalar properties in `render_oneshot_items`, which is the actual model-facing text.
For incoming scalar conflicts on a shared property key, update the stored property and
remove the stale scalar from current content while retaining the new one. The binding
S05 criterion requires May 1 present and April 15 absent: a historical "previously
April 15" clause cannot satisfy that criterion. Preserve append behavior for free-text
conflicts without a shared scalar key; truncate oldest text first. Do not change hosted
prompts, profiles, tools or settings.

Write the canned S05 regression first and run it against unchanged product code.
Save raw output as `validation/stage4-s05-red-attempt1.txt`; report its failing assertion.
Then implement and test all three fixture triplets. Assert rendered prompt content
directly, including scalar property values; a FunctionModel that ignores its messages
does not prove rendering. Cover truncation preserving new values.

Before any live baseline, repair the evidence dependencies promoted from Stage 1:
scope additionally includes `scripts/qwen_speed_probe.py`, `scripts/fact_retention.py`,
`tests/unit/test_qwen_speed_probe.py`, `tests/unit/test_fact_retention.py`.
Read backlog items 6–8 and 10. Catch missing extraction cache entries at the cell
boundary and persist an explicit failure row without crashing the whole run. Include
fixture content/revision in cache provenance for triplets. Prevent a multi-word fact
from matching across unrelated nodes. Narrow the S11 scorer docstring to acknowledge
its approximation. Add targeted tests that reproduce these defects. No shared-repo
scoring change is required: this plan uses fresh episode repos.
Also close backlog 11's probe docstring overclaim: normalized ontology type names in
`edge_types_after` are the explicit metadata exemption. Stage 2 traced these names to
`InMemoryRepository.get_or_create_edge_type` and `normalize_edge_type`; document that
provenance without suggesting arbitrary model text is safe to export.

## Checks and evidence

- Focused: `uv run pytest tests/test_oneshot_librarian.py tests/test_qwen_extractor.py tests/unit/test_qwen_speed_probe.py tests/unit/test_fact_retention.py -q`.
- Hosted: `uv run pytest tests/test_qwen_extractor.py::test_qwen_extractor_carries_the_output_ceiling_and_hosted_does_not tests/test_oneshot_librarian.py::test_qwen_models_select_oneshot_and_hosted_keeps_its_tools tests/test_local_provider_routing.py -q`.
- Full: `uv run pytest tests/ -q`; lint: `uv run ruff check .`.
- Save each raw attempt under `validation/stage4-<check>-attempt<n>.txt`.
- Run the exact Stage 4 baseline command from `resources/commands.md` with
  `--test-model`, `--corpus both`, `--thinking off`, `--per-call-timeout 300`,
  `--episode-timeout 600`, `--max-wall-seconds 1200`, and isolated mock cache
  `.tmp/plan34/mock-stage4-cache`. Output `validation/stage4-testmodel.json`.
  Inspect 8 compact plus 3 triplet rows and their fact_score/supersession fields.
- Provide hosted branch identity evidence against `8766e90`, respecting the Qwen-only
  additions already accepted in Stage 2.

Assignment A makes no live model call. Report changes and evidence to coordinator;
the bounded detached live baseline is a separate assignment after deterministic gates.
Do not commit or edit run records, briefs, or review files. Never weaken existing tests.

## Assignment B: bounded live baseline (not yet dispatched)

After coordinator accepts deterministic evidence, preflight then launch one detached
all-off baseline, timeout 300 s per call and 1200 s wall budget. Keep live cache
separate from mock cache at `.tmp/plan34/cache`; use the command in the stage specification.
Use a managed asynchronous command session, not `nohup ... &`: D-16 records the
runner lifecycle failure. Corrected attempt2 retains the original 13:39:43 UTC deadline.
Poll at intervals of at least five minutes. Persist remaining units explicitly as
TIMEOUT/NOT MEASURED; copy the finished JSON to `resources/sweep/off.json`.
Do not rerun a live measurement without a coordinator-recorded root-caused change.
For in-memory probes, launch with `env -u GOOGLE_API_KEY -u GEMINI_API_KEY` so
`resolve_embeddings` returns None/none. This preserves the offline-scoring design
and ensures no hosted embedding request is made. Pin the local base URL explicitly
to `http://127.0.0.1:24000/v1`; credentials remain environment-only.
