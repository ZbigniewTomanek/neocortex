# Stage 4: Measurement Harness

**Goal**: Build the missing connective tissue — a corpus loader, a metrics emitter, and an arm orchestrator — so a bake-off arm is one command and its result is a machine-diffable JSON file.
**Dependencies**: None strictly, but run after Stage 3 so both arms measure hardened prompts (D5).

---

## What already exists (do not rebuild)

| Asset | Path | Status |
|---|---|---|
| Ontology metrics SQL | `docs/plans/29-ontology-validation/resources/queries.md:29-71` | Complete, per-schema, all-in-one |
| 14-scenario recall gate (≥11/14) | `scripts/e2e_plan15_scenarios_test.py` | Complete, self-contained corpus + scoring |
| 14-scenario gate (≥13/14) + 8 episodes | `scripts/e2e_plan17_validation.py` | Complete |
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
     - **Tier 1** — Plan 29's all-in-one SQL per schema (garbage types, instance-level types, active
       node/edge type counts, unused edge %, type reuse ratio); job failure rate from
       `GET /admin/jobs/summary`; a type-name validity scan (≤60 chars, ≤5 segments, PascalCase);
       and a leak scan applying `normalization._TOOL_CALL_ARTIFACT` across all stored node names,
       edge type names, and node content.
     - **Tier 2** — exit codes and parsed scores from the five e2e scripts; entity dedup rate
       (Plan 22 M1 method); episodes-consolidated percentage; M1–M4 from step 2.
     - **Tier 3** — per-episode p50/p95 wall-clock derived from `GET /admin/jobs`; per-stage timings;
       total LLM calls and prompt/completion/reasoning tokens; tool calls per extraction; retry counts.
   - **Reuse the SQL verbatim** from Plan 29's resource file rather than retyping it — the point is
     that the two runs' numbers are comparable with the numbers already recorded there.

4. **Make latency and token cost measurable at all.**
   - File: `src/neocortex/extraction/pipeline.py`
   - Details: 8 `logger.debug("stage_timing", stage=…, elapsed_s=…)` calls already exist
     (`metadata_fetch`, `ontology_agent`, `type_persist`, `extractor_agent`, `embedding_precompute`,
     `librarian_agent` ×2, `persist_payload`). They are DEBUG-level and **not** bound to `action_log`,
     so they never reach `agent_actions.log`. Bind them with `logger.bind(action_log=True).info(...)`
     so Tier 3 is derivable from a durable artifact.
   - Also log each agent's `result.usage()` (`input_tokens`, `output_tokens`,
     `details.reasoning_tokens`, `requests`, `tool_calls`) to the audit log after every
     `agent.run()`. NeoCortex has never counted tokens; this is required to reason about the
     endpoint's `max_running_requests=8` ceiling.

5. **Arm orchestrator.**
   - File: `scripts/model_bakeoff.sh` (new)
   - Details: given an arm name and the four model strings, run end-to-end unattended:
     ```
     manage.sh start --fresh
     assert embeddings live          # see step 6
     provision seed schemas          # see step 6
     corpus_loader.py
     poll /admin/jobs/summary until todo+doing == 0 (or timeout)
     run the 5 e2e scripts, capturing exit codes
     recall_scorer.py
     compute_metrics.py --arm <name>
     manage.sh snapshot save <name>
     ```
     Both arms must run the identical sequence. Log the resolved model strings and thinking efforts
     into the metrics JSON so an arm can never be misattributed.

6. **Two pre-flight assertions that silently corrupt an arm if skipped.**
   - Details:
     - **Embeddings must be live.** `embedding_service.py` returns `None` without `GOOGLE_API_KEY`
       and degrades recall to text-only **with no error** (index Backlog #3). Assert a non-null
       embedding comes back before ingesting anything.
     - **Seed schemas must be provisioned.** `.claude/skills/neocortex/KNOWN_ISSUES.md` documents
       this as a mandatory pre-flight step whose omission silently zeroes domain routing — which is
       exactly how Plan 18.5's M5 scored 0/28. Assert the shared schemas exist before ingesting.

---

## Verification

- [ ] `uv run python scripts/corpus_loader.py --dry-run` parses exactly **28** episodes with
      importance and context preserved.
- [ ] **The harness reproduces already-known numbers.** Run `compute_metrics.py` against the
      *existing* graph and confirm the Plan 29 metrics match what
      `docs/plans/29-ontology-validation/index.md` recorded for the same data. If they disagree,
      the harness is wrong — fix it before it is used to judge a model.
- [ ] `scripts/model_bakeoff.sh --dry-run` prints the full command sequence without executing.
- [ ] `uv run pytest tests/ -v` passes (the pipeline logging change touches production code).
- [ ] After one real extraction, `log/agent_actions.log` contains `stage_timing` entries and
      per-agent token usage.
- [ ] Both pre-flight assertions fail loudly when deliberately broken (unset `GOOGLE_API_KEY`;
      skip schema provisioning).

---

## Commit

`feat(scripts): add model bake-off harness — corpus loader, metrics emitter, orchestrator`
