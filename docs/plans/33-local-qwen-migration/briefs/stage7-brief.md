---
stage: 7
implementer: codex/gpt-5.6-sol, effort high
reviewer: codex/gpt-5.6-sol, effort high
tier: strong
tier-reason: produces schema-validated evidence and per-agent decisions from incomplete, privacy-sensitive provenance
sources: stages/07-quality-gate.md; Stage 6 blocked record; run 20260911T001509Z-swift3; qwen-parsing-report-compact.schema.json
collected: 2026-09-11
status: FROZEN
---

# Stage 7 brief: quality decision and evidence reports

## Decision boundary

Issue `HOLD` for ontology, extractor, librarian, and domain classifier. No agent may receive `MIGRATE` because Stage 6 integrity is `NOT MEASURED`, the fixed 20-node/20-edge sample cannot be reconstructed from a privacy-safe graph export, and the final E2E result is 0/5. Do not infer agent-specific fitness from 30/30 terminal stability, zero failure counters, speed, an earlier passing child, or the absence of a hosted baseline.

The report must distinguish:

- operational result: 30/30 jobs succeeded in 2,397 seconds with 68 requests and zero reasoning tokens;
- measured quality: recall M1–M4 exists, but the five required E2Es all fail in the final arm;
- integrity gap: 16 missing-endpoint skips and five temporal conflicts lack per-event attribution;
- scope: compact revision 1 only; not 28-episode endurance, hosted equivalence, or fully offline NeoCortex.

## Files owned by the implementer

- `scripts/generate_qwen_parsing_report.py`
- `tests/unit/test_qwen_parsing_report.py`
- `resources/qwen-parsing-inputs.json`
- `resources/qwen-parsing-report.json`
- `resources/qwen-parsing-report.md`
- `resources/qwen-parsing-report-compact.schema.json`
- `resources/quality-sample-qwen-flash-next.json`
- `resources/quality-sample-qwen-flash-next.schema.json`
- `resources/bakeoff-comparison.md`
- `decisions.md` (append one D-entry for the four `HOLD` verdicts)
- `validation/stage7-*.txt|json` produced by the named checks

Do not edit `goal.md`, `state.json`, `journal.md`, `backlog.md`, briefs, stage files, or review files. Do not read or copy credentials, authorization headers, private logs, prompts, episode text, hidden reasoning, raw model output, dynamic domain values, dynamic schema names, email addresses, or sensitive audit records.

## Generator contract

Create a deterministic CLI that reads only the fixed compact corpus metadata, canonical metrics, final E2E manifest, final recall artifact, and their file metadata. The JSON schema is the field authority. The generator must:

1. Refuse a run id other than `20260911T001509Z-swift3` or artifact run/digest/profile/episode-set mismatches.
2. Create the input manifest first with relative paths, SHA-256, and availability for corpus, metrics, snapshot, admin jobs, graph export, audit log, E2E manifest, and recall. Record unavailable sources as `NOT MEASURED` with reasons. Never extract the snapshot or copy audit/admin content.
3. Emit exactly `E02,E04,E05,E10,E18,E20,E26,E27`, once each and in that order. Map only values supported by safe committed aggregates; every absent per-episode value is `NOT MEASURED` with a reason and source reference.
4. Extend the compact schema with a required per-episode evidence array. Each record carries a JSON Pointer to the report field, `status`, the exact safe `value`, a relative `source`, and a non-empty `reason` when status is `NOT_MEASURED`. The validator must require evidence coverage for every measured or `NOT MEASURED` leaf in jobs, domains, ontology, extraction, librarian actions, events, and quality/integrity; it must verify that the evidence value equals the pointed-to report value. Additional fields remain forbidden.
5. Use only schema-approved safe value forms. Never invent an opaque id, hash, type, relation, action, domain, job outcome, count, or source link.
6. Validate the schema with `Draft202012Validator.check_schema`, validate the report instance, validate exact episode membership/order, validate evidence coverage/equality and every source link/digest, and run privacy/safe-value scans before writing `checks.domain_privacy=PASS`.
7. Render Markdown from the validated JSON, preserving the template field order and all `NOT MEASURED` reasons.
8. Be idempotent: a second run on unchanged inputs produces byte-identical JSON/Markdown/manifest outputs. Use no current timestamp or date field.

The CLI is frozen as:

- `generate --plan-dir PATH --output-dir PATH`
- `validate --plan-dir PATH --input-manifest PATH --report PATH --sample PATH`
- `self-check --plan-dir PATH --output PATH`
- `privacy-scan --input-manifest PATH --report PATH --markdown PATH --sample PATH --comparison PATH --output PATH`

`generate` writes the manifest, JSON report, Markdown report, and sample to `output-dir`. `validate` emits only a compact status/count JSON object. `self-check` generates twice in tool-created temporary directories, compares all four files byte-for-byte, validates both sets, removes those directories, and writes only status/counts to `--output`. `privacy-scan` writes only pattern names and match counts; it never prints matches.

