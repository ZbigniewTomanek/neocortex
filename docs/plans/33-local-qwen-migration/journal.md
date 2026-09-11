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

## 2026-09-03 -- Stage 1: local Flash Next routing and authenticated preflight -- BLOCKED
**Did**: Updated `tests/test_local_provider_routing.py` to use the exact `local:qwen3.8-flash-next` route, verify hosted-string preservation, missing-base-URL failure, environment-only authentication, explicit effort/sampling/timeout settings, and mixed local/hosted agents. The existing model factory and MCP settings wiring required no product change. Unit fixtures use `_env_file=None`; `.env` was not edited.
**Verification**:
- GATE `NEOCORTEX_EXTRACTION_ENABLED=true uv run pytest tests/test_local_provider_routing.py -q`: **PASS**, 9 passed. Input: the updated routing test module. A provider-selection, settings, or auth-wiring regression turns this red.
- GATE `POSTGRES_PORT=15432 NEOCORTEX_EXTRACTION_ENABLED=true NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini uv run pytest tests/test_local_provider_routing.py tests/ -q`: **PASS**, 923 passed, 7 skipped in 45.24s. Inputs: repository tests, explicit settings overrides, and the running PostgreSQL service on port 15432. A regression in relevant tests turns this red; the unoverridden local `.env`/default port is not used because it is malformed/unavailable on this machine.
- GATE authenticated `GET http://127.0.0.1:24000/v1/models` with the original environment `VLLM_API_KEY`: **RED**, HTTP 401. Input: live response from the required endpoint using the environment variable as supplied. A wrong credential, missing authorization, endpoint error, or model mismatch turns this red.
- REPORT authenticated preflight with a process-only alias of the usable LiteLLM credential assigned to `VLLM_API_KEY`: `/models` **HTTP 200**, exact ids `['qwen3.8-flash-next']`, 0.070s; chat completion **HTTP 200**, valid JSON/model `qwen3.8-flash-next`, 0.491s; PydanticAI structured output **success**, `SmokeOutput`, 2.304s. Inputs: live endpoint and model factory; no credential value was recorded.
- CHECK formatting/type tools: `uv run ruff check src/neocortex/model_factory.py tests/test_local_provider_routing.py`, `uv run black --check src/neocortex/model_factory.py tests/test_local_provider_routing.py`, and `uv run ty check src/neocortex/model_factory.py src/neocortex/mcp_settings.py`: **PASS**.
**Provenance**: The direct credential gate is red because the supplied `VLLM_API_KEY` is not accepted by this LiteLLM endpoint. The passing process-only alias demonstrates endpoint availability and model identity but does not satisfy the exact credential contract until the environment is corrected.
**Problems**: Backlog item 11 is `IN_PROGRESS`; Stage 1 is `BLOCKED` and dependent stages remain pending. The local `.env` has an invalid boolean value for `extraction_enabled`; explicit `NEOCORTEX_EXTRACTION_ENABLED=true` was used for commands and no `.env` change was made.

## 2026-09-03 -- Stage 1 resume: authenticated preflight recheck -- BLOCKED
**Did**: Rechecked the live endpoint and Stage 1 routing after the interrupted run. No product routing defect was found. The exact inherited `VLLM_API_KEY` was used without printing or persisting its value; a process-only alias from the separately available LiteLLM credential was used only to confirm service behavior and was not written to disk.
**Verification**:
- GATE authenticated `GET http://127.0.0.1:24000/v1/models` with the exact inherited `VLLM_API_KEY`: **RED**, HTTP 401. Response identified a LiteLLM virtual-key format mismatch. Input: live endpoint response and the environment-only credential. A rejected credential or unexpected model id turns this gate red.
- REPORT authenticated `GET /v1/models` with the process-only alias: **HTTP 200**, exact model ids `['qwen3.8-flash-next']`. Input: live endpoint JSON; no credential value recorded.
- REPORT raw authenticated chat completion with the process-only alias: **HTTP 200**, model `qwen3.8-flash-next`, valid stopped completion with content `OK` after whitespace normalization, 1.124512s (`curl` `time_total`). Input: one request with `temperature=0` and `max_tokens=128`; a non-200 response, malformed JSON, wrong model, or absent completion content would fail this check.
- REPORT PydanticAI structured-output smoke with the process-only alias: **success**, output type `SmokeOutput`, non-empty `answer`, 2.316s. Input: `build_model('local:qwen3.8-flash-next', LocalEndpoint(...))` and a typed PydanticAI agent; transport failure or invalid output would fail this check.
- GATE `POSTGRES_PORT=15432 NEOCORTEX_EXTRACTION_ENABLED=true NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini uv run pytest tests/test_local_provider_routing.py tests/ -q`: **PASS**, 923 passed, 7 skipped in 45.26s. Inputs: repository tests with explicit model and extraction settings; a provider-selection, settings, or regression failure turns this red.
**Provenance**: The exact-key 401 remains reproducible, while all service and model checks pass only with the process-only alias. The alias is not equivalent evidence for the required credential contract. Existing routing tests remain the only Stage 1 code change; `.env` was not edited.
**Problems**: Backlog item 11 remains `IN_PROGRESS`; Stage 1 remains `BLOCKED` with `blocked_by: [11]`. The environment must provide the LiteLLM virtual key under `VLLM_API_KEY` before the authenticated GATE can pass.

## 2026-09-03 -- Stage 1 completion: configured local credential and fail-fast auth -- DONE
**Did**: Amended the active-run credential assumption after the independent endpoint audit. This run sets `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY` and uses the configured `LITELLM_API_KEY` directly. The product default remains `VLLM_API_KEY` for other environments. `build_model` now raises a clear `ValueError` when a named local credential environment is absent or empty; an explicitly empty environment-name setting remains available for unauthenticated local endpoints. No secret value was printed, logged, persisted, or committed.
**Verification**:
- GATE authenticated `GET http://127.0.0.1:24000/v1/models` with the configured `LITELLM_API_KEY`: **PASS**, HTTP 200 in 0.255443s, exact model ids `['qwen3.8-flash-next']`. Input: live endpoint JSON with `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY`; wrong id, missing auth, malformed JSON, or endpoint failure turns this red.
- REPORT raw authenticated chat completion with the configured `LITELLM_API_KEY`: **PASS**, HTTP 200 in 1.011488s, model `qwen3.8-flash-next`, stopped completion content `OK` after whitespace normalization. Input: `temperature=0`, `max_tokens=128`; non-200, malformed JSON, wrong model, or absent content turns this check red.
- REPORT PydanticAI structured-output smoke with the configured `LITELLM_API_KEY`: **PASS** after a schema-explicit prompt, output type `SmokeOutput`, non-empty `answer`, 5.875s. An initial under-specified prompt produced plain `OK` and failed typed validation; the successful check used an explicit JSON-object instruction. Input: `build_model('local:qwen3.8-flash-next', LocalEndpoint(... api_key_env='LITELLM_API_KEY'))`; transport or typed-output failure turns this check red. Prompt sensitivity remains a Stage 2/3 compatibility concern.
- GATE `NEOCORTEX_EXTRACTION_ENABLED=true uv run pytest tests/test_local_provider_routing.py -q`: **PASS**, 9 passed in 0.24s. Input: routing/auth regression tests, including missing-key failure and explicit unauthenticated-endpoint opt-out; provider selection, missing setting, or weakened auth assertion turns this red.
- GATE `POSTGRES_PORT=15432 NEOCORTEX_EXTRACTION_ENABLED=true NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini uv run pytest tests/test_local_provider_routing.py tests/ -q`: **PASS**, 923 passed, 7 skipped in 45.64s. Input: repository tests with explicit hosted model overrides and extraction enabled; a provider regression, failed auth assertion, or unrelated test failure turns this red. The malformed local `.env` is not used.
- CHECK `uv run ruff check src/neocortex/model_factory.py tests/test_local_provider_routing.py`, `uv run black --check src/neocortex/model_factory.py tests/test_local_provider_routing.py`, and `uv run ty check src/neocortex/model_factory.py src/neocortex/mcp_settings.py tests/test_local_provider_routing.py`: **PASS** after formatting.
- CHECK plan lint: `jq` state validation, stage-file reference validation, and `git diff --check`: **PASS** after the final state update.
**Provenance**: Backlog item 11 is resolved by using the credential environment that the endpoint accepts, not by aliasing or changing a secret. The state disposition is Stage 1 `DONE`; subsequent stages may use the active credential setting from `resources/commands.md`.
**Problems**: The generic structured-output prompt was insufficient for this model and remains recorded as a prompt-compatibility signal for Stage 2/3. No Stage 1 routing or authentication blocker remains.

