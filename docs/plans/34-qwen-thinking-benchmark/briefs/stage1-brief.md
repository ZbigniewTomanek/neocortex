# Stage 1 brief — Fact-retention scorer and probe extension

| | |
|---|---|
| Implementer | `claude/opus`, effort `high` (strong tier) |
| Reviewer | `claude/opus`, effort `high` (strong tier) |
| Tier reason | The stage designs a scorer, a fixture format, and a CLI restructure. Nothing here is a fully specified mechanical edit, so it is not helper work. |
| Plan stage | [stages/01-fact-retention-scorer.md](../stages/01-fact-retention-scorer.md) |
| Spec | [resources/fact-fixture-spec.md](../resources/fact-fixture-spec.md) — binding for the fixture and the scoring rules |
| Run contract | [goal.md](../goal.md) · [PROTOCOL.md](../PROTOCOL.md) |

**No live model call in this stage.** Everything runs with `--test-model` or canned data. If you find
yourself about to contact `127.0.0.1:24000`, stop and report instead.

---

## Why this stage exists

Stage 6 must judge a thinking level in minutes on the in-memory repository, with no services. Today the
probe measures only speed. It needs a quality signal: did the graph keep the facts the source text
stated, and did a later correction reach node `content`? Without that, the sweep produces timings and no
way to choose a level.

---

## Scope

Change only these paths:

- `docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json` (new)
- `scripts/fact_retention.py` (new)
- `scripts/qwen_speed_probe.py`
- `src/neocortex/db/mock.py` (one read-only helper, see step 3)
- `tests/unit/test_fact_retention.py` (new)
- `tests/unit/test_qwen_speed_probe.py` (extend; weaken nothing)

Anything else is out of scope. Report it rather than changing it.

---

## Step 1 — the fixture

Write `docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json` in the shape the spec's *JSON
shape* section gives.

**Episode facts.** One `episodes[]` entry per compact key `E02, E04, E05, E10, E18, E20, E26, E27`.
The spec lists candidate facts per key. **Copy each candidate from the corpus text, do not type it from
the spec table**: the source is `load_corpus(profile="compact")` in `scripts/corpus_loader.py`, backed by
`docs/plans/33-local-qwen-migration/resources/compact-corpus.md`.

Verify every candidate against the episode text before you write it. A candidate that is not an exact
case-insensitive, whitespace-normalized substring of its episode text is **dropped, not adjusted into
something that matches** — for example `Precision, Recall, F1` may well not appear with that spacing.
Keep 6–10 facts per episode; prefer numbers, identifiers, and code names. If dropping leaves an episode
under 6, say so in your report with the candidates you rejected and what the text actually says. Do not
invent replacements to reach the floor (`goal.md` invariant: never generate a row to satisfy a count).

**Chain.** `{"episodes": ["E18","E20","E26"], "min_temporal_edges": 1}`.

**Supersession triplets.** Three entries with `id`, `initial_text`, `update_text`, `anchor_names`,
`new_tokens`, `old_tokens`, copied **verbatim** from the E2E scripts so the probe measures the same
defect the E2E children measure:

| id | initial_text | update_text | anchor_names | new_tokens | old_tokens |
|---|---|---|---|---|---|
| S05 | `S5_INITIAL` (`scripts/e2e_plan15_scenarios_test.py:141`) | `S5_UPDATE` (:142) | `["zenith"]` | `["may 1","may"]` | `["april 15","april"]` |
| S11 | `S11_INITIAL` (:190) | `S11_UPDATE` (:191) | `["plan 42","scaling exponent"]` | `["0.62"]` | `["0.57"]` |
| S07 | `EP1_TEAM` (`scripts/e2e_plan17_validation.py:70`) | `EP7_PRECISION` (:106) | `["dataforge","nlp","precision"]` | `["94.2"]` | `[]` |

S07's `old_tokens` is deliberately empty: the correction legitimately restates the old 87%, so
`old_absent` is vacuously true there and only `new_present` carries signal. Do not invent an old token
for symmetry.

Add `"revision": 1`.

---

## Step 2 — `scripts/fact_retention.py`

Importable as `scripts.fact_retention` (the existing test convention: `from scripts import
qwen_speed_probe as probe`).

**Graph view.** `Edge` (`src/neocortex/models.py:37`) carries `type_id`, not a type name, so a scorer
that must recognise `SUPERSEDES`/`CORRECTS` needs the type tables. Define:

```python
@dataclass(frozen=True)
class GraphView:
    nodes: list[Node]
    edges: list[Edge]
    node_type_names: dict[int, str]   # type_id -> name
    edge_type_names: dict[int, str]
```

