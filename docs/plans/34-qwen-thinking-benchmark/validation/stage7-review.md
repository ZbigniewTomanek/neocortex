# Stage7 post-review — b0d6195

Reviewer: codex/gpt-5.6-sol, effort high. Single post-review.
Verdict: SIGNIFICANT CONCERNS — one P0, three P1, all BLOCKING. Four candidates refuted.

## F1 — Supervisor signals can interrupt mandatory snapshot restore

- Axis: data integrity/correctness. Location: validation/stage7_arm_supervisor.py:107.
- Claim: forward_signal forwards every subsequent TERM/INT, including after deadline cleanup starts. The deadline itself targets the whole group without knowing whether the bake-off already entered restoration.
- Failing input: deadlineTERM begins EXIT restore; a later user/sessionTERM is forwarded and interrupts snapshot load, potentially leaving the local database wiped or partially restored. Harmless committed-supervisor reproduction produced RESTORE_START, RESTORE_INTERRUPTED, childexit77.
- Refutation: exists at107–111/132–136; reachable via deadline or external signals; no one-shot latch/restore isolation; prohibited by the frozen no-kill-recovery rule.
- Fix: one-shot termination, bake-off-owned targeted active-workload shutdown, ignore further signals after cleanup begins, restoration outside signalled workload group.
- Severity P0, confidence high, BLOCKING mandatory recovery/data-integrity property.

## F2 — Expected quality failures abort instead of producing HOLD evidence

- Axis correctness. Location scripts/model_bakeoff.sh:383.
- Claim: poll_jobs treats failed+cancelled rate>0.10 as fatal although stability is REPORT-only underD-7. run poll_jobs exits before snapshot/metrics/exporters/recall/manifest/report.
- Failing input: terminal summary todo0/doing0/succeeded8/failed1/cancelled1/total10 yields20%failure; harness returns2 with no evidence continuation. Committed test at test_model_bakeoff.py:821 asserts this behavior.
- Refutation: exists and reachable from real terminal summary; no later finalizer; D-7 explicitly permits failed quality as a report input.
- Fix: terminal summaries continue regardless of rate, exact summary persists in metrics, Stage8 judges rate. Also continue when a producer wrote a valid NOT_MEASURED artifact successfully.
- Severity P1, confidence high, BLOCKING D-7 REPORT-not-GATE and artifact-existence gate.

## F3 — Timeout restores without preserving required partial evidence

- Axis correctness/edge cases. Location scripts/model_bakeoff.sh:566.
- Claim: deadline handler records one event, waits only activeE2E, then exits to restore. It does not persist last summary or explicit NOT_MEASURED metrics/recall/child outcomes/manifest/report.
- Failing input: jobs active at6600s while in poll_jobs. Latest summary exists only in transient stdout; Stage7 artifacts remain absent, preventing timeout-as-HOLD consumption.
- Refutation: existing fake timeout proves cleanup only, no deadline finalization path. Frozen brief requires last summary and partial artifacts.
- Fix: deadline-aware finalization stops new work, persists last summary and truthful NOT_MEASURED evidence for unrun portions, then restores.
- Severity P1, confidence high, BLOCKING deadline partial-persistence and artifact-existence gate.

## F4 — Provenance failure does not prevent child reset

- Axis correctness/data integrity. Location scripts/model_bakeoff.sh:419.
- Claim: function is called in if at750, suppressing set-e inside it. Failed planned provenance continues to background child/start--fresh.
- Failing input: provenance I/O failure after corpus, for example full filesystem, still starts child reset without durable planned event. Shell-only reproduction confirms failed command in condition-called function continues to external write.
- Refutation: cited caller/function pair exists; I/O failure reachable; fake-child assertion detects omission after launch only; brief mandates durability before launch.
- Fix: explicit checked provenance return before creating/launching child.
- Severity P1, confidence high, BLOCKING write-ahead provenance property.

## Gate dispositions

