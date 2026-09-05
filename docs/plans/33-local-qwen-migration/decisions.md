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

### D25: Amend the Stage 1 active credential environment
**Date**: 2026-09-03 - **Stage**: 1 - **Type**: AMENDMENT
**Original**: ~~The endpoint requires `Authorization: Bearer $VLLM_API_KEY`; Stage 1 reads `local_model_api_key_env=VLLM_API_KEY`.~~ → The active run sets `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY` and sends `Authorization: Bearer $LITELLM_API_KEY`.
**Evidence**: The live endpoint returned HTTP 401 for the inherited `VLLM_API_KEY`, while direct use of the separately configured `LITELLM_API_KEY` returned HTTP 200 with exactly `qwen3.8-flash-next`, and raw chat plus PydanticAI structured output succeeded. No credential value was recorded.
**Disposition**: Stage 1 uses `LITELLM_API_KEY` explicitly for this machine; the product setting default remains `VLLM_API_KEY` for other environments.
**Class**: Runtime measurement assumption; the model/provider contract and secret handling are unchanged.

### D26: Fail fast for missing configured local authentication
**Date**: 2026-09-03 - **Stage**: 1
**Options**: A) pass an empty key to the provider and fail later with an opaque HTTP 401 B) raise a clear configuration error when a named key environment is absent, while allowing an explicit empty environment name for unauthenticated local endpoints.
**Chosen**: B.
**Rationale**: A configured authenticated endpoint must not silently downgrade to an empty credential. The explicit empty `local_model_api_key_env` option preserves the documented OpenAI-compatible local endpoint support for services such as unauthenticated Ollama.

### D27: Keep separate ingestion and capability-probe corpus contracts
**Date**: 2026-09-03 - **Stage**: 2
**Options**: A) make the 28-episode ingestion loader serve probe calls B) retain `load_corpus` for ingestion and expose `load_probe_corpus` for the fixed three-episode Plan 33 corpus.
**Chosen**: B.
**Rationale**: The two harnesses intentionally consume different fixed corpora and return different shapes. A compatibility function in the shared loader repairs the stale probe import without changing the ingestion/bake-off contract or corpus contents.

### D28: Prefer the lowest effort that passes quality
**Date**: 2026-09-03 - **Stage**: 3
**Options**: A) select xhigh by default B) validate low first and raise effort only when measured quality improves.
**Chosen**: B.
**Rationale**: The user observed that Flash Next at xhigh can loop or overthink. Indexing time is acceptable, but unnecessary reasoning increases operational risk; later effort tuning must use measured quality benefit and must not choose xhigh by default.

### D29: Make measurement provenance fail closed
**Date**: 2026-09-03 - **Stage**: 4
**Options**: A) let the bake-off infer completion and continue with degraded recall B) require explicit
auth, terminal jobs, embedding health, and source paths before interpreting quality metrics.
**Chosen**: B.
**Rationale**: The harness must not convert queued work, missing embeddings, or an untraceable graph
into a passing result. ~~A derived timeout is based on configured per-call timeout, three serial model
stages, three attempts, fixed corpus size, and worker concurrency.~~ The Stage 4 timeout is an
operational acceptance budget; D31 records its routed-stage inputs and exclusions. Non-terminal jobs
produce only an exact NOT_MEASURED sidecar. The live auth check uses the repository dev-token map and
restores a pre-check snapshot. Audit hooks record credential-free model/tool/retry/timing dimensions
and exclude prompts, outputs, tool arguments, and secrets.

### D30: Require a per-episode parsing report
**Date**: 2026-09-03 - **Stage**: 7/9
**Options**: A) publish aggregate metrics only B) publish a fixed 28-row report with machine-readable provenance.
**Chosen**: B.
**Rationale**: Aggregate metrics cannot show episode-level failures. The report links each row to database, job, audit, corpus, and snapshot evidence.
**Controls**: The report uses `NOT MEASURED` for missing evidence. It excludes prompts, hidden reasoning, raw model output, secrets, and sensitive audit fields. A JSON Schema and a fixed episode-set check reject fabricated rows.

### D31: Clarify the Stage 4 timeout as an operational acceptance budget
**Date**: 2026-09-03 - **Stage**: 4 - **Type**: AMENDMENT
**Original**: D29 described a derived timeout using three serial model stages.
**Replacement**: The timeout is an operational acceptance budget based on the registered route/extract retry policies, initial domain count 4, routed-domain cap 5, route/extract attempts 3, corpus size 28, and worker concurrency 2. The explicit run uses 5,460 operational stage invocations and a 101,070-second budget at a 37-second per-call timeout; the default 600-second timeout gives 1,638,060 seconds.
**Exclusions**: Parent-seed recursion, internal PydanticAI retries, and non-model work are outside this budget. An overrun is `NOT_MEASURED` and a stability failure; the budget is not a theoretical upper bound.
**Evidence**: Stage 4 dry-run provenance and the independent acceptance record in `resources/stage4-harness-evidence.json`.

### D32: Invalidate the interrupted local arm
**Date**: 2026-09-03 - **Stage**: 4/6
**Options**: A) treat the partial run as local quality evidence B) invalidate it and rerun after repository-wide audit-privacy acceptance.
**Chosen**: B.
**Rationale**: The run was non-terminal and exposed source/model-derived strings in action records. A librarian request-budget defect also prevented a truthful completion result.
**Evidence**: Journal entry for run `20260903T133626Z-60064`; recovery archive `backups/qwen-flash-next-pre-20260903T133626Z-60064-20260903-153627.tar.gz`; corrective implementation `6a2c0b3`.

### D33: Keep the repository-wide privacy gate open
**Date**: 2026-09-03 - **Stage**: 4
**Options**: A) accept extraction-side redaction as complete B) audit every repository `action_log=True` path before closing Stage 4.
**Chosen**: B.
**Rationale**: The run proved that extraction-side correction did not cover all action-audit paths. The gate must cover repository adapters, mocks, routing, ingestion, and extraction.
**Evidence**: Journal entry for run `20260903T133626Z-60064` and commit `6a2c0b3`; backlog item 13 tracks the remaining acceptance.

### D34: Require a fresh, separated evidence run after non-convergence
**Date**: 2026-09-05 - **Stage**: 6 - **Type**: IMPLEMENTATION / PROVENANCE
**Options**: A) resume the non-converged attempt B) start a fresh run with separated, run-scoped evidence.
**Chosen**: B.
**Rationale**: Run `20260903T174929Z-31844` completed 110/110 corpus jobs, but recall returned 401, the pre-snapshot label was incorrect, and no E2E children ran. The accepted redesign binds corpus graph metrics to the live corpus and an exact post-snapshot/hash, attaches a separate offline five-child E2E manifest, requires strict Plan 15 PASS-only evidence, enforces terminal `(failed+cancelled)/total <= 0.10`, and records safe aggregate recall. The old attempt is diagnostic only. This is an implementation/provenance decision and does not amend thresholds.