The spec sketches `score_episode(nodes, edges, fixture)`; taking a `GraphView` instead is the same
information with the type tables the edge rule needs. Say so in the module docstring.

**API.**

```python
def load_fixture(path: Path, *, corpus: list[dict[str, object]] | None = None) -> Fixture
def score_episode(graph: GraphView, episode: EpisodeFixture) -> FactScore
def score_supersession(graph: GraphView, triplet: SupersessionFixture) -> SupersessionScore
```

- `FactScore(facts_total: int, facts_found: int, missing_keys: list[int])` — `missing_keys` holds
  **fixture indices only**, never fact text.
- `SupersessionScore(new_present: bool, old_absent: bool, temporal_edge_present: bool)`.
- Both must serialize to plain JSON dicts for the probe rows (`dataclasses.asdict` is fine).

**`load_fixture` validation.** Defaults `corpus` to `load_corpus(profile="compact")`. For every episode
entry, every fact must be a case-insensitive substring of the whitespace-normalized episode text. Raise
`ValueError` naming the episode key and the fixture index (not the fact text) otherwise. Also reject an
unknown episode key and a triplet missing any required field.

**Normalization**, applied identically to the needle and the haystack: lower-case, then collapse all
whitespace runs to one space, then strip.

**`score_episode`.** Haystack = the normalized concatenation of `name`, `content` (treat `None` as `""`),
and the stringified values of `properties` across **all non-forgotten nodes** in the graph. `facts_found`
counts distinct fixture facts whose normalized form occurs in that haystack. Deduplicate by fixture
index, so a fact listed twice cannot be counted twice.

**`score_supersession`.** Mirrors the E2E checks exactly:

- Anchor nodes = non-forgotten nodes whose normalized `name` **contains** any `anchor_names` entry
  (already normalized).
- Anchor text = the normalized concatenation of the anchor nodes' `content` only — **not** `name`, not
  `properties`. The E2E children assert on content, and widening the haystack here would make the probe
  pass where the E2E child fails, which is the one error that would invalidate the whole sweep.
- `new_present` = any `new_tokens` entry occurs in the anchor text.
- `old_absent` = no `old_tokens` entry occurs in the anchor text (vacuously `True` for an empty list).
- `temporal_edge_present` = some edge whose resolved type name is `SUPERSEDES` or `CORRECTS` has an
  anchor node id at either end.
- With no anchor node at all: `new_present=False`, `old_absent=True`, `temporal_edge_present=False`.
  A missing anchor must never read as a pass on `new_present`.

**Privacy.** No function in this module may return, log, or print graph text, episode text, or fact
strings. Only counts, booleans, and fixture indices.

---

## Step 3 — enumeration helper on `InMemoryRepository`

`src/neocortex/db/mock.py` stores one graph in `self._nodes` / `self._edges` (lines 45–46) and its
existing aggregate readers ignore `agent_id` (see `get_ontology_summary`). Add one **synchronous,
read-only** method:

```python
def graph_snapshot(self) -> tuple[list[Node], list[Edge], dict[int, str], dict[int, str]]:
    """Return active nodes, edges, and the type-id tables for offline scoring.

    Test-only surface for the speed probe's fact-retention scorer.  Deliberately
    not on ``MemoryRepository``: production callers must not enumerate a graph.
    """
```

Return non-forgotten nodes only, all edges, and the two `type_id -> name` tables. Take no `agent_id`
argument — the mock holds a single graph and inventing a parameter it ignores would mislead. **Do not
add this to `src/neocortex/db/protocol.py`.**

---

## Step 4 — extend `scripts/qwen_speed_probe.py`

### 4a. `THINKING`

Add `"high": "high"`. Nothing else; `xhigh` is out of scope (D-1).

### 4b. Per-agent thinking flags

Add `--thinking-ontology`, `--thinking-extractor`, `--thinking-librarian`, `--thinking-classifier`, each
`choices=tuple(THINKING)`, `default=None` meaning "fall back to `--thinking`". Resolve them once, then
build **three** `AgentInferenceConfig` objects (ontology, extractor, librarian) and pass them to the
matching parameters of `run_extraction` (`src/neocortex/extraction/pipeline.py:208-210`, which already
takes them separately). `_classify` takes the resolved classifier level instead of
`THINKING[args.thinking]`. Record all four resolved levels in `run_meta`.

### 4c. `--corpus` and `--fixture`

`--corpus {episodes,compact,supersession,both}`, **default `episodes`**.

- `episodes` — today's behaviour: the keys in `--episodes` (default `["E04","E05"]`). This default keeps
  `test_cli_defaults` true and keeps every existing invocation byte-identical.