- PASS: focused34; full1498/7; Ruff; shellsyntax/dryrun; scopedhooks; documentation/STE.
- PASS: graphcapture before reset; metricmerge before digest; reportaftermanifest/recall; historicalcollision refusal; credentials/private diagnostics; run_e2e singlecleanup143; normal single-signal timeout124 versusrestorefailure3.
- FAIL: mandatoryrestore under signalsF1; REPORTcontinuationF2; deadlinepartialpersistenceF3; durableprovenanceF4.
- PASS hostedidentity: no hosted model implementation changed.
- DEFERRED by protocol: livearm/artifactexistence and all live stability/integrity/skip/sample/E2E/recall/cost/wall reports.

## Dropped candidates

- commands.md:102 lacks TestModel launch — REFUTEDgate4: frozen brief explicitly uses dry-run service harness after earlier TestModel modelpaths.
- model_bakeoff:695 graph sampled after childreset — REFUTEDgate3: exports precede firstchild.
- run_e2e:103 TERM doublecleanup — REFUTEDgate3: TERM/INTexit only, soleEXITcleanup, committedtest sees one stop.
- model_bakeoff:15 legacy600 default violates limit — REFUTEDgate3: frozen Stage7 command explicitly exports300, prior-arm behavior retained.

## Triage

- F1 ACCEPT/BLOCKING. Coordinator inspected unconditional group forwarding and deadline groupTERM, plus handler restores without isolation. Treat priority as P1 (requires signal/deadline timing), not unconditional P0. Fix both repeated-signal and first-deadline-during-natural-restore cases, including external-signal-before-deadline then automatic deadline. Recovery must survive all three.
- F2 ACCEPT/BLOCKING for tuned arm. Coordinator read terminal rate check and condition-called tests. Keep legacy arms unchanged; tuned terminal high-failure rate must produce exact measured REPORT evidence, not abort. A producer's nonzero exit is not permission to invent success; continue only with valid explicit unavailable evidence or truthful finalization.
- F3 ACCEPT/BLOCKING. Coordinator read handler: only event/wait/exit, no last-summary/partial-artifact persistence. Add deadline finalization with explicit unavailable fields, no new model/service work, and restore. Do not fabricate measured rows to meet artifact counts.
- F4 ACCEPT/BLOCKING. Coordinator inspected if caller and unchecked provenance call before background child. Explicit checked return must prevent child launch, with injected actual I/O-failure test.

All four assigned together in the single fix round. No re-review. Deterministic same-finding verification only.

## Single-fix verification and acceptance

- Coordinator inspected the complete four-path implementation/test diff and generated fake partial JSON. F1: control-only one-shot signals, recovery marker and ignored recovery signals protect restoration. Owned daemon receipts verify process group, PID files and start times before targeted shutdown. Fake persistent request markers stop before finalization and restoration. Unproven shutdown skips unsafe finalization and attempts recovery.
- F2: terminal20%failure stays measuredFAIL. Only a newly written, strictly validated current-run unavailable producer artifact permits continued benchmark work. Stale or malformed markers and unclassified infrastructure failures stop later E2E launches. Original producer exit codes remain in provenance.
- F3: last validated summary persists, unknown rates stay null, missing artifacts use distinct unavailable forms, unlaunched children lack invented exit codes, and no fake sample rows appear. Local writer failure72 remains nonzero; finalizer failure71 still attempts restoration. Poll errors stop workers before finalization.
- F4: failed planned child provenance returns73 before launch, with zero children and one recovery attempt. No reliance on errexit inside condition-called functions.
- Same-F1 fixture race corrected by READY-after-child-spawn synchronization. The2s wait,143exit and exactlyonecleanup assertions remain unchanged. Ten repeated isolated passes; earlier failing attempts retained.
- Final coordinator focused48/101.60s and full1512passed/7skipped/116.92s PASS (attempt3), fullRuffPASS, scopedhooksPASS(attempt2), shellsyntax/exact300/domaintrue/all4false/compact/orderPASS. Fake proof: validation/stage7-fix1-evidence-attempt2. No live measurements claimed.
- All four BLOCKING findings accepted as fixed. One repair consumed, no re-review. Live arm remains the next gate.
