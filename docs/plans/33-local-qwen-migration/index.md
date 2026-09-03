# Plan: Local Qwen Flash Next Migration

**Date**: 2026-09-03<br>
**Branch**: `plan/33-local-qwen-migration`<br>
**Predecessors**: [Plan 21 — generic model provider](../21-generic-model-provider/index.md), [Plan 28 — ontology alignment](../28-ontology-alignment/index.md), [Plan 29 — ontology validation](../29-ontology-validation/index.md). Historical Plan 33 evidence is retained in `journal.md`, `decisions.md`, and `resources/`.<br>
**Goal**: Determine whether the locally authenticated Qwen Flash Next service can drive NeoCortex's reasoning agents, make it stable when it can, and leave a truthful cutover or technical report when it cannot.

Executed per [PROTOCOL.md](PROTOCOL.md). Status of record: [state.json](state.json).<br>
Runtime record: [journal.md](journal.md) · [decisions.md](decisions.md) · [backlog.md](backlog.md)

## Context

The active target is the local OpenAI-compatible endpoint `http://127.0.0.1:24000/v1`, with model id
`qwen3.8-flash-next`. The endpoint requires `Authorization: Bearer $VLLM_API_KEY`; the key is already
available in the execution environment and must never be printed, copied to a plan file, or committed.
The `local:` model prefix and provider-routing implementation already exist, but prior capability and
bake-off evidence targeted remote `qwen3.8-27b` and is not evidence for Flash Next.

Four reasoning surfaces are in scope: ontology, extraction, librarian, and domain classification (the
seed generator follows classification). Embeddings (`gemini-embedding-001`) and media description
(`gemini-3-flash-preview`) remain cloud services; this plan therefore does not claim a fully offline
NeoCortex deployment. Long indexing time is acceptable. Quality and operational correctness matter more
than latency, which is recorded but never blocks a decision.

The supervisor's initial audit found that basic structured output and domain classification reach the
local service, while ontology and extractor calls can receive HTTP 400 because PydanticAI emits multiple
system messages and this deployment requires one system message at the beginning. The probe script also
needs a compatibility fix if it imports the old `load_probe_corpus` name after the corpus loader change.
These are hypotheses to verify and repair, not migration conclusions.

Historical raw probe JSON and earlier baseline output remain under `resources/`; their remote endpoint,
model id, and incomplete run status are explicitly historical and cannot satisfy current Flash Next gates.

## Strategy

Phase A (Stages 1–3) validates authenticated model identity, probes every real agent, and iteratively
repairs prompt/API compatibility. Each fix is delegated by the supervisor to a dedicated GPT-5.6-Luna
xhigh subagent where available, with a fresh provenance audit after the fix.

Phase B (Stages 4–6b) makes instrumentation and authentication reliable, optionally measures a hosted
comparison when it is useful, and runs the full local corpus. Baseline comparison is advisory: it may not
deadlock the local stability run. Isolation and root-cause work is required for failures that cannot be
attributed from joint output.

Phase C (Stages 7–9) records the quality decision, tunes effort only for agents that pass, and either
cuts over those agents with rollback or publishes an ASD-STE100 technical report explaining why quality
was inadequate and what root cause/design change is required.

Execution ordering is deliberate. Stage 6b depends on Stages 3 and 4, not Stage 6, and appears after
Stage 6 in `state.json`; therefore the runner attempts the local arm first, then runs diagnosis even
when Stage 6 is `BLOCKED`. Stage 7 depends on 6b, so it cannot run before the diagnosis/no-op outcome.
Stage 6b and Stage 8 always finish `DONE` with an explicit outcome or no-op note. This keeps the
no-agent-pass path reachable to Stage 9, which publishes the technical report.

## Success Criteria

GATE blocks the owning stage. REPORT is measured, recorded in `journal.md`, and never blocks. A GATE
measurement must come from this run's inputs; never use a literal, default, midpoint, copied output, or
generated padding. `NOT MEASURED` is not `PASS`: it blocks a GATE and is published without blocking only
for a REPORT. Every measured GATE names its input and the defect that would turn it red.

