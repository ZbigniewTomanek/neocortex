# Stage 2 brief — Privacy-safe integrity evidence export

| | |
|---|---|
| Implementer | `codex/gpt-5.6-sol`, effort `high` (strong tier; resumed on Codex) |
| Reviewer | `codex/gpt-5.6-sol`, effort `high` (strong tier) |
| Tier reason | Two new exporters, a privacy contract, a SQL access path, and a byte-identity constraint on a historical artifact. Nothing mechanical. |
| Plan stage | [stages/02-integrity-evidence-export.md](../stages/02-integrity-evidence-export.md) |
| Run contract | [goal.md](../goal.md) · [PROTOCOL.md](../PROTOCOL.md) |

**No live model call. No live PostgreSQL call.** Every database path in this stage is exercised against a
fake connection in unit tests. Stage 7 is the first time these scripts touch a real database.

---

## Why this stage exists

Plan 33 could not attribute its integrity gaps. `edge_skipped_missing_node` (16 events) and
`edge_skipped_temporal_pair` (5) are already logged per event with full identifiers — but only to
`log/agent_actions.log`, which the evidence tooling refuses to read because it is private. The graph
"sample" was a raw `pg_dump`. Cap-triggered relation drops were not counted at all. This stage turns
three private or absent signals into committed, privacy-safe artifacts so Stage 7 can measure them.

---

## Ground truth, already verified — build on these, do not re-derive

From an inventory of the current tree:

- `scripts/compute_metrics.py:240` `_audit_log_paths() -> list[Path]` globs `ROOT/"log"` for
  `agent_actions*.log`, sorting the active file first. `:252` `_read_audit_logs() -> tuple[list[Path],
  list[str], bool]` returns paths, all lines, and a read-error flag.
- `scripts/compute_metrics.py:437` `audit_metrics(*, run_id=None, correlation_id=None) -> dict`. Its
  `audit_event_counts` is a **generic** per-event-name counter (`counts[event] = counts.get(event,0)+1`,
  line 479). Neither skip event is named anywhere in the file; they appear only as keys in that counter.
  That counter is the "aggregate" your consistency check compares against.
- `compute_metrics.py` has a **flat** argparse (lines 550-565): `--arm` (required), `--phase`,
  `--merge`, `--corpus-profile`, `--snapshot-path`, `--snapshot-sha256`, `--ingestion-url`, `--run-id`.
  Output goes to `docs/plans/33-local-qwen-migration/resources/metrics-{arm}.json`; `--merge` nests the
  new payload under `old["phases"][phase]`. Writes go through `_atomic_write_json`.
- `src/neocortex/extraction/oneshot_librarian.py:598` logs
  `edge_skipped_missing_node` with `source_id`, `target_id`, `source_present`, `target_present`,
  `reason_code="missing_node"`, plus `**audit`.
  `:609` logs `edge_skipped_temporal_pair` with `source_id`, `target_id`,
  `reason_code="temporal_pair"`, plus `**audit`. **The temporal event carries no `source_present` /
  `target_present`**, and neither event carries a relation type.
- `src/neocortex/extraction/agents.py:473` `build_audit_fields` derives
  `"run_id": os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID") or "unavailable"`.
- Temporal edges are written at `oneshot_librarian.py:649-668` as
  `upsert_edge(agent_id, source_id=bound[outcome.index], target_id=outcome.predecessor.id, ...)` —
  that is **new → old**, written as given, not reversed.
- `src/neocortex/normalization.py:11-12`:
  `_VALID_NODE_TYPE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")`,
  `_VALID_EDGE_TYPE = re.compile(r"^[A-Z]([A-Z0-9_]*[A-Z0-9])?$")`.
- `src/neocortex/db/scoped.py`: `schema_scoped_connection(pool, schema_name)` and
  `graph_scoped_connection(pool, schema_name, agent_id=None, required_permission=None)`, both
  `@asynccontextmanager`.
- `scripts/generate_qwen_parsing_report.py:19-20` `RUN_ID = "20260911T001509Z-swift3"`,
  `ARM = "qwen-flash-next-compact"`; `:44` `MISSING_GRAPH_PATH`; `:53-54` `REASON_GRAPH`, `REASON_AUDIT`.
  `_parser()` at `:821` builds `add_subparsers(dest="command", required=True)` with `generate`
  (`--plan-dir`, `--output-dir`), `validate`, `self-check`, `privacy-scan`.
  `_validate_safe_content(*documents) -> None` at `:394` raises `ReportError` when any `_privacy_counts`
  category is nonzero.