## 2026-09-03 -- Stage 1 verifier bookkeeping -- RECORDED
**Did**: Confirmed the Stage 1 completion state and commit reference `4ab4284`; active Stage 2 and Stage 6 instructions now use the configured credential environment and name `LITELLM_API_KEY` for this run.
**Verification**: `state.json` reports Stage 1 `DONE` with backlog item 11 resolved; no source files or credentials changed.
**Provenance**: Commit reference is the verified Stage 1 fix commit; historical `VLLM_API_KEY` mentions remain only where they describe prior evidence or the preserved product default.

## 2026-09-03 -- Stage 2: local Flash Next capability probes -- DONE
**Did**: Repaired the stale probe corpus import by adding `load_probe_corpus` to `scripts/corpus_loader.py` while preserving the 28-episode `load_corpus` ingestion contract. Added import-level regression tests. Extended `scripts/probe_local_model.py` to capture per-attempt model/effort/source hash, outcome, exception and failure class, raw validation output when available, wall clock, usage, tool order, retries, and normalization rejections. Ran the real ontology, extractor, librarian, and domain-classifier agents against the fixed three-episode corpus at low, medium, high, and xhigh with concurrency 2 and a 300-second timeout.
**Verification**:
- GATE loader/import regression: `uv run pytest tests/unit/test_probe_corpus_loader.py tests/test_local_provider_routing.py -q` **PASS**, 11 passed. Input: shared loader and routing tests; a stale import, altered corpus contract, or weakened auth/routing assertion turns this red.
- GATE medium probe: `uv run python scripts/probe_local_model.py --model local:qwen3.8-flash-next --effort medium --timeout 300` **PASS**, 60 real records (15 per each of four agents), with all four agent names present. Input: live authenticated local endpoint, fixed E1-E3 corpus, effort medium, repeats 5, concurrency 2; missing records, unbounded calls, or fabricated output turns this red.
- GATE probe output schema: all four `resources/probe-results-{low,medium,high,xhigh}.json` files **PASS**, 60 records each, exact model id, episode/effort/outcome/source hash, measured elapsed time, tool arrays, and failure/normalization fields. Input: the four files emitted by this run; missing provenance or copied/default records turns this red.
- REPORT four-effort sweep: 240 total records. Ontology, extractor, and librarian: 0/15 success at every effort, 15/15 `http_400_system_message_order` per effort; exact body contains `code: 400` and `System message must be at the beginning.` Domain classifier: low 14/15, medium 15/15, high 12/15, xhigh 14/15; each miss was E3 `invalid_structured_output` after one validation retry. No timeout, refusal, empty-content, or malformed-tool-argument outcome was observed.
- CHECK formatting/lint/diff: `uv run ruff check scripts/corpus_loader.py scripts/probe_local_model.py tests/unit/test_probe_corpus_loader.py`, `uv run black --check ...`, and `git diff --check` **PASS**. Inputs: changed harness/test files and worktree diff; a lint, formatting, or whitespace defect turns this red.
- CHECK full suite: `POSTGRES_PORT=15432 NEOCORTEX_EXTRACTION_ENABLED=true NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini uv run pytest tests/ -q` **PASS**, 925 passed, 7 skipped in 45.85s. Input: the repository test suite with explicit hosted model overrides and extraction enabled; any regression in the repository tests turns this red.
**Provenance**: Raw records are in `resources/probe-results-low.json`, `probe-results-medium.json`, `probe-results-high.json`, and `probe-results-xhigh.json`; findings are in `resources/probe-findings.md`. The endpoint used `LITELLM_API_KEY` selected by `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV`; its value was never printed or persisted. Ontology and librarian exercised isolated `InMemoryRepository` tool surfaces, so this is not PostgreSQL persistence evidence.
**Problems**: Stage 2 provisional finding is **NEEDS HARDENING**, not `BLOCKED`: three surfaces hit a reproducible message-order transport contract and the classifier has E3 structured-output misses. Stage 3 owns compatibility/prompt investigation and must re-run the real probes after its changes. Token usage for rejected calls is `NOT MEASURED` because the service returned HTTP 400 before generation; timing remains informational.

## 2026-09-03 -- Stage 2 provenance correction and rerun -- DONE
**Did**: Corrected the probe evidence contract after audit. Each artifact now records run-level source revision and source/worktree cleanliness, source diff and probe-script hashes, fixed corpus id/path/hash and exact episode set, endpoint URL/model id, direct-call mode with explicit `job_ids: []` and no-job explanation, UTC timestamp/run id, and concurrency/timeout/repeat settings. Record paths are repository-relative. Failed/timeout calls now use explicit `NOT_MEASURED` values with availability flags for retries, raw validation output, usage, tool calls, and normalization rejection counts; successful calls retain measured values. The corpus and prompts were unchanged.
**Verification**:
- GATE metadata schema: `uv run pytest tests/unit/test_probe_corpus_loader.py -q` **PASS**, 3 passed. The test validates all four emitted artifacts, schema version, source/corpus/endpoint/direct-call metadata, exact 60-record counts, model/effort consistency, repository-relative source path, and measured-versus-`NOT_MEASURED` availability semantics. Missing provenance, ambiguous nulls, or a stale artifact turns this red.
- GATE medium probe rerun: **PASS**, 60 real records with all four agent surfaces and metadata run id `e2583d566fa244d8ba6cd356a82cc61d`; endpoint `http://127.0.0.1:24000/v1`, model `qwen3.8-flash-next`, concurrency 2, timeout 300s, repeats 5, direct mode, `job_ids: []`. Missing records, wrong endpoint/model, unbounded calls, or enqueued jobs turns this red.
- GATE four-effort provenance: **PASS**, low run `d225ff53f99542c8b9a07e79b879962e`, medium `e2583d566fa244d8ba6cd356a82cc61d`, high `a665d29bc6654ce2a5e92682b967a934`, xhigh `49779e9b526c4d9bb07e740df2f6c28e`; all 60 records per artifact, exact corpus SHA-256 `5e9c2402dc87d2976d4dab0fac1a77689903843bf6d3a3ace2f6f17f062b967f`, exact `[E1,E2,E3]` set, source revision `920a2083846311a04fdf8bfdf9cfd1febc9f60eb`, source diff SHA-256 `2083ad1bb987b5f4c153d251d87db49c4205098e6aa5f80b410049284dfba294`, probe-script SHA-256 `d4e8eb431a957b3de1aade0f024ca4edbe4225a8107c4a98149b0f6082b86a0e`. Input: all four raw JSON files; changed corpus, missing hashes, absolute paths, or ambiguous unavailable values turns this red.
- REPORT corrected outcomes: 240 records. Ontology/extractor/librarian were 0/15 successes at each effort and 15/15 `http_400_system_message_order` failures per effort; domain classifier was low 13/15, medium 14/15, high 14/15, xhigh 12/15, with E3 `invalid_structured_output` failures. No timeout, refusal, empty-content, or malformed-tool-argument outcomes occurred.
- CHECK focused quality: `uv run ruff check scripts/probe_local_model.py scripts/corpus_loader.py tests/unit/test_probe_corpus_loader.py`, `uv run black --check scripts/probe_local_model.py scripts/corpus_loader.py tests/unit/test_probe_corpus_loader.py`, and `git diff --check` **PASS**. Inputs: corrected harness, loader, test, and evidence diff; lint/format/whitespace regressions turn this red.
- CHECK full suite: `POSTGRES_PORT=15432 NEOCORTEX_EXTRACTION_ENABLED=true NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini uv run pytest tests/ -q` **PASS**, 926 passed, 7 skipped in 46.38s. Input: repository tests with explicit hosted model overrides; any regression turns this red.
**Provenance**: Corrected raw artifacts are `resources/probe-results-{low,medium,high,xhigh}.json`; each contains direct-call metadata and exact source hashes. The active credential environment was `LITELLM_API_KEY`; no secret value was recorded. Ontology/librarian remain isolated `InMemoryRepository` tool-surface probes, not PostgreSQL persistence evidence.
**Problems**: Stage 2 remains **NEEDS HARDENING** as a provisional model-compatibility finding, not a provenance blocker. The three-agent HTTP 400 message-order defect and classifier E3 output failures remain assigned to Stage 3. `NOT_MEASURED` usage/retry/raw-validation values are intentional because rejected/failed calls returned no `RunResult`; no values were inferred from exception text.

