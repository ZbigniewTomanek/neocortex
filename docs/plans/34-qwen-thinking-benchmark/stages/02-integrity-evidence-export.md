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
     `source_present`, `target_present`, `source_id`, `target_id`, `timestamp`, and for temporal events
     `survived` (filled in step 2, default `null`). There is no `relation_type` on either event — add it
     at the `logger.bind` call in `_apply` if the exporter needs it, rather than emitting a null column.
     `run_id` comes from `build_audit_fields`, which reads `NEOCORTEX_BAKEOFF_RUN_ID` and falls back to
     the literal `"unavailable"`; a run whose worker did not export that variable cannot be filtered, so
     treat an all-`"unavailable"` selection as `NOT MEASURED`, not as zero events. Refuse to write when any selected event
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
     `target_id`, `weight`, `source_episode`, `endpoints_exist`. `type_valid` uses `_VALID_NODE_TYPE` /
     `_VALID_EDGE_TYPE` from `src/neocortex/normalization.py` (the regexes `normalize_node_type` and
     `normalize_edge_type` enforce) — not the weaker length/uppercase check in `extraction/schemas.py`,
     which would pass names the normalizer rejects and make Stage 7's sample gate a rubber stamp.
     Output does **not** validate against Plan 33's `quality-sample-qwen-flash-next.schema.json`: that
     schema is `additionalProperties: false` and requires `name` (an `opaque_id`/`one_way_hash` union),
     `source_job_id` and `source_episode_key`, none of which this field set emits. Write a new
     `docs/plans/34-qwen-thinking-benchmark/resources/quality-sample-tuned.schema.json` for the field set
     above, commit it, and leave the Plan 33 schema untouched so its historical artifact keeps validating.
     Fewer than 20 rows is written as a shortfall with `count`, never padded.

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
   - Details: for a child recorded by exit status only, capture `failure_step` (the last progress banner
     printed) and `exception_class` (the class name on the final traceback line). Never the message text.
     The children use three conventions and the parser must handle all three, because the banner text
     differs per child: `=== Step N: … ===` (`e2e_cognitive_recall_test.py`,
     `e2e_extraction_pipeline_test.py`), `=== Stage N: … ===` (`e2e_episodic_memory_test.py` — the child
     that hosts the formatter defect, so a parser that misses it blinds the one failure this plan most
     wants attributed), and `--- {scenario docstring} ---` (`e2e_plan15_scenarios_test.py`,
     `e2e_plan17_validation.py`). `model_bakeoff.sh` already captures `$stdout_path`/`$stderr_path`; thread
     both into `write-exit-result`, since banners go to stdout and tracebacks to stderr.
   - Tests: one fixture per convention, so a parser matching only `=== Step` turns the gate red.

6. Parametrize the parsing report.
   - Where: `RUN_ID`, `ARM`, `REASON_AUDIT`, `REASON_GRAPH`, `MISSING_GRAPH_PATH` in
     `scripts/generate_qwen_parsing_report.py`.
   - Details: add `--run-id` and `--arm` to the **`generate` subparser** (`_parser()` builds
     `add_subparsers(dest="command", required=True)` with `generate|validate|self-check|privacy-scan`;
     `generate` already requires `--plan-dir` and `--output-dir`). Do not make the subcommand optional and
     do not move the flags to the top level — the other three subcommands do not take them. Defaults keep
     the swift3 values so existing invocations are unchanged. When a skip-events file and a sample file
     for that run exist, the per-episode skip and graph fields read from them; otherwise the existing
     `NOT MEASURED` reasons stay.
   - Note: regeneration also digests `run_metadata.source_paths.graph_snapshot`, a tarball under the
     gitignored `backups/`. It is present on the development machine; on a clean checkout the byte-identity
     gate below is `NOT MEASURED`, not red.

---

## Verification

- [ ] GATE `uv run pytest tests/unit/test_export_skip_events.py tests/unit/test_export_graph_sample.py tests/unit/test_qwen_parsing_report.py -q` — passes: a fixture log with 3 missing-node and 2 temporal events yields exactly those rows; a fixture event carrying a `name` field is refused; a fake connection with 25 nodes/30 edges yields a deterministic 20/20; a fake with 7 edges yields a shortfall row, not 20; a canned extraction over the cap logs `relations_dropped_by_cap == 1`; a stderr fixture for each of the three banner conventions (`=== Step`, `=== Stage`, `--- docstring ---`) yields a non-null `failure_step`, so a parser matching only one convention turns it red.
- [ ] GATE `uv run python scripts/generate_qwen_parsing_report.py generate --plan-dir docs/plans/33-local-qwen-migration --output-dir docs/plans/33-local-qwen-migration/resources --run-id 20260911T001509Z-swift3 --arm qwen-flash-next-compact` regenerates `docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.json` byte-identically (`git diff --exit-code` on that file) — any change to the historical report turns it red. If the `backups/` snapshot named in the metrics file is absent, record `NOT MEASURED` for this line and say so.
- [ ] GATE `uv run pytest tests/ -q` and `uv run ruff check .` — pass.

REPORT in `journal.md`: live exporter behaviour against PostgreSQL is `NOT MEASURED` in this stage by design; Stage 7 measures it.

---

## Commit

`feat(scripts): export privacy-safe skip events and graph samples`