- `scripts/e2e_manifest.py:268` `write_exit_result(path, *, script, child_run_id, exit_code)` writes
  `schema_version, kind, script, child_run_id, status, exit_code, reason`. Its argparse at `:720` takes
  `--path --script --child-run-id --exit-code`. **No stdout/stderr field or flag exists.**
- `scripts/model_bakeoff.sh:357-364` is the **only** `write-exit-result` call site. `stdout_path` and
  `stderr_path` are set at `:320-321` and today reach only `record_private_diagnostic`.
- `cap_extraction_entities(result, cap) -> ExtractionResult` at `agents.py:89` drops low-importance
  entities and silently filters relations whose endpoints no longer survive. `pipeline.py:479-492` logs
  `extractor_cardinality_capped` with `before`, `after`, `cap`, gated on `capped is not
  extraction_result.output`.
- **The swift3 snapshot is present on this machine**:
  `backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz`, SHA-256
  `4e3dc2e6bbbbf461aa8a2a32351a82ccfc965da285304ecd33b94fc4f3bee95b`, matching
  `run_metadata.source_paths.graph_snapshot_sha256` in `metrics-qwen-flash-next-compact.json`. So gate
  G2 below **is measurable**; do not record it `NOT MEASURED` without showing a command that failed.

---

## Scope

- `scripts/export_skip_events.py` (new)
- `scripts/export_graph_sample.py` (new)
- `docs/plans/34-qwen-thinking-benchmark/resources/skip-events.schema.json` (new)
- `docs/plans/34-qwen-thinking-benchmark/resources/quality-sample-tuned.schema.json` (new)
- `docs/plans/34-qwen-thinking-benchmark/resources/qwen-parsing-report-tuned.schema.json` (new; nondefault runs only)
- `scripts/compute_metrics.py`
- `scripts/generate_qwen_parsing_report.py`
- `scripts/e2e_manifest.py`
- `scripts/model_bakeoff.sh`
- `src/neocortex/extraction/agents.py` (one new pure function only)
- `src/neocortex/extraction/pipeline.py` (the one log call)
- `tests/unit/test_export_skip_events.py` (new), `tests/unit/test_export_graph_sample.py` (new),
  `tests/unit/test_qwen_parsing_report.py`, `tests/unit/test_e2e_manifest.py`,
  `tests/test_qwen_extractor.py`

**Do not touch** `docs/plans/33-local-qwen-migration/resources/*` — the historical artifacts must stay
byte-identical. Do not touch `src/neocortex/admin/`.

---

## Step 1 — `scripts/export_skip_events.py`

CLI: `--run-id` (required), `--arm` (required), `--output PATH` (required).

Import `_audit_log_paths` and `_read_audit_logs` from `scripts.compute_metrics`; do not reimplement the
log discovery. Parse each line as the audit JSON does in `audit_metrics` and select records whose event
name is `edge_skipped_missing_node` or `edge_skipped_temporal_pair` **and** whose `run_id` equals
`--run-id`.

**Emitted fields — this list is the allowlist, nothing else may be written:**
`reason_code`, `episode_id`, `correlation_id`, `stage`, `source_present`, `target_present`, `source_id`,
`target_id`, `timestamp`, and `survived` (temporal events only; default `null`, filled by step 2).

`edge_skipped_temporal_pair` does not log `source_present`/`target_present`, so those two keys are
`null` on temporal rows. Do **not** synthesize `true`. There is no `relation_type` on either event; the
stage permits adding one at the `logger.bind` call if the exporter needs it — **it does not need it, so
do not add it.** An emitted null column would be worse than an absent one.

**Privacy refusal.** Before writing, pass the assembled document through
`_validate_safe_content` from `scripts.generate_qwen_parsing_report`, and additionally refuse — raising
with a message naming the offending key but **not its value** — when any selected source record carries a
key outside the allowlist whose value is a string longer than 40 characters or whose key name contains
`name`, `content`, `description`, `text`, or `title`. `privacy_scan` in that module is **not** reusable
here: its signature is `privacy_scan(paths: list[Path], output: Path)` and it hard-codes the parsing
report's five-file layout and expected-nonzero comparison counts. Say so in a comment rather than
bending it.

