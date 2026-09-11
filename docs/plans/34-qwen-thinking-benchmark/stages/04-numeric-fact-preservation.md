# Stage 4: Numeric-fact preservation in the Qwen path

**Goal**: Keep explicit numbers, dates, percentages, and versions in node content through Qwen extraction and the one-shot merge, so the sweep measures the thinking level and not a known merge defect.
**Dependencies**: 1

First live model call of the plan, bounded to 20 minutes, only after the deterministic tests pass.
Hosted prompts and profiles do not change.

---

## Steps

1. Qwen extractor prompt keeps scalars.
   - Where: `QWEN_EXTRACTOR_PROMPT` in `src/neocortex/extraction/agents.py`.
   - Details: keep the one-sentence description cap, but require the sentence to state every explicit
     number, date, percentage, version, or code identifier from the source that describes the entity, and
     to put the same values into `properties` as scalars. When the source says a value replaces an older
     one, the description states the new value and names the old one as superseded. Do not touch the hosted
     instructions inside `build_extractor_agent`.

2. Host merge writes the newer scalar into content.
   - Where: `_merge_content`, `_decision_for`, and the merge-item construction in
     `src/neocortex/extraction/oneshot_librarian.py`; `MERGE_CONTENT_CHARS`.
   - Details: include the incoming entity's `properties` in the merge item the model sees. In the host
     default merge, when an incoming scalar property conflicts with an existing property of the same key,
     replace the stale value in content (a "now X, previously Y" sentence) instead of appending, and update
     the property. Content truncation drops the oldest text first so the newest fact survives. Free-text
     conflicts without a shared property key keep the current append behaviour.

3. Deterministic tests with canned extraction results.
   - Where: `tests/test_oneshot_librarian.py`, `tests/test_qwen_extractor.py`.
   - Details: the three triplets from `resources/fact-fixture.json` as canned `ExtractionResult` pairs:
     after merge, content contains `May 1` and not `April 15`; contains `0.62`; contains `94.2`. Run the
     merge test on the pre-fix code first and record its failure in `journal.md`. Hosted prompt and
     profile tests unchanged.

4. Bounded live baseline at `off` (the `off` arm of the Stage 6 sweep).
   - Where: `scripts/qwen_speed_probe.py`.
   - Details: run `--test-model --corpus both` first. Then, detached, per
     [resources/commands.md](../resources/commands.md): `--corpus both --thinking off --per-call-timeout
     300 --episode-timeout 600 --max-wall-seconds 1200 --cache-dir .tmp/plan34/cache --output
     .tmp/plan34/sweep/off.json`. Copy the output to `resources/sweep/off.json`. Stage 6 reuses this cache
     and does not rerun `off`.

---

## Verification

- [ ] GATE `uv run pytest tests/test_oneshot_librarian.py tests/test_qwen_extractor.py -q` — passes; the S05 merge test was recorded red on pre-fix code in `journal.md`; a merge that still appends turns it red.
- [ ] GATE hosted identity — `git diff 8766e90 -- src/neocortex/extraction/agents.py src/neocortex/extraction/oneshot_librarian.py` touches only `QWEN_EXTRACTOR_PROMPT`, the one-shot merge functions, and Qwen-only branches; the hosted branches of `build_extractor_agent`, `build_ontology_agent`, and `build_librarian_agent` (`profile == "hosted"`) are byte-identical, and `tests/test_qwen_extractor.py::test_qwen_extractor_carries_the_output_ceiling_and_hosted_does_not`, `tests/test_oneshot_librarian.py::test_qwen_models_select_oneshot_and_hosted_keeps_its_tools`, and `tests/test_local_provider_routing.py` pass.
- [ ] GATE `uv run pytest tests/ -q` and `uv run ruff check .` — pass.
- [ ] REPORT `resources/sweep/off.json` — per-episode `fact_score`, the three triplet results, timeouts, wall time. Record in `journal.md`. A `TIMEOUT` is a valid recorded value.

---

## Commit

`fix(extraction): keep scalar facts through Qwen extraction and one-shot merge`
