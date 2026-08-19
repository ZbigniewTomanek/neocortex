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
    """Build the LLM model from inference config."""
    if config.use_test_model:
        logger.debug("Using TestModel for extraction agents")
        return TestModel()
    logger.debug("Using model={}", config.model_name)
    return config.model_name
```

It returns a bare string and lets pydantic-ai infer the provider. This stage adds an explicit
construction path for local models while leaving the string path untouched for hosted ones.

Two facts that shape where the code goes: `_build_model` is called only by the three extraction agent
builders (`agents.py:83`, `:299`, `:420`), and `domains/classifier.py` / `domains/seed_generator.py`
construct `Agent(self._model, …)` inline on **every call** without touching it. So the factory has to
live outside `extraction/` — see step 2.

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

2. **Create the shared model factory — a new module, not a helper in `agents.py`.**
   - File: `src/neocortex/model_factory.py` (**new**)
   - Details: five call sites need this — the three extraction agent builders plus
     `domains/classifier.py` and `domains/seed_generator.py`. The latter two have no
     `AgentInferenceConfig` and import nothing from `neocortex.extraction`, so a private
     `_build_model(config)` in `agents.py` cannot serve them without either a cross-package
     private import or a fake config object. Put the logic where all five can reach it:
     ```python
     LOCAL_PREFIX = "local:"

     @dataclass(frozen=True)
     class LocalEndpoint:
         """Resolved local-endpoint config. Built once from MCPSettings."""
         base_url: str | None
         api_key_env: str
         temperature: float
         top_p: float
         temperature_nothink: float
         top_p_nothink: float
         timeout_s: float

         @classmethod
         def from_settings(cls, settings) -> LocalEndpoint: ...

     def is_local_model(model_name: str) -> bool:
         return model_name.startswith(LOCAL_PREFIX)

     def build_model(model_name: str, endpoint: LocalEndpoint | None) -> str | Model: ...
     def build_model_settings(
         thinking_effort: ThinkingLevel | None,
         model_name: str,
         endpoint: LocalEndpoint | None,
     ) -> ModelSettings | None: ...
     ```
     `local:qwen3.8-27b` means "the model named `qwen3.8-27b` at `local_model_base_url`". Routing
     stays purely in the existing `*_model` settings — no new per-agent fields, and no global env
     var that would leak across agents.

3. **`build_model` — explicit model object for local strings, unchanged string for hosted.**
   - File: `src/neocortex/model_factory.py`
   - Details: follow the bot's proven factory
     (`~/projects/my-telegram-bot/telegram_bot/ai_assistant/pydantic_ai_model_factory.py`):
     ```python
     from pydantic_ai.models.openai import OpenAIChatModel
     from pydantic_ai.providers.openai import OpenAIProvider

     def build_model(model_name, endpoint):
         if not is_local_model(model_name):
             return model_name  # hosted path unchanged — pydantic-ai infers the provider
         if endpoint is None or not endpoint.base_url:
             raise ValueError(
                 f"{model_name!r} requires NEOCORTEX_LOCAL_MODEL_BASE_URL to be set"
             )
         return OpenAIChatModel(
             model_name.removeprefix(LOCAL_PREFIX),
             provider=OpenAIProvider(
                 base_url=endpoint.base_url,
                 api_key=os.environ.get(endpoint.api_key_env, ""),
             ),
         )
     ```
   - Then make `extraction/agents.py:50-56` `_build_model()` a thin delegate that keeps its
     `use_test_model` branch and its two `logger.debug` calls, and add a `local_endpoint` field to
     `AgentInferenceConfig` (it already carries `model_name` and `thinking_effort` and is built from
     settings in `jobs/tasks.py:76-87`) rather than importing settings into `agents.py`.
   - `AgentInferenceConfig` is also constructed in `extraction/pipeline.py:81-83` and in eight test
     files, so give `local_endpoint` a `None` default — a required field would break all of them.

4. **`build_model_settings` — one settings type for both paths (D6, revised).**
   - File: `src/neocortex/model_factory.py`; consumed by
     `AgentInferenceConfig.model_settings` at `extraction/agents.py:42-47`
   - Details: the original plan branched to `OpenAIChatModelSettings(openai_reasoning_effort=…)` for
     local models. **Do not.** `OPENAI_REASONING_EFFORT_MAP` in the installed pydantic-ai 1.72.0 is an
     identity map for every string level, and `OpenAIChatModel._get_reasoning_effort` falls back to it
     when `openai_reasoning_effort` is unset — so both spellings put the same string on the wire, and
     base `ModelSettings` already carries `temperature` / `top_p` / `timeout`. One path:
     ```python
     def build_model_settings(thinking_effort, model_name, endpoint):
         if thinking_effort is None:
             return None                      # preserve today's behaviour exactly
         if not is_local_model(model_name):
             return ModelSettings(thinking=thinking_effort)   # hosted unchanged
         thinking_on = thinking_effort is not False
         return ModelSettings(
             thinking=thinking_effort,
             temperature=endpoint.temperature if thinking_on else endpoint.temperature_nothink,
             top_p=endpoint.top_p if thinking_on else endpoint.top_p_nothink,
             timeout=endpoint.timeout_s,
         )
     ```
     Note the existing property returns `None` when `thinking_effort is None` — **keep that branch**;
     the plan previously described it as unconditional. `ThinkingLevel` is
     `bool | Literal['minimal','low','medium','high','xhigh']`, so `xhigh` is representable and
     `"none"` is not — do not test for the string `"none"`. The stock Qwen3.8 template allowlist is
     `{low, medium, xhigh}` and unrecognised values clamp silently rather than raise; Stage 8 measures
     what `high` actually does, this stage only makes the value transmittable.

5. **Apply the same routing to the classifier and seed generator.**
   - Files: `src/neocortex/domains/classifier.py` (`__init__` at `:44-48`, `Agent` built in
     `classify()` at `:79-83`), `src/neocortex/domains/seed_generator.py` (`:29` default, `Agent`
     built in `_generate_seed()` at `:119-127`)
   - Details: both build a fresh `Agent` on **every call**, and neither goes through
     `_build_model`. Have each accept a `LocalEndpoint | None` in `__init__`, store it, and call
     `model_factory.build_model(...)` / `build_model_settings(...)` at the point where they construct
     the `Agent`. This is the change D4's "librarian local, ontology hosted" outcome depends on — a
     fix scoped to `_build_model` alone would leave both of these on the hosted path forever.
   - Give the seed generator its own `seed_generator_thinking_effort` setting: it passes **no**
     `model_settings` at all today, so on a local model it would inherit the template's `xhigh`
     default (a measured 77-second path). Note it also has no model setting of its own —
     `services.py:69-72` and `:154-157` both pass `settings.domain_classifier_model`.

6. **Wire the new settings through.**
   - Files: `src/neocortex/services.py:69-72,130-133,154-157`, `src/neocortex/jobs/tasks.py:76-87`
   - Details: build one `LocalEndpoint.from_settings(settings)` per process and pass it into all three
     `AgentInferenceConfig` constructions in `tasks.py`, the `AgentDomainClassifier` construction at
     `services.py:130-133`, and both `SeedGenerator` constructions at `:69-72` and `:154-157`.

7. **Update hardcoded defaults so they cannot silently reintroduce the Responses API.**
   - Files: `src/neocortex/extraction/agents.py:30-31`, `domains/classifier.py:44`, `domains/seed_generator.py:29`
   - Details: leave the values at `openai-responses:gpt-5.4-mini` for now (Stage 9 flips them), but
     add a module-level comment pointing at this plan so the next reader knows the local path exists.

8. **Add tests.**
   - File: `tests/test_local_provider_routing.py` (new)
   - Details: assert that (a) a `local:` string builds an `OpenAIChatModel` whose provider base_url
     matches the setting, (b) a non-`local:` string is returned unchanged as a string, (c) a `local:`
     string with no `local_model_base_url` raises with a message naming
     `NEOCORTEX_LOCAL_MODEL_BASE_URL`, (d) `build_model_settings` returns `None` for
     `thinking_effort=None`, a bare `ModelSettings(thinking=…)` for hosted, and one carrying
     `temperature`/`top_p`/`timeout` for local, (e) `xhigh` round-trips through the settings field and
     the factory without validation error, (f) two agents can be configured with *different* providers
     simultaneously — this is the D4 requirement and the one that would regress silently, and
     (g) the classifier and seed generator honour a `local:` string, since they bypass `_build_model`.
     Use `MCPSettings(...)` construction directly; no network calls in unit tests.

---

## Verification

- [ ] `uv run pytest tests/ -v` — all tests pass (**916** collected as of 2026-08-19).
- [ ] `uv run pytest tests/test_local_provider_routing.py -v` — new tests pass, including the
      mixed-provider case.
- [ ] Live smoke against the real endpoint (requires `VLLM_API_KEY` and z-spark reachable):
      ```bash
      export VLLM_API_KEY=$(grep -E '^VLLM_API_KEY=' ~/projects/my-telegram-bot/.env | cut -d= -f2-)
      export NEOCORTEX_LOCAL_MODEL_BASE_URL=http://z-spark.tail215ba1.ts.net:4000/v1
      uv run python -c "
      import asyncio
      from neocortex.mcp_settings import MCPSettings
      from neocortex.model_factory import LocalEndpoint, build_model, build_model_settings
      from pydantic_ai import Agent
      ep = LocalEndpoint.from_settings(MCPSettings())
      name = 'local:qwen3.8-27b'
      a = Agent(build_model(name, ep), system_prompt='Reply with exactly: OK')
      ms = build_model_settings('medium', name, ep)
      print(asyncio.run(a.run('ping', model_settings=ms)).output)
      "
      ```
      Expected: `OK`. A 401 means the key did not resolve. A pydantic-ai `UserError` about an unknown
      model or provider means a raw `local:` string reached the string path instead of the factory.
- [ ] `grep -rnc "openai-responses:" src/neocortex/ | ...` — the repo-wide count is **7**, unchanged by
      this stage (`mcp_settings.py:125,127,129,142`, `domains/classifier.py:44`,
      `domains/seed_generator.py:29`, `extraction/agents.py:30`). Stage 9 flips them.
- [ ] Confirm no key material entered the repo: `git diff --staged | grep -iE "sk-|api[_-]?key\s*=\s*['\"]"` returns nothing.

---

## Commit

`feat(models): add per-agent local OpenAI-compatible endpoint routing`
