# Stage 7 pre-review — complete finding set

Reviewer: `codex/gpt-5.6-sol`, effort `high`
Verdict: needs revision — two P1 and one P2 blocking findings; four candidates refuted.

## Findings

### F1 — P1 BLOCKING — compact schema cannot carry required measurement metadata

The brief requires source references for measured values and reasons/sources for `NOT MEASURED` values, but the compact schema provides no such fields for jobs, domains, ontology/extraction collections, librarian actions, or events; `additionalProperties: false` prevents adding them. This blocks the per-episode report gate.

### F2 — P1 BLOCKING — fixed sample has no executable validator contract

The brief described the intended `NOT MEASURED` sample but assigned no schema, validator API, corrupt-digest/fabrication tests, or exact command. A wrong digest or fabricated 20/20 sample could pass all named commands. This blocks the fixed-sample property.

### F3 — P2 BLOCKING — determinism and privacy gates are not runnable

The output-directory and validate-only interfaces were unspecified, and no exact count-only privacy command or evidence paths existed. This blocks the protocol's exact-gate requirement and report privacy gate.

## Gate dispositions

- Verdict completeness and integrity disposition: DEFERRED; four `HOLD` verdicts and the Stage 6 gap are directionally correct.
- Per-episode report: DEFERRED, blocked by F1.
- Report privacy: DEFERRED, blocked by F3.
- Fixed sample: truthfully NOT MEASURED, but its control artifact is blocked by F2.
- Quality comparison, generator/tests, deterministic rerun, schema validation, full regression, and static checks: DEFERRED pending implementation.

## Refuted candidates

- Four `HOLD` verdicts are overly broad: refuted by D21, B16, Stage 6 integrity, and final 0/5 E2E.
- `NOT MEASURED` weakens the 20/20 threshold: refuted; it fails closed to `HOLD` and is not PASS.
- A new backlog edit is required from the implementer: refuted; B16 already carries the cause and next action, and only the orchestrator edits backlog.
- The implementer must dispatch the provenance reviewer: refuted; the protocol reserves dispatch to the orchestrator.

## Triage

- F1: FIX. Add the compact schema to implementer ownership and add schema-approved per-field evidence records carrying field pointer, status/value, source, and a required reason for every `NOT MEASURED` value; validator enforces complete coverage and equality.
- F2: FIX. Add a dedicated sample schema, generator/validator behavior, corruption/fabrication tests, and exact validation command/evidence path.
- F3: FIX. Freeze the CLI subcommands/signatures and exact generate, validate, self-check, privacy, and evidence-output commands.