## 2026-09-03 -- Stage 2 correction verifier bookkeeping -- RECORDED
**Did**: Confirmed the provenance correction commit `edc33eb` and updated `state.json` to reference that actual commit. The state remains Stage 2 `DONE`; the provisional capability finding remains **NEEDS HARDENING** for Stage 3.
**Verification**: `state.json` reports Stage 2 `DONE` with commit `edc33eb`; no credentials or unrelated `.plan_runner_done` changes were included.
**Provenance**: The correction commit contains the harness, strengthened schema test, four rerun artifacts, findings, journal, and state correction. Raw artifacts retain source revision `920a208...`, source diff hash, and probe-script hash for the exact code used during measurement.

## 2026-09-03 -- Stage 3: local Flash Next compatibility hardening -- DONE
**Did**: Added `LocalOpenAIChatModel`, a local-only subclass of PydanticAI 1.72.0 `OpenAIChatModel`. Its private `_map_messages` override delegates all standard mapping, combines every mapped `system` message in source order with blank-line separators, emits one typed system message at index zero, and retains every non-system mapped message object unchanged. Hosted model names still return their original string route. The adapter docstring records the pinned-version/private-hook upgrade risk. Added focused tests for tuple static plus dynamic instruction ordering, tool-call/return order and IDs, stream request tool/native structured-output parity against the unmodified base model, and hosted string routing. No agent prompt, output schema, normalizer, or hosted request was weakened or changed.
**Verification**:
- GATE focused compatibility suite: `uv run pytest tests/test_local_provider_routing.py -q` **PASS**, 12 passed. Input: the local model factory and focused mapping/request tests; a failure in message coalescing, non-system ID/order preservation, tool/structured-output payload parity, or hosted string routing turns this red.
- GATE targeted medium rerun: `uv run python scripts/probe_local_model.py --model local:qwen3.8-flash-next --effort medium --timeout 300 --repeats 5 --concurrency 2` **PASS**, 60 real records in `resources/stage3-probe-results-medium-after-coalescing.json`. Input: endpoint `http://127.0.0.1:24000/v1`, model `qwen3.8-flash-next`, `LITELLM_API_KEY` selected through `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV`, direct PydanticAI calls, fixed E1-E3 corpus, and the exact Stage 2 bounds. The former system-order HTTP 400 occurred 0/60 times; a missing record, changed corpus/endpoint, swallowed failure, or unbounded run turns this red. Artifact SHA-256: `321eeeb513fc22b4bd6b5afaf59f2959640e547ccad7559c96f9d2e32315c570`; complete raw-output sidecar SHA-256: `71eed69f39a790e9499de42d366e91e437ff58276ff7b6cafbbbfd9f3fa9774d`.
- GATE low-effort confirmation: `uv run python scripts/probe_local_model.py --model local:qwen3.8-flash-next --effort low --timeout 300 --repeats 1 --concurrency 2 --output resources/stage3-probe-results-low-after-coalescing.json` **PASS**, 12 real records. Input: the same endpoint, model, corpus, direct-call mode, concurrency, and per-attempt timeout with one confirmation repeat; all four agents completed 3/3 and no system-order 400 occurred. Artifact SHA-256: `4f129f91f6d8d83a137fdc97ce7605185040372c345e774364d584ea737b3467`.
- GATE hosted-path regression: `POSTGRES_PORT=15432 NEOCORTEX_EXTRACTION_ENABLED=true NEOCORTEX_ONTOLOGY_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_EXTRACTOR_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_LIBRARIAN_MODEL=openai-responses:gpt-5.4-mini NEOCORTEX_DOMAIN_CLASSIFIER_MODEL=openai-responses:gpt-5.4-mini uv run pytest tests/ -q` **PASS**, 929 passed, 7 skipped in 45.22s. Input: all repository tests with explicit hosted model overrides; a regression in hosted tools, schemas, persistence, routing, or probe-artifact contracts turns this red.
- CHECK static validation: `git diff --check`, focused `ruff`, `black --check`, and `ty check` **PASS** for `src/neocortex/model_factory.py` and `tests/test_local_provider_routing.py`. Input: changed source/test files; a formatting, type, or whitespace defect turns this red.
**REPORT compatibility delta**: Stage 2 corrected medium evidence had ontology/extractor/librarian 0/15 each with 15 HTTP 400/order failures, and classifier 14/15 with one E3 invalid structured output. Stage 3 medium produced ontology 13/15 (two explicit 300-second generation timeouts), extractor 15/15, librarian 15/15, and classifier 13/15 (two E3 invalid structured-output failures). The former HTTP 400 was eliminated for all 60 medium and 12 low records. Medium successful librarian calls retained tool traces (13/15 had two validation retries; 2/15 had none); low calls were 3/3 with 2/3 having two retries. No successful extractor/librarian normalization rejection was recorded.
**REPORT classifier diagnosis**: The two medium E3 failures ended in `Exceeded maximum retries (1) for output validation`, with unavailable raw validation/usage correctly marked `NOT_MEASURED`. Four separate direct E3 diagnostics at medium effort each returned valid structured output in one model request, so no deterministic malformed marker or schema-field defect was observed. No classifier prompt fix was attempted because the evidence did not support one; backlog 12 tracks the residual stochastic output risk and medium ontology timeouts for Stage 6/6b.
**Provenance**: The medium artifact was first generated at the probe's canonical path, then moved to the Stage 3 path; the committed Stage 2 medium blob was restored byte-for-byte (SHA-256 `c18d295b5780916613c0c27b80e6724b0133c16903a6966858bf5cc99d7ab922`). No secret value was printed, logged, or persisted. User direction recorded in D28: validate low first and increase effort only with measured quality benefit; xhigh was not rerun or selected.
**Problems**: Stage 3 resolves the confirmed transport compatibility defect but does not certify local model quality. Backlog item 12 is OPEN for the residual generation reliability risk. Stage 6/6b must measure full-flow completion and isolate timeout/structured-output behavior before any cutover decision.