- `compact` — all eight compact keys.
- `supersession` — the three fixture triplets.
- `both` — all eight compact keys then the three triplets.

`--fixture PATH` (default `None`) loads the fixture through `load_fixture`. `--corpus` values other than
`episodes` that need triplets (`supersession`, `both`) require `--fixture`; error clearly if it is
missing. Without `--fixture`, compact rows carry `fact_score: null`.

Generalize the run unit. A triplet runs `initial_text` then `update_text` through the full pipeline on
**one shared `InMemoryRepository`**, regardless of `--repo`, and produces **one** summary row keyed by
the triplet id (`S05`, `S11`, `S07`). Its `words` is the sum over both texts and its `seconds_total` the
sum of both runs; `status` is `ok` only when both texts completed. Compact keys keep today's importance
from the corpus record; triplet texts use importance `0.5`.

### 4d. `fact_score` and `supersession` on the rows

Every episode summary gains a `fact_score` key. For a compact key with a fixture loaded, it is
`asdict(score_episode(...))` computed from the repository **after** that episode's pipeline run. For a
triplet, and for any episode with no fixture entry, it is **`null`** — the fixture defines no `facts[]`
for triplets, and writing `{"facts_total": 0, "facts_found": 0}` there would read as a measured
full-marks score. A triplet summary additionally carries `supersession:
asdict(score_supersession(...))`; non-triplet rows carry `supersession: null`.

When `--corpus` is `compact` or `both` and `--repo shared`, also evaluate the fixture's `chain`
expectation after the run and record `chain: {"episodes": [...], "min_temporal_edges": N,
"temporal_edges": M, "satisfied": bool}` in `run_meta`. With `--repo fresh` the chain cannot be
measured across episodes: record `chain: {"status": "NOT MEASURED", "reason": "repo_mode=fresh"}`.
Do not silently omit the key.

### 4e. `--per-call-timeout`

`--per-call-timeout` (float, default `300.0`) feeds `resolve_local_endpoint`, which sets
`MCPSettings.local_model_timeout_s` (`src/neocortex/mcp_settings.py:149`) and reaches the model through
`LocalEndpoint.timeout_s`. Today `resolve_local_endpoint(args.episode_timeout)` conflates the two.
After this change `--episode-timeout` (default `900.0`, unchanged) stays the `asyncio.wait_for` bound
around the whole episode, and `--per-call-timeout` bounds a single model call. Record both in `run_meta`.
`test_local_endpoint_defaults_to_the_probe_endpoint` calls `resolve_local_endpoint(1500.0)` directly and
must keep passing unchanged.

### 4f. `--max-wall-seconds`

`--max-wall-seconds` (float, default `None` = unbounded). Before launching each unit, if the elapsed
wall time is at or past the budget, stop launching. Every unit not launched gets a summary row with
`status: "NOT MEASURED"`, `reason: "wall_budget"`, and null measurements — never a zero-valued row that
reads as measured. Record `wall_budget_exhausted: bool` in `run_meta`. The file is still written and the
process still exits through the normal path.

### 4g. Incremental output

Extract the output write into a helper and call it **after every unit**, not only at the end. A killed
run must leave a valid JSON file holding every unit that finished. The final write also fills
`wall_seconds`.

### 4h. Cache key

The cache holds an `ExtractionResult` plus the ontology snapshot it was produced against — artifacts the
**ontology** and **extractor** agents produce and the librarian never influences. Extend:

```python
def cache_key(episode, model, thinking, corpus_sha256, *, test_model,
              ontology_thinking=None, extractor_thinking=None) -> str
```

Each new parameter defaults to `None`, meaning "the same as `thinking`", so the four existing positional
call sites and `test_cache_key_is_setup_specific` keep working. Fold both resolved values into the
preimage. The base level stays `--cache-thinking or --thinking`.

Deliberately **not** in the key: the librarian and classifier levels. Including the librarian level would
break Stage 6 step 2, whose whole design is a librarian sweep reusing one extraction cached at the pinned
`L_ext`; a single-valued `--cache-thinking` cannot express a per-agent key, so the librarian sweep would
find no cache entry at any level and re-run extraction on every cell. Excluding it satisfies the stage's
actual requirement — "a librarian-only rerun cannot silently reuse an extraction produced at another
extractor level" — because the extractor level *is* in the key. Put this reasoning in the function
docstring and assert the invariant in the test (step 5).

---

## Step 5 — tests

**New `tests/unit/test_fact_retention.py`.** Build `GraphView` instances by hand; no pipeline run needed.

