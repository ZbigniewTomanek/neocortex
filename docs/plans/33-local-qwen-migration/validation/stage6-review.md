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