## 2026-09-03 -- Code review follow-up: Stage 3 backlog disposition -- RECORDED
**Review outcome**: A five-axis review found no correctness, edge-case, SQL-performance, security, or modularity defect in the Stage 3 source change. The review scope was the already committed adapter/tests and Plan 33 evidence; no source or SQL edits were required.
**Disposition**: Fixed the confirmed bookkeeping finding by marking backlog item 9 **RESOLVED** with implementation commit `1df6c2a` and the measured medium/low rerun references. Backlog item 12 remains **OPEN** for the separately measured ontology timeout and stochastic classifier structured-output risk.

## 2026-09-03 -- Stage 4: measurement harness, instrumentation, and auth stability -- DONE
**Did**: Completed the bake-off harness for the fixed 28-episode ingestion corpus. Metrics now record
live graph, snapshot, audit-log, admin jobs API, corpus, run id, model, endpoint identity, effort,
worker, timeout, and source revision metadata. Model, tool, retry/rejection, stage-timing, usage, and
normalization-rejection events carry agent, agent id, episode id, correlation id, model, credential-free
endpoint, effort, and run id. The harness uses explicit admin and MCP tokens, rejects absent or
misplaced credentials, derives a bounded poll timeout from per-call timeout/corpus/concurrency, refuses
quality output for non-terminal jobs, and preserves/restores a snapshot around a live auth check.
Embedding health fails clearly when GOOGLE_API_KEY is not supplied; no text-only recall result is
certified as embedding health.
**Verification**:
- GATE fixed corpus and related harness regressions: uv run pytest tests/unit/test_measurement_harness.py tests/test_extraction_pipeline.py tests/test_local_provider_routing.py tests/test_domain_classifier.py tests/test_domain_router.py tests/unit/test_domain_routing.py -q **PASS**, 68 passed. Input paths and the exact corpus SHA-256 are recorded in resources/stage4-harness-evidence.json; a parser change, fabricated episode, or instrumentation regression turns this red.
- GATE non-terminal safeguard: test_non_terminal_cli_writes_only_not_measured_sidecar **PASS**. A summary with todo=1 returns exit 2, writes an exact NOT_MEASURED sidecar, and leaves the quality metrics path absent. Input: the test's temporary output directory and exact job summary; writing a quality artifact before terminal completion turns this red.
- GATE admin/MCP authentication: uv run python scripts/auth_self_check.py **PASS** against the live services. Invalid admin and MCP credentials were rejected and the valid admin-token mapping in dev_tokens.json was accepted. Input paths: scripts/auth_self_check.py, dev_tokens.json, /admin/graphs, and /mcp; accepting an invalid token or rejecting the valid token turns this red.
- GATE timeout/report dry run: ./scripts/model_bakeoff.sh --arm qwen-flash-next --dry-run **PASS**, resolved model local:qwen3.8-flash-next, endpoint http://127.0.0.1:24000/v1, low default effort, worker concurrency 2, per-call timeout 37 seconds, corpus size 28, derived poll timeout 4722 seconds, and the metrics/audit paths. Input: the script, fixed corpus, and environment-only token names; a secret value, stale model, missing path, or unbounded timeout turns this red.
- CHECK static validation: focused Black, Ruff, Ty, bash -n scripts/model_bakeoff.sh, and git diff --check **PASS**.
- REPORT full repository regression: explicit hosted-model overrides produced 935 passed and 7 skipped in 5.44 seconds with PostgreSQL running from the restored pre-check snapshot; no test was weakened or removed.
- REPORT embedding health and recall: NOT MEASURED because the invoking measurement environment did not supply GOOGLE_API_KEY; the harness exits before a recall claim rather than silently degrading.
**Provenance**: The complete machine-readable record is resources/stage4-harness-evidence.json. The
live auth check used the pre-check snapshot stage4-auth-live-pre and loaded it after the check; app
services were left stopped. No credential value was printed, logged, or committed. No quality metrics
JSON was created because no local corpus run with terminal jobs and live embedding health was performed.
**Problems**: Backlog item 8 remains **OPEN** for the full live orchestrator. Backlog item 3 remains
**OPEN** for a general application startup health policy beyond this bake-off's explicit preflight.

## 2026-09-03 -- Stage 4 acceptance correction -- ACCEPT
**Did**: Reconciled the Stage 4 record with the independent acceptance of source revision `72c7275`.
The later docs-only commit `5bbeb6b` is retained as the documentation successor and adds the
per-episode Qwen parsing report contract. Embedding health, graph-derived recall, and local quality
metrics remain `NOT MEASURED`; no quality artifact was created.
**Verification**:
- GATE privacy/lifecycle focus: `uv run pytest tests/unit/test_dynamic_routing_audit_privacy.py tests/unit/test_domain_router_bounds.py tests/unit/test_domain_routing.py -q` **PASS**, 14 passed. The action audit contained 57 records and five dynamic-routing sentinels were absent.
- GATE combined focused acceptance: **PASS**, 108 passed under the independent acceptance run.
- GATE full repository suite: **PASS**, 965 passed and 7 skipped with the restored PostgreSQL snapshot.
- REPORT explicit dry run: timeout 37 seconds, worker concurrency 2, corpus 28, initial domains 4, routed-domain cap 5, route and extraction attempts 3, maximum route invocations 84, maximum routed extraction jobs 420, and 5,460 operational acceptance stage invocations. The resulting poll budget is 101,070 seconds. With the default 600-second per-call timeout, the corresponding budget is 1,638,060 seconds.
**Timeout semantics**: The poll value is an operational acceptance budget, not a theoretical upper
bound. Parent-seed recursion, internal PydanticAI retries, and non-model work are excluded. An
overrun is `NOT_MEASURED` and a stability failure.
**Provenance**: The machine-readable evidence is `resources/stage4-harness-evidence.json`; the source
acceptance is `72c7275` and its docs successor is `5bbeb6b`. No prompt, output, credential, or
dynamic-routing identifier was recorded in the action audit.

## 2026-09-03 -- Stage 5: optional hosted baseline comparison -- DONE / NOT MEASURED
**Did**: Checked credential and hosted-configuration environment-variable presence by name only. `OPENAI_API_KEY`
was present, but this execution had no provisioned isolated hosted runtime or current same-prompt hosted
comparison environment. No hosted request was made. The historical `resources/metrics-baseline-gpt54mini.json`
is a single 2026-08-19 run-one artifact with no current source revision, corpus hash, run id, or job summary;
it is retained as context and is not a baseline threshold.
**Verification**:
- GATE baseline disposition: **NOT MEASURED**. Two complete, same-input hosted runs and raw artefacts were
  unavailable; `resources/baseline-comparison.md` remains intentionally absent under the Stage 5 no-op path.
- GATE same-input check: **NOT MEASURED**. The historical one-run file cannot prove current Stage 3 prompt,
  schema, corpus, concurrency, timeout, or instrumentation identity.
- REPORT hosted latency, token, quality, and variance distributions: **NOT MEASURED**. No values were
  inferred from the historical partial evidence.
**Provenance**: The only current credential signal was the presence of `OPENAI_API_KEY`; its value was never
  read, printed, logged, or persisted. `NEOCORTEX_HOSTED_MODEL_API_KEY_ENV`, `NEOCORTEX_HOSTED_ENDPOINT`,
  and `NEOCORTEX_HOSTED_MODEL` were absent. Existing artifact SHA-256 is
  `b447c4af9c5bf67c8459bf93d2e061b9da0fd48c0777773c9b450892c165b714`. Stage 5 is an optional no-op and does
  not block the local Stage 6 run; backlog item 6 remains **OPEN**.
**Problems**: No hosted variance, tolerance, or quality comparison can be claimed. The local run remains
  eligible and must produce its own terminal, run-scoped evidence.

