# Decisions

Append-only. Each entry is kept short; detailed measurements belong in `resources/` and `journal.md`.

### D1: Scope the reasoning surface
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) migrate every cloud service B) migrate four reasoning surfaces only.
**Chosen**: B.
**Rationale**: Embeddings and media description have different model requirements and remain cloud-bound; a full offline migration needs a separate plan.

### D2: Use objective quality gates
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) strict point parity B) absolute integrity floor plus baseline-relative reports.
**Chosen**: B.
**Rationale**: Objective integrity defects block; noisy model comparisons are reported with provenance.

### D3: Latency is informational
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) latency gate B) quality and completion gates only.
**Chosen**: B.
**Rationale**: Indexing is asynchronous and the user accepts long processing time.

### D4: Permit partial cutover
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) all agents move together B) each agent receives its own verdict.
**Chosen**: B.
**Rationale**: Per-agent routing supports a mixed local/hosted result without a global endpoint side effect.

### D5: Harden prompts before comparison
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) tune after local results B) apply shared fixes before any comparison arm.
**Chosen**: B.
**Rationale**: Prompt changes must be a constant across arms; a local failure must not be repaired only after measuring its treatment arm.

### D6: Keep unified model settings
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) provider-specific settings B) shared `ModelSettings.thinking` plus local sampling and timeout.
**Chosen**: B.
**Rationale**: Installed PydanticAI maps string effort levels identically; one settings path reduces compatibility branches.

### D7: Extend artifact defense
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) replace artifact regex B) extend `_TOOL_CALL_ARTIFACT` additively.
**Chosen**: B.
**Rationale**: Existing normalization defense is useful, but rejection counts must expose entities it drops.

### D8: Reuse existing corpus and metrics
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) rebuild all validation assets B) reuse Plan 29 SQL and existing E2E scripts, adding only missing harness glue.
**Chosen**: B.
**Rationale**: It preserves comparability and reduces untested replacement logic.

### D9: Run isolation only for attribution
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) four isolation arms unconditionally B) isolate only agents implicated by a joint miss.
**Chosen**: B.
**Rationale**: Joint output cannot identify one agent; conditional isolation supplies evidence without making every run expensive.

### D10: Count rejected artifacts
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) count only stored garbage B) count stored garbage and normalization rejections.
**Chosen**: B.
**Rationale**: A stronger regex can make stored garbage zero while silently dropping entities.

### D11: Match worker concurrency
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) retain default concurrency B) equalize arms at a safe local concurrency.
**Chosen**: B.
**Rationale**: Concurrency changes ontology visibility and therefore corrupts model comparison.

### D12: Baseline variance is optional evidence
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) block local execution on two baseline runs B) use a complete baseline when available and otherwise report `NOT MEASURED`.
**Chosen**: B.
**Rationale**: The prior second baseline hung; baseline evidence must not deadlock the local migration.

### D13: Bound all probes
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) unbounded calls B) explicit per-call and job-poll timeouts.
**Chosen**: B.
**Rationale**: A timeout is an observed outcome and distinguishes an endpoint stall from a model failure.

### D14: Preserve extractor properties schema
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) narrow open dictionaries in the shared run B) isolate schema experiments.
**Chosen**: B.
**Rationale**: Changing persisted graph semantics during the comparison would confound quality results.

### D15: Do not reuse incomplete evidence as a gate
**Date**: 2026-08-19 - **Stage**: planning
**Options**: A) treat one finished arm as baseline B) mark missing variance and E2E values `NOT MEASURED`.
**Chosen**: B.
**Rationale**: A partial run cannot define a tolerance band or prove no regression.

### D16: Flash Next is the sole active local target
**Date**: 2026-09-03 - **Stage**: planning
**Options**: A) continue remote `qwen3.8-27b` evidence B) validate exact local `qwen3.8-flash-next`.
**Chosen**: B.
**Rationale**: The user supplied the local endpoint and model id; remote evidence is historical context only.

### D17: Treat system-message ordering as compatibility work
**Date**: 2026-09-03 - **Stage**: planning
**Options**: A) weaken agent prompts B) coalesce or adapt static/dynamic system messages for local calls.
**Chosen**: B.
**Rationale**: The observed HTTP 400 is a transport/template contract failure, not evidence that the model cannot perform the task; preserve the hosted path while repairing local compatibility.

### D18: Diagnose before cutover
**Date**: 2026-09-03 - **Stage**: planning
**Options**: A) cut over on superficial pass rates B) require root-cause analysis and an ASD-STE100 report when quality is inadequate.
**Chosen**: B.
**Rationale**: A local setup is valuable only when its stored graph and agent behavior are trustworthy.

### D19: Amend Stage 6b dependency for blocked-arm diagnosis
**Date**: 2026-09-03 - **Stage**: planning - **Type**: AMENDMENT
**Original**: "**Dependencies**: Stage 6 DONE."
**Replacement**: "Stages 3 and 4 DONE; Stage 6b follows Stage 6 by state ordering and runs after a blocked attempt."
**Evidence**: The runner unlocks dependencies only when they are `DONE`; journal correction entry 2026-09-03.
**Class**: execution dependency, not a quality relaxation.

### D20: Amend control-stage dispositions
**Date**: 2026-09-03 - **Stage**: planning - **Type**: AMENDMENT
**Original**: "otherwise mark it `SKIPPED`" and "Stage 8 may be `SKIPPED`".
**Replacement**: Stage 6b and Stage 8 finish `DONE` with an explicit no-op or `NOT MEASURED` outcome.
**Evidence**: Stage 7/9 dependencies require `DONE`; journal correction entry 2026-09-03.
**Class**: execution control, not a correctness relaxation.

### D21: Amend no-baseline quality decision
**Date**: 2026-09-03 - **Stage**: planning - **Type**: AMENDMENT
**Original**: "use absolute checks and qualitative review".
**Replacement**: Require measured passing extraction, episodic, cognitive, Plan 15 (≥11/14), Plan 17 (≥13/14), integrity, and fixed 20-node/20-edge mechanical sample checks; any `NOT MEASURED` forces `HOLD`.
**Evidence**: The prior wording allowed subjective same-artifact approval; journal correction entry 2026-09-03.
**Class**: measurement rubric, amendable because it defines evidence, not a product invariant.

### D22: Use the repository's real dev-token map
**Date**: 2026-09-03 - **Stage**: planning
**Options**: A) test token file and fallback admin token B) root `dev_tokens.json` with `admin-token`.
**Chosen**: B.
**Rationale**: `dev_tokens.json` is the repository production-dev map and explicitly maps `admin-token` to `admin`; this aligns model bake-off admin and seed-schema checks.

### D23: Preserve the explicit local credential variable
**Date**: 2026-09-03 - **Stage**: 1
**Options**: A) change the product default to `LITELLM_API_KEY` B) retain `VLLM_API_KEY` and diagnose the credential mismatch.
**Chosen**: B.
**Rationale**: The required contract names `VLLM_API_KEY`; the environment value was rejected with HTTP 401, while a process-only alias of the usable credential passed. No secret or `.env` value is changed.

### D24: Isolate routing tests from malformed developer `.env`
**Date**: 2026-09-03 - **Stage**: 1
**Options**: A) edit `.env` B) pass `_env_file=None` in unit fixtures and use explicit environment overrides for live checks.
**Chosen**: B.
**Rationale**: `.env` contains an invalid boolean representation for `extraction_enabled`; tests must remain deterministic without modifying or committing the local file.
