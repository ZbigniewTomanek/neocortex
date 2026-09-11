---
stage: 6
implementer: codex/gpt-5.6-sol, effort high
reviewer: codex/gpt-5.6-sol, effort high
tier: strong
tier-reason: evidence reconciliation spans live-run provenance, integrity, retry behavior, and quality boundaries
sources: stages/06-qwen-arm.md; briefs/postmortem-qwen-swift.md; validation/stage6-review.md; commit 219e56e
collected: 2026-09-11
status: FROZEN
---

# Stage 6 brief: reconcile the completed compact Qwen arm

## Purpose

Finish Stage 6 from the durable evidence produced by the completed `.tmp/qwen-swift` attempt. Do not launch another multi-hour corpus arm unless a named gate cannot be reconstructed from the committed run-3 artifacts. The completed run used `20260911T001509Z-swift3` at source revision `653cbd62c962dbb8388518873fe47cd44e7fc77d`, and commit `219e56e` records its canonical metrics, recall, and E2E manifest in the plan.

This stage decides only stability/integrity and records quality outcomes. It does not issue migration verdicts; Stage 7 does that. A fast, terminal, integrity-clean corpus run can pass Stage 6 even when its measured E2E quality is inadequate, provided the inadequate result remains explicit and forces `HOLD` downstream.

## Scope

The implementer may create only:

- `validation/stage6-repair-evidence.md`
- additional `validation/stage6-*-attempt<n>.txt` files produced directly by the named checks if needed

Do not edit product code, committed run artifacts, stage files, `goal.md`, `state.json`, `journal.md`, `backlog.md`, or any review file. Report any inconsistency instead of repairing it. Do not read or copy credentials, private logs, prompts, episode text, hidden reasoning, raw model output, or dynamic schema names.

## Evidence inputs

- `resources/metrics-qwen-flash-next-compact.json`
- `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json`
- `resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json`
- the snapshot path and digest named by those artifacts, checked only for existence/digest without extracting private graph content
- `.tmp/qwen-swift/validation/stage4-run3-summary.json`, `stage4-run3-compare.md`, and `stage4-review.md` as prior-run corroboration
- original findings F1–F6 in `validation/stage6-review.md`
- current source at or after commit `219e56e`

## Required reconstruction

Write `validation/stage6-repair-evidence.md` as a compact, privacy-safe table with: criterion; direct source path and JSON selector or command; observed value; `PASS`, `REPORT`, or `NOT MEASURED`; and the defect that would make it red.

Reconstruct and cross-check:

1. Run/model/corpus identity: run id, exact four model ids, source revision, compact profile, eight selected episode ids, endpoint identity without credentials, effort values, concurrency, timeout, and source-worktree-clean caveat.
2. Completion: `todo=doing=failed=cancelled=0`, `succeeded=total=30`, all submitted compact episodes consolidated, and failure/stall rate `0/30`.
3. Integrity: all named schemas have zero stored artifact markers, leaked reasoning markers, invalid type names/references, garbage types, unproven librarian failures, agent-run failures, and tool-validation rejections. Separately read the run-3 counters `edge_skipped_missing_node=16` and `edge_skipped_temporal_pair=5`: explain every missing-endpoint skip from current safe evidence, and prove the required `CORRECTS`/`SUPERSEDES` edges survived all five skipped ordinary conflicts. If either population cannot be fully attributed without private/raw evidence, mark integrity `NOT MEASURED`; do not treat a nonzero skip as zero. Any absent required signal is `NOT MEASURED`, not zero.
4. Isolation/retry provenance: no cached-plan/search-path failure, collision-free opaque extraction correlations, no unexplained failed mutation attempt, and snapshot digest consistency.
5. Restore: use the prior review and terminal bakeoff behavior only if their evidence is sufficient; otherwise mark restore `NOT MEASURED`.
6. Recall: record the final measured status and M1–M4 values with denominators; do not reinterpret them as a migration pass.
7. E2E: record all five child exit statuses and Plan 15/17 score counts. Preserve the final `0/5` result, the numeric-fact failures, formatted-context failure, and infrastructure flakes. Do not infer a pass from an earlier attempt.
8. Timing/usage: record wall time, requests by agent, reasoning tokens, and the comparison with the 7.7-hour reference as REPORT values only.
9. Original F1–F6: identify which later commit/evidence resolves each old Stage 6 finding and which finding becomes a Stage 7 `HOLD` input rather than a Stage 6 repair.

## Resume ledger

This stage resumes after a legacy post-review and one incomplete repair. Preserve `review.used=true`, `repair.rounds=1`, and `repair.used=true`; never run another full Stage 6 post-review and never reuse repair round 1. After reconstruction, the orchestrator appends triage for original F1–F6 to `validation/stage6-review.md`. The only review still available is `repairReview.used=false`: review only the accumulated repair commits/evidence against F1–F6. A second repair round is permitted only if that changed-lines re-review finds a blocking defect, and no review follows round 2.

## Gates and commands

Run these against the real committed artifacts:

1. `uv run python scripts/e2e_manifest.py validate --manifest-path docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json --run-id 20260911T001509Z-swift3`
2. `uv run pytest tests/ -q`
3. `uv run pytest tests/test_oneshot_librarian.py tests/unit/test_qwen_speed_probe.py tests/unit/test_compact_corpus.py tests/unit/test_e2e_manifest.py tests/unit/test_extraction_correlation.py -q`
4. `uv run ruff check src scripts tests`
5. `git diff --check`

The orchestrator already measured gate 2 after the owner's `.env` correction: 1251 passed and 7 skipped in 38.70 seconds. The implementer reruns it so the stage evidence is independently reproducible.

## Acceptance

- Completion, integrity, provenance, snapshot, restore, manifest validation, current tests, and static checks are `PASS` on direct inputs.
- Recall and all five E2Es are measured and truthfully recorded. Their quality values do not need to pass Stage 6, but any missing value is `NOT MEASURED` and must be carried to Stage 7.
- No unsupported claim says the compact arm proves full-profile endurance, hosted equivalence, fully offline operation, or migration fitness.
- No current product change is required. If any gate is red, stop and report the exact artifact/selector rather than modifying evidence.

## Non-goals

- Do not generate the per-episode parsing report, quality sample, verdicts, or technical report; those are Stages 7 and 9.
- Do not tune effort or cut over defaults.
- Do not change thresholds, tests, corpus membership, or committed run output.
- Do not start services or make live model/database writes unless the orchestrator issues a separate brief after a proven evidence gap.