## 2026-09-03 -- Stage 6: local Flash Next arm interrupted -- CERTIFICATION INVALID / NOT MEASURED
**Did**: Started run `20260903T133626Z-60064` with the fixed 28-episode corpus, low effort, worker
concurrency 2, and the process-only `GOOGLE_API_KEY` alias from `GEMINI_API_KEY` for embeddings. The
local model used the configured `LITELLM_API_KEY` environment. The run was intentionally terminated
after about 3 hours 34 minutes when audit-privacy and librarian request-budget defects were proven.
**Verification**:
- REPORT terminal summary near termination: 14 succeeded, 1 failed, 2 doing, and 53 todo, 70 jobs
  total. This was not a terminal run and is not a quality result.
- REPORT Spark service health: the vLLM service remained healthy at concurrency 2. This is an
  operational observation only and does not certify NeoCortex output quality.
- REPORT one librarian attempt: PydanticAI applied its default `request_limit=50` even though the
  configured tool-call limit was 150. Episode 5 ended with a librarian `UsageLimitExceeded` after
  extractor retries. Successful extractor outputs ranged from 4,433 to 13,147 tokens. Output
  termination source is **NOT MEASURED**; no NeoCortex or vLLM fixed output cap was configured.
- GATE action-audit privacy: **RED**. Action records exposed source/model-derived strings. The run
  therefore cannot support a metrics, integrity, quality, or cutover claim.
**Provenance**: The pre-run database snapshot is
`backups/qwen-flash-next-pre-20260903T133626Z-60064-20260903-153627.tar.gz`. The pre-run database was
restored after termination. No metrics JSON, named graph snapshot, or per-episode Qwen parsing report
from this attempt is accepted. Raw run logs remain diagnostic only and must not be copied into reports.
Commit `6a2c0b3` records extraction-side request-budget and audit-privacy corrections; it does not yet
establish repository-wide privacy acceptance.
**Problems**: Stage 6 remains **PENDING**. Stage 4 is reopened as **IN_PROGRESS** pending repository-
wide audit-privacy acceptance. No Stage 6 gate passed, and no local quality outcome was measured.

## 2026-09-03 -- Stage 4: repository-wide action-audit privacy acceptance -- DONE / ACCEPT
**Did**: Applied the librarian request-budget implementation in `dc5fd15` and the repository and
ingestion privacy cleanup in `f1ba3bc`. An independent acceptance audited 90 `action_log=True` call
sites and found zero raw source/model field violations.
**Verification**:
- GATE focused extraction/privacy checks: **PASS**, 76 passed.
- GATE full safe suite: **PASS**, 977 passed and 7 skipped.
- CHECK `git diff --check`: **PASS**; the worktree was clean.
- REPORT acceptance verdict: **ACCEPT**. This closes backlog item 13 and does not change the
  certification-invalid disposition of the interrupted Stage 6 run.
**Provenance**: Evidence covers corrective source commits `dc5fd15` and `f1ba3bc`, the repository-wide
action-log call-site audit, focused extraction/privacy tests, the full safe suite, and the clean
worktree check. Stage 6 remains **PENDING** and requires a new valid run with its own metrics, snapshot,
and per-episode Qwen parsing report.

## 2026-09-05 -- Stage 6: post-non-convergence redesign checkpoint -- RECORDED / NOT MEASURED
**Did**: Reviewed failed run `20260903T174929Z-31844`: all 110/110 corpus jobs reached terminal success, recall exited 401, the pre-snapshot label was incorrect, and no E2E child ran. Two independent non-convergence investigations reached the same finding; the evidence harness redesign was implemented and the final fresh review was **ACCEPT**. The old metrics artifact was moved to a recoverable diagnostic archive; no canonical metrics artifact remains.
**Verification**:
- CHECK focused redesign suite: `uv run pytest tests/unit/test_e2e_manifest.py tests/unit/test_recall_scorer.py tests/unit/test_measurement_harness.py tests/unit/test_model_bakeoff.py -q` — **PASS**, 101 passed.
- CHECK privacy/identifier subset: `uv run pytest tests/unit/test_model_bakeoff.py tests/unit/test_recall_scorer.py tests/unit/test_e2e_manifest.py -k 'token or credential or private or redact or privacy or missing_top_ids or identifier or producer' -q` — **PASS**, 45 passed, 36 deselected.
- CHECK full safe repository suite with explicit hosted-model overrides — **PASS**, 1055 passed, 7 skipped.
- CHECK static validation: shell syntax, Ruff, Ruff format, compileall, Ty, credential-pattern scan, and `git diff --check` — **PASS**.
**Disposition**: A fresh Stage 6 run is required. Corpus graph metrics remain separate from the offline five-child E2E manifest; strict Plan 15 PASS-only scoring, terminal `(failed+cancelled)/total <= 0.10`, safe aggregate recall, exact snapshot/path/digest binding, and run-scoped evidence are enforced. Stage 6 remains **PENDING / NOT MEASURED**; Stage 4 remains **DONE**. No real corpus or E2E was rerun.
**Provenance**: The failed attempt remains diagnostic only. No raw contents, prompts, outputs, identifiers, credentials, or audit content were copied into this entry.

## 2026-09-05 -- Stage 6: harness checkpoint bookkeeping -- RECORDED / NOT MEASURED
**Did**: Recorded accepted evidence-harness corrections in commit `a2ac2174728c9a7a11a7a0c0dd6739829c307f61`. The prior run remains diagnostic only; no Stage 6 measurement was accepted, and a fresh full run is required.
**Disposition**: Stage 4 remains **DONE** at its existing stage commit `dc5fd15`. Stage 6 remains **PENDING / NOT MEASURED**; state bookkeeping does not certify corpus, recall, E2E, quality, or cutover results.

## 2026-09-05 -- Stage 6: fresh arm parser failure and repair -- RECORDED / NOT MEASURED
**Did**: Run `20260905T010813Z-stage6fresh` passed preflight, embeddings, and authentication checks and submitted 28/28 corpus episodes. Terminal job counts are **NOT MEASURED** because the embedded job-summary parser failed with a syntax error; no recall, post-snapshot, metrics, or E2E child ran. The pre-run snapshot was restored successfully. A separate vLLM check observed 3/3 HTTP 200 responses with no OOM or error evidence.
**Verification**: The parser repair was accepted in `6e33a6c0e3b8a33c30cbbeeff9198e3e0df36205`; its focused bake-off suite passed 25 tests and the hosted-override full repository suite passed 1056 tests with 7 skipped. No job count or quality result is inferred from this failed arm.
**Disposition**: Both the earlier attempt and this fresh arm remain diagnostic only. Stage 6 remains **PENDING / NOT MEASURED** and requires a fresh full run after the accepted parser repair.

## 2026-09-06 -- Stage 6: fresh arm batch-overflow and provenance failure -- CERTIFICATION INVALID / BLOCKED / NOT MEASURED
**Did**: Recorded run `20260905T014401Z-stage6fresh2` from a clean start/worktree at source HEAD
`f635d1f835c4f4d876b04dc6dccd7cf5fd9e38cc`. The run used `local:qwen3.8-flash-next` at the
redacted local endpoint `http://127.0.0.1:24000/v1`, low effort for ontology, extractor, librarian,
and domain-classifier roles, worker concurrency 2, and a 600-second timeout. All `E01`-`E28`
episodes were submitted. The 28 route jobs succeeded, all 28 primary extraction jobs succeeded,
and routed jobs 57-114 comprised 58 jobs covering all 28 episodes.
**Verification**:
- Last harness summary before cleanup: `todo=45`, `doing=2`, `succeeded=67`, `failed=0`,
  `cancelled=0`, `total=114`. This is non-terminal, so extraction successes are 39/86 (28 primary
  plus 11 routed), the completion gate is **RED**, and failure rate is **NOT MEASURED**. It must
  not be reported as 0%.
