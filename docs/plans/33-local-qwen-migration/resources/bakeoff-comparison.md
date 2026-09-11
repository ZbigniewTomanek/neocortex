# Qwen Flash Next compact quality decision

Decision: `HOLD` for ontology, extractor, librarian, and domain classifier. Keep the current model defaults.

This evidence covers run `20260911T001509Z-swift3`, arm `qwen-flash-next-compact`, compact corpus revision 1, and episodes `E02,E04,E05,E10,E18,E20,E26,E27`. It does not establish 28-episode endurance, hosted equivalence, or a fully offline NeoCortex deployment. Performance is informational only.

## Evidence summary

| Measure | Local compact arm | Hosted baseline | Delta | Direct evidence | Disposition and caveat |
|---|---:|---:|---:|---|---|
| Terminal jobs | 30/30 succeeded | NOT MEASURED | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json` | Operational stability only; it does not prove output quality. |
| Failed, cancelled, or stalled jobs | 0/30 | NOT MEASURED | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json` | Zero terminal failures does not close the integrity gap. |
| Full bake-off wall time | 2,397 seconds | NOT MEASURED | NOT MEASURED | `validation/stage6-repair-evidence.md` | Reported performance only. Compact runtime cannot be compared with a full-profile run. |
| Model requests | 68 | NOT MEASURED | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json` | Aggregate only. |
| Reasoning tokens | 0 | NOT MEASURED | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json` | Aggregate only; this does not establish reasoning quality. |
| Recall M1 maximum activation | 0.6666464868975309 | NOT MEASURED | NOT MEASURED | `resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Measured over six compact queries. |
| Recall M2 maximum top-1 count | 2 | NOT MEASURED | NOT MEASURED | `resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Measured over six compact queries. |
| Recall M3 specific-event pass | 1/1 | NOT MEASURED | NOT MEASURED | `resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Compact denominator is one. |
| Recall M4 temporal pass | 3/3 | NOT MEASURED | NOT MEASURED | `resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Compact denominator is three. |
| Extraction smoke | FAIL | NOT MEASURED | NOT MEASURED | `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Exit status only; no passing quality result. |
| Plan 15 | FAIL: 9 PASS of 14; threshold 11 | NOT MEASURED | NOT MEASURED | `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Three PARTIAL results do not count as PASS. |
| Plan 17 | FAIL: 12 ACCEPTABLE of 14, one FAIL | NOT MEASURED | NOT MEASURED | `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Requires at least 13 ACCEPTABLE and zero FAIL. |
| Episodic memory | FAIL | NOT MEASURED | NOT MEASURED | `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Exit status only; no passing quality result. |
| Cognitive recall | FAIL | NOT MEASURED | NOT MEASURED | `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | Exit status only; no passing quality result. |
| Required E2E set | 0/5 passed | NOT MEASURED | NOT MEASURED | `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | The absolute quality rubric fails. |
| Missing-endpoint skips | 16 | NOT MEASURED | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json` | Aggregate events lack per-event episode, edge, and retry attribution. Integrity is NOT MEASURED. |
| Temporal-pair conflicts | 5 | NOT MEASURED | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json` | Aggregate events do not prove that `SUPERSEDES` and `CORRECTS` survived. Integrity is NOT MEASURED. |
| Fixed graph sample | NOT MEASURED | NOT MEASURED | NOT MEASURED | `resources/quality-sample-qwen-flash-next.json` | No committed privacy-safe graph export supports an actual 20-node/20-edge sample. The snapshot was hash-verified and not extracted. |
| Per-episode parsing | NOT MEASURED | NOT MEASURED | NOT MEASURED | `resources/qwen-parsing-report.json` | Aggregate evidence cannot support per-episode jobs, domains, ontology, extraction, librarian actions, events, or integrity values. |

No valid two-run, same-input hosted baseline exists. All hosted values, noise bands, and deltas are `NOT MEASURED`. The measured recall result does not override the failed E2E set or the missing integrity evidence.

## Per-agent verdicts

| Reasoning agent | Verdict | Integrity disposition | E2E and quality disposition | Hosted baseline | Direct evidence | Next action |
|---|---|---|---|---|---|---|
| Ontology | HOLD | Per-episode proposals, accepted/rejected type counts, and attribution for the 16 endpoint skips and five temporal conflicts are NOT MEASURED. | Final arm passed 0/5 E2Es; the fixed graph sample is NOT MEASURED. | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json`; `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json`; `resources/qwen-parsing-report.json`; `resources/quality-sample-qwen-flash-next.json` | Add privacy-safe per-event reason and correlation evidence, add temporal-survival assertions, preserve scalar numeric facts and formatted recall context, make waits readiness/model aware, rerun the same compact arm, and repeat Stage 7. |
| Extractor | HOLD | Stable entity/relation ids, per-episode counts, and the endpoints behind 16 skips are NOT MEASURED. | Extraction smoke failed; final arm passed 0/5 E2Es; the fixed graph sample is NOT MEASURED. | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json`; `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json`; `resources/qwen-parsing-report.json`; `resources/quality-sample-qwen-flash-next.json` | Add privacy-safe per-event reason and correlation evidence, add temporal-survival assertions, preserve scalar numeric facts and formatted recall context, make waits readiness/model aware, rerun the same compact arm, and repeat Stage 7. |
| Librarian | HOLD | Per-episode actions are NOT MEASURED. Sixteen endpoint skips and five temporal conflicts lack the evidence needed to prove graph mutation integrity. | Plan 15 and Plan 17 failed; final arm passed 0/5 E2Es; the fixed graph sample is NOT MEASURED. | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json`; `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json`; `resources/qwen-parsing-report.json`; `resources/quality-sample-qwen-flash-next.json` | Add privacy-safe per-event reason and correlation evidence, add temporal-survival assertions, preserve scalar numeric facts and formatted recall context, make waits readiness/model aware, rerun the same compact arm, and repeat Stage 7. |
| Domain classifier | HOLD | Per-episode accepted domains and proposals are NOT MEASURED; aggregate completion cannot establish routing correctness. | Final arm passed 0/5 E2Es; the fixed graph sample is NOT MEASURED. | NOT MEASURED | `resources/metrics-qwen-flash-next-compact.json`; `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json`; `resources/qwen-parsing-report.json`; `resources/quality-sample-qwen-flash-next.json` | Add privacy-safe per-event reason and correlation evidence, add temporal-survival assertions, preserve scalar numeric facts and formatted recall context, make waits readiness/model aware, rerun the same compact arm, and repeat Stage 7. |

The endpoint is operational, so `BLOCKED` is not the verdict. The evidence is insufficient and the absolute quality checks fail, so `MIGRATE` is not authorized.
