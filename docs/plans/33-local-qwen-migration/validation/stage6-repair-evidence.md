# Stage 6 repair evidence: final compact Qwen arm

Run: `20260911T001509Z-swift3`

Source revision recorded by the run: `653cbd62c962dbb8388518873fe47cd44e7fc77d`

Canonical artifact commit: `219e56eab81185583ae161747cf6a36f20e25aaa`

This reconstruction uses only committed aggregate artifacts and the safe prior-run summaries named in the frozen brief. It does not inspect the snapshot contents, private logs, prompts, source episode text, or raw model output. `REPORT` records a measured result without turning it into a quality or migration pass. `NOT MEASURED` is not a pass.

Artifact aliases used in the selectors below can be set from the repository root with:

```sh
PLAN_DIR=docs/plans/33-local-qwen-migration
M="$PLAN_DIR/resources/metrics-qwen-flash-next-compact.json"
E="$PLAN_DIR/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json"
R="$PLAN_DIR/resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json"
S=.tmp/qwen-swift/validation/stage4-run3-summary.json
C=.tmp/qwen-swift/validation/stage4-run3-compare.md
V=.tmp/qwen-swift/validation/stage4-review.md
P="$PLAN_DIR/briefs/postmortem-qwen-swift.md"
```

## Reconstructed gate evidence