- No canonical metrics, recall result, post-run snapshot, E2E child results, parsing report, or
  quality decision was produced. These values are **NOT MEASURED**.
- Two independent read-only audits agree that the run cannot certify: repeated first-attempt
  librarian `UsageLimitExceeded` is attributable to PydanticAI checking a complete next tool-call
  batch against limit 150 (job66/E04 reached 149 tool completions), and failed attempts can
  mutate the graph before consolidation without rollback. Job66/E04 recorded 149 tool completions,
  83 model completions, 65 mutation-audit calls, and 5 validation rejections. Job67/E05 had the
  same error, but exact post-collision counts are **NOT MEASURED**. Job68/E05 succeeded on its
  first attempt with librarian elapsed 1538.6633 seconds and 41 observed actions; job67/E05 later
  succeeded on retry during graceful cleanup with librarian elapsed 589.4272 seconds and 24
  observed actions. Job66/E04 remained incomplete. The later
  retry therefore cannot certify graph cleanliness. The E04 retry extractor elapsed 1113.1499
  seconds; an outer OpenAI timeout retry can amplify a 600-second inactivity timeout.
- Correlation `job:{agent}:{episode}` collided for routed jobs. E05 per-job audit counts after
  `2026-09-06 14:51:10.699+02` are **NOT MEASURED**. This is a provenance defect, not a quality
  pass or a threshold amendment. vLLM remained healthy at concurrency 2; this is an operational
  report only.
**Restoration**: Graceful SIGINT invoked EXIT restoration. Snapshot
`backups/qwen-flash-next-pre-20260905T014401Z-stage6fresh2-20260905-034422.tar.gz` was preserved
with SHA-256 `0000c3ebf75511a6afdf81fdbc32ae0d710137eb74f7e70c116d8cd36c13f642`. The run queue of
114 disappeared; the database was restored to 14 jobs (maximum id 14); MCP and ingestion stopped;
PostgreSQL was healthy; the snapshot hash was unchanged; no canonical metrics file existed; and the
worktree was clean after restoration.
**Provenance**: Raw diagnostic logs remain at
`/tmp/neocortex-stage6-qwen-flash-next-20260905T014401Z-stage6fresh2.log` and
`log/agent_actions.log`. Raw/private fields are excluded from this record. The run is invalidated
under D35 and Stage 6b is the ordered next diagnosis. Backlog 12 is `IN_PROGRESS`; the separate
correlation/provenance defect is tracked in backlog 14. No accepted commit hash exists for Stage 6.
No Stage 6 threshold, corpus assumption, or quality criterion was weakened.
**Problems**: Stage 6 is **BLOCKED** by the non-terminal completion gate, the librarian batch
overflow with possible partial mutations, and the correlation collision. Stage 6b remains
**PENDING** and eligible because Stages 3 and 4 are `DONE`; it must diagnose the defects before
Stage 7 can issue any quality decision.

## 2026-09-06 -- Stage 6b: isolation and root-cause repairs -- DONE / ACCEPT
**Did**: Diagnosed the historical local Flash Next failure and applied the two bounded repairs authorized for Stage 6b. The historical run `20260905T014401Z-stage6fresh2` remains invalid because its queue was non-terminal, the librarian hit PydanticAI whole-batch tool-call accounting with possible pre-consolidation mutations, and routed extraction audit correlation values collided. Hosted behavior, thresholds, corpus assumptions, privacy rules, and low local effort were preserved.
**Failure diagnosis**:
- Deterministic PydanticAI 1.72.0 regression returned two tool calls in one response with `tool_calls_limit=1` and `request_limit=10`; one model request was made, zero tools executed, and `UsageLimitExceeded` was raised before tool execution. The request limit was not the cause.
- Fresh direct local probes used `local:qwen3.8-flash-next` at `http://127.0.0.1:24000/v1`, low effort, and a new `InMemoryRepository` for each fixed corpus episode. The isolation agent mix was `ontology`, `extractor`, and `librarian` only; it did not exercise `domain_classifier`. E04 succeeded and consolidated with 16 nodes and 13 edges: 52 pipeline tool-call starts/completions, 39 librarian-phase starts/completions, maximum one librarian tool start between model requests, and zero failure events. E05 succeeded and consolidated with 26 nodes and 28 edges: 74 pipeline tool-call starts/completions, 63 librarian-phase starts/completions, maximum one, and zero failure events.
**Repairs**:
- Local librarian calls set `parallel_tool_calls=false` only for local OpenAI-compatible models. A safe cardinality/progress event records aggregate counts and configured limits; failed librarian attempts remain failures and record `graph_cleanliness=NOT_MEASURED`.
- Every extraction enqueue creates a fresh opaque `extract-[0-9a-f]{32}` id. Direct task, direct pipeline, and admin retry boundaries replace absent or legacy values silently; valid ids remain byte-for-byte unchanged across retries. The metrics collector refuses canonical quality output after an unproven librarian failure that could have mutated the graph.
**Verification**:
- Coordinator pre-repair validation: focused extraction/privacy set **PASS**, 97 tests; hosted-overridden full suite **PASS**, 1065 passed and 7 skipped.
- Final Stage 6b validation: focused boundary/evidence set **PASS**, 94 tests; hosted-overridden full suite **PASS**, 1078 passed and 7 skipped. Ruff, ty, format checks, JSON parsing, privacy scan, and `git diff --check` passed.
**Provenance**: Source baseline was commit `53b20bab4517426d4b813048a6b881c278284db8`. Safe evidence is in `docs/plans/33-local-qwen-migration/resources/isolation-attribution.md` and `docs/plans/33-local-qwen-migration/resources/isolation-evidence-20260906.json`. Fixed corpus input path is `docs/plans/18.5-e2e-revalidation/resources/episodes.md`; historical diagnostic input is `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json`. Temporary aggregate probe streams are `/tmp/neocortex-stage6b-e04.stdout` (SHA-256 `b6c028b5dfde62c4688caa09ea0a0b170ca7a63fb097b2b29e37825161e9235a`), `/tmp/neocortex-stage6b-e04.stderr` (`2ce129968ddf6d8064b21ae706b3fbd2b770ab4e51942309165d80b26863acac`), `/tmp/neocortex-stage6b-e05.stdout` (`8d259500ba77426501bcea387a692b9f1eb358c91a51f2a7b387d4d1c291f7f4`), and `/tmp/neocortex-stage6b-e05.stderr` (`54d76a60341e4954cdd04576b0be489c22958a13c594c175668fdcbb55eab31b`). No raw source, prompts, model output, reasoning, identifiers, or secrets were copied into plan evidence.
**Disposition**: Stage 6b is `DONE` / `ACCEPT`. The prior Stage 6 run remains certification-invalid; no Stage 6 success or quality result is claimed. Backlog items 12 and 14 remain `IN_PROGRESS` until a fresh full arm measures terminal reliability, graph cleanliness after failed attempts, and collision-free run-scoped provenance.
**NOT MEASURED**: No hosted comparison, PostgreSQL isolation, queue retry amplification, full 28-episode Stage 6 arm, recall, post-run snapshot, E2E result, per-episode parsing report, or quality decision was produced. A fresh Stage 6 arm is pending and must pass its own terminal, integrity, provenance, and quality gates.

