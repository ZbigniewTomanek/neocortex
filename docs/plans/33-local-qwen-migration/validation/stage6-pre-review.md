# Stage 6 pre-review — complete finding set

Reviewer: `codex/gpt-5.6-sol`, effort `high`
Verdict: needs revision — two P1 and one P2 blocking findings; six candidates refuted.

## Findings

### F1 — P1 BLOCKING — resume ledger is underspecified

The brief did not define how reconciliation attaches to the spent Stage 6 ledger: `review.used=true`, `repair.rounds=1`, `repair.used=true`, and `repairReview.used=false`. The original six findings also lack protocol-required triage. A normal stage loop could incorrectly run a second full post-review or reuse fix round 1. This blocks the Review gate and permanent-ledger invariant.

### F2 — P1 BLOCKING — nonzero edge-skip signals omitted

The integrity reconstruction omitted `edge_skipped_missing_node=16` and `edge_skipped_temporal_pair=5`. It could therefore declare integrity PASS without accounting for unresolved endpoints or proving that `CORRECTS`/`SUPERSEDES` edges survived the skipped ordinary conflicts. This blocks the integrity gate and endpoint/temporal-edge invariants.

### F3 — P2 BLOCKING — focused test path does not exist

The brief named `tests/test_qwen_speed_probe.py`; the file is `tests/unit/test_qwen_speed_probe.py`. The written command exits 4 and runs zero tests. This blocks the focused regression gate.

## Gate dispositions

- Run/model/corpus identity: PASS, preserving `source_worktree_clean=false` as a caveat.
- Completion: PASS, 30/30 terminal and succeeded with all eight inputs covered.
- Integrity: NOT MEASURED until F2 is resolved.
- Isolation/retry provenance: PASS.
- Snapshot digest: PASS.
- Restore: PASS on the prior review's trap and exit-code evidence.
- Recall measurement: PASS as measurement, not quality acceptance.
- E2E measurement: PASS as measurement; observed quality is 0/5.
- Timing/usage: PASS as REPORT evidence.
- F1–F6 reconciliation: NOT MEASURED until durable triage and remaining re-review exist.
- Manifest validation: PASS.
- Full regression suite: PASS, 1251 passed and 7 skipped.
- Focused regressions: NOT MEASURED as written; corrected command passed 83 tests during review.
- Ruff and diff check: PASS.
- Hosted baseline, Stage 7 reports/sample, and migration verdict: DEFERRED to their declared stages. The observed 0/5 E2E result already prohibits `MIGRATE` unless later current evidence changes it.

## Refuted candidates

- Stale manifest metrics digest: refuted; the current manifest digest validates.
- Dirty source flag makes provenance irrecoverable: refuted; retain it as a caveat.
- Restore must be NOT MEASURED: refuted by the prior review's accepted trap/exit-code evidence.
- Stage 6 can treat 0/5 E2E as quality success: refuted by the brief's explicit Stage 7 boundary.
- Eight-episode consolidation is unsupported: refuted by corpus metadata, terminal counts, and audit coverage.
- Invalid type references require another snapshot query: refuted by enforced graph foreign keys; Stage 7 still owns the fixed sample.

## Triage

- F1: FIX in the brief with a resume-ledger section; preserve all spent flags, append triage for original F1–F6 after evidence reconstruction, run only the remaining changed-lines repair re-review, and allow round 2 only if that re-review blocks.
- F2: FIX in the brief; require direct selectors, explanations for all 16 missing-endpoint skips, and proof that temporal edges survived all five skipped ordinary conflicts. Otherwise mark integrity NOT MEASURED.
- F3: FIX the test path to `tests/unit/test_qwen_speed_probe.py`.