| Criterion | Direct source and selector or command | Observed value | Disposition | Red condition |
|---|---|---|---|---|
| Run and arm identity | `jq '{run_id:.run_metadata.run_id,arm:.run_metadata.arm,phase:.run_metadata.phase}' "$M"` | Run `20260911T001509Z-swift3`; arm `qwen-flash-next-compact`; phase `corpus` | PASS | A missing or inconsistent run, arm, or phase |
| Exact reasoning models | `jq '.run_metadata.model_ids' "$M"` | Ontology, extractor, librarian, and domain classifier are all exactly `local:qwen3.8-flash-next` | PASS | Any missing agent or different model id |
| Endpoint identity and model activity | `jq '{endpoint:.run_metadata.endpoint,started:.audit.audit_event_counts.model_request_started,completed:.audit.audit_event_counts.model_request_completed}' "$M"` | Loopback endpoint `http://127.0.0.1:24000/v1`; 68 requests started and 68 completed. No credential value is present. | PASS | Non-loopback or inconsistent endpoint, or incomplete request accounting |
| Effort, concurrency, timeout | `jq '{efforts:.run_metadata.efforts,worker_concurrency:.run_metadata.worker_concurrency,per_call_timeout_s:.run_metadata.per_call_timeout_s}' "$M"` | All four efforts are the string `false`; concurrency `2`; timeout `600` seconds | PASS | Missing/different values or an unbounded timeout |
| Compact corpus membership | `jq '{profile:.run_metadata.corpus_profile,size:.run_metadata.corpus_size,episode_ids:.run_metadata.corpus_episode_ids}' "$M"` | Profile `compact`; eight selected source ids: `2, 4, 5, 10, 18, 20, 26, 27` | PASS | Profile is not compact, size is not eight, or membership differs |
| Source revision and current lineage | `git merge-base --is-ancestor 219e56e HEAD; git rev-parse HEAD; git diff --quiet 219e56e -- "$M" "$E" "$R"` | All exit 0; current `HEAD` is `219e56eab81185583ae161747cf6a36f20e25aaa`; the three canonical artifacts match that commit | PASS | `219e56e` is not an ancestor, or a canonical artifact differs |
| Source-worktree caveat | `jq '.run_metadata.source_worktree_clean' "$M"` | `false`; the run records revision `653cbd6...` but cannot prove that no uncommitted source delta was present | REPORT | Omitting this caveat or claiming byte-for-byte source reconstruction from the revision alone |
| Terminal completion | `jq '.job_summary' "$M"` | `todo=0`, `doing=0`, `failed=0`, `cancelled=0`, `succeeded=30`, `total=30` | PASS | Any nonterminal/failed/cancelled job or `succeeded != total` |
| Submitted episode consolidation | `jq '{classifier_runs:.agent_totals.domain_classifier.runs,ontology_runs:.agent_totals.ontology.runs,extractor_runs:.agent_totals.extractor.runs,librarian_trajectory:.audit_event_counts.librarian_trajectory}' "$S"`; `jq '{ontology_complete:.audit.audit_event_counts.ontology_agent_complete,extractor_cardinality:.audit.audit_event_counts.extractor_cardinality,curation_complete:.audit.audit_event_counts.curation_complete}' "$M"` | Eight classifier runs cover the eight submitted inputs; 22 routed extraction paths each have ontology completion, extractor cardinality, librarian trajectory, and curation completion. `8 + 22 = 30` successful jobs. | PASS | Fewer than eight classifier runs, unequal 22-path completion counters, or a non-successful job |
| Failure/stall rate | Computed from `.job_summary`: `(.failed + .cancelled + .todo + .doing) / .total` | `0/30 = 0%` | PASS | Above 10%, or any nonterminal job |
| Stored artifact/reasoning markers | `jq '{schema_count:(.schemas|length),schemas_with_leaks:([.schemas[]|select((.stored_leaks|length)>0)]|length),artifact_regex}' "$M"`; scanner implementation `scripts/compute_metrics.py:357-364` | Six schemas scanned; zero schemas have `stored_leaks`. The scanner covers node name/content and includes tool-call and `<think>`-style markers. | PASS | Any stored marker, an absent scan, or fewer than six schema results |
| Invalid names and garbage types | `jq '{bad_types:([.schemas[]|.invalid_type_names|length]|add),bad_node_names:([.schemas[]|.invalid_node_type_names|length]|add),bad_edge_names:([.schemas[]|.invalid_edge_type_names|length]|add),garbage:([.schemas[].garbage_types]|add)}' "$M"` | All four totals are `0` across six schemas | PASS | Any nonzero total or absent field |
| Invalid stored type references | Foreign keys in `migrations/graph/001_base_tables.sql:25,56-58`; Stage 6 pre-review refutation | Nodes reference a node type; edges reference source node, target node, and edge type with enforced foreign keys | PASS | Missing/disabled constraints or evidence of an orphan reference |
| Agent, librarian, and validation failures | `jq '.audit_event_counts \| {agent_run_failed,librarian_failed,tool_validation_rejected}' "$S"` and `jq '.unproven_librarian_failures' "$S"` | `agent_run_failed=0`, `librarian_failed=0`, `tool_validation_rejected=0`, `unproven_librarian_failures=0` | PASS | Any nonzero count; an absent required field is `NOT MEASURED`, not zero |
| Missing-endpoint skips | `jq '.audit_event_counts.edge_skipped_missing_node' "$S"` | `16`; see the separate accounting below | NOT MEASURED | Any skip not individually attributable to a safe reason, or a required endpoint lost |
| Temporal-pair skips and correction-edge survival | `jq '.audit_event_counts.edge_skipped_temporal_pair' "$S"`; `.tmp/qwen-swift/validation/stage3-fix-temporal-chain.json` selectors `.episodes[1].edge_types_after` and `.episodes[2].edge_types_after` | `5` run-3 ordinary conflicts were skipped. The earlier focused chain ends with one `SUPERSEDES` and one `CORRECTS`, but it does not tie each of the five run-3 skips to its surviving required edge. | NOT MEASURED | A skipped ordinary conflict overwrites or accompanies a missing required `CORRECTS`/`SUPERSEDES` edge |
| Overall integrity | The preceding integrity rows | Stored scans and failure counters are clean, but the two nonzero skip populations are not fully attributable from privacy-safe evidence | NOT MEASURED | Any critical defect, or either skip population remains unexplained |
| Cached-plan/search-path failure in the replacement run | `jq '{jobs:.job_summary,agent_run_failed:.audit_event_counts.agent_run_failed,librarian_failed:.audit_event_counts.librarian_failed}' "$S"`; repair commit `6d3bae4` | 30/30 jobs succeeded; explicit safe summary has zero agent and librarian failures after statement caching was disabled | PASS | A cached-plan/search-path error, failed agent, failed librarian, or failed job |
| Opaque extraction correlations | `jq '[.audit.usage[]|select(.agent != "domain_classifier")|.correlation_id] as $c | {observations:($c|length),distinct:($c|unique|length),all_opaque:($c|map(test("^extract-[0-9a-f]{32}$"))|all)}' "$M"` | 57 agent-stage observations refer to 22 distinct extraction correlations; every one is opaque and all 22 pipeline runs have a distinct id | PASS | A malformed identifier or fewer distinct ids than pipeline runs |
| Failed mutation-attempt provenance | `jq '{unproven_librarian_failures,agent_run_failed:.audit_event_counts.agent_run_failed,librarian_failed:.audit_event_counts.librarian_failed}' "$S"` | All three are `0`; no unexplained failed mutation attempt is recorded | PASS | Any failed mutation attempt without rollback/cleanliness proof |
| Metrics/recall provenance digests | `sha256sum "$M" "$R"`; `jq '{metrics:.corpus_metrics.sha256,recall:.recall.sha256}' "$E"` | Metrics `dbaccaeb4cb5e57fad7c3a4ec454c83a6d23dc51ab2c5e2783775df1dc01f5ff` and recall `b80edd9c82628c88f8f1a1eaa0a37009f5a585bc50b37552303cc0c88a872b48` match the manifest exactly | PASS | Any digest mismatch or missing referenced file |
| Snapshot existence and digest | `p=$(jq -r '.input_paths.graph_snapshot' "$M"); actual=$(sha256sum "$p"); actual=${actual%% *}; test -f "$p" && test "$actual" = "$(jq -r '.input_paths.graph_snapshot_sha256' "$M")"`; cross-check `.post_snapshot.sha256` in `E` | File exists; computed, metrics, manifest, and summary digest are all `4e3dc2e6bbbbf461aa8a2a32351a82ccfc965da285304ecd33b94fc4f3bee95b` | PASS | Missing archive or any digest mismatch |
| Development restore | `V`, Gate dispositions and Triage; terminal bakeoff exit behavior described in `P` | Prior independent review accepted restore from the failure-only restore trap, bakeoff exit `1` attributable to E2E children rather than restore exit `3/4`, and direct development-schema observations after earlier runs | PASS | Restore-specific exit `3/4`, missing trap evidence, or an observed unrestored development schema |
| Recall measurement | `jq '{status,query_count,metrics,query_set,top1_id_availability}' "$R"`; identical embedded values in `.recall.result` in `E` | `MEASURED`; M1 max activation `0.6666464868975309` across 6 queries; M2 maximum top-1 count `2` across 6 known top-1 ids; M3 specific-event `1/1`; M4 temporal `3/3`; top-1 ids known `6/6` | REPORT | Missing status/value/denominator, digest mismatch, or unknown top-1 ids |
| E2E aggregate | `jq '{status,e2e:{total:.e2e.total,passed:.e2e.passed,failed:.e2e.failed}}' "$E"` | Manifest `MEASURED`; `0/5` passed and `5/5` failed | REPORT | Missing child/status or any reinterpretation of the final run as a pass |
| Plan 15 scores | `jq '.e2e.children[]|select(.script=="e2e_plan15_scenarios_test.py")|{exit_code,result:{status:.result.status,counts:.result.counts,gate:.result.gate}}' "$E"` | Exit `1`, `FAIL`; 9 PASS, 3 PARTIAL, 2 FAIL, total 14; 12 acceptable; PASS-basis threshold 11 was not met | REPORT | Missing counts, exit/status inconsistency, or threshold weakening |
| Plan 17 scores | `jq '.e2e.children[]|select(.script=="e2e_plan17_validation.py")|{exit_code,result:{status:.result.status,counts:.result.counts,gate:.result.gate}}' "$E"` | Exit `1`, `FAIL`; 12 ACCEPTABLE, 1 PARTIAL, 1 FAIL, total 14; acceptable-basis threshold 13 was not met | REPORT | Missing counts, exit/status inconsistency, or threshold weakening |
| Quality failure classification | `sed -n '25,27p' "$P"` | Numeric facts failed in the deadline contradiction, superseded exponent, and correction-precision cases. Episodic recall returned episodes without a formatted episode block. Infrastructure failures were a PostgreSQL connection reset during migration and a fixed 120-second job wait. | REPORT | Omitting a failure class or promoting an earlier passing attempt over the final run |
| Timing comparison | `jq '.wall_seconds' "$S"`; `C`, wall-time row | `2,397` seconds for the full bakeoff versus approximately `27,700` seconds (7.7 hours) for the reference; performance only | REPORT | Missing wall time, mismatched run, or treating speed as quality evidence |