## 2026-09-06 -- Stage 6: selected arm endpoint preflight blocker -- BLOCKED / NOT MEASURED
**Did**: Preflighted selected run `20260906T155218Z-stage6-after6b` from clean committed source at the preserved plan HEAD. No harness PID was present, no jobs were submitted, and MCP/ingestion remained down. Local Docker forwarders listened and accepted local TCP, but authenticated `/v1/models` repeatedly returned HTTP 000 with 0 bytes after connecting locally.
**Verification**: Tailscale ping got no reply; SSH port 2023 timed out before a banner; forwarder logs showed outbound timeouts/SYN-SENT to the same remote peer. Independent read-only diagnosis attributed more than 95% of the blocker to Tailscale/remote-peer reachability, not NeoCortex or a proven vLLM failure.
**Disposition**: Backlog item 15 is the sole Stage 6 blocker. The selected run remains unstarted and is not invalidated by model behavior. Thresholds and corpus assumptions are unchanged. No Stage 6 gate or quality result was measured. Stage 6b stays `DONE`; Stages 7-9 remain `PENDING`. Resume only after the external owner restores the remote Tailscale/host/firewall path and bounded Tailscale ping, SSH banner, and authenticated exact-model `/v1/models` checks pass. No credentials, tokens, IP addresses, or raw logs were recorded.

## 2026-09-09 -- Compact corpus amendment -- IMPLEMENTED / LIVE RESULTS NOT MEASURED
**Request**: The user reports that the endpoint is reachable and that the previous corpus run took
over 16 hours. They request a smaller corpus. Backlog 15 is resolved on the user report; no fresh
endpoint or authentication measurement is claimed. Every actual arm still requires preflight.
**Did**: D38 selects eight unchanged original episodes E02,E04,E05,E10,E18,E20,E26,E27.
Both historical dense failure cases remain, together with the complete Metaphone decision/correction
chain and the team-role update chain. The full 28-episode corpus and its default loader behavior remain.
The explicit compact profile propagates through ingestion, metrics, and recall. Metrics name the
actual corpus path/hash/profile/IDs. Compact recall runs Q2,Q3,Q6,Q7,Q8,Q9, records omitted Q1,Q4,Q5,
and reports M3 out of 1 and M4 out of 3. Manifest validation rejects mixing full and compact recall.
The compact parsing schema requires the eight selected keys exactly once; the original schema is retained.
**Scope**: The five independent E2E children, their thresholds, all integrity/privacy/provenance gates,
and the actual 20-node/20-edge quality sample remain unchanged. Compact evidence cannot establish
28-episode endurance or be compared directly with prior full-profile metrics. Runtime benefit is
NOT MEASURED; episode count falls by 71%, but dense cases, routing, retries, and independent E2Es remain.
**Verification**: Focused corpus/harness/metrics/recall/manifest/probe regression suite: 129 passed.
Tests reject missing/duplicate/reordered inputs, compare compact contents against the original source,
check exact report-key coverage, and reject false recall denominators and mismatched profiles.
Ruff, Ty, shell syntax, and diff checks passed. Plan lint found no errors; existing long stage-note
warnings remain. An initial Ruff invocation incorrectly included the shell file; it was rerun against
Python files only, with `bash -n` for the shell. Independent review verified unchanged episode contents
and found one stale metrics filename in the report template; that reference is corrected.
**Disposition**: Stage 6 is PENDING with a fresh compact run ID required. The old unstarted full-profile
run is not resumed or relabelled. Stages 7–9 use compact evidence per D38. No services, ingestion, live
model calls, performance measurements, quality verdicts, or cutover were performed by this amendment.
**Resources**: `resources/compact-corpus-design.md`, `resources/compact-corpus.md`,
`resources/qwen-parsing-report-compact.schema.json`, and updated `resources/commands.md`.

**Additional validation**: The source loader measured 742 whitespace-separated words in the compact
corpus versus 2,759 in the original (73% less source text). This is not a runtime measurement.
The initial full-suite attempt failed on a pre-existing `extraction_enabled` boolean parsing error
from local settings; its result was 1021 passed, 7 skipped, 30 failed, and 49 errors. A safe diagnostic
reported only the invalid field name/type, without its value. The rerun sets
`NEOCORTEX_EXTRACTION_ENABLED=true` and explicit hosted reasoning-model overrides for tests only.
**Full-suite rerun**: PASS — 1100 passed, 7 skipped in 38.80 seconds with the explicit test overrides above. No test assertion was removed or weakened.

## 2026-09-09 -- Compact plan execution alignment and commit
**Did**: Aligned active Stage 4–9 instructions, Stage 6 naming, backlog next actions, and execution
commands with compact revision 1. Commands now set all four low efforts, extraction and domain routing,
concurrency 2, timeout 600, compact profile, and a fresh run ID explicitly. The preflight remains
bounded and reads the credential through stdin. Stage 8's dependency text now agrees with its required
DONE/no-op path. Recorded the existing accepted Stage 6b source commit `b6b0950` without claiming any
new live result. Historical full-profile evidence and the full loader default remain intact.
**Validation**: Implementation validation remains the preceding 1100-pass, 7-skip full suite; this
follow-up changes plan documentation/state only. Plan lint, diff checks, and commit hooks are run
before delivery. No model or ingestion run is started.

## 2026-09-09 — Compact benchmark execution resumed
User requests the local benchmark and an upgrade feasibility recommendation. Stage 6 resumes
with compact revision 1 and the existing integrity and quality thresholds. The plan protocol
and stage briefs remain the contract. Added durable review/repair ledger fields for this fresh
stage attempt; historical accepted stages are unchanged. Dedicated executor owns the live arm;
coordinator owns state and the subsequent independent evidence audit. No result is yet claimed.

### Live arm launch — 20260909T180657Z-compact
Authenticated exact-model preflight returned HTTP 200 in 0.082 seconds. User authorized
process-only GEMINI_API_KEY to GOOGLE_API_KEY alias; embedding health returned 768 dimensions
in 0.757 seconds. Full regression suite: 1100 passed, 7 skipped in 29.31 seconds.
Dedicated Luna executor returned no status or artifacts after repeated prompts; interrupted
and reassigned execution to coordinator to keep progress. No concurrent writer remains.
Harness PID and private log path are in validation/stage6-active-run.json. All four roles use
local Flash Next, low effort, concurrency 2, timeout 600, compact revision 1. Results pending.

### Compact arm progress checkpoint
Run 20260909T180657Z-compact remains IN_PROGRESS. The live admin queue reached
5 succeeded, 2 doing, 15 todo, 0 failed/cancelled (22 total after routing).
One dense librarian completed at 141 tool calls; no model/agent failure events recorded
at this checkpoint. Intermediate graph capture: 56 nodes, 64 edges. These are live
progress observations, not terminal quality certification. validation/capture_stage6.py
saves immutable sanitized captures and runs a separate one-second terminal watcher.
Snapshot-derived sample, recall, E2Es, complete integrity verdict and recommendation remain NOT MEASURED.

### Live classifier defect — E18
Focused read-only diagnosis confirms two completed classifier requests and two ValidationError
output rejections, followed by UnexpectedModelBehavior at 19:13:01Z. Router catches the error
and returns an empty list; routing job10 succeeds without shared extraction for E18 (DB episode5).
Thus zero failed queue jobs does not establish classifier success. The exact rejected field is
NOT MEASURED because detailed exception output is unavailable. Safe provenance and the affected
integrity criterion are in validation/stage6-classifier-diagnosis.json. The arm continues without
prompt, threshold, or configuration changes so the remaining evidence is comparable.

### Long-request observation — E27
At20:22:09Z, E27 extractor job15 had one request outstanding since19:55:08.870Z
(approximately27minutes), without a completion/error. E26 librarian continues progressing.
The configured600s timeout is transport operation/read inactivity, not pipeline wall time;
SDK default2 transport retries can extend duration, but actual retry occurrence and delay
cause are NOT MEASURED. Safe provenance: validation/stage6-long-request-diagnosis.json.
No configuration changes or additional live probes were made during the measured arm.

## 2026-09-10 — Qwen librarian harness repair saved with validation incomplete

