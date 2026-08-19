# Stage 4: Measurement Harness

**Goal**: Build the missing connective tissue — a corpus loader, a metrics emitter, and an arm orchestrator — so a bake-off arm is one command and its result is a machine-diffable JSON file.
**Dependencies**: None strictly, but run after Stage 3 so both arms measure hardened prompts (D5).

---

## What already exists (do not rebuild)

| Asset | Path | Status |
|---|---|---|
| Ontology metrics SQL | `docs/plans/29-ontology-validation/resources/queries.md:29-71` | **5 of the 6 claimed metrics** — no instance-level types; `{schema}` is find-and-replace; garbage regex is a stale copy |
| 14-scenario recall gate (≥11/14) | `scripts/e2e_plan15_scenarios_test.py` | Complete corpus + scoring; **always exits 0** — parse the score line |
| 14-scenario gate (≥13/14) + 8 episodes | `scripts/e2e_plan17_validation.py` | Complete; **always exits 0** — parse the score line |
| Binary pipeline smoke | `scripts/e2e_extraction_pipeline_test.py` | Complete |
| Episodic + cognitive gates | `scripts/e2e_episodic_memory_test.py`, `scripts/e2e_cognitive_recall_test.py` | Complete |
| Service lifecycle + fresh DB | `scripts/run_e2e.sh`, `scripts/manage.sh start --fresh` | Complete |
| Graph state save/restore | `scripts/manage.sh snapshot save\|load` | Complete |
| Per-job timings | `GET /admin/jobs` (`created_at`, `started_at`, `finished_at`, `attempts`) | Exposed, **never aggregated** |
| 28-episode golden corpus | `docs/plans/18.5-e2e-revalidation/resources/episodes.md` | **Data only — no loader** |
| 9 recall queries + pass criteria | `docs/plans/18.5-e2e-revalidation/resources/recall-queries.md` | **Protocol only — no runner** |

## What is missing (build exactly this, nothing more)

1. a loader for the 28-episode corpus,
2. a runner+scorer for the 9 recall queries (M1–M4),
3. a metrics emitter that produces one JSON per arm,
4. an orchestrator that runs a whole arm unattended.

---

## Steps

1. **Corpus loader.**
   - File: `scripts/corpus_loader.py` (new)
   - Details: parse `docs/plans/18.5-e2e-revalidation/resources/episodes.md` — 28 episodes across
     4 phases, each with a fixed `importance` (0.5–0.9) and a `context` tag
     (`e2e_revalidation_phase1` …). Ingest via `POST /ingest/text` preserving both.
     **Pass `"force": true`** — Plan 26 added SHA-256 content dedup and identical re-ingestion is
     otherwise skipped, which would silently produce an empty second arm. Do **not** use Plan 32's
     `uuid4().hex[:8]` suffix trick: it defeats dedup but also makes the two arms' inputs differ.
     Fresh DB per arm is the correct isolation.
   - Print a per-episode confirmation and exit non-zero if fewer than 28 episodes were accepted.

2. **Recall query runner and M1–M4 scorer.**
   - File: `scripts/recall_scorer.py` (new)
   - Details: execute Q1–Q9 from `recall-queries.md` against the MCP `recall` tool and compute:
     - **M1** max `activation_score` across all results (target ≤ 0.70; Plan 18.5 measured 0.666)
     - **M2** single-episode dominance — count of queries where the same item ranks #1 (target ≤ 3/9)
     - **M3** specific-event recall — Q3/Q4/Q5, pass = target episode in top 5 (target ≥ 2/3)
     - **M4** temporal evolution — Q7/Q8/Q9, pass = latest correction outranks the older version
       (target ≥ 2/3; Plan 18.5 measured **0/3 FAIL**, so this is a known-weak metric and a
       regression here is less informative than a gain)
     Each query's expected top-5 is already written in the resource file; encode it as data, not code.

