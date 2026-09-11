# Stage 6: Per-agent thinking-level sweep

**Goal**: Measure fact retention, validity, cost, and timeouts for each distinct thinking level per agent on the in-memory probe, and select one level per agent by a pre-committed rule.
**Dependencies**: 4, 5
**Reference**: [resources/commands.md](../resources/commands.md)

Live budget 4 hours total, detached, incremental. Each cell runs once.

If Stage 5's cancellation rule fired (`distinct_levels == ["off"]`), this stage runs **no live cells**:
write `resources/effort-sweep.json` with every cell `NOT MEASURED`, reason `endpoint_ignores_effort`,
select `off` for all four agents, and continue. Do not spend the budget confirming Stage 5.

---

## Steps

0. Preconditions. Read `distinct_levels` from `resources/effort-levels.json` (drop `off`; call the rest
   `L*`). Every agent's sweep runs `L*` **plus its own `off` cell** at that agent's pinned upstream
   configuration. Stage 4's baseline is the extractor's `off` cell only — it ran with every agent `off`,
   so it is not a valid `off` row for the librarian, ontology or classifier, and comparing against it
   would confound the agent's own level with a different upstream setting. Four extra cells; they are the
   cheapest cells in the sweep and, per D28, `off` must be able to win. Run the whole cell plan with `--test-model` first; it must finish in seconds with every row
   present. Launch every live cell with `nohup` per `resources/commands.md`, poll no more often than
   every 5 minutes, and copy each finished probe JSON to `resources/sweep/<agent>-<level>.json`.

1. Extractor sweep. The `off` cell is Stage 4's baseline (same configuration; do not rerun it). For each
   level in `L*`: `--corpus both --thinking off --thinking-extractor <level>
   --per-call-timeout 300 --episode-timeout 600 --max-wall-seconds 3600 --cache-dir .tmp/plan34/cache`.
   Ontology and librarian stay `off`. Select `L_ext` by the rule below.

2. Librarian sweep. Run `off` first at the pinned `L_ext`, then for each level in `L*`: `--stage librarian --cache-thinking <L_ext cache>
   --thinking-librarian <level>` on `--corpus both`, fresh in-memory repo per episode plus the shared
   triplet repos. The one-shot profile makes at most one request per episode, so this is cheap. Select
   `L_lib`.

3. Ontology sweep. Run `off` first at the pinned `L_ext`/`L_lib`, then for each level in `L*`: `--thinking-ontology <level> --thinking-extractor <L_ext>
   --thinking-librarian <L_lib>` on `--corpus compact`. Record accepted/rejected type counts and downstream
   `fact_score`. Select `L_ont`.

4. Classifier sweep. Run `off` first, then for each level in `L*`: `--classify --thinking-classifier
   <level>` on the eight compact episodes. Stage 4's baseline never ran `--classify`, so the classifier
   has no `off` row from anywhere else. Record `valid_result`, elapsed, and the returned domain set per
   episode. Select the lowest level with 8/8 valid results — `off` counts as the lowest — and report
   domain agreement across levels.

5. Selection rule (pre-committed; apply mechanically and write the applied arithmetic).
   - Disqualify a level for an agent when any raw row shows a critical defect (invalid type name, leaked
     reasoning marker, validation failure after retries, unknown tool call) or more than 1 `TIMEOUT` in
     14 episodes.
   - Rank on triplet passes first (a pass is `new_present and old_absent`, max 3). The triplets are the
     defect class that produced every real quality miss in Plan 33, and `facts_found` cannot see that
     defect at all: the scorer matches over `name + content + property values`, so a scalar stranded in
     `properties` — exactly what Stage 4 fixes — still scores. A 3-vs-47 weighting would let one incidental
     fact outrank a lost supersession, so the terms are not summed.
   - Within the highest triplet-pass tier, rank on Σ compact `facts_found`.
   - Then apply D28 explicitly: among levels within 2 `facts_found` of the best in that tier, choose the
     **lowest** level (`off` < `low` < `medium` < `high`), not the highest score. Effort is a cost, and the
     plan's standing rule is the lowest effort that passes.
   - Write the applied arithmetic: the tier of every level, the tie band, and why the winner won.
   - Write `resources/effort-sweep.json` (`cells[]` with `agent`, `level`, `raw_path`, `episodes`,
     `triplet_passes`, `facts_found`, `facts_total`, `tier`, `selected`, `timeouts`, `critical_defects`,
     `median_reasoning_tokens`, `p50_s`, `p95_s`, `status`) and `resources/effort-sweep.md` with the
     selection table and the rule as applied.

6. Budget. Launch order within each agent is `off` first, then `L*` ascending, so a truncated agent still
   has the baseline its selection needs. If 4 hours elapse, stop launching cells, mark the remaining cells
   `NOT MEASURED`, select among measured cells, and say so in the sweep file and `journal.md`. An agent
   with no measured cell selects `off` and is reported as `NOT MEASURED`, which Stage 8 reads as `HOLD`.
   Do not extend the budget.

---

## Verification

- [ ] GATE sweep completeness and provenance — every cell in `resources/effort-sweep.json` either names a `raw_path` under `resources/sweep/` whose row count equals `episodes`, or is `TIMEOUT`/`NOT MEASURED`; a cell whose numbers do not match its raw file, or a default row, turns it red.
- [ ] GATE selected levels are clean — for each agent the selected level's raw rows show an empty `critical_defects` list and `timeouts <= 1`; a selection that violates the rule turns it red.
- [ ] REPORT `uv run pytest tests/ -q` and `uv run ruff check .` — no product code should change in this stage; record the result and, if code did change, why.
- [ ] REPORT per-cell fact scores, triplet passes, tokens, p50/p95 seconds, timeouts, total live wall time, and the selection — record in `journal.md`.

---

## Commit

`test(models): sweep Qwen thinking levels per agent`
