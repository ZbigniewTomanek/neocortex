# Local Qwen Flash Next migration, run contract

Authority: `docs/plans/33-local-qwen-migration/index.md`
Goal ID: `none`
Started: 2026-09-11
Protocol: [PROTOCOL.md](PROTOCOL.md) · Status: [state.json](state.json) · Record: [journal.md](journal.md) · [backlog.md](backlog.md)

## Contract

Determine whether NeoCortex can use the authenticated local `qwen3.8-flash-next` service for each reasoning surface from now on. Finish the compact-corpus measurement, preserve truthful integrity and quality evidence, and either cut over each proven agent with rollback or publish an ASD-STE100 `HOLD` report with concrete causes and next actions. The run may change only the plan directory, `src/neocortex/`, `scripts/`, `tests/`, `.env.example`, and targeted configuration documentation. Embeddings and media description remain cloud-bound and are not migration claims.

## Stages and gates

1. `Authenticated local preflight and routing` — accepted at `4ab4284`; exact authenticated model identity and provider routing were measured.
2. `Real-agent Flash Next probes` — accepted at `edc33eb`; all four real reasoning surfaces reached the selected service and incompatibilities were recorded.
3. `Iterative prompt and compatibility hardening` — accepted at `1df6c2a`; local-only compatibility repairs passed focused and hosted-path regressions.
4. `Harness, instrumentation, and auth stability` — accepted through `dc5fd15` and `a2ac217`; audit privacy, run provenance, and fail-closed metrics were verified.
5. `Optional hosted baseline comparison` — accepted no-op at `5e7d075`; no valid two-run baseline exists and local absolute quality remains authoritative.
6. `Compact local stability and quality run` — the final compact run must have an authenticated exact model, all jobs terminal with failure/stall rate at most 10%, zero critical integrity defects, a restored development schema, measured recall/E2E outcomes, and current regression tests. Performance is reported, not a quality pass.
6b. `Isolation and root-cause diagnosis` — accepted at `b6b0950`; opaque correlations, retry attribution, and fail-closed graph-mutation evidence are required by Stage 6.
7. `Quality decision and evidence report` — all four agents receive `MIGRATE`, `HOLD`, or `BLOCKED`; the eight-row parsing report, manifest, privacy scans, fixed snapshot sample or explicit `NOT MEASURED`, and comparison report must validate against current evidence.
8. `Thinking-effort tuning` — tune only agents with a Stage 7 `MIGRATE`; otherwise record a measured `DONE` no-op. Any selected effort requires raw records and a fresh combined compact arm.
9. `Conditional cutover or ASD-STE100 report` — validated agents receive defaults and rollback, or every unsuitable agent receives an evidence-backed technical report. The final suite, mock boot, configuration checks, report privacy, and local smoke must pass or be explicitly blocked.

## Evidence index

- `briefs/postmortem-qwen-swift.md`: safe reconstruction of the completed `.tmp/qwen-swift` attempt and its failure modes.
- `briefs/stage6-brief.md`: frozen Stage 6 resume contract and evidence mapping.
- `resources/metrics-qwen-flash-next-compact.json`: canonical final compact-run metrics at commit `219e56e`.
- `resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json`: final five-child E2E outcomes and provenance.
- `resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json`: final compact recall measurement.
- `validation/stage6-review.md`: original Stage 6 findings and durable triage/re-review lineage.
- `validation/stage<n>-*.txt|json|md`: raw or safely summarized gate evidence for resumed stages.

## Allowed actions

The owner replied `proceed` to the announced scope: repository edits and commits, authenticated calls to the local Qwen endpoint, local NeoCortex service start/stop, and isolated PostgreSQL schema creation/drop. No push, deployment, external publication, destructive fresh start, or modification of credentials is authorized.

## Invariants

- No credential, token, or cookie is written beneath this directory.
- `.tmp/qwen-swift` is prior evidence only; durable lineage and final status live in this plan directory.
- A compact eight-episode run does not establish 28-episode endurance or a fully offline deployment.
- A terminal job count or faster runtime does not substitute for quality, integrity, recall, or E2E evidence.
- Explicit dates, deadlines, versions, exponents, precision values, correction direction, and unrelated facts must survive extraction, merge, correction, and recall before a reasoning agent can migrate.
- Qwen compaction may shorten prose but must not silently discard scalar facts or fact-bearing entities.
- Parallel schema-scoped operations must not reuse prepared statements across `search_path` values or write across schemas.
- `SUPERSEDES` and `CORRECTS` edges must survive conflicting ordinary relations; skipped conflicts must be audited.
- Replays and same-name/different-type entities must remain idempotent unless an explicit create requires a new node; unresolved endpoints must be counted.
- E2E children require readiness-derived, model-aware waits; connection resets and fixed-timeout failures remain failures until measured or diagnosed.
- Recall that returns episodes must also return at least one parseable formatted episode block.
- Unreproduced historical defects and absent inputs remain `NOT MEASURED`; no threshold, assertion, or evidence count is weakened after observing a result.
- Do not start lengthy `xhigh` model runs in this execution. Stage 8 is a no-op when Stage 7 has no `MIGRATE` verdict. Any future effort sweep must use a short bounded probe before a larger arm and must stop when the result cannot change the decision.
- Review flags in `state.json` are permanent. Resuming this run never restores a spent one.