Tests must cover happy-path generation, exact eight-key membership, missing required source, digest mismatch, run mismatch, missing evidence metadata, evidence/value mismatch, missing `NOT MEASURED` reason, forbidden text/domain/schema values, invented safe-value kinds, absent per-episode evidence becoming `NOT MEASURED`, and byte-identical reruns.

## Fixed sample

`resources/quality-sample-qwen-flash-next.json` must be a truthful control artifact, not fabricated padding. Because no privacy-safe graph export with source episode/job ids is committed, record:

- `status: NOT_MEASURED`;
- required counts 20 nodes and 20 edges, observed safe counts unavailable;
- the named snapshot relative path and verified SHA-256;
- the exact missing input (`graph_export`) and why the snapshot was not extracted;
- the consequence: absolute quality rubric fails closed and all agents remain `HOLD`.

Do not emit empty arrays that look like a completed sample and do not inspect private snapshot contents.

Create `resources/quality-sample-qwen-flash-next.schema.json`. It has a tagged union: `MEASURED` requires exactly 20 nodes and 20 edges, source episode/job ids, safe values, declared types, valid references, and a validator result; `NOT_MEASURED` forbids node/edge arrays and requires the expected counts, unavailable observed counts, snapshot path/digest, missing input, reason, and `HOLD` consequence. The validator recomputes the snapshot digest and rejects a measured sample without exact 20/20 records. Tests cover corrupt digest, arrays under `NOT_MEASURED`, fabricated measured status, and wrong measured counts.

## Comparison and verdicts

`resources/bakeoff-comparison.md` must include one row per reasoning agent with verdict `HOLD`, direct evidence paths, integrity disposition, E2E/quality disposition, hosted baseline `NOT MEASURED`, and the next action. It must include all metrics and caveats required by Stage 7 and B16. Append one decisions entry that records why stability/speed does not authorize migration.

The next action must be concrete: add privacy-safe per-event endpoint reason/correlation evidence, add temporal-survival assertions, retain scalar numeric facts and formatted recall context, make E2E waits readiness/model aware, rerun the same compact arm, then repeat Stage 7. Do not change current model defaults.

## Gates

1. Generator and unit tests, saved as `validation/stage7-focused-tests.txt`: `uv run pytest tests/unit/test_qwen_parsing_report.py tests/unit/test_compact_corpus.py tests/unit/test_e2e_manifest.py -q`.
2. Determinism, saved as `validation/stage7-self-check.json`: `uv run python scripts/generate_qwen_parsing_report.py self-check --plan-dir docs/plans/33-local-qwen-migration --output docs/plans/33-local-qwen-migration/validation/stage7-self-check.json`.
3. Committed generation: `uv run python scripts/generate_qwen_parsing_report.py generate --plan-dir docs/plans/33-local-qwen-migration --output-dir docs/plans/33-local-qwen-migration/resources`.
4. Schema/report/sample validation, saved as `validation/stage7-validation.json`: `uv run python scripts/generate_qwen_parsing_report.py validate --plan-dir docs/plans/33-local-qwen-migration --input-manifest docs/plans/33-local-qwen-migration/resources/qwen-parsing-inputs.json --report docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.json --sample docs/plans/33-local-qwen-migration/resources/quality-sample-qwen-flash-next.json > docs/plans/33-local-qwen-migration/validation/stage7-validation.json`.
5. Count-only privacy scan, saved as `validation/stage7-privacy.json`: `uv run python scripts/generate_qwen_parsing_report.py privacy-scan --input-manifest docs/plans/33-local-qwen-migration/resources/qwen-parsing-inputs.json --report docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.json --markdown docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.md --sample docs/plans/33-local-qwen-migration/resources/quality-sample-qwen-flash-next.json --comparison docs/plans/33-local-qwen-migration/resources/bakeoff-comparison.md --output docs/plans/33-local-qwen-migration/validation/stage7-privacy.json`.
6. Full regression, saved as `validation/stage7-full-tests.txt`: `uv run pytest tests/ -q`.
7. Static checks, saved separately as `validation/stage7-ruff.txt`, `validation/stage7-format.txt`, and `validation/stage7-diff-check.txt`: `uv run ruff check src scripts tests`; `uv run ruff format --check scripts/generate_qwen_parsing_report.py tests/unit/test_qwen_parsing_report.py`; `git diff --check`.

Save concise raw check outputs under `validation/stage7-*.txt`. A gate is red if a required value is invented, a missing source is called measured, any forbidden content is persisted, the exact episode set differs, schema validation fails, outputs are nondeterministic, any verdict is not `HOLD`, or any command fails.

## Non-goals

- No snapshot extraction, live model/database call, hosted baseline, tuning, or cutover.
- No attempt to repair Stage 6 within Stage 7.
- No `MIGRATE` or `BLOCKED` verdict: the endpoint works, but present integrity and quality evidence cannot authorize use as the default.
- Do not update current defaults or `.env.example`; Stage 9 owns final operational documentation.