**The `unavailable` rule.** `run_id` falls back to the literal `"unavailable"` when the worker did not
export `NEOCORTEX_BAKEOFF_RUN_ID`. If every candidate record in the log carries `run_id ==
"unavailable"`, the selection cannot be attributed to this run: write a document with
`"status": "NOT MEASURED"`, `"reason": "run_id_unavailable"`, and **no** event rows. Zero events and
unattributable events are different answers and must not collapse into the same file.

Otherwise write `{"schema_version": 1, "kind": "neocortex-skip-events", "run_id", "arm", "status":
"MEASURED", "counts": {"missing_node": N, "temporal_pair": M}, "events": [...]}`. Ship
`resources/skip-events.schema.json` describing it, `additionalProperties: false` on the event objects.

Both new schemas go in **this plan's** `resources/`, not Plan 33's: Plan 33's resources are frozen
historical evidence and gate G2 proves they do not change. (Decision D-12.)

## Step 2 — `scripts/export_graph_sample.py`

Async, `asyncpg`, parameterized queries only (`$1`, `$2` — never string interpolation of a value).
Schema names reach SQL only after validating against `^ncx_[a-z0-9]+__[a-z0-9_]+$`. Use
`schema_scoped_connection` from `src/neocortex/db/scoped.py`.

CLI: `--run-id`, `--arm`, `--check-temporal PATH` (a skip-events file), `--sample N` (default 20),
`--output PATH`.

**Testability is a requirement, not a nicety.** Every query must go through an injected connection
object used only as `await conn.fetch(query, *args)`, so `tests/unit/test_export_graph_sample.py` can
drive the whole selection and shaping logic with a fake. Structure the module so the pure functions
(`select_sample`, `shape_node_row`, `shape_edge_row`, `survival_query_args`) are importable and callable
with no database at all.

**Which schemas.** Read the run's metrics JSON at
`docs/plans/33-local-qwen-migration/resources/metrics-{arm}.json`. Report in your final message which key
actually carries the schema list. If no such key exists, fall back to querying
`information_schema.schemata` for names matching the `ncx_` pattern, and record
`"schema_source": "metrics" | "information_schema"` in the output so a reader knows which path ran.

**Deterministic selection**, specified exactly so two runs agree: fetch all candidate ids ordered by
`id ASC`; if the count is `<= N`, take all of them and set `"shortfall": true` with the real `count`;
otherwise `stride = count // N` and take `rows[0::stride][:N]`. Never pad. A shortfall is the honest
answer and Stage 7 reports it as a shortfall.

**Node row**: `schema`, `id`, `type`, `name_length`, `content_length`, `property_key_count`,
`source_episode` (the `_source_episode` property, `null` when absent), `type_valid`.
**Edge row**: `id`, `type`, `source_id`, `target_id`, `weight`, `source_episode`, `endpoints_exist`.
No names, no content, no property values — lengths and counts only.

`type_valid` uses `_VALID_NODE_TYPE` / `_VALID_EDGE_TYPE` imported from
`src/neocortex/normalization.py`. **Not** the weaker length/uppercase check in
`extraction/schemas.py`: that one accepts names the normalizer rejects, which would make Stage 7's
sample gate a rubber stamp.

**`--check-temporal`.** For each `temporal_pair` event, query whether an edge whose type name is
`SUPERSEDES` or `CORRECTS` exists between `source_id` and `target_id` **in either direction**, and write
`survived` back into a copy of the skip-events document. The production write direction is new → old
(`oneshot_librarian.py:649-668`), but a skipped pair's logged orientation is not guaranteed to match, so
check both and say so in a comment.

Ship `resources/quality-sample-tuned.schema.json` for this field set. Do **not** try to validate against
Plan 33's `quality-sample-qwen-flash-next.schema.json`: it is `additionalProperties: false` and requires
`name` (an `opaque_id`/`one_way_hash` union), `source_job_id`, and `source_episode_key`, none of which
this field set emits. Leave that file untouched so its historical artifact keeps validating.

## Step 3 — count cap-triggered relation drops

`cap_extraction_entities` currently returns a bare `ExtractionResult` and `pipeline.py:479-492` depends
on the identity check `capped is not extraction_result.output`. **Do not change that signature.** Add a
sibling pure function in `src/neocortex/extraction/agents.py`:

```python
def count_capped_relations(before: ExtractionResult, after: ExtractionResult) -> tuple[int, list[tuple[str, str]]]:
    """Return how many relations the entity cap dropped, and their endpoint name pairs."""
```

