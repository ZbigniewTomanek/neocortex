# Stage 7 post-review — complete finding set

Commit: `27387b0`
Reviewer: `codex/gpt-5.6-sol`, effort `high`
Verdict: approve with fixes — five P1 and two P2 blocking findings; six candidates refuted.

## Findings

### F1 — P1 BLOCKING — invented per-episode values pass validation

Evidence validation accepts any allowed source and does not require the canonical source for a pointer. Changing an ontology count to `999`, marking it measured, and citing the schema still returns PASS. This blocks the no-invented-values gate.

### F2 — P1 BLOCKING — report status does not fail closed

Top-level status can change to `MEASURED` while required per-episode fields remain `NOT_MEASURED`. This blocks the fail-closed report property.

### F3 — P1 BLOCKING — report run provenance is not fully bound

Validation binds only `source_revision`. False corpus and snapshot paths/digests with valid syntax pass. This blocks report provenance.

### F4 — P1 BLOCKING — a fabricated measured sample passes

A self-consistent invented 20-node/20-edge sample passes while the manifest says `graph_export` is unavailable. This blocks the fixed-sample anti-fabrication property.

### F5 — P1 BLOCKING — free-form reasons bypass privacy controls

Forbidden source text in an evidence reason or Markdown can pass validation and the privacy scan. This blocks report privacy.

### F6 — P2 BLOCKING — verdict count does not prove exact agent coverage

Four HOLD rows pass even when one required agent is replaced by a duplicate. This blocks four-agent verdict completeness.

### F7 — P2 BLOCKING — evidence records are not bound to their episode

An evidence record can move to another episode array while global coverage still passes. Markdown then shows evidence under the wrong episode. This blocks per-episode evidence ownership.

## Gate dispositions

- Focused tests: NOT MEASURED because the seven adversarial cases are missing.
- Determinism and committed generation: PASS.
- Schema/report/sample validation: NOT MEASURED because F1–F4 and F7 fail open.
- Privacy scan: NOT MEASURED because F5–F6 fail open.
- Full regression: PASS, 1274 passed and 7 skipped.
- Ruff, format, and diff checks: PASS.
- Current decision: four HOLD verdicts are correct and source digests match, but the control code must reject fabricated alternatives.

## Refuted candidates

- Four current HOLD verdicts are too broad: refuted by Stage 6 integrity, 0/5 E2E, and the absent sample.
- Current NOT MEASURED sample weakens the threshold: refuted because it contains no record arrays and forces HOLD.
- Current outputs are nondeterministic: refuted by byte-identical regeneration.
- Current input digests are stale: refuted by recomputation.
- Missing legacy control rows break the report: refuted because the manifest table preserves the links.
- Reading canonical metrics violates audit privacy: refuted; metrics are authorized and copied output remains safe.

## Triage

- F1: FIX by comparing submitted output with a freshly generated canonical expected report and by enforcing canonical pointer sources.
- F2: FIX by deriving report status from required leaf and source availability.
- F3: FIX by comparing the complete report run object with canonical values.
- F4: FIX by rejecting `MEASURED` unless a digest-verified graph export is available and each sample record matches it.
- F5: FIX by restricting reasons to approved constants and extending all-format label scans.
- F6: FIX by parsing the verdict table and requiring the exact four-agent set once each with HOLD.
- F7: FIX by validating evidence coverage and pointer prefixes separately for each episode.