The manifest records these five final child outcomes; all have exit code `1` and status `FAIL`:

| Child | Safe result |
|---|---|
| `e2e_extraction_pipeline_test.py` | Exit-status-only failure; prior safe diagnosis classifies it as the PostgreSQL connection-reset infrastructure flake |
| `e2e_plan15_scenarios_test.py` | 9 PASS / 3 PARTIAL / 2 FAIL; threshold not met |
| `e2e_plan17_validation.py` | 12 ACCEPTABLE / 1 PARTIAL / 1 FAIL; threshold not met |
| `e2e_episodic_memory_test.py` | Exit-status-only failure; prior safe diagnosis records the missing formatted episode block |
| `e2e_cognitive_recall_test.py` | Exit-status-only failure; prior safe diagnosis records the fixed 120-second job-wait timeout |

## Nonzero edge-skip accounting

The final safe summary explicitly records 16 `edge_skipped_missing_node` events. The safe prior journal explains the event class: relation endpoints named by the extractor but not bound to extracted entities are skipped; commit `653cbd6` added graph-side exact-name/alias resolution and reduced the count from 28 in run 2 to 16 in run 3. The committed metrics retain only the aggregate counter. They contain no privacy-safe per-event endpoint, reason-code, episode, or correlation breakdown. Therefore none of the 16 may be silently treated as zero, and the evidence cannot prove that every one was benign. Individual attribution of all `16/16` is `NOT MEASURED`.

