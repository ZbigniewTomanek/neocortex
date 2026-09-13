# Stage 6 review — commit 80f2b98

Reviewer: codex/gpt-5.6-sol, effort high. Single post-review.
Verdict: APPROVE WITH FIX — one confirmed P2, BLOCKING numeric-evidence truthfulness; three candidates refuted.

## F1 — Missing usage is reported as zero after ordinary timeouts

- Axis: correctness.
- Location: scripts/qwen_speed_probe.py:147; validation/effort_sweep_runner.py:361.
- Claim: `_blank_row()` initializes every usage counter, including `reasoning_tokens`, to zero. For ordinary episode/provider timeouts, `run_text()` uses `aggregate_stage_rows()` directly, so a stage that started but never emitted `agent_usage` retains those invented zeros; the sweep runner then treats them as measured values when computing `median_reasoning_tokens`.
- Failing input: the reachable timeout exercised by tests/unit/test_qwen_speed_probe.py:275 emits `agent_run_started` and no usage event. Its ontology row has reasoning_tokens == 0; a cell with this single allowed timeout can remain PASS and publish a median containing that fabricated zero instead of null.
- Attempted refutation: COUNT_FIELDS includes reasoning_tokens and blank rows seed all count fields with zero; committed episode/provider-timeout tests establish reachability. `partial_stage_rows()` nulls absent usage only for outer hard-wall cancellation, not normal episode/provider timeouts. The frozen brief requires unavailable numeric quantities to remain null and medians to use actual target-agent rows.
- Proposed fix: generalize stages_with_usage handling so incomplete timeout/error rows without agent_usage receive null usage counters. Retain zero only when established. Extend timeout tests through analyse_raw().
- Severity: P2. Confidence: high.
- Disposition: BLOCKING — Stage6 null-semantics and per-cell token-reporting property.

## Gate dispositions

- PASS: classifier domain-key accuracy/canonicalization/allowlisting/privacy; ontology accepted/rejected proposal instrumentation; hard in-flight deadline/cancellation; request/episode/cell/global launch budgets; remaining-cell and aggregate partial persistence; model identity/hosted refusal/configuration pinning; Stage5 cancellation/level interpretation.
- PASS: exact TestModel sweep (16 evidence cells including distinct off cells, raw paths reopened and declared selection arithmetic); mock classifier agreement from actual sets; mock completeness/provenance/selected-cell cleanliness.
- PASS: focused69; full1485/7; Ruff; scoped hooks; hosted path identity (no hosted product path changed).
- FAIL: numeric unavailable-value reporting, F1.
- DEFERRED by protocol: live sweep completeness/selections/four-hour budget. No live Stage6 run expected before review.

## Dropped candidates

- Runner:676 nonzero child exit with complete raw could be accepted — REFUTED at gate2. Normal probe failures produce non-OK summaries/defects that disqualify cells; no realistic committed flow with complete clean raw plus failing exit established.
- Runner:449 fallbackoff can reference a timed-out/disqualified cell — REFUTED at gate3. Selection explicitly reports NOT MEASURED, never a passing selection.
- Probe:1065 second-text triplet cancellation loses first-text aggregate defect list — REFUTED at gate4. Unit-level observation incomplete, so null summary truthful; observed raw stage rows retained.

## Triage

- F1 ACCEPT/BLOCKING. Coordinator inspected blank-row zero initialization, normal-timeout tests, aggregate call at run_text and runner median collection. Existing partial cancellation normalization does not cover that path. Fix absent usage for incomplete error/timeout rows and prove the propagated median is null. One fix round; no re-review.

## Single-fix verification

- F1 RESOLVED by coordinator deterministic inspection, not re-review. Actual episode/provider timeout regressions assert null counters; observed0/nonzero preserved. Runner bridge with one allowed timeout reports median_reasoning_tokens=null. Null requests_total propagation prevents downstream int(None).
- Coordinator focused74/0.89s; full1498 passed/7 skipped/55.44s; lintPASS; own exact14400s mock16cells/7.316s with raw paths reopened. Implementation hooksPASS. Evidence validation/stage6-fix1-*-coordinator-attempt1; full suite includes paused Stage7 test additions.