Then, in the existing `extractor_cardinality_capped` log call in `pipeline.py`, add
`relations_dropped_by_cap=<count>`, `relations_before=len(before.relations)`,
`relations_after=len(capped.relations)`.

**Log the count only. Never the endpoint names.** The stage text says "with their endpoints", but the
audit log is privacy-scanned and an entity name is graph text; at cap time no node ids exist yet, so
names are the only endpoints available. The function returns the pairs for unit testing; the log carries
integers. (Decision D-13.)

Aggregate `relations_dropped_by_cap` into `audit_metrics` in `scripts/compute_metrics.py` as a summed
field, alongside the existing generic event counter.

## Step 4 — consistency check in `compute_metrics.py`

Add `--skip-events PATH` to the flat parser. When given, add to the metrics output:

- `skip_events_consistent: {"missing_node": bool, "temporal_pair": bool}` — each `true` only when the
  exported event count for that `reason_code` equals the corresponding `audit_event_counts` entry.
  A missing aggregate key with zero exported events is `true`; a missing aggregate key with exported
  events is `false`.
- `temporal_survived: {"total": int, "survived": int}` from the `survived` fields.
- When the skip-events document is `status: "NOT MEASURED"`, both consistency flags are the string
  `"NOT MEASURED"`, never `false` and never `true`.

## Step 5 — diagnosable E2E failures

Add `--stdout-path` and `--stderr-path` (both optional) to the `write-exit-result` subcommand and thread
them into `write_exit_result`, which gains two fields: `failure_step` and `exception_class`, each `null`
when unobtainable.

`failure_step` is the **last** progress banner printed on stdout. Three conventions exist and the parser
must handle all three:

| Convention | Children | Verified at |
|---|---|---|
| `=== Step N: … ===` | `e2e_cognitive_recall_test.py`, `e2e_extraction_pipeline_test.py`, `e2e_weight_stability_test.py`, `e2e_content_update_test.py` | `e2e_cognitive_recall_test.py:147`, `e2e_extraction_pipeline_test.py:216` |
| `=== Stage N: … ===` | `e2e_episodic_memory_test.py` | `:239` |
| `--- {scenario docstring} ---` | `e2e_plan15_scenarios_test.py`, `e2e_plan17_validation.py` | `e2e_plan15_scenarios_test.py:951`, `e2e_plan17_validation.py:959` |
| `PHASE X: …` (plain line, sometimes inside a `"=" * 70` rule) | `e2e_plan15_scenarios_test.py`, `e2e_plan17_validation.py` | `e2e_plan15_scenarios_test.py:852-855` |

The `=== Stage` case is not optional: that child hosts the formatter defect this plan most wants
attributed, so a parser matching only `=== Step` blinds the one failure that matters most.

**The fourth row is a correction to the stage text, found by inventory and confirmed in the tree.**
`e2e_plan15_scenarios_test.py` and `e2e_plan17_validation.py` print **both** a coarse `PHASE A:`-style
banner and a fine `--- docstring ---` banner, so "the last banner printed" is ambiguous for exactly the
two children whose failures Plan 33 most needs attributed. Resolve it by precedence, not by recency:
**prefer the last `--- docstring ---` line when the run printed any; otherwise fall back to the last
`=== Step`/`=== Stage`/`PHASE` line.** The scenario docstring localizes the failure to one scenario,
which is the diagnostic the rubric needs; the phase banner only says which third of the run it died in.
Record the matched convention alongside the value as `failure_step_kind` so a reader can tell a precise
attribution from a coarse one. A `"=" * 70` rule line is never itself a banner.

`exception_class` is the class name on the final traceback line of stderr (the `NameError: ...` form →
`NameError`). **Never the message text** — it can contain graph or episode content.

In `scripts/model_bakeoff.sh`, pass `--stdout-path "$stdout_path" --stderr-path "$stderr_path"` at the
single `write-exit-result` call site (lines 357-364). Leave the `write-missing-result` branch alone.

## Step 6 — parametrize the parsing report

Add `--run-id` and `--arm` to the **`generate` subparser only**. Defaults keep the current module
constants (`"20260911T001509Z-swift3"`, `"qwen-flash-next-compact"`) so every existing invocation is
unchanged. Do not make the subcommand optional; do not move the flags to the top level — the other three
subcommands do not take them.

