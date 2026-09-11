# Stage 1: Fact-retention scorer and probe extension

**Goal**: Give `scripts/qwen_speed_probe.py` an offline quality signal and per-agent thinking controls, so a thinking level can be judged on the in-memory repository in minutes with no services.
**Dependencies**: None
**Reference**: [resources/fact-fixture-spec.md](../resources/fact-fixture-spec.md)

No live model call in this stage. Everything runs with `--test-model` or canned data.

---

## Steps

1. Build the fixture `resources/fact-fixture.json` from the spec.
   - Where: `docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json` (new); source texts are
     `load_corpus(profile="compact")` in `scripts/corpus_loader.py` and the seed constants named in the spec
     (`S5_INITIAL`/`S5_UPDATE`, `S11_INITIAL`/`S11_UPDATE` in `scripts/e2e_plan15_scenarios_test.py`;
     the 87% → 94.2% precision pair in `scripts/e2e_plan17_validation.py`).
   - Details: one `episodes[]` entry per compact key `E02,E04,E05,E10,E18,E20,E26,E27` with `facts[]`
     (exact substrings copied from the corpus text), and three `supersession[]` triplets with
     `initial_text`, `update_text`, `anchor_names`, `new_tokens`, `old_tokens`, copied verbatim from the E2E
     scripts so the probe measures the same defect the E2E children measure. Add the chain expectation
     `{"chain": ["E18","E20","E26"], "min_temporal_edges": 1}`. A fact string that does not occur in its
     episode text is a fixture error; the loader must reject it.

2. Implement the scorer.
   - Where: new `scripts/fact_retention.py`.
   - Details: `load_fixture(path)` validates every fact against its episode text. `score_episode(nodes,
     edges, episode_fixture) -> FactScore(facts_total, facts_found, missing_keys)` matches each fact
     case-insensitively over whitespace-normalized `name + content + str(property values)` of all nodes.
     `score_supersession(nodes, edges, triplet) -> SupersessionScore(new_present, old_absent,
     temporal_edge_present)` mirrors the E2E checks: `new_present` is any `new_tokens` in the content of nodes
     whose name matches an anchor; `old_absent` is no `old_tokens` in that same content;
     `temporal_edge_present` is any `SUPERSEDES`/`CORRECTS` edge touching an anchor node. Output never
     contains graph text; `missing_keys` are fixture indices only. Read nodes/edges through
     `InMemoryRepository` in `src/neocortex/db/mock.py`; add a read-only enumeration helper there if none
     exists, and do not add it to the `MemoryRepository` protocol.

3. Extend the probe.
   - Where: `THINKING` map, argument parser, per-episode row builder, and the config construction in
     `scripts/qwen_speed_probe.py`.
   - Details: (a) `THINKING["high"] = "high"`. (b) `--thinking-ontology`, `--thinking-extractor`,
     `--thinking-librarian`, `--thinking-classifier`, each defaulting to `--thinking`, wired into the
     matching `AgentInferenceConfig` (`src/neocortex/extraction/agents.py`). (c) `--corpus
     {compact,supersession,both}` and `--fixture PATH`; a supersession triplet runs its `initial_text` then
     `update_text` on one shared repo per triplet. (d) Every row gains `fact_score` and, for triplets,
     `supersession`. (e) `--per-call-timeout` (default 300) reaching the local model timeout the same way
     `NEOCORTEX_LOCAL_MODEL_TIMEOUT_S` does; find the settings field in `MCPSettings`
     (`src/neocortex/mcp_settings.py`) and the endpoint object the config carries. (f) `--max-wall-seconds`:
     stop launching episodes past the budget and still write the file. (g) Write the output JSON after every
     episode, not only at the end. (h) The cache key (`test_cache_key_is_setup_specific` in
     `tests/unit/test_qwen_speed_probe.py`) must include each agent's level so a librarian-only rerun cannot
     silently reuse an extraction produced at another extractor level unless `--cache-thinking` says so.

4. Tests.
   - Where: new `tests/unit/test_fact_retention.py`; extend `tests/unit/test_qwen_speed_probe.py`.
   - Details: canned in-memory graph scores full marks; deleting one fixture fact lowers `facts_found` by
     exactly one (mutation test); a graph holding only the stale value yields `new_present=false`; a graph
     holding both values yields `old_absent=false`; the fixture loader rejects a fact absent from its
     episode; the CLI parses `--thinking high` and per-agent overrides; the cache key changes when any
     per-agent level changes.

---

## Verification

- [ ] GATE `uv run pytest tests/unit/test_fact_retention.py tests/unit/test_qwen_speed_probe.py -q` — passes, including the mutation test; a scorer that returns full marks regardless of input turns it red.
- [ ] GATE `uv run python scripts/qwen_speed_probe.py --test-model --corpus both --thinking off --thinking-extractor high --fixture docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json --output .tmp/plan34/stage1-testmodel.json` — exits 0; the output holds one row per compact episode and per triplet, each with `fact_score`, read from that JSON; a missing row or absent field turns it red.
- [ ] GATE `uv run pytest tests/ -q` and `uv run ruff check .` — pass.

REPORT in `journal.md`: wall time of the `--test-model` run (expected seconds). Zero live model calls in this stage.

---

## Commit

`feat(scripts): add offline fact-retention scoring to the Qwen speed probe`