The final safe summary also records five `edge_skipped_temporal_pair` events. The deterministic chain evidence from the accepted repair shows the intended behavior: after the final step, one `SUPERSEDES` and one `CORRECTS` edge survive. That focused evidence proves the mechanism, but it is not run-3 per-event evidence. The committed aggregate and unopened snapshot do not prove that a required temporal edge survived each of the five run-3 ordinary-relation conflicts. Survival attribution for all `5/5` is `NOT MEASURED`.

The brief requires the whole integrity criterion to be `NOT MEASURED` when either population lacks complete attribution. No new corpus run or snapshot-content inspection was authorized by this repair brief.

## Usage and timing report

Direct source: `jq '{agent_totals,stage_timings,wall_seconds}' "$S"` and the reference columns in `C`.

| Agent | Runs | Requests | Output tokens | Reasoning tokens | Stage time, sum / p50 / p95 seconds |
|---|---:|---:|---:|---:|---:|
| Domain classifier | 8 | 8 | 706 | 0 | Not separately summarized |
| Ontology | 22 | 25 | 5,671 | 0 | 245.1 / 8.8 / 24.1 |
| Extractor | 22 | 22 | 23,383 | 0 | 815.5 / 35.4 / 45.0 |
| Librarian | 13 | 13 | 3,193 | 0 | 142.1 / 5.2 / 20.5 |
| **Total** | 65 | 68 | 32,953 | 0 | Full bakeoff wall time 2,397 seconds |

