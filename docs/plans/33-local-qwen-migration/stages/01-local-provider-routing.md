# Stage 1: Local Provider Routing

**Goal**: Make any single agent addressable at an OpenAI-compatible endpoint via config alone, so a local model can be piloted per-agent without disturbing the agents still on the hosted model.
**Dependencies**: None.

---

## Why this is a code change and not just env vars

pydantic-ai's OpenAI provider reads `OPENAI_BASE_URL` from the environment, so a *global* swap
needs no code. But **D4 requires a partial pass to ship** — "librarian local, ontology hosted" is
a supported outcome of this plan, and a single global env var cannot express it. `_build_model()`
in `src/neocortex/extraction/agents.py:50-56` is currently:

```python
def _build_model(config: AgentInferenceConfig) -> str | TestModel:
    if config.use_test_model:
        return TestModel()
    return config.model_name
```

It returns a bare string and lets pydantic-ai infer the provider. This stage adds an explicit
construction path for local models while leaving the string path untouched for hosted ones.

---

## Steps

1. **Add local-endpoint settings.**
   - File: `src/neocortex/mcp_settings.py` (near the per-agent block at `:123-143`)
   - Details: add
     ```python
     # Local OpenAI-compatible endpoint (LiteLLM / vLLM / SGLang / Ollama).
     # Any *_model value prefixed "local:" is routed here instead of to a hosted provider.
     local_model_base_url: str | None = None      # e.g. http://z-spark.tail215ba1.ts.net:4000/v1
     local_model_api_key_env: str = "VLLM_API_KEY"  # name of the env var holding the key
     local_model_temperature: float = 0.6          # thinking-on default (bot-measured)
     local_model_top_p: float = 0.95               # thinking-on default (bot-measured)
     local_model_temperature_nothink: float = 0.3  # thinking-off default
     local_model_top_p_nothink: float = 0.9        # thinking-off default
     local_model_timeout_s: float = 600.0          # no LLM timeout exists today; 4 stalls exhaust the worker pool
     ```
     Read the key with `os.environ.get(local_model_api_key_env)`. **Never** put the key itself in
     settings or `.env.example`.

2. **Introduce the `local:` model-string prefix.**
   - File: `src/neocortex/extraction/agents.py`
   - Details: add a helper next to `_build_model`:
     ```python
     LOCAL_PREFIX = "local:"

     def is_local_model(model_name: str) -> bool:
         return model_name.startswith(LOCAL_PREFIX)
     ```
     `local:qwen3.8-27b` means "the model named `qwen3.8-27b` at `local_model_base_url`".
     This keeps per-agent routing purely in the existing `*_model` settings — no new
     per-agent fields, and no global env var that would leak across agents.

3. **Build an explicit model object for local strings.**
   - File: `src/neocortex/extraction/agents.py`, `_build_model()` at `:50-56`
   - Details: follow the bot's proven factory
     (`~/projects/my-telegram-bot/telegram_bot/ai_assistant/pydantic_ai_model_factory.py`):
     ```python
     from pydantic_ai.models.openai import OpenAIChatModel
     from pydantic_ai.providers.openai import OpenAIProvider

     if is_local_model(config.model_name):
         if not settings.local_model_base_url:
             raise ValueError("local: model requires NEOCORTEX_LOCAL_MODEL_BASE_URL")
         return OpenAIChatModel(
             config.model_name.removeprefix(LOCAL_PREFIX),
             provider=OpenAIProvider(
                 base_url=settings.local_model_base_url,
                 api_key=os.environ.get(settings.local_model_api_key_env, ""),
             ),
         )
     return config.model_name  # hosted path unchanged
     ```
     `_build_model` currently takes only `config`; thread the needed endpoint values onto
     `AgentInferenceConfig` (preferred — it already carries `model_name` and `thinking_effort`
     and is constructed from settings in `jobs/tasks.py:78-86`) rather than importing settings
     into `agents.py`.

