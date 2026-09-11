# Stage 5: Thinking-level identity probe

**Goal**: Prove that `off` sends zero reasoning tokens and find which of `low`, `medium`, `high` the local endpoint actually distinguishes, so the sweep pays only for distinct levels.
**Dependencies**: 1

Live budget 20 minutes. Twelve requests at most.

---

## Steps

1. Identity probe script.
   - Where: new `scripts/effort_level_probe.py`.
   - Details: for each level in `off, low, medium, high`, build the real Qwen extractor agent through
     `AgentInferenceConfig` and `build_model_settings` (`src/neocortex/model_factory.py`) and send 3
     identical requests on the E04 compact text with a 300 s per-call timeout. Record per request:
     `reasoning_tokens`, `output_tokens`, `elapsed_s`, `valid_output`, `timeout`, plus the request-side
     settings actually built: `openai_reasoning_effort`, whether `extra_body` carries
     `chat_template_kwargs.enable_thinking=false`, and `thinking`. `off` maps to the boolean `False`
     (there is no `"none"` literal in `ThinkingLevel`). Write `resources/effort-levels.json` after each
     request and a Markdown table at the end. Stop on a 20-minute budget and mark remaining cells
     `NOT MEASURED`. Support `--test-model`.

2. Alias rule.
   - Where: same script, `distinct_levels()`.
   - Details: two levels are one alias when their median `reasoning_tokens` differ by less than 20% and
     their min–max ranges overlap. `off` is always distinct. Write `distinct_levels` to the JSON; Stage 6
     sweeps exactly that list.

3. Tests.
   - Where: new `tests/unit/test_effort_level_probe.py`.
   - Details: alias rule on canned distributions (identical → alias; 0 vs 800 → distinct); `off` builds
     settings with `openai_reasoning_effort == "none"` and `enable_thinking == False`; `high` builds
     settings with `thinking == "high"` and no nothink switch; `--test-model` completes with 12 rows.

---

## Verification

- [ ] GATE `uv run pytest tests/unit/test_effort_level_probe.py -q` and the `--test-model` run — pass.
- [ ] GATE `off` is off — on all 3 `off` rows in `resources/effort-levels.json`, `reasoning_tokens` reads zero **and** `output_tokens > 0` **and** `valid_output == true` (a row with zero output tokens is an instrument failure, not a pass); a nonzero reasoning count or a `<think>` marker turns it red. `NOT MEASURED` blocks.
- [ ] GATE every planned request has a real row or an explicit `TIMEOUT`/`NOT MEASURED`; no default row.
- [ ] REPORT median reasoning tokens per level, `distinct_levels`, wall time — record in `journal.md`.

---

## Commit

`test(models): measure Qwen thinking-level identity`
