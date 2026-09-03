# Stage 1: Authenticated Local Preflight and Routing

**Goal**: Prove that NeoCortex can address the exact local service through its per-agent provider path without changing the hosted path.
**Dependencies**: None.

## Steps

1. Inspect `neocortex.model_factory.build_model`, `LocalEndpoint.from_settings`, and the five agent
   construction sites. Keep `local:` routing per agent. The active string is
   `local:qwen3.8-flash-next`; the endpoint default remains unset so other environments fail clearly.
2. Validate settings in `neocortex.mcp_settings.MCPSettings`: base URL,
   `local_model_api_key_env=VLLM_API_KEY`, sampling settings, and timeout are read from environment
   variables. Never add a key value to source, fixtures, logs, or this plan.
3. Run a preflight with the key supplied only by the environment. Parse the authenticated
   `GET http://127.0.0.1:24000/v1/models` response and require exactly `qwen3.8-flash-next`. Then
   send one small authenticated chat-completion request and one PydanticAI structured-output request.
   A 401, 404, 5xx, malformed JSON, or unexpected model id is a diagnostic failure, not a model pass.
4. Repair only routing/config defects found by the preflight. Delegate each focused light fix to a
   dedicated GPT-5.6-Luna xhigh subagent when available. Preserve the hosted `openai-responses:` path.
5. Add or update unit tests for local/hosted selection, missing-base-URL failure, environment-only
   authentication, explicit effort, and simultaneous mixed providers. Run formatting and type checks.

## Verification

- [ ] GATE `uv run pytest tests/test_local_provider_routing.py tests/ -q` — every test passes; a broken provider selection, missing setting, or changed assertion makes this red.
- [ ] GATE authenticated `/v1/models` response — read from the live JSON response using `$VLLM_API_KEY`; a wrong id, missing auth, or endpoint failure makes this red.
- [ ] REPORT structured-output smoke — record model id, HTTP status, completion validity, and elapsed time in `journal.md`; do not record the key.

## Commit

`feat(models): validate local Flash Next provider routing`
