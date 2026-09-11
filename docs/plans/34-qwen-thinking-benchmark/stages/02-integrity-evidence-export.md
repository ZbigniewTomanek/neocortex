# Stage 2: Privacy-safe integrity evidence export

**Goal**: Turn the per-event skip evidence that already exists in the private audit log, and the raw graph, into committed privacy-safe artifacts so Plan 33 backlog 16 and the 20-node/20-edge sample become measurable.
**Dependencies**: None

No live model call. Live PostgreSQL verification happens in Stage 7; here everything is unit-tested with
fixture logs and a fake connection.

---

## Steps

1. Skip-event exporter.
   - Where: new `scripts/export_skip_events.py`; reuse `_audit_log_paths` and `_read_audit_logs` from
     `scripts/compute_metrics.py`.
   - Details: select events named `edge_skipped_missing_node` and `edge_skipped_temporal_pair` (emitted in
     `_apply` of `src/neocortex/extraction/oneshot_librarian.py`) whose `run_id` matches `--run-id`. Emit
     `skip-events-<arm>-<run_id>.json` with only: `reason_code`, `episode_id`, `correlation_id`, `stage`,
     `relation_type`, `source_present`, `target_present`, `source_id`, `target_id`, `timestamp`, and for
     temporal events `survived` (filled in step 2, default `null`). Refuse to write when any selected event
     carries a field outside the allowlist that looks like text (name, content, description); reuse
     `_validate_safe_content` and `privacy_scan` from `scripts/generate_qwen_parsing_report.py`. Ship a JSON
     Schema next to the existing report schemas.

2. Temporal survival and graph sample.
   - Where: new `scripts/export_graph_sample.py`, using `schema_scoped_connection` from
     `src/neocortex/db/scoped.py` and parameterized `asyncpg` queries only.
   - Details: `--check-temporal skip-events.json` queries, per `temporal_pair` event and schema, whether an
     edge of type `SUPERSEDES` or `CORRECTS` exists between `source_id` and `target_id` (either direction —
     confirm against the write in `_apply`) and writes `survived`. `--sample 20` selects a deterministic
     20 nodes and 20 edges (order by id, stride) across the schemas listed in the run's metrics JSON and
     emits per node: `schema`, `id`, `type`, `name_length`, `content_length`, `property_key_count`,
     `source_episode` (the `_source_episode` property), `type_valid`; per edge: `id`, `type`, `source_id`,
     `target_id`, `weight`, `source_episode`, `endpoints_exist`. `type_valid` uses the same type-name rule
     the extraction normalizer applies (find it in `src/neocortex/extraction/`). Output must validate
     against `resources/quality-sample-qwen-flash-next.schema.json` in Plan 33; extend that schema if a
     field is new, and keep it committed. Fewer than 20 rows is written as a shortfall with `count`, never
     padded.

3. Count cap-triggered drops.
   - Where: `cap_extraction_entities` in `src/neocortex/extraction/agents.py`; the
     `extractor_cardinality_capped` event in `run_extraction` (`src/neocortex/extraction/pipeline.py`);
     `audit_metrics` in `scripts/compute_metrics.py`.
   - Details: return the number of relations dropped with their endpoints; log it as
     `relations_dropped_by_cap`; aggregate it into the metrics JSON.

4. Consistency check in metrics.
   - Where: `scripts/compute_metrics.py`.
   - Details: `--skip-events PATH` adds `skip_events_consistent: {missing_node: bool, temporal_pair: bool}`
     comparing exported counts with the aggregate counters, and `temporal_survived: {total, survived}`.

5. Diagnosable E2E failures.
   - Where: `write-exit-result` in `scripts/e2e_manifest.py` and its callers in `scripts/model_bakeoff.sh`.
   - Details: for a child recorded by exit status only, capture `failure_step` (the last `=== Step` or
     scenario label printed) and `exception_class` (the class name on the final traceback line). Never the
     message text. Tests cover a fixture stderr.

6. Parametrize the parsing report.
   - Where: `RUN_ID`, `ARM`, `REASON_AUDIT`, `REASON_GRAPH`, `MISSING_GRAPH_PATH` in
     `scripts/generate_qwen_parsing_report.py`.
   - Details: `--run-id` and `--arm` replace the constants (defaults keep the swift3 values). When a
     skip-events file and a sample file for that run exist, the per-episode skip and graph fields read from
     them; otherwise the existing `NOT MEASURED` reasons stay.

---

## Verification

- [ ] GATE `uv run pytest tests/unit/test_export_skip_events.py tests/unit/test_export_graph_sample.py tests/unit/test_qwen_parsing_report.py -q` — passes: a fixture log with 3 missing-node and 2 temporal events yields exactly those rows; a fixture event carrying a `name` field is refused; a fake connection with 25 nodes/30 edges yields a deterministic 20/20; a fake with 7 edges yields a shortfall row, not 20; a canned extraction over the cap logs `relations_dropped_by_cap == 1`.
- [ ] GATE `uv run python scripts/generate_qwen_parsing_report.py --run-id 20260911T001509Z-swift3 --arm qwen-flash-next-compact` regenerates `docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.json` byte-identically (`git diff --exit-code` on that file) — any change to the historical report turns it red.
- [ ] GATE `uv run pytest tests/ -q` and `uv run ruff check .` — pass.

REPORT in `journal.md`: live exporter behaviour against PostgreSQL is `NOT MEASURED` in this stage by design; Stage 7 measures it.

---

## Commit

`feat(scripts): export privacy-safe skip events and graph samples`
