# Stage5 post-review — 3c52202

Reviewer: codex/gpt-5.6-sol/high, single independent read-only review.
Verdict: two BLOCKING evidence-correctness findings.

## F1 — Final wall-limited timeout leaves budget_exhausted false

- P2 BLOCKING, correctness/missing evidence, high confidence.
- Location scripts/effort_level_probe.py:423-446,469-472.
- Input: final request, per-call300, remaining wall5, request takes longer than5.
  _run_one times out at5, row becomes TIMEOUT, loop finishes naturally, final
  budget_exhausted remainsfalse because only a later iteration sets it.
- Refutation: reachable on request12; _refresh_payload never derives this flag.
  Blocks truthful wall-budget evidence. Fix wall-limited timeout/finalization flag
  and add delayed-final-request regression.

## F2 — Invalid observations are OK and can yield exit0

- P1 BLOCKING, false PASS/correctness, high confidence.
- Location scripts/effort_level_probe.py:454-466,474-486.
- Input: valid ExtractionResult containing <think> in a property/description,
  reasoning_tokens0, positive output_tokens. Markertrue still gives statusOK;
  all such rows yield live exit0. Zero-output rows have the same false-success path.
- Refutation: _usable_row excludes them from analysis, but row status and exit
  do not use it; structured validation permits marker strings. Blocks marker and
  output validity gates. Use non-OK code-owned status/reason for invalid output,
  marker or nonpositive output, and enforce full live criteria. Keep synthetic
  missing-reasoning allowance only for TestModel; add exit regressions.

## Gate dispositions

- Focused19 PASS; exact mock12 PASS for current valid artifact, own effort
  none/low/medium/high, positive output, no markers/timeouts, reasoningnull.
- Boundary positive control, one-request/no-retry, both timeout classes PASS.
- Alias/nontransitive reduction/cancellation and missing usage handling PASS.
- Privacy PASS: counts, booleans, fixed reasons and exception classes only.
- Wall-limit validation PASS statically; exhaustion evidence blocked by F1.
- Invalid status/exit semantics blocked by F2.
- Full1446/7 and Ruff PASS. Live identity DEFERRED until review/fix.

## Candidates refuted

- Missing off usage stays null by design, never inferred zero.
- Off stays distinct by explicit rule; missing data cannot trigger cancellation.
- Preallocated row count does not falsely pass pending rows: NOT MEASURED fails
  the live status gate.
- Boundary once per level suffices for immutable configuration and identical repeats.

Reviewer made no file/service/commit/live changes.

## Triage

- F1 ACCEPT/FIX: coordinator traced final iteration to finalization; neither
  path sets exhaustion when the final shortened request uses the remaining wall.
- F2 ACCEPT/FIX: coordinator read success row.update and live statuses==OK
  return; present counts alone yieldOK despite markertrue or output0. _usable_row
  is used only in analysis. Enforce declared full live gates, not exit0 on bad rows.
- One fix round authorized; no re-review. Live remains unlaunched.

## Fix1 verified

- F1 FIXED: final wall-limited timeout sets exhaustion; finalization also checks
  actual elapsed. Deterministic final5s timeout persists true/finalizedtrue.
- F2 FIXED: invalid structure, marker, output0 and off reasoningnonzero give
  code-owned ERROR reasons and exit1. Tests exercise both live and TestModel policies
  without HTTP. Full live exit checks validity, boundary and off reasoning0.
- Coordinator read complete fix diff and ran focused30/0.32s, full1462 passed/
  7 skipped/41.10s, whole-tree Ruff PASS. Fresh mock12 valid,0.045s, nullreasoning,
  no markers/timeouts, exact effort boundaries and cancellationnull.
- Evidence: stage5-fix1-*-coordinator-attempt1 files including actual JSON.
  Single repair consumed; no re-review. No live identity call yet.