The compact run `20260909T180657Z-compact` finished after about 7.7 hours. All 31
ingestion jobs succeeded, but recall was not measured and all five E2E checks failed.
The evidence review found that the librarian was the main cost: 23 runs made 1,837
model requests and 1,793 tool calls. Some trajectories repeated reads without reaching
a useful mutation or a final result.

The repair adds a Qwen-specific bounded workflow. It uses five batch tools, indexed
entity and relation state, duplicate detection, fixed budgets, host-bound database
identities, code-owned allowed decisions, recoverable item errors, and end-to-end
micro-batches of at most eight items. Hosted-model behavior is unchanged. The live
probe now uses PostgreSQL target schemas, the configured embedding service, private raw
output, immutable input caching, partial timeout counters, and exact graph checks.

Deterministic validation passes: 1,162 tests passed and 7 were skipped. In the last
complete A2-only probe, E04 and E05 both completed their primary and idempotence passes.
Every graph assertion category was zero, no unknown tool was called, and the one
representable E04 fixture fact was preserved. The primary passes still took about 558
and 653 seconds, so performance acceptance is not complete.

The full A0/A1/A2 comparison was stopped cleanly when the user requested session close.
Both A0 cases and both A1 cases had timed out. A2/E04 was active and healthy but had not
finished, and A2/E05 had not started. No probe process or temporary graph schema remains.
The material reduction gate and independent Stage 4 review are not measured. No new
compact benchmark was launched. On resume, finish the cached six-row comparison, run the
independent review, and launch the benchmark detached only if those gates pass.

## 2026-09-11, run started

- Run directory created by `init_run.sh`. Preset `unattended` (review-each-stage-before-and-after, two-fix-rounds-max, never-stop).
- Roles: orchestrator `codex/gpt-6-astra` (coordinator), implementer `codex/gpt-5.6-sol` effort `high` (strong), reviewer `codex/gpt-5.6-sol` effort `high` (strong), helper `codex/gpt-5.6-luna` effort `medium` (light).
- Stages: Authenticated local preflight and routing, Real-agent Flash Next probes, Iterative prompt and compatibility hardening, Harness, instrumentation, and auth stability, Optional hosted baseline comparison, Compact local stability and quality run, Isolation and root-cause diagnosis, Quality decision and evidence report, Thinking-effort tuning, Conditional cutover or ASD-STE100 report.
- Owner's reply to the settings message: "proceed".
- The reply accepted the announced defaults: Codex strong/light roles, preset `unattended`, groups `A=6` and `B=7,8,9`, the stated local/repository action scope, in-place run directory, and replacement of `PROTOCOL.md` with preservation as `PROTOCOL.previous.md`.
- Accepted lineage exists: `b6b0950` (last previously DONE control stage) and `219e56e` (latest Qwen compact-run evidence commit) both resolve as commits.
- Baseline attempt before the owner's local correction: `uv run pytest tests/ -q` gave 29 failed, 1173 passed, 7 skipped, and 49 errors because `.env` supplied the already-known invalid boolean `NEOCORTEX_EXTRACTION_ENABLED='true\\'`; no source regression was inferred.
- After the owner said "I removed the backslash", the same unoverridden command `uv run pytest tests/ -q` passed: 1251 passed, 7 skipped in 38.70 seconds. Input: the current repository and corrected local environment. Any repository test failure turns this gate red.

## 2026-09-11, Stage 6 compact local stability and quality run blocked

- Prior run: `.tmp/qwen-swift`; safe post-mortem is `briefs/postmortem-qwen-swift.md`. Canonical evidence commit: `219e56e`; run `20260911T001509Z-swift3` at source `653cbd6`.
- Pre-review (`codex/gpt-5.6-sol`, high): three blocking brief defects fixed; finding set and triage in `validation/stage6-pre-review.md`.
- Implementer (`codex/gpt-5.6-sol`, high) reconstructed `validation/stage6-repair-evidence.md`; no product code changed. Original F1–F6 triage is in `validation/stage6-review.md`.
- PASS: exact four local model ids; compact eight-item corpus; 30/30 terminal successes; 0% failure/stall; zero stored markers, invalid names, garbage types, agent/librarian failures, validation rejections, or unproven failed mutations; opaque correlations; matching metrics/recall/snapshot digests; restore.
- PASS checks: manifest validator; full suite 1251 passed/7 skipped; focused suite 83 passed; Ruff; diff check. Recall is measured. Final E2E is measured at 0/5; Plan 15 is 9 PASS/3 PARTIAL/2 FAIL and Plan 17 is 12 acceptable/1 partial/1 fail.
- Repair re-review (`codex/gpt-5.6-sol`, high): one P1 BLOCKING. Sixteen missing-endpoint skips lack safe per-event attribution, and five temporal conflicts lack run-3 proof that required correction edges survived. Overall integrity is `NOT MEASURED`.
- Disposition: Stage 6 `BLOCKED` on B16. The repair budget and re-review are spent. Stages 7–9 remain reachable through accepted Stage 6b and must issue `HOLD`; speed (2397 seconds, 68 requests, zero reasoning tokens) is REPORT evidence only.
- Backlog 12 and 14 are resolved by the replacement arm. No new live model run, external write, or commit was made in this disposition.

## 2026-09-11, owner ruling on execution efficiency

- Owner's instruction: "continue, but be aware, that your role, as a coordinator is to make sure that the whole process goes smoothly and efficiently. do spiral into rabbithole of running lenghty tests on xhigh that take hours, that was the case historically"
- Applied interpretation from context: do not repeat historical multi-hour `xhigh` experiments or continue a test after it cannot change the decision.
- Stage 7 already requires four `HOLD` verdicts, so Stage 8 will record the planned `DONE` no-op. This run will make no `xhigh` model call.
- Future effort work requires a short bounded probe before any larger arm and remains outside this execution unless a later Stage 7 result is `MIGRATE`.

## 2026-09-11, Stage 7 quality decision accepted

- Implementation commit: `27387b0`. Repair commits: `a6fdb85` and `c6391f4`.
- The report contains the exact eight compact episodes and 400 evidence records. Regeneration is byte-identical.
- Schema validation, source digests, privacy counts, and the exact four-agent verdict table pass.
- Focused checks: 70 passed. Full regression evidence: 1,283 passed and 7 skipped.
- The second repair changed only the Markdown verdict parser and tests. The full suite was not repeated after that narrow fix.
- The fixed 20-node and 20-edge quality sample is `NOT MEASURED` because no privacy-safe graph export exists.
- Final E2E remains 0/5. Sixteen missing-endpoint skips and five temporal conflicts lack safe event-level proof.
- Verdict: `HOLD` for ontology, extractor, librarian, and domain classifier. No model default changes.
- Review tiers: implementer and reviewer both used `codex/gpt-5.6-sol`, effort `high`.

## 2026-09-11, Stage 8 effort tuning completed as a no-op

- D20 applies because Stage 7 has zero `MIGRATE` verdicts.
- The bounded check found the exact four agents with `HOLD` and both Stage 7 state gates at `PASS`.
- `validation/stage8-no-op.json` records `DONE_NO_OP`, migration count zero, and both tuning actions as `NOT_RUN`.
- No effort sweep, tuned arm, Qwen call, benchmark, or new tuning artifact ran.
- Stage 8 is `DONE` with `commit: null`. The strong pre-review and post-review are complete.

## 2026-09-11, owner stopped execution before Stage 9

- Owner instruction: "do not execute this stage, commit current state, we'll need to fix this later"
- Stage 9 remains `PENDING`. No cutover, documentation update, local smoke, or model call ran.
- The run remains `IN_PROGRESS` at Stage 9. Resume from the Stage 9 brief step after the underlying quality and integrity faults are fixed.
