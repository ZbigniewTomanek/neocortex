# Stage 6 single independent review — complete finding set

Confirmed findings from the read-only Stage 6 review:

1. **BLOCKING — manifest-to-metrics provenance digest is stale.**
   The standalone and embedded E2E manifest claim metrics digest `de65002f…`, while the persisted canonical metrics file hashes to `a47c2914…`. The snapshot digest is consistent (`c187d105…`). The published-manifest validator passes because it does not verify the referenced metrics file. This blocks exact artifact provenance.

2. **BLOCKING — E18 classifier failure silently suppresses shared routing.**
   `stage6-classifier-diagnosis.json` records two validation rejections followed by `UnexpectedModelBehavior`; the routing job is reported successful with zero routed domains and no shared extraction job. Queue success therefore does not establish classifier correctness. The rejected field remains `NOT_MEASURED`.

3. **BLOCKING — E20/E26 extractor failures are hidden by retries.**
   Canonical metrics contain three `agent_run_failed` events: E18 classifier plus E20 and E26 extractors. The E20/E26 jobs eventually succeed on attempt 2, so the terminal-job gate remains green, but Stage 7’s integrity floor still blocks the implicated extractor agents on observed structured-output failures.

4. **BLOCKING — 24 unexplained tool-validation rejections.**
   Canonical metrics record 24 `tool_validation_rejected` events: 20 librarian, 2 ontology, and 2 classifier. No stored leaks or invalid types result, but the rejection causes are not fully measured; Stage 6 explicitly requires unexplained rejections to fail integrity.

5. **BLOCKING — per-episode Qwen parsing report is absent.**
   No compact JSON/Markdown parsing report or input manifest exists. Only the schema and template are present, so the report gate is `NOT_MEASURED`.

6. **BLOCKING — quality cannot be decided.**
   Recall is explicitly `NOT_MEASURED` after scorer exit 1. The E2E manifest records 0/5 passed: three `FAIL` by exit status and two `NOT_MEASURED` because scenario scores were missing. No 20-node/20-edge snapshot sample exists. The absolute rubric therefore remains `HOLD`.

Gate dispositions:

- Exact local model identity/auth preflight: **PASS** for `/models`; direct chat/PydanticAI preflight field is `NOT_MEASURED`, though the arm recorded model requests.
- Regression suite: **PASS** — 1100 passed, 7 skipped.
- Compact terminal-job completion: **PASS** — 31/31 jobs terminal and succeeded; 8/8 episodes consolidated; failure rate 0/31.
- Integrity scan: **BLOCKING**.
- Per-episode report: **NOT_MEASURED**.
- Snapshot digest: **PASS**; snapshot path and SHA-256 agree across metrics, manifest, and archive.
- Overall provenance: **BLOCKING** because the persisted manifest metrics digest is stale.
- Recall: **NOT_MEASURED**.
- Five E2Es: **NOT_MEASURED** overall; their safe exit-status evidence is sufficient to prevent a quality pass, though discarded stdout/stderr prevents root-cause diagnosis.
- Absolute quality rubric: **NOT_MEASURED / HOLD**.
- Hosted baseline: **DEFERRED** under existing backlog item 6.
- Runtime benefit and cutover recommendation: **DEFERRED**.

Refuted candidate defects: terminal counts are corroborated by the terminal watcher and sanitized capture; corpus IDs/hash, run ID, and source revision agree; correlation IDs are collision-free across episodes; graph capture shows zero artifact markers, invalid types, invalid references, and stored leaks; post-snapshot restoration is evidenced by `corpus_replaced: true`. No additional non-blocking findings were confirmed.

## Triage

- F1: FIXED by canonical run-3 artifacts at `219e56e`; current metrics and manifest digests match and manifest validation exits 0.
- F2: FIXED for the replacement arm by `ad85426` plus run-3 evidence: eight classifier runs completed with zero agent failures or validation rejections. The unreproduced historical rejected field remains `NOT MEASURED` and is not claimed fixed by reproduction.
- F3: FIXED for the replacement arm: run 3 has zero agent failures/rejections, 30/30 terminal successes, and complete 22-path audit coverage. Historical failures remain recorded.
- F4: FIXED for the replacement arm: run 3 records zero tool-validation rejections.
- F5: DEFERRED to the plan's declared Stage 7 deliverable. It does not block the Stage 6 stability measurement, but it continues to block Stage 7 and Stage 9 until the eight-row report validates.
- F6: MEASURED by run 3, not fixed as quality. Recall is measured and all five final E2E children fail; this is mandatory Stage 7 `HOLD` input and can never support `MIGRATE`.

The accumulated repair evidence is `validation/stage6-repair-evidence.md`. It additionally finds Stage 6 integrity `NOT MEASURED`: all 16 missing-endpoint skips lack individual safe attribution and none of the five run-3 temporal-pair skips has per-event proof that the required temporal edge survived. The remaining repair re-review must judge that evidence without reopening the full review or repair round 1.

## Re-review

Reviewer: `codex/gpt-5.6-sol`, effort `high`. Scope: accumulated repair commits and `validation/stage6-repair-evidence.md` only. Verdict: **BLOCK** with one P1 blocking finding.

### F7 — P1 BLOCKING — integrity remains NOT MEASURED

The repair correctly records 16 `edge_skipped_missing_node` events and five `edge_skipped_temporal_pair` events, but cannot individually attribute the former or prove required `CORRECTS`/`SUPERSEDES` survival for the latter. Marking Stage 6 complete could certify a graph with a missing required endpoint or temporal correction edge. This blocks the Stage 6 integrity gate and endpoint/temporal-edge invariants. Supply privacy-safe attribution for all 16/16 skips and run-3 survival evidence for all 5/5 temporal conflicts, or leave Stage 6 blocked.

All original F1–F6 dispositions, direct selectors, and other gates were independently verified. Run/model/corpus identity, 30/30 terminal completion, stored leak/type/failure scans, isolation/retry provenance, opaque correlations, digests, snapshot, restore, recall measurement, E2E measurement, timing, manifest validation, 1251-pass full suite, 83-pass focused suite, Ruff, and diff check are PASS. The parsing report and verdict remain Stage 7 deliverables. The final 0/5 E2E result requires `HOLD`, not `MIGRATE`.

### Re-review triage

- F7: ACCEPT as blocking. The repair budget is spent and current privacy-safe artifacts do not contain the required per-event attribution. Stage 6 is `BLOCKED`; Stage 7 remains independently reachable through Stage 6b and must publish `HOLD` with this gap.