3. **Metrics emitter.**
   - File: `scripts/compute_metrics.py` (new)
   - Details: takes `--arm <name>` and writes
     `docs/plans/33-local-qwen-migration/resources/metrics-<arm>.json` containing every Tier 1–3
     metric from the index's Success Criteria:
     - **Tier 1a — Plan 29's all-in-one SQL per schema.** It returns **five** columns
       (`active_node_types`, `active_edge_types`, `unused_edge_type_pct`, `garbage_types`,
       `type_reuse_ratio`) despite its header claiming six. `{schema}` is a textual placeholder, so
       substitute it per schema. **One deliberate edit to the "verbatim" rule:** its `garbage_types`
       regex is a hardcoded pre-Qwen copy of `_TOOL_CALL_ARTIFACT`. Interpolate the live pattern
       instead — `_TOOL_CALL_ARTIFACT.pattern` from `neocortex.normalization` — or the metric cannot
       see the shapes Stage 3 step 6 just added. Everything else stays byte-identical so the numbers
       remain comparable with Plan 29's.
     - **Tier 1b — instance-level type candidates.** *Not* in that SQL; Plan 29 computed it by human
       review ("query returns candidates, human judges"), which an unattended run cannot do. Use this
       explicit rule instead: a type name is a candidate when it is multi-segment PascalCase **and**
       its leading segment exactly matches another, shorter existing type name in the same schema
       (`Dish` + `Greg` → `DishGreg`; `Location` + `SalCapeVerde` → `LocationSalCapeVerde`). Emit the
       candidate list, not just a count, and gate on **count above baseline** rather than absolute 0 —
       a heuristic this blunt will have standing false positives that both arms share.
     - **Tier 1c — invalid-type rejection rate.** Parse `log/agent_actions.log` for the five events
       step 4 binds (`skipping_entity_invalid_type`, `skipping_invalid_node_type`,
       `skipping_invalid_edge_type`, `invalid_node_type_rejected`, `invalid_edge_type_rejected`) plus
       `propose_type` rejections. Report the rate as rejections ÷ total entity attempts, and the raw
       counts and rejected names alongside. **This is the metric that makes Qwen leakage visible at
       all** — see Stage 3 step 6.
     - **Tier 1d** — job failure rate from `GET /admin/jobs/summary`; a type-name validity scan
       (≤60 chars, ≤5 segments, PascalCase); and a leak scan applying the live
       `_TOOL_CALL_ARTIFACT` across all stored node names, edge type names, and node content
       (the regex itself only ever guarded type names, so this scan is new coverage).
     - **Tier 2** — parsed scores from the five e2e scripts. `e2e_plan15_scenarios_test.py` and
       `e2e_plan17_validation.py` **always exit 0** — they swallow per-scenario exceptions and never
       call `sys.exit` — so read their printed `Acceptable (PASS only): X/14` line and never `$?`.
       The other three are genuinely exit-code gated (uncaught `assert`). Plus entity dedup rate
       (Plan 22 M1 method); episodes-consolidated percentage (`episode.consolidated` is a real
       column — count it in SQL); M1–M4 from step 2.
     - **Tier 3** — per-episode p50/p95 wall-clock derived from `GET /admin/jobs`; per-stage timings;
       total LLM calls and prompt/completion/reasoning tokens; tool calls per extraction; retry counts.

4. **Make latency and token cost measurable at all.**
   - File: `src/neocortex/extraction/pipeline.py`
   - Details: 8 `logger.debug("stage_timing", stage=…, elapsed_s=…)` calls already exist
     (`metadata_fetch`, `ontology_agent`, `type_persist`, `extractor_agent`, `embedding_precompute`,
     `librarian_agent` ×2, `persist_payload`). They are DEBUG-level and **not** bound to `action_log`,
     so they never reach `agent_actions.log`. Bind them with `logger.bind(action_log=True).info(...)`
     so Tier 3 is derivable from a durable artifact.
   - Also log each agent's `result.usage()` to the audit log after every `agent.run()`. Today only the
     **ontology** stage does this, at `pipeline.py:184`, and it stringifies the whole object
     (`usage=str(ontology_result.usage())`). Emit **structured numeric fields** instead, for all three
     agents plus the classifier: `RunUsage` carries `requests`, `tool_calls`, `input_tokens`,
     `output_tokens` as typed ints, and `details` is a plain `dict[str, int]` — so read
     `usage.details.get("reasoning_tokens")` and record `null` when the provider omits it rather than
     assuming the key exists. NeoCortex has never counted tokens; this is required to reason about the
     endpoint's `max_running_requests=8` ceiling.
   - **Bind the invalid-type rejection events to `action_log` too** (Tier 1c depends on them being in
     `agent_actions.log`, and today they are plain `logger.warning` calls landing only in the service
     log): `skipping_entity_invalid_type` and `skipping_invalid_node_type` /
     `skipping_invalid_edge_type` in `extraction/pipeline.py` (`:417-421`, `:446-449`), and
     `invalid_node_type_rejected` / `invalid_edge_type_rejected` in `db/adapter.py` (`:536-540`,
     `:568-572`). Include the rejected name and the raising reason in the bound fields.