When a skip-events file and a sample file for that run id exist in the output directory, the per-episode
skip and graph fields read from them instead of emitting `REASON_AUDIT` / `REASON_GRAPH`. When they do
not exist, the existing `NOT MEASURED` reasons stay exactly as they are today.

**Resume correction (2026-09-13):** nondefault runs need a new tuned report schema because
the frozen historical schema requires effort `false`. Emit exact four-agent `efforts`
maps from measured metadata in run and episode provenance, validate with the new schema,
and use arm/run-suffixed output filenames. Existing tuned graph sample is an input,
never overwritten by a placeholder. Keep default generation byte-identical. Validate
source artifact identities and measurement status before deriving any measured value;
unavailable episode attribution remains explicitly NOT MEASURED.

For temporal annotation, permit atomic annotation of this run's skip file when input
and output share a directory, as the Stage 7 command specifies; do not reject that
documented command. Never certify survival from an unrelated schema sharing numeric
node ids. If existing safe metadata cannot identify the graph, retain `survived: null`
and record the unresolved attribution instead of guessing.

---

## Gates — run these exact commands, save raw output to these paths

| # | Command | Evidence | What turns it red |
|---|---|---|---|
| G1 | `uv run pytest tests/unit/test_export_skip_events.py tests/unit/test_export_graph_sample.py tests/unit/test_qwen_parsing_report.py tests/unit/test_e2e_manifest.py tests/test_qwen_extractor.py -q` | `validation/stage2-unit-1.txt` | any failure |
| G2 | `uv run python scripts/generate_qwen_parsing_report.py generate --plan-dir docs/plans/33-local-qwen-migration --output-dir docs/plans/33-local-qwen-migration/resources --run-id 20260911T001509Z-swift3 --arm qwen-flash-next-compact` then `git diff --exit-code -- docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.json` | `validation/stage2-byteidentity-1.txt` (both commands' output) | a non-empty diff on the historical report |
| G3 | `uv run pytest tests/ -q` | `validation/stage2-suite-1.txt` | fewer than 1,288 passed, or any failure |
| G4 | `uv run ruff check .` | `validation/stage2-ruff-1.txt` | anything but `All checks passed!` |

G1's test files must contain, at minimum, these cases — each one exists to make a specific wrong
implementation fail:

1. A fixture log with 3 `missing_node` and 2 `temporal_pair` events at the target run id yields exactly
   those 5 rows, and events at a *different* run id are excluded.
2. A fixture event carrying a `name` field is **refused** (the exporter raises; nothing is written).
3. A fixture log where every candidate carries `run_id == "unavailable"` yields
   `status: "NOT MEASURED"`, not an empty measured file.
4. A fake connection with 25 nodes and 30 edges yields a deterministic 20/20, and the same fake yields
   the identical ids on a second call.
5. A fake with 7 edges yields a shortfall row with `count: 7`, not 20 and not padding.
6. `type_valid` is `false` for a type name the normalization regex rejects but the weaker
   `extraction/schemas.py` check would accept.
7. `--check-temporal` marks `survived: true` for an edge present in the reverse direction.
8. A canned extraction over the cap yields `relations_dropped_by_cap == 1` from
   `count_capped_relations`, and the emitted log event carries the integer and **no entity name**.
9. One stdout fixture per banner convention (`=== Step`, `=== Stage`, `--- docstring ---`, `PHASE X:`)
   yields a non-null `failure_step` — a parser matching only one convention must fail this.
9b. A fixture containing **both** a late `PHASE B:` line and an earlier `--- scenario docstring ---`
   line resolves to the docstring, with `failure_step_kind == "scenario"`. A naive "last banner wins"
   parser must fail this case.
9c. A `"=" * 70` rule line is never returned as `failure_step`.
10. `exception_class` is extracted without the message text.

---

## Report back

- Every changed path; each gate with exit code, runtime, evidence path.
- Which metrics-JSON key carries the schema list for `export_graph_sample.py` (or that none does).
- Confirmation, with the command output, that G2's diff was empty — or the exact failure.
- Any place where the stage text and the code disagreed, and which you followed.
- Everything you could not measure.

Do not commit. Do not edit `goal.md`, `state.json`, `journal.md`, `backlog.md`, `decisions.md`,
`PROTOCOL.md`, or any `validation/stage*-review.md`. Do not modify anything under
`docs/plans/33-local-qwen-migration/resources/`.