4. **Use the precise reasoning knob for local models (D6).**
   - File: `src/neocortex/extraction/agents.py`, `AgentInferenceConfig.model_settings` at `:42-47`
   - Details: currently returns `ModelSettings(thinking=self.thinking_effort)` unconditionally.
     For local models return instead:
     ```python
     from pydantic_ai.models.openai import OpenAIChatModelSettings

     thinking_on = self.thinking_effort not in (None, False, "none")
     return OpenAIChatModelSettings(
         openai_reasoning_effort=self.thinking_effort,
         temperature=... if thinking_on else ...,   # from the settings added in step 1
         top_p=...     if thinking_on else ...,
         timeout=...,
     )
     ```
     Hosted models keep `ModelSettings(thinking=…)` exactly as today. Note the stock Qwen3.8
     template allowlist is `{low, medium, xhigh}` and unrecognised values clamp silently rather
     than raise — Stage 8 measures what `high` actually does; this stage only makes the value
     transmittable.

5. **Apply the same routing to the classifier and seed generator.**
   - Files: `src/neocortex/domains/classifier.py:44-48`, `src/neocortex/domains/seed_generator.py:29`
   - Details: both construct a fresh `Agent` on **every call** (inside `classify()` and
     `_generate_seed()`). Reuse the same `_build_model` helper rather than duplicating the
     provider construction. Give the seed generator its own `seed_generator_thinking_effort`
     setting — today it passes no `model_settings` at all, so on a local model it would inherit
     the template's `xhigh` default (a measured 77-second path).

6. **Wire the new settings through.**
   - Files: `src/neocortex/services.py:69-72,130-133,154-157`, `src/neocortex/jobs/tasks.py:78-86`
   - Details: pass the endpoint config into every `AgentInferenceConfig` and classifier construction.

7. **Update hardcoded defaults so they cannot silently reintroduce the Responses API.**
   - Files: `src/neocortex/extraction/agents.py:30-31`, `domains/classifier.py:44`, `domains/seed_generator.py:29`
   - Details: leave the values at `openai-responses:gpt-5.4-mini` for now (Stage 9 flips them), but
     add a module-level comment pointing at this plan so the next reader knows the local path exists.

8. **Add tests.**
   - File: `tests/test_local_provider_routing.py` (new)
   - Details: assert that (a) a `local:` string builds an `OpenAIChatModel` whose provider base_url
     matches the setting, (b) a non-`local:` string is returned unchanged as a string, (c) a `local:`
     string with no `local_model_base_url` raises, (d) `model_settings` returns
     `OpenAIChatModelSettings` with the right `openai_reasoning_effort`/temperature for local and
     plain `ModelSettings` for hosted, (e) two agents can be configured with *different* providers
     simultaneously — this is the D4 requirement and is the one that would regress silently.
     Use `MCPSettings(...)` construction directly; no network calls in unit tests.

---

## Verification

- [ ] `uv run pytest tests/ -v` — all tests pass (Plan 29 recorded 832; count may have grown).
- [ ] `uv run pytest tests/test_local_provider_routing.py -v` — new tests pass, including the
      mixed-provider case.
- [ ] Live smoke against the real endpoint (requires `VLLM_API_KEY` and z-spark reachable):
      ```bash
      export VLLM_API_KEY=$(grep -E '^VLLM_API_KEY=' ~/projects/my-telegram-bot/.env | cut -d= -f2-)
      export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://z-spark.tail215ba1.ts.net:4000/v1
      uv run python -c "
      import asyncio, os
      from neocortex.extraction.agents import AgentInferenceConfig, _build_model
      from pydantic_ai import Agent
      cfg = AgentInferenceConfig(model_name='local:qwen3.8-27b', thinking_effort='medium')
      a = Agent(_build_model(cfg), system_prompt='Reply with exactly: OK')
      print(asyncio.run(a.run('ping', model_settings=cfg.model_settings)).output)
      "
      ```
      Expected: `OK`. A 401 means the key did not resolve; a 404 on `/responses` means a
      `local:` string leaked into the hosted path.
- [ ] `grep -rn "openai-responses:" src/neocortex/` — still 5 hits (unchanged; Stage 9 flips them).
- [ ] Confirm no key material entered the repo: `git diff --staged | grep -iE "sk-|api[_-]?key\s*=\s*['\"]"` returns nothing.

---

## Commit

`feat(models): add per-agent local OpenAI-compatible endpoint routing`
