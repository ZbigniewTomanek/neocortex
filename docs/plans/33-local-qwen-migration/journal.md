# Journal

Append-only. Newest entries are at the bottom. Historical entries below preserve evidence from the
former remote-Qwen attempt; they do not set active `state.json` status for Flash Next.

## 2026-08-19 -- Historical Stage 1: remote provider routing -- evidence retained
**Did**: Implemented and committed per-agent `local:` OpenAI-compatible routing, sampling controls,
timeouts, classifier/seed wiring, and unit tests. Commit `3e3c85f`; the tested model was remote
`qwen3.8-27b`, not the current target.
**Verification**: Historical full suite reported 911 passed, 11 skipped. No current Flash Next gate.
**Provenance**: Test output from that commit; endpoint identity came from the remote `/v1/models` response.
**Problems**: None recorded for that historical run.

## 2026-08-19 -- Historical Stage 2: remote capability probes -- evidence retained
**Did**: Probed all four real agent surfaces across low/medium/high/xhigh with bounded timeouts and
the fixed three-episode corpus. Raw JSON remains in `resources/probe-results-*.json`.
**Verification**: Historical remote results showed structured output and tools could work, but timeouts
were frequent; ontology, extractor, and librarian were marked NEEDS HARDENING, classifier READY WITH
TIMEOUT CAVEAT. The probe used `InMemoryRepository`, so it was not PostgreSQL evidence.
**Provenance**: Values came from the raw result files and the remote endpoint described by historical
`resources/probes.md`; they are not Flash Next measurements.
**Problems**: Tool-call refusal was prompt-shaped; the real extraction schema was expensive and medium
did not finish inside the old 150-second cap.

## 2026-08-19 -- Historical Stage 3: prompt hardening -- evidence retained
**Did**: Added source-text framing, terminal contracts, dynamic-context ordering, duplicate-text
removal, and additive artifact rejection. Commit `71dcbbd`.
**Verification**: Historical suite reported 916 passed, 11 skipped. Hosted E2E and isolated open-dict
experiment were not measured. This does not establish Flash Next quality.
**Provenance**: Test output and committed diff from the historical run; no live Flash Next input.
**Problems**: Two E501 lines and raw-normalization ordering were fixed in that run.

## 2026-08-19 -- Historical Stage 4: harness -- evidence retained
**Did**: Added corpus loader, metrics emitter, recall scorer, audit timing/usage/rejection events, and
arm orchestrator. Commit `eb05376`.
**Verification**: Dry-run/parser checks passed. Live DB/API reproduction, embedding preflight, and
bounded completion polling were not measured.
**Provenance**: Unit/dry-run artefacts from the historical commit; no complete live arm.
**Problems**: AsyncMock usage warning was fixed. Keep the harness fixable before final evidence.

## 2026-08-19 -- Historical Stage 5: hosted baseline -- incomplete evidence
**Did**: One GPT-5.4-mini corpus run completed 102/102 jobs with zero failures and was snapshotted;
the second run left two jobs in `doing` for more than 30 minutes. Commit `89e7f95`.
**Verification**: Run-two variance, E2E scores, and baseline-derived thresholds are `NOT MEASURED`.
The old baseline must not block the current local run.
**Provenance**: `resources/metrics-baseline-gpt54mini.json` records run-one output only; no run-two
artifact exists. Any baseline comparison in this plan is advisory until two complete same-prompt runs.
**Problems**: Admin/test-token and listener lifecycle mismatches also prevented a truthful E2E gate.

## 2026-09-03 -- Planning audit: Flash Next compatibility hypotheses -- IN PROGRESS
**Did**: Retargeted active execution to `http://127.0.0.1:24000/v1`, model `qwen3.8-flash-next`, and
environment-only `VLLM_API_KEY`. Supervisor audit reached basic structured output and domain
classification, but ontology and extractor requests received HTTP 400 because multiple system messages
were emitted before the user message. The probe harness may import stale `load_probe_corpus` after the
loader exposes `load_corpus`.
**Verification**: These are diagnostic observations to reproduce in Stage 1/2, not quality gates yet.
**Provenance**: Current local endpoint response and current source inspection; the key value was never
read into this record.
**Problems**: Stage 3 owns system-message coalescing or a local-only adapter; Stage 4 owns probe-import
compatibility and auth/timeout instrumentation.

## 2026-09-03 -- Pre-review correction -- execution paths and quality rubric -- RECORDED
**Did**: Corrected `state.json` so 6b depends on Stages 3 and 4 and follows Stage 6 by ordering, while
Stage 7 depends on 6b. Stage 6b and Stage 8 are control stages that finish `DONE` with explicit
no-op/`NOT MEASURED` outcomes. Stage 9 therefore remains reachable when the local arm is blocked or
when no agent passes.
**Verification**: State dependencies use only `DONE` unlock semantics. `state.json` does not propagate
`BLOCKED`; the ordered 6b diagnosis runs after a Stage 6 attempt even if Stage 6 is blocked.
**Provenance**: Dependency values are read from this plan's `state.json`; an accidental dependency on
6 for 6b or 6 for 7 would make the intended recovery path unreachable.
**Problems**: Previous control flow could deadlock diagnosis behind a blocked local arm; corrected in
the stage briefs and state file.

## 2026-09-03 -- Pre-review correction -- absolute quality rubric -- RECORDED
**Did**: Added a deterministic no-baseline rubric: extraction smoke, episodic-memory, and cognitive-
recall checks exit 0; Plan 15 score is at least 11/14; Plan 17 score is at least 13/14; integrity
metrics pass; and exactly 20 real nodes plus 20 real edges from the named local snapshot pass mechanical
schema, reference, marker, and fixed-corpus source checks.
**Verification**: Any missing input or `NOT MEASURED` quality value forces `HOLD`; a subjective visual
comparison cannot produce `MIGRATE`. Stage 7 records all source paths in the comparison artefact.
**Provenance**: Scores come from script output lines, integrity values from `compute_metrics.py`, and
sample rows from the local snapshot. Fabricated rows or copied target values are forbidden.
**Problems**: The prior plan allowed a subjective same-artifact judgement when the hosted baseline was
missing; the rubric now makes that path deterministic.

## 2026-09-03 -- Pre-review correction -- repository authentication -- RECORDED
**Did**: Verified the repository root contains `dev_tokens.json` and that it maps `admin-token` to
`admin`. Updated the local arm commands to export `NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json` and
`NEOCORTEX_ADMIN_TOKEN=admin-token`; the test token file and obsolete fallback are excluded.
**Verification**: No `VLLM_API_KEY` value was read or recorded. The exact key name remains an
environment-only input for the local model endpoint.
**Provenance**: Token path/name read from `dev_tokens.json` and `scripts/manage.sh`; a wrong file or
fallback token would cause admin/seed checks to return 401 or use the wrong agent identity.
**Problems**: Existing bake-off defaults were ambiguous about test versus real dev tokens; the plan now
names the verified repository map explicitly.
