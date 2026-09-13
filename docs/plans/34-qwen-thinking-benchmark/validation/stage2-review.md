# Stage 2 post-review — commit 8932147

Reviewer: codex/gpt-5.6-sol, effort high. Complete set received 2026-09-13.
Verdict: APPROVE WITH FIXES — one confirmed P2, three candidates, two refuted.

## Findings

### F1 — P2 correctness — BLOCKING — scripts/e2e_manifest.py:288

`parse_failure_step` gives every `--- … ---` line absolute precedence over later
Stage/Step banners. The episodic-memory child uses these lines as section headings,
so a later failure is attributed to a stale earlier section.

Failing input: `e2e_episodic_memory_test.py:348` prints
`--- Cross-Session Isolation Check ---`, then :386 prints
`=== Stage 3: STM Boost Validation ===`. If Stage 3 raises, the fallback records
the earlier heading with kind scenario. This blocks Stage 2's diagnosable-failure
deliverable. Fix precedence with child context: scenario-over-phase precedence
belongs to Plan15/17; other children select the last matching banner. Add the
episodic earlier-heading/later-stage fixture. Confidence high.

## Gate dispositions

- G1 PASS: stage2-unit-gatefix1-attempt1.txt, 138 passed.
- G2 PASS: stage2-byteidentity-coordinator-attempt1.txt, empty historical diff.
- G3 PASS: stage2-suite-coordinator-attempt2.txt, 1,404 passed / 7 skipped.
- G4 PASS: stage2-ruff-coordinator-attempt1.txt, clean.
- Hooks PASS: stage2-stage5-precommit-gatefix1-attempt2.txt, all scoped hooks pass.
- Hosted identity PASS: only Qwen cap-accounting branch changed; no hosted prompt/profile change.
- Live PostgreSQL exporters DEFERRED to Stage7. Live model behavior DEFERRED by design.

## Dropped candidates

- compute_metrics.py:583, no skip artifact arm comparison: REFUTED at reachability.
  Sanctioned workflow binds unique producing run_id; other-run inputs become unknown
  and tuned report independently validates arm. False comparison needs deliberate
  run identity reuse across arms, outside the contract.
- export_graph_sample.py:157, raw invalid type could carry text: REFUTED at sanctioned
  behavior. Stage2 explicitly asks for raw type plus type_valid, including invalid-type
  fixtures. A representation change would be a plan/privacy-contract choice.

## Notable

- Multi-schema temporal survival remains unresolved rather than matching unrelated ids.
- Malformed/unmeasured/mismatched skip evidence never becomes a zero-count pass.
- Cap-drop logs contain counts only.

## Triage

- F1 ACCEPT/FIX: coordinator reproduced exact stale heading result with the two printed
  lines and verified both literals in the child. Incorrect failure attribution blocks
  the declared diagnostic deliverable. One fix round, no re-review under protocol.
- Both dropped candidates accepted as refuted against the stated workflow/contract.

## Fix round 1 disposition

- F1 FIXED: write_exit_result now supplies child identity. The actual episodic
  sequence reports `=== Stage 3: STM Boost Validation ===`, kind `stage`;
  Plan15/17 scenario-over-phase tests remain green. Coordinator reproduced the
  corrected return value and inspected both changed files.
- Focused 84 passed; full suite 1,413 passed / 7 skipped; scoped hooks passed.
  Evidence: stage2-fix1-focused-attempt1.txt, stage2-fix1-suite-attempt1.txt,
  stage2-fix1-hooks-attempt1.txt. One fix consumed; no re-review.