1. A canned graph holding every fixture fact for one episode scores `facts_found == facts_total` and
   `missing_keys == []`.
2. **Mutation test (the gate's load-bearing case).** From that same canned graph, remove exactly one
   fact's text and assert `facts_found` drops by **exactly one** and `missing_keys` names that one index.
   A scorer returning full marks regardless of input must fail here.
3. A graph holding only the stale value for a triplet yields `new_present is False`.
4. A graph holding both values yields `old_absent is False`.
5. A graph whose anchor node has the new value only yields `new_present and old_absent`.
6. No anchor node at all yields `new_present is False` (not a vacuous pass).
7. `temporal_edge_present` is `True` only when an edge whose resolved type name is `SUPERSEDES` or
   `CORRECTS` touches an anchor; an edge of another type between the same nodes yields `False`.
8. `load_fixture` raises `ValueError` on a fact absent from its episode text, and the message names the
   episode key and index but **not** the fact text.
9. `load_fixture` accepts the committed `resources/fact-fixture.json` against the real compact corpus.
   This is the fixture's own regression test.
10. A scorer result contains no graph text: assert the serialized `FactScore`/`SupersessionScore` hold
    only ints, bools, and indices.

**Extend `tests/unit/test_qwen_speed_probe.py`.** Weaken nothing that is there.

11. `--thinking high` parses and `THINKING["high"] == "high"`.
12. Each per-agent flag parses and defaults to `None`; the resolver falls back to `--thinking` for a
    `None` and honours an explicit override.
13. Extend `test_cache_key_is_setup_specific` (do not replace it): the key changes when
    `ontology_thinking` changes and when `extractor_thinking` changes, **and is unchanged** when only a
    librarian or classifier level differs — with a comment giving the step-4h reason.
14. `--per-call-timeout` defaults to `300.0` and reaches `LocalEndpoint.timeout_s`, while
    `--episode-timeout` keeps its own default.
15. `--corpus` defaults to `episodes`; `compact` selects all eight keys; `both` selects eleven units;
    `supersession`/`both` without `--fixture` exits with a clear error.
16. A `--test-model --corpus both --fixture <the committed fixture>` run through `probe.main` writes
    eleven summary rows, each carrying a `fact_score` key, the three triplet rows carrying a
    `supersession` dict, and the file parses as JSON. Follow the loguru teardown pattern in
    `test_test_model_run_over_two_episodes` (restore a plain sink in `finally`).
17. `--max-wall-seconds 0` launches nothing and still writes a valid file whose rows are all
    `status: "NOT MEASURED"`.

---

## Gates — run these exact commands, save raw output to these paths

| # | Command | Evidence path | What turns it red |
|---|---|---|---|
| G1 | `uv run pytest tests/unit/test_fact_retention.py tests/unit/test_qwen_speed_probe.py -q` | `validation/stage1-unit-1.txt` | any failure; in particular a scorer that returns full marks regardless of input fails test 2 |
| G2 | `uv run python scripts/qwen_speed_probe.py --test-model --corpus both --thinking off --thinking-extractor high --fixture docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json --output .tmp/plan34/stage1-testmodel.json` | `validation/stage1-testmodel-1.txt` (stdout+stderr) and the JSON itself | non-zero exit; fewer than 11 rows; any row missing `fact_score`; any triplet row missing `supersession` |
| G3 | `uv run pytest tests/ -q` | `validation/stage1-suite-1.txt` | fewer than 1,288 passed, or any failure. Baseline at `b47f6ba`: 1,288 passed, 7 skipped |
| G4 | `uv run ruff check .` | `validation/stage1-ruff-1.txt` | anything but `All checks passed!` |

Save each command's raw output, unedited, one file per attempt. If you must rerun a check, write
`-2.txt`, never append to `-1.txt`.

G2 is the first run of this code path, so its exact form is unverified at baseline — if a flag name in
it does not match what you built, **change the code to match the command**, not the command.

---

## Report back

- Every changed path.
- Each gate command, its exit code, its runtime, and the evidence path.
- From the G2 JSON, quoted: the eleven row keys, and the `fact_score` of E04 and E05 with a one-line
  note on whether TestModel's canned output plausibly explains the number. TestModel produces stub
  entities, so **low or zero `facts_found` is the expected, correct result here** — G2 proves the
  plumbing, not the quality. Say so rather than tuning the scorer until the number looks good.
- Any fixture candidate you dropped and why.
- Anything in this brief that turned out to be wrong about the code.
- Everything you could not measure.

Do not commit. Do not edit `goal.md`, `state.json`, `journal.md`, `backlog.md`, `decisions.md`, or any
`validation/stage*-review.md`.
