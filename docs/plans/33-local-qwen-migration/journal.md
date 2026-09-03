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