| Metric | Baseline | Target | Kind | If missed | If unmeasurable |
|--------|----------|--------|------|-----------|-----------------|
| Every GATE value is derived from a measurement of this run's own inputs | n/a | no literal/default/midpoint/generated row | GATE | block stage | REPORT `NOT MEASURED` and block |
| Authenticated model preflight | endpoint response | `/v1/models` contains exactly `qwen3.8-flash-next`; authenticated chat and PydanticAI calls succeed | GATE | block Stage 1 and diagnose auth/compatibility | REPORT `NOT MEASURED` and block |
| Unit and harness regression suite | current repository tests | all relevant tests pass; no assertion is weakened or deleted | GATE | block owning stage | n/a |
| Full local corpus completion | not yet measured | every submitted episode reaches a terminal job state within the configured timeout; failure/stall rate ≤10% from `/admin/jobs/summary` | GATE | block local stability and diagnose root cause | REPORT `NOT MEASURED` and block |
| Critical integrity defects | not yet measured | zero stored artifact types, leaked reasoning markers, invalid type names, or unhandled auth/structured-output failures in the measured run | GATE | block affected agent and diagnose | REPORT `NOT MEASURED` and block |
| Absolute quality rubric when baseline is unavailable | not yet measured | `MIGRATE` only when all five real quality inputs are measured and pass: extraction smoke exits 0; episodic-memory and cognitive-recall checks exit 0; Plan 15 score is ≥11/14; Plan 17 score is ≥13/14; and a fixed 20-node/20-edge sample from the named local snapshot passes the mechanical schema/reference checks in Stage 7. Any `NOT MEASURED` quality input means `HOLD`. | REPORT | publish `HOLD` and continue to report | publish `NOT MEASURED`; never `MIGRATE` |
| Quality versus hosted baseline | prior baseline incomplete | per-agent quality verdict supported by current local evidence; baseline is used only when two complete same-prompt runs exist | REPORT | publish and continue | publish `NOT MEASURED`, continue local decision |
| Reasoning/tool compatibility | historical remote probes only | real-agent probes record output validity, tool order, retries, and rejection causes for every agent and selected effort | REPORT | publish and continue | publish `NOT MEASURED`, open backlog |
| Effort/quality and cost | not measured for Flash Next | selected effort per migrated agent, with token and p50/p95 duration distributions; latency is informational | REPORT | publish and continue | publish `NOT MEASURED`, open backlog |
| Cutover or technical report | no current verdict | either validated per-agent local defaults plus rollback, or an ASD-STE100 report with evidence, root cause, and next action | REPORT | publish unresolved decision and backlog | publish `NOT MEASURED`, open backlog |

## Files That May Be Changed

- `docs/plans/33-local-qwen-migration/` — canonical plan structure, stage briefs, evidence, journal, and decisions.
- `src/neocortex/`, `scripts/`, and `tests/` — only when a stage identifies a provider, prompt, instrumentation, or compatibility defect.
- `.env.example` and targeted configuration documentation — placeholders and local setup only; never secrets.

## Stages

Routing table only. Status, notes, and commits live in `state.json` and nowhere else.

| # | Stage |
|---|-------|
| 1 | [Authenticated local preflight and routing](stages/01-local-provider-routing.md) |
| 2 | [Real-agent Flash Next probes](stages/02-capability-probes.md) |
| 3 | [Iterative prompt and compatibility hardening](stages/03-prompt-hardening.md) |
| 4 | [Harness, instrumentation, and auth stability](stages/04-measurement-harness.md) |
| 5 | [Optional hosted baseline comparison](stages/05-baseline-arm.md) |
| 6 | [Full local stability and quality run](stages/06-qwen-arm.md) |
| 6b | [Isolation and root-cause diagnosis](stages/06b-isolation-arms.md) |
| 7 | [Quality decision and evidence report](stages/07-quality-gate.md) |
| 8 | [Thinking-effort tuning](stages/08-thinking-effort-tuning.md) |
| 9 | [Conditional cutover or ASD-STE100 report](stages/09-cutover-and-docs.md) |
