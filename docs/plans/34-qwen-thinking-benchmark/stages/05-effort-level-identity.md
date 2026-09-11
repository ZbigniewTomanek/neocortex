# Stage 5: Thinking-level identity probe

**Goal**: Prove that `off` sends zero reasoning tokens, that every level actually reaches the request, and which of `low`, `medium`, `high` the local endpoint distinguishes — so the sweep pays only for distinct levels and only if any level is distinct at all.
**Dependencies**: 1

Live budget 20 minutes. Twelve requests at most.

This stage is the plan's positive control. Before D-6 the client dropped every positive level, so Plan
33's four effort probes are indistinguishable (median reasoning tokens 196 / 229 / 224 / 180 across
low/medium/high/xhigh — every pair an alias under the rule below). D-6 fixed the client side. Whether the
**server** honours `reasoning_effort` is still unmeasured, and this stage is the only thing that measures
it. A null result here is a real, publishable answer, not a failure.

---

## Steps

1. Identity probe script.
   - Where: new `scripts/effort_level_probe.py`.
   - Details: for each level in `off, low, medium, high`, build the real Qwen extractor agent through
     `AgentInferenceConfig` and `build_model_settings` (`src/neocortex/model_factory.py`) and send 3
     identical requests on the E04 compact text with a 300 s per-call timeout. Record per request:
     `reasoning_tokens`, `output_tokens`, `elapsed_s`, `valid_output`, `timeout`, plus the request-side
     settings actually built: `thinking`, whether `extra_body` carries
     `chat_template_kwargs.enable_thinking=false`, and — the load-bearing one —
     `resolved_reasoning_effort`, read at the PydanticAI boundary rather than from the settings dict:
     `model.prepare_request(settings, ModelRequestParameters())` then
     `model._get_reasoning_effort(resolved_settings, params)`. Recording the settings dict alone is not
     enough: `thinking` is populated there even when the profile drops it, which is exactly how the
     pre-D-6 defect stayed invisible. `off` maps to the boolean `False` (there is no `"none"` literal in
     `ThinkingLevel`; `False` resolves to `"none"`). Write `resources/effort-levels.json` after each
     request and a Markdown table at the end. Stop on a 20-minute budget and mark remaining cells
     `NOT MEASURED`. Support `--test-model`.

2. Alias rule.
   - Where: same script, `distinct_levels()`.
   - Details: two levels are one alias when their median `reasoning_tokens` differ by less than 20% and
     their min–max ranges overlap. `off` is always distinct. The relation is pairwise and can be
     non-transitive on noisy data (on Plan 33's probes `medium` vs `xhigh` reads distinct while both alias
     to `high`), so reduce it to a set deterministically: walk the levels in ascending order
     `low, medium, high`, keep a level only when it is distinct from every level already kept, and record
     the kept list plus the full pairwise matrix. With three requests per level the sample is small and
     the ranges are wide — prefer declaring an alias over splitting on noise.
   - Cancellation rule: if no level's median `reasoning_tokens` exceeds the `off` rows' maximum, the
     endpoint ignores `reasoning_effort`. Write `distinct_levels: ["off"]`, record the finding, and Stage 6
     runs no cells — the sweep has nothing to measure and Stage 8 reports that as the result.

3. Tests.
   - Where: new `tests/unit/test_effort_level_probe.py`.
   - Details: alias rule on canned distributions (identical → alias; 0 vs 800 → distinct); the
     non-transitive canned case reduces to a deterministic set; the cancellation rule fires when every
     median sits at or below the `off` maximum; `off` resolves to `"none"` with `enable_thinking == False`
     at the PydanticAI boundary; `low`/`medium`/`high` each resolve to their own name there (the D-6
     regression guard, mirroring `tests/unit/test_qwen_thinking_settings.py`); `--test-model` completes
     with 12 rows.

---

## Verification

- [ ] GATE `uv run pytest tests/unit/test_effort_level_probe.py -q` and the `--test-model` run — pass.
- [ ] GATE every level reaches the request — in `resources/effort-levels.json` each level's `resolved_reasoning_effort` equals that level's own name (`off` → `"none"`). Any level resolving to `Omit`, null, or another level's name means the client is dropping it again: stop, diagnose `build_model_settings`, and do not spend the Stage 6 budget. `NOT MEASURED` blocks.
- [ ] GATE `off` is off — on all 3 `off` rows in `resources/effort-levels.json`, `reasoning_tokens` reads zero **and** `output_tokens > 0` **and** `valid_output == true` (a row with zero output tokens is an instrument failure, not a pass); a nonzero reasoning count or a `<think>` marker turns it red. `NOT MEASURED` blocks.
- [ ] GATE every planned request has a real row or an explicit `TIMEOUT`/`NOT MEASURED`; no default row.
- [ ] REPORT median reasoning tokens per level, the pairwise alias matrix, `distinct_levels`, whether the cancellation rule fired, and wall time — record in `journal.md`. Compare against Plan 33's `probe-results-{low,medium,high,xhigh}.json` and say whether the fix changed the picture.

---

## Commit

`test(models): measure Qwen thinking-level identity`