5. **Arm orchestrator.**
   - File: `scripts/model_bakeoff.sh` (new)
   - Details: given an arm name and the four model strings, run end-to-end unattended:
     ```
     manage.sh start --fresh
     assert embeddings live          # see step 6
     provision seed schemas          # see step 6
     corpus_loader.py
     poll /admin/jobs/summary until todo+doing == 0   # see the two rules below
     compute_metrics.py --arm <name>  --phase corpus  # graph metrics, BEFORE any e2e run
     recall_scorer.py                                 # M1-M4, also on the corpus graph
     manage.sh snapshot save <name>
     run the 5 e2e scripts, parsing scores            # each rebuilds its own graph
     compute_metrics.py --arm <name> --phase e2e --merge
     ```
     Both arms must run the identical sequence. Log the resolved model strings, thinking efforts, and
     `worker_concurrency` into the metrics JSON so an arm can never be misattributed.
   - **Order matters, and this is the one ordering bug that would silently void an arm.**
     `run_e2e.sh:122` calls `manage.sh start --fresh`, which runs `docker compose down -v` — it
     **wipes the database** — and it takes exactly one test script per invocation (enforced at
     `run_e2e.sh:90`). So every graph-derived metric (all of Tier 1, the ontology and dedup halves of
     Tier 2, and M1–M4) must be computed **and snapshotted** against the 28-episode corpus graph
     *before* the first e2e script runs. The five e2e scripts each bring their own corpus and their own
     fresh DB; their contribution is their score line, nothing more. Do **not** try to run them
     against the corpus graph, and do not run `compute_metrics.py` after them expecting the corpus to
     still be there.
   - **Poll timeout: derive it, do not guess, and abort rather than proceed.** Stage 5 budgets the
     *faster* hosted arm at 30–45 min for these 28 episodes; `resources/probes.md` Probe 5 measured the
     Qwen extractor **alone** at 124.8 s at `low` (and past 150 s at `medium`), which is one of three
     sequential agents at the cheapest effort. Budget the Qwen arm at **≥ 4 h** and pass the timeout in
     as a parameter per arm. If the poll expires with anything still in `todo`/`doing`, the orchestrator
     must **exit non-zero without computing metrics** — a partially-extracted graph produces numbers
     indistinguishable from a real quality collapse, and reporting them would poison Stage 7.

6. **Two pre-flight assertions that silently corrupt an arm if skipped.**
   - Details:
     - **Embeddings must be live.** `embedding_service.py` returns `None` without `GOOGLE_API_KEY`
       and degrades recall to text-only **with no error** (index Backlog #3). Assert a non-null
       768-dim embedding comes back before ingesting anything. Use the **real constructor signature** —
       `EmbeddingService(model: str | None = None, dimensions: int = 768)`, matching the production
       call site at `services.py:112`:
       ```python
       e = EmbeddingService(model=MCPSettings().embedding_model)
       ```
       Passing an `MCPSettings` object positionally (as an earlier draft of
       `resources/commands.md` did) binds it to `self._model`; the Gemini SDK then rejects it, and
       `embed()`'s bare `except Exception: return None` swallows the error — so the assertion reports
       "embeddings dead" even when they are perfectly healthy. Note `GOOGLE_API_KEY` is read straight
       from `os.environ`, not from `MCPSettings`.
     - **Seed schemas must be provisioned.** `.claude/skills/neocortex/KNOWN_ISSUES.md` documents
       this as a mandatory pre-flight step whose omission silently zeroes domain routing — which is
       exactly how Plan 18.5's M5 scored 0/28. Assert the shared schemas exist before ingesting.

---

## Verification

- [ ] `uv run python scripts/corpus_loader.py --dry-run` parses exactly **28** episodes with
      importance and context preserved. (Delimiters: `### Episode N -- Title`, then
      `**Importance**: X`, `**Context**: "tag"`, then a fenced block with the text. Observed importance
      values are `{0.5, 0.6, 0.7, 0.8}` — 4 phases of 8/9/8/3.)
- [ ] **The harness reproduces already-known numbers.** Restore the Plan 29-era graph first —
      `./scripts/manage.sh snapshot load pre-plan30-20260407-201234` — then run `compute_metrics.py`
      against it and confirm the Plan 29 metrics match what
      `docs/plans/29-ontology-validation/index.md` recorded (its Stage 6 vs Stage 8 table). If they
      disagree, the harness is wrong — fix it before it is used to judge a model.
      **Do not run this against the live graph**: it has drifted through Plans 30–32 and its
      `graph_registry` holds schemas created as late as 2026-07-28, so a mismatch there tells you
      nothing about the harness. Snapshot the current graph first if you want it back.
- [ ] `scripts/model_bakeoff.sh --dry-run` prints the full command sequence without executing.
- [ ] `uv run pytest tests/ -v` passes (the pipeline logging change touches production code).
- [ ] After one real extraction, `log/agent_actions.log` contains `stage_timing` entries and
      per-agent token usage.
- [ ] Both pre-flight assertions fail loudly when deliberately broken (unset `GOOGLE_API_KEY`;
      skip schema provisioning) **and pass when correctly configured** — the second half is the one
      that catches a mis-constructed `EmbeddingService`.
- [ ] Tier 1c is wired end-to-end: feed a node type containing `<think>` through
      `get_or_create_node_type`, then confirm `compute_metrics.py` reports a non-zero rejection count
      for that arm. A rejection metric that silently reads 0 is worse than not having one.
- [ ] `compute_metrics.py` interpolates the live `_TOOL_CALL_ARTIFACT` pattern into the garbage-type
      SQL — verify by asserting the emitted SQL contains `tool_call`, which Plan 29's frozen copy
      does not.
- [ ] The orchestrator exits non-zero, without writing a metrics file, when the job poll times out
      with work still outstanding (test by setting an absurdly short timeout).

---

## Commit

`feat(scripts): add model bake-off harness — corpus loader, metrics emitter, orchestrator`
