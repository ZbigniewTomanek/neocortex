# Stage4 post-review — commit 2f199a3

Reviewer: codex/gpt-5.6-sol/high. Single complete review, 2026-09-13.
Verdict: NOT PASS, two blocking scalar-integrity findings. No edits or live calls.

## F1 — Bounded display projection suppresses scalar corrections

- Correctness/edge cases, P1 BLOCKING, high confidence.
- Location: src/neocortex/extraction/oneshot_librarian.py:147-150.
- _merge_content reuses _scalar_properties, which keeps only eight sorted
  properties. Existing a..h plus z_deadline=April15 drops z_deadline; incoming
  z_deadline=May1 then leaves both dates in content while stored properties update.
- Refutation: repository and ExtractedEntity dictionaries have no eight-scalar
  limit. No later repair occurs. The brief bounds rendering, not host correctness.
- Minimal fix: unbounded scalar conflict projection for host merge, bounded
  projection for rendered context only. Add greater-than-eight regression.

## F2 — Value-only replacement corrupts unrelated facts or retains stale values

- Correctness/data integrity, P1 BLOCKING, high confidence.
- Location: src/neocortex/extraction/oneshot_librarian.py:120-135,149-155.
- Input1: content `Retry threshold 15; team size 15.`, properties retry_threshold=15,
  team_size=15, incoming retry_threshold=16/team_size=15. Global replacement changes
  both occurrences to16 while unchanged team_size remains15 in properties.
- Input2: `Retries 15, timeout 15.`, incoming retries16/timeout17. One old value maps
  to two new values, so both replacements are discarded and stale values remain.
- Refutation: supported scalar dictionaries, reachable host-default path. Token
  boundaries cannot distinguish these complete tokens. No fallback restores consistency.
- Minimal fix: property/context-aware conflict handling with a safe repeated-value
  fallback, without globally rewriting unrelated occurrences. Add both regressions.

## Gate dispositions

- S05 red-before-fix PASS.
- Focused118 PASS as executed, scalar correctness blocked by F1/F2.
- Rendered scalar assertion PASS; hosted14 and identity hashes PASS.
- Full1429/7 PASS; ruff PASS.
- Exact mock PASS for eight compact/three triplet coverage and scoring fields.
- Classifier TestModel/provider-denial PASS through focused tests.
- Live off baseline DEFERRED by protocol, not a defect.

## Dropped after refutation

- Empty synthetic extraction explains mock zero facts; no live quality claim.
- Missing verbatim old-value/superseded prompt wording is not a defect without
  observed wrong output; wording/model-behavior speculation is backlog-only.
- Model-authored merge content bypassing host default is intentional in the
  frozen scope; no demonstrated failing case.

## Triage

- F1 ACCEPT/FIX: coordinator's direct input with a..h plus z_deadline returned
  both April15 and May1. Rendering limits must not discard host conflict keys.
- F2 ACCEPT/FIX: coordinator reproduced unchanged team-size corruption to16
  and both old15 values retained in the two-property update. Both violate scalar
  integrity. Fix in the single round, no re-review.
- Dropped candidates remain refuted; no expansion to hosted or model-authored paths.

## Fix round 1 disposition

- F1 FIXED: host conflict projection includes every exact scalar; display bounds
  remain model-facing only. Ninth-property regression removes the old deadline.
- F2 FIXED for demonstrated attributable cases: full property labels/direct
  connectors identify values; unlabeled fallback requires unique textual owner.
  Same-valued unchanged facts, mixed-type owners, generic suffixes and cascading
  updates have deterministic regression coverage. Truly ambiguous old text stays
  intact, with the exact incoming description appended; no attribution is invented.
- Coordinator inspected the complete fix diff and reproduced corrected values.
  Final focused125, full1445/7, lint PASS; fresh mock11/11, embeddings none.
  Evidence: stage4-fix1-focused-coordinator-attempt1.txt,
  stage4-fix1-suite-coordinator-attempt1.txt, stage4-fix1-ruff-coordinator-attempt1.txt,
  stage4-fix1-testmodel-coordinator-attempt1.json; scoped hooks attempt7 pass.
- Single fix consumed. No re-review. Live baseline remains the next measurement.