The 7.7-hour reference used 2,030 requests and 630,260 reasoning tokens. These values are `REPORT` only: the compact corpus does not establish full-profile endurance, hosted equivalence, fully offline operation, or migration fitness.

## Original Stage 6 findings F1-F6

| Original finding | Later commit/evidence | Reconciliation |
|---|---|---|
| F1: stale manifest-to-metrics digest | Commit `219e56e`; current `sha256sum` and `E.corpus_metrics.sha256` both equal `dbaccaeb4cb5e57fad7c3a4ec454c83a6d23dc51ab2c5e2783775df1dc01f5ff` | Resolved for the canonical run-3 artifacts |
| F2: E18 classifier failure silently suppressed shared routing | Classifier safeguards in `ad85426`; replacement run-3 summary in `219e56e` has 8 classifier runs/8 requests, 0 agent failures, and 0 validation rejections | Resolved for the replacement arm. The historical rejected field was not reproduced and remains `NOT MEASURED`; it is not claimed fixed by reproduction. |
| F3: E20/E26 extractor failures hidden by retries | Replacement run-3 evidence in `219e56e` has 0 agent failures, 0 validation rejections, 30/30 successful jobs, and complete 22-path audit coverage | Resolved for the replacement arm; no historical failure is erased |
| F4: 24 unexplained tool-validation rejections | Replacement run-3 safe summary in `219e56e` explicitly records `tool_validation_rejected=0` | Resolved for the replacement arm |
| F5: per-episode Qwen parsing report absent | Frozen resumed goal assigns the eight-row parsing report to Stage 7; this Stage 6 brief explicitly makes it a non-goal | Not a Stage 6 repair. It remains a required Stage 7 deliverable. |
| F6: quality could not be decided | Commit `219e56e` supplies measured recall and a measured five-child manifest; recall is M1 `0.666646...`, M2 `2`, M3 `1/1`, M4 `3/3`, while E2E is `0/5` with numeric-fact, formatted-context, and infrastructure failures | Missing measurement is resolved. The observed quality result is a Stage 7 `HOLD` input, not a Stage 6 repair or migration pass. |

No second full Stage 6 post-review is available. This evidence preserves the legacy ledger: `review.used=true`, `repair.rounds=1`, `repair.used=true`, and only the accumulated-repair changed-lines review remains available as `repairReview.used=false`.

## Required command reruns

Commands ran from repository root on 2026-09-11. No raw output file was needed because each command produced only a compact, privacy-safe terminal result.

| Command | Exit | Observed output | Runtime |
|---|---:|---|---:|
| `uv run python scripts/e2e_manifest.py validate --manifest-path docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json --run-id 20260911T001509Z-swift3` | 0 | No stdout/stderr | 0.07 s real |
| `uv run pytest tests/ -q` | 0 | `1251 passed, 7 skipped in 40.21s` | 41.12 s real |
| `uv run pytest tests/test_oneshot_librarian.py tests/unit/test_qwen_speed_probe.py tests/unit/test_compact_corpus.py tests/unit/test_e2e_manifest.py tests/unit/test_extraction_correlation.py -q` | 0 | `83 passed in 2.33s` | 2.89 s real |
| `uv run ruff check src scripts tests` | 0 | `All checks passed!` | 0.03 s real |
| `git diff --check` | 0 | No output | 0.01 s real |

## Unmeasured criteria and boundary

- Individual safe attribution of all 16 missing-endpoint skips: `NOT MEASURED`.
- Run-3 proof that the required temporal edge survived each of all five temporal-pair skips: `NOT MEASURED`.
- Overall integrity under the frozen brief, because both preceding populations are required inputs: `NOT MEASURED`.
- The historical E18 rejected field that triggered original F2: `NOT MEASURED`; the replacement run did not reproduce it.
- Full-profile endurance, hosted equivalence, fully offline operation, migration fitness, the Stage 7 parsing report/fixed sample, and migration verdicts are outside this Stage 6 evidence repair.
