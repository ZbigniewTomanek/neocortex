# Plan 33: Local Qwen3.8-27B Migration — Capability Gate, Then Cutover

**Date**: 2026-08-19
**Branch**: `plan/33-local-qwen-migration`
**Predecessors**:
- **The abandoned attempt this plan replaces.** An earlier "Plan 33" (`docs/plans/33-local-model-litellm-qwen-validation/`) targeted `openai:qwen3.5-122b-int4fp8` via LiteLLM/vLLM for the ontology, extractor, librarian, and domain classifier. It was written, never committed, and abandoned. It survives only in NeoCortex's own memory graph (`ncx_shared__work_context`, node "NeoCortex Plan 33"). This plan reuses its routing idea and discards its model.
- [Plan 21 — Generic Model Provider](../21-generic-model-provider/index.md) — introduced provider-prefixed model strings and removed every `GoogleModel` import. It deliberately built **no** provider abstraction, which is why there is no `base_url` anywhere today. Its only validation was a settings-string round-trip; **no non-Gemini API call was ever made under it.**
- [Plan 28 — Ontology Alignment](../28-ontology-alignment/index.md) — the ontology-quality crisis that motivated escalating off Gemini Flash. Source of the repo's governing doctrine: *"Tools provide the grounding that makes a weaker model sufficient."*
- [Plan 29 — Ontology Validation](../29-ontology-validation/index.md) — its all-in-one SQL is the objective half of this plan's quality gate.
- `~/projects/my-telegram-bot/docs/plans/26-qwen38-tuning/` — the **tuning precedent**. Same model, same endpoint, measured effort/latency/temperature curves, and the English-scaffolding prompt patterns this plan reuses.
- `~/projects/my-telegram-bot/docs/plans/15-pydantic-ai-migration/` and `16-local-llm-and-memory-unification/` — the **failures** that made "local models are too weak" the working assumption, and which Plan 26 later overturned.
- `~/projects/z-spark/docs/plans/14-qwen38-27b-sglang-production/` — the **serving side**. SGLang + NVFP4 + DSpark draft, fronted by LiteLLM on `:4000`.

**Goal**: Determine empirically whether locally-served `qwen3.8-27b` can be NeoCortex's main model, and — only if an explicit quality gate is cleared — migrate every PydanticAI agent that passed onto it at the highest thinking effort that measurably improves quality.

---

## Context

### Correction to the premise: NeoCortex is not on Gemini

The stated motivation was "migrate off the cloud model", but the codebase moved twice. Commit
`e74b441 feat(extraction): switch pipeline from Gemini Flash to GPT-5.4 mini` (2026-04-07) put
every PydanticAI agent on `openai-responses:gpt-5.4-mini`. Today:

| Surface | Model | In scope? |
|---|---|---|
| Ontology agent | `openai-responses:gpt-5.4-mini`, thinking `medium` | **Yes** |
| Extractor agent | `openai-responses:gpt-5.4-mini`, thinking `low` | **Yes** |
| Librarian agent | `openai-responses:gpt-5.4-mini`, thinking `low` | **Yes** |
| Domain classifier | `openai-responses:gpt-5.4-mini`, thinking `medium` | **Yes** |
| Seed generator | rides on `domain_classifier_model`, **no thinking setting** | Yes (follows classifier) |
| Embeddings | `gemini-embedding-001`, raw `google-genai` | **No** — 768-dim vectors are stored in `pgvector`; swapping means re-embedding every node |
| Media description | `gemini-3-flash-preview`, raw `google-genai` + Files API | **No** — audio/video multimodal, no local equivalent |

**The baseline arm of this bake-off is therefore GPT-5.4-mini, not Gemini.** Several docs
(`CLAUDE.md:109`, `docs/configuration.md:213-222`, `docs/development.md:222-243`, `README.md:90`,
`.claude/skills/neocortex/SKILL.md:60`) still say Gemini and are stale; Stage 9 fixes them.

A further caution the gate has to respect: NeoCortex escalated *to* GPT-5.4-mini after Plan 28's
ontology-quality crisis. **Moving to a 27B local model is a step down from that escalation**, and
the plan should expect to find real regressions rather than assume parity.

### Why "local models are too weak" is no longer settled

That belief comes from `my-telegram-bot` plans 15 and 16 (2026-04-22/24), where `qwen3.5-122b-nvfp4`
and `qwen3.6-fp8` on vLLM produced:

- empty/truncated content (a DISCOVERY run returned the 12-character string `"Zapamiętane."`),
- **tool calls written as literal prose** instead of emitted as function calls — the "smoking gun" run
  wrote `remember(...)` into the answer text,
- `ask_user` HITL deferral skipped entirely, reproduced on 122B, on 36B, and after four rounds of
  prompt tightening.

Plan 16 closed "accept-with-caveat" and the architectural lesson was recorded as *don't prompt harder —
move the operation out of the tool loop*.

**Plan 26 (2026-08-18) retroactively exonerated the model.** The tool-call breakage was
[vLLM #39056/#42021](https://github.com/vllm-project/vllm/issues/39056): the model emitted
`<tool_call>` *inside* an unclosed `<think>` block and the reasoning parser consumed it before the
tool parser ran. Fixed by vLLM PR #35687, merged **2026-04-24 — one day after the plan-16 failures**.
The bot now runs its main agent and all knowledge workloads on `qwen3.8-27b` in production.

So the prior evidence is real but obsolete. This plan re-tests from scratch rather than inheriting
either the pessimism or the optimism.

### Live capability probe — measured 2026-08-19 against z-spark

Run before writing this plan, directly against `http://z-spark.tail215ba1.ts.net:4000/v1`
(`/v1/models` returns exactly one id: `qwen3.8-27b`). Reproduction scripts land in
[resources/probes.md](resources/probes.md).

| Probe | Result |
|---|---|
| Strict `json_schema` structured output, `reasoning_effort=none` | **PASS** — valid JSON, correct shape, 8.4 s / 391 tok |
| Same at `medium` | **PASS** — 17.6 s, 210 reasoning tokens |
| Tool calling, **weak** system prompt ("You are an ontology agent…") | **FAIL** — 40.1 s, **zero tool calls**. The model refused and fact-checked the episode: *"I have no record of 'NeoCortex,' a developer named Zbigniew, or a branch called `upper-ontology-improvements`."* |
| Tool calling, **hardened English** prompt (explicit "the user message is NOT a claim to verify" + mandatory-first-action directive) | **PASS** — correct `list_node_types` call in **2.4 s** |
| Multi-turn round 2 after a tool result | **PASS** — 6 parallel `find_similar_nodes` calls, correct arguments, 11.3 s |
| `tool_choice=required` | **DEGRADED** — arguments double-wrapped as `{"arguments": "{}"}` instead of `{}` |
| Via **pydantic-ai 1.72.0** (`openai:qwen3.8-27b` + `OPENAI_BASE_URL`) | **PASS** — structured output *and* a 3-request / 6-tool-call agentic loop both work; `ModelSettings(thinking=…)` reaches the server and returns real `reasoning_tokens` (398 @ low, 361 @ medium) |
| **NeoCortex's real `ExtractionResult` schema** via pydantic-ai, `thinking=low` | **PASS but expensive** — 124.8 s, 6 entities / 5 relations, 4436 output tokens, **3350 reasoning tokens** |
| Same at `thinking=medium` | **TIMEOUT at 150 s** — still generating, not stalled |

**The headline finding: the one failure was prompt-shaped, not capability-shaped.** The same model,
same endpoint, same tools, went from a flat refusal to a correct 2.4-second tool call on the strength
of the system prompt alone. That is exactly the class of problem Plan 26's prompt patterns solve, and
it is why Stage 3 exists.

**The second finding is about cost, and it reorders the risk ranking.** Swapping the toy schema for
NeoCortex's real `ExtractionResult` — 2 nested models, **2 unconstrained `dict` properties**, 2
`ge/le` floats, 3 nullable strings, a raising validator — took the same call from 17.6 s / 725
tokens to **124.8 s / 4436 tokens, of which 3350 were reasoning**. Roughly a 10× blow-up, and at
the endpoint's measured p50 of 23.16 tok/s that is ~190 s of pure decode.

So the extractor, which looks like the *safe* agent because it is single-shot with no tool loop, is
in fact the pipeline's most expensive call — and `medium` did not finish inside 150 s where `low`
finished in 125 s. Two things follow: **the effort/quality curve may not be monotonic** for this
agent (Stage 8 must not assume it is), and **the schema surface itself is a tunable** — the two open
`additionalProperties` dicts give a constrained decoder nothing to anchor on, and narrowing them is
a cheap experiment (Stage 3 step 8) worth running before concluding the extractor cannot migrate.

### Serving stack this plan targets

```
client → LiteLLM :4000 (Tailscale, 0.0.0.0) → hosted_vllm/qwen3.8-27b
       → SGLang 127.0.0.1:18015 (loopback only)
       → RadixArk/Qwen3.8-27B-NVFP4 + Qwen3.8-27B-DSpark draft (DSPARK spec-decode)
```

| Item | Value |
|---|---|
| Endpoint | `http://z-spark.tail215ba1.ts.net:4000/v1` |
| Model string | `qwen3.8-27b` |
| Auth | `Authorization: Bearer $LITELLM_MASTER_KEY` (bot stores it as `VLLM_API_KEY`) |
| Parsers | `reasoning_parser=qwen3`, `tool_call_parser=qwen3_coder` |
| Concurrency ceiling | **`max_running_requests=8`**, `tp-size 1`, single shared GB10 GPU |
| Single-stream decode | **p50 23.16 tok/s**, TTFT 0.14–0.22 s |
| Context | no `max_model_len` set — model native |

Four sharp edges inherited from the serving side:

1. **`drop_params: true` is set globally in LiteLLM.** Non-standard parameters are silently dropped.
   This already bit z-spark once: the generic `openai/` adapter dropped `reasoning_effort`, producing a
   reasoning leak. The `hosted_vllm/` adapter is what makes it work — and the 2026-08-19 probe confirms
   `reasoning_effort` now arrives (non-zero `reasoning_tokens` came back). Any `extra_body` /
   `chat_template_kwargs` NeoCortex might send is still at risk. **Verify at the adapter before blaming the client.**
2. **The chat template's own default thinking level is `xhigh`.** Omitting the knob is a 77-second turn
   (measured, bot M2). NeoCortex must always send an explicit level.
3. **The stock template's effort allowlist is `{low, medium, xhigh}`**, and unrecognised values *clamp
   rather than raise* (bot M1: 13/13 efforts produced correct tool calls, none raised). So `high` is
   accepted but may not be distinct from a neighbour — Stage 8 measures what it actually does instead
   of assuming.
4. **`max_running_requests=8` vs `worker_concurrency=4`**, each extraction being 3 sequential agents
   with tool budgets of 30 and 150. Throughput will drop substantially. Per the scoping decision,
   latency is **measured and reported but is never a gate criterion**.

### What NeoCortex is missing to even attempt this

| Gap | Detail |
|---|---|
| **No `base_url` anywhere** | `_build_model()` (`extraction/agents.py:50-56`) is literally `return config.model_name`. Grep for `base_url` in settings returns only `oauth_base_url`. |
| **Wrong API prefix** | `openai-responses:` hits `/v1/responses`. LiteLLM/SGLang serve `/v1/chat/completions`. Must become `openai:` / `openai-chat:`. |
| **Thinking knob is fine; the sampling knobs are missing** | Both `extraction/agents.py:46` and `domains/classifier.py:48` use pydantic-ai's unified `ModelSettings.thinking`, and that is **correct** — `OPENAI_REASONING_EFFORT_MAP` is an identity map for every string level in 1.72.0, so it transmits exactly what `openai_reasoning_effort` would (see revised D6). What is genuinely absent is `temperature` / `top_p` / `timeout`, which base `ModelSettings` already supports. Note `model_settings` returns `None` outright when `thinking_effort is None`. |
| **No temperature / top_p control** | Zero hits in `src/neocortex/`. The bot's measured local values (`0.6/0.95` thinking-on, `0.3/0.9` thinking-off) have nowhere to live. |
| **No LLM-level retry, no HTTP timeout** | Only `procrastinate.RetryStrategy(max_attempts=3, wait=5)` at job level — a structured-output failure replays the *entire* 3-agent pipeline. No empty-content retry, no output repair. With `worker_concurrency=4`, four stalls exhaust the pool. |
| **No metrics script** | Plan 18.5's M1–M7 were produced by a human reading MCP output and typing numbers into markdown. There is no `compute_metrics.py`, no JSON emitter, no A/B diff, no token/latency accounting. |
| **No loader for the golden corpus** | The 28 episodes in `docs/plans/18.5-e2e-revalidation/resources/episodes.md` are fenced markdown blocks with no runner. |

### Existing assets this plan reuses rather than rebuilds

- **Plan 29's all-in-one metrics SQL** (`docs/plans/29-ontology-validation/resources/queries.md:29-71`) —
  objective, zero-judgement, per-schema, one psql call, with baseline values already recorded for two runs.
  Three caveats: it returns **five** columns (`active_node_types`, `active_edge_types`,
  `unused_edge_type_pct`, `garbage_types`, `type_reuse_ratio`) — despite its own header claiming six, it
  does **not** compute instance-level types; `{schema}` is a textual find-and-replace placeholder, not a
  bound parameter; and its `garbage_types` regex is a hardcoded pre-Qwen copy of
  `_TOOL_CALL_ARTIFACT` (see D8).
- **`scripts/e2e_plan15_scenarios_test.py`** (14 scenarios, gate ≥11/14) and
  **`scripts/e2e_plan17_validation.py`** (8 embedded episodes, 14 scenarios, gate ≥13/14) — self-contained,
  already runnable under `run_e2e.sh`. **Neither is exit-code gated**: both wrap every scenario in
  `try/except` and neither calls `sys.exit`, so both exit 0 at any score. Their result must be read by
  parsing the printed score line (`Acceptable (PASS only): X/14`), never from `$?`.
- **`scripts/e2e_extraction_pipeline_test.py`** — cheapest binary smoke gate.
- **`scripts/manage.sh snapshot save|load`** — the A/B state-preservation mechanism.
- **`/admin/jobs`** already exposes `created_at` / `started_at` / `finished_at` / `attempts` per job —
  the per-episode latency source, currently unaggregated.
- **`src/neocortex/normalization.py:19-26`** `_TOOL_CALL_ARTIFACT` — the accumulated regex defense against
  exactly this failure mode (originally against Gemini Flash). **Extend it, don't replace it.**
  It already carries `UpdateEdge`, `functionName` and `Updating\w*Id\d` beyond the shapes named in D7. It
  is a plain unanchored alternation searched with `.search()` under `IGNORECASE` — no `\b` anchors, so
  literal `<think>` / `<function=` additions are syntactically safe. It is consulted **only** by
  `normalize_node_type` / `normalize_edge_type`, which **raise** on a match, so it guards type names
  only — never node names or node content. That is what D10 exists to measure.

---

## Strategy

Three phases, ten stages (one conditional). The ordering is load-bearing: the cheapest disqualifying evidence is
gathered first, and both bake-off arms run on *identical* prompts so the only variable is the model.

- **Phase A — Enablement and fail-fast (Stages 1–3).** Build the provider routing that makes a local
  endpoint addressable per-agent, then spend ~15 minutes probing all four agents against Qwen with their
  *real* schemas and *real* tools before investing in a full bake-off. Harden the prompts that fail.
- **Phase B — The bake-off (Stages 4–6b).** Build the metrics harness NeoCortex has never had, run the
  hosted baseline arm, then the all-four-agents Qwen arm, on the same corpus with the same prompts.
  Stage 6b is conditional: it runs single-agent isolation arms **only** when the joint arm misses a
  Tier 2 metric, which is the only way to attribute a joint miss to one agent.
- **Phase C — Gate and cutover (Stages 7–9).** Evaluate the gate per agent, tune thinking effort upward
  on whatever passed, and migrate defaults with a documented rollback.

Three rules hold across every stage:

- **Both arms run identical prompts.** Stage 3's hardening lands *before* the baseline arm in Stage 5,
  so prompt changes are a shared constant and never a confound. If a hardening change helps GPT-5.4-mini
  too, that is a real result and stays.
- **Latency is measured, reported, and never a gate criterion.** Extraction is async background work.
  The scoping decision is explicit: tune for quality, record the cost.
- **The gate is per-agent, and a partial pass ships.** Any agent that clears moves to Qwen; the rest stay
  on `openai-responses:gpt-5.4-mini` with the measured evidence recorded in the Backlog. This is why
  Stage 1's routing must be per-agent rather than a single global `OPENAI_BASE_URL`.
- **A per-agent verdict needs per-agent evidence (D9).** Every Tier 2 metric is a joint output of all
  four agents on one graph, so the single Stage 6 arm can support "all four migrate" or "all four hold"
  but cannot say *which* agent caused a miss. Stage 6b buys that attribution with single-agent arms, and
  it is skipped entirely when the joint arm passes — because in that case the configuration that shipped
  is exactly the configuration that was measured.

---

## Success Criteria

Three tiers. **Hard-fail metrics** must pass on the Qwen arm and encode the Plan 28 ontology crisis.
**Near-parity metrics** are scored against the measured baseline arm with a stated tolerance.
**Tier 3** is recorded and never gates.

Two Tier 1 rows are deliberately baseline-relative rather than absolute — the invalid-type rejection
rate and the instance-level type candidate count. Both are heuristics with standing false positives
that *both* arms share, so an absolute `0` would fail the hosted baseline too. They are still hard
fails: a Qwen arm that rejects materially more than the baseline is blocked regardless of how good the
rest of its numbers look.

### Tier 1 — hard fail (any miss blocks that agent from migrating)

| Metric | Source | Target | Baseline (fill in Stage 5) | Qwen (fill in Stage 6) |
|---|---|---|---|---|
| Garbage / tool-call-artifact types **stored** | `compute_metrics.py`, regex read live from `normalization._TOOL_CALL_ARTIFACT` | **0** | | |
| Invalid-type **rejection rate** — rejections ÷ total entity attempts | `compute_metrics.py` over `log/agent_actions.log` (Stage 4 step 4 binds the events) | **≤ baseline + 2 pp** | | |
| Instance-level type candidates | `compute_metrics.py` instance-type scan (Stage 4 step 3) | **0 above baseline** | | |
| Extraction job failure rate | `/admin/jobs/summary` | **≤ 10%** (Plan 23 baseline was 29%) | | |
| Type names ≤ 60 chars, ≤ 5 segments, PascalCase | Plan 19 S3 | **100%** | | |
| Reasoning / `<think>` text leaked into any stored node **name** or node **content** | `compute_metrics.py` leak scan (new coverage — the regex only ever guarded type names) | **0** | | |
| `e2e_extraction_pipeline_test.py` | exit code | **pass** | | |

**Why the rejection rate is a Tier 1 metric and not a footnote.** `_TOOL_CALL_ARTIFACT` is consulted
only inside `normalize_node_type` / `normalize_edge_type`, which **raise**, and every caller swallows
the raise: `propose_type` returns `accepted: false` (`extraction/agents.py:216`),
`get_or_create_node_type` logs `invalid_node_type_rejected` and returns `None`
(`db/adapter.py:536-540`), and `pipeline.py:446-448` does
`if node_type is None: logger.warning("skipping_entity_invalid_type", …); continue`. So once Stage 3
step 6 teaches the regex the Qwen shapes, a leaked `<think>` can **never** reach the graph — and the
two "stored artifact" rows above would read 0 for the exact failure mode they exist to catch, while
entities are dropped on the floor. Counting the rejections is the only way the gate can see it.
The same reasoning is why the stored-artifact scan reads its regex from `normalization.py` at runtime
rather than reusing the hardcoded copy inside Plan 29's SQL, which predates the Qwen shapes.

### Tier 2 — near-parity (scored against the measured baseline arm)

| Metric | Source | Target | Baseline | Qwen |
|---|---|---|---|---|
| Plan 15 scenarios acceptable | `e2e_plan15_scenarios_test.py` **score line** (it always exits 0) | ≥ 11/14 **and** ≥ baseline − 1 | | |
| Plan 17 scenarios acceptable | `e2e_plan17_validation.py` **score line** (it always exits 0) | ≥ 13/14 **and** ≥ baseline − 1 | | |
| Active node types per schema | Plan 29 SQL | within ±25% of baseline | | |
| Active edge types per schema | Plan 29 SQL | within ±25% of baseline | | |
| Unused edge type % | Plan 29 SQL | not worse than baseline + 10 pp | | |
| Type reuse ratio (nodes / active types) | Plan 29 SQL | ≥ baseline × 0.75 | | |
| Entity dedup rate | Plan 22 M1 method | ≥ 70% and ≥ baseline − 10 pp | | |
| Episodes consolidated | graph stats | ≥ 90% and ≥ baseline − 5 pp | | |
| `e2e_episodic_memory_test.py`, `e2e_cognitive_recall_test.py` | exit codes | pass, both arms | | |

**The three ontology-size rows are relative-only on purpose.** Plan 28's absolute ranges (25–35 active
node types, 30–50 active edge types, < 15% unused edge types) were deliberately dropped from the Target
column, because Plan 29 already scored the current stack against those exact numbers and recorded
6–32 / 0–22 / 46–100% — marking them *"N/A (low volume)"* and *"UNCHANGED (seed size vs volume)"* with
the explicit finding: *"Seed edge types created upfront but never used. Driven by seed ontology size,
not extraction quality."* Since Stage 4 step 6 **mandates** provisioning those same seed schemas before
either arm ingests, keeping the absolute floors would fail both arms — including the hosted baseline —
and drag every agent to HOLD for a reason that has nothing to do with either model. The Plan 28 ranges
remain a useful long-term aspiration; they are not a valid instrument for a model-vs-model comparison.

### Tier 3 — recorded, never gating

| Metric | Why recorded |
|---|---|
| p50 / p95 wall-clock per episode, per agent stage | Cost of the migration; feeds Stage 8's effort choice |
| Total LLM calls, prompt + completion + reasoning tokens per episode | NeoCortex has never measured this; needed to reason about the `max_running_requests=8` ceiling |
| Tool calls per extraction (ontology avg 12.2 / budget 30; librarian budget 150) | Budget-exhaustion is a predicted weak-model failure mode |
| Retry count and `ModelRetry` round-trips | Structured-output fragility signal |

---

## Files That May Be Changed

### Provider routing (Stage 1)
- `src/neocortex/model_factory.py` — **new.** Shared `build_model()` / `build_model_settings()` used by
  all five agent construction sites. It must not live in `extraction/agents.py`: `domains/classifier.py`
  and `domains/seed_generator.py` need it too, they have no `AgentInferenceConfig`, and importing a
  private `_build_model` across packages is the wrong boundary.
- `src/neocortex/mcp_settings.py` — add `local_model_base_url`, `local_model_api_key_env`,
  `local_model_temperature` / `_top_p` (+ `_nothink` variants), `local_model_timeout_s`,
  `seed_generator_thinking_effort`; keep the four `*_model` and `*_thinking_effort` fields.
- `src/neocortex/extraction/agents.py` — `_build_model()` at `:50-56` (currently returns
  `config.model_name` after two `logger.debug` calls) delegates to the shared factory;
  `AgentInferenceConfig.model_settings` at `:42-47` (note it already returns `None` when
  `thinking_effort is None` — preserve that branch); `DEFAULT_MODEL_NAME`/`DEFAULT_THINKING_EFFORT` at `:30-31`.
- `src/neocortex/domains/classifier.py` — `:44-48` stores the model *string* and `ModelSettings`; the
  `Agent` is built fresh inside `classify()` at `:79-83` on **every call**. Both need the factory.
- `src/neocortex/domains/seed_generator.py` — `:29` default; `Agent` built inside `_generate_seed()` at
  `:119-127` with **no** `model_settings` at all; give it its own thinking setting.
- `src/neocortex/services.py` — `:69-72`, `:130-133`, `:154-157` wiring. Note `SeedGenerator` has no
  model setting of its own — both sites pass `settings.domain_classifier_model`.
- `src/neocortex/jobs/tasks.py` — `:76-87` `AgentInferenceConfig` construction (three configs).

### Prompt hardening (Stage 3)
- `src/neocortex/extraction/agents.py` — ontology system prompt (`:88-122`), extractor (`:304-335`),
  librarian tool-mode (`:426-501`), and the three `@agent.instructions` blocks (`:248-276`, `:338-384`, `:1050-1111`).
- `src/neocortex/domains/classifier.py` — `:56-77`.
- `src/neocortex/normalization.py` — extend `_TOOL_CALL_ARTIFACT` (`:19-26`) with any new artifact shapes Stage 2 finds.
- `src/neocortex/extraction/schemas.py` — *possibly* narrow `ExtractedEntity.properties` / `ExtractedRelation.properties` from open `dict` if Stage 3 step 8 shows it recovers the extractor's cost. Any change here must keep the hosted arm passing.

### Measurement harness (Stage 4)
- `scripts/corpus_loader.py` — **new.** Parses `docs/plans/18.5-e2e-revalidation/resources/episodes.md`.
- `scripts/compute_metrics.py` — **new.** Emits the Tier 1–3 tables as JSON.
- `scripts/model_bakeoff.sh` — **new.** Orchestrates one arm end-to-end.
- `src/neocortex/extraction/pipeline.py` — promote the 8 existing `stage_timing` DEBUG logs to
  `action_log=True` so latency is durably recorded (they exist at `:134`, `:166`, `:228`, `:245`, `:263`, `:285`, `:346`, `:366`).

### Docs (Stage 9)
- `CLAUDE.md:109`, `docs/configuration.md:191,205,213,220-222`, `docs/development.md:222-243`,
  `README.md:90`, `.claude/skills/neocortex/SKILL.md:60` — all still claim Gemini.
- **Also stale, outside the original list:** `docs/multi-agent.md:84`
  (`NEOCORTEX_DOMAIN_CLASSIFIER_MODEL` shown as `google-gla:gemini-3-flash-preview`),
  `docs/e2e-reproduction.md:9` ("used for extraction agents + embeddings") and `:95`
  ("3 sequential Gemini API calls"), `.claude/skills/neocortex/PERMISSIONS.md:130`
  ("A classifier (Gemini model) assigns semantic domain labels").
  `docs/reports/00-extraction-pipeline-e2e-validation.md` is a dated historical report — leave it.
- `.env.example` — currently documents **neither** `GOOGLE_API_KEY` nor `OPENAI_API_KEY`, and has no
  comments at all, so the explanatory comment Stage 9 adds is a new convention for that file.

### Explicitly NOT changed
- `src/neocortex/embedding_service.py` — 768-dim `pgvector` semantics; swapping means re-embedding everything.
- `src/neocortex/ingestion/media_description.py` — multimodal + Gemini Files API, no local equivalent.
- `src/pydantic_agents_playground/` — dead demo code, not served.
- Any test assertion. Stage 3 changes prompts; if a test asserts on prompt text it is updated to
  assert the new contract, never deleted.

---

## Progress Tracker

**Phase A — Enablement and fail-fast**

| # | Stage | Status | Notes | Commit |
|---|-------|--------|-------|--------|
| 1 | [Local provider routing](stages/01-local-provider-routing.md) | DONE | Added per-agent `local:` OpenAI-compatible routing, local sampling/timeout settings, classifier and seed-generator wiring, and unit coverage. Full suite: 911 passed, 11 skipped. | 3e3c85f |
| 2 | [Per-agent capability probes](stages/02-capability-probes.md) | DONE | Added fixed three-episode corpus, bounded-concurrency real-agent probe harness, 60 records per effort at low/medium/high/xhigh, and per-agent findings. Medium used a 60s cap for the completed sweep; see findings for timeout caveat and repository limitation. Full suite: 911 passed, 11 skipped. | 82f4580 |
| 3 | [Prompt hardening](stages/03-prompt-hardening.md) | DONE | Added source-text framing, terminal structured-output/tool contracts, reordered dynamic context, removed duplicate episode user messages, removed the misleading exact-match deprecation notice, and extended artifact rejection. Full suite: 916 passed, 11 skipped. Hosted E2E and open-dict variant experiment deferred to Backlog #6–#7. | |

**Phase B — The bake-off**

| # | Stage | Status | Notes | Commit |
|---|-------|--------|-------|--------|
| 4 | [Measurement harness](stages/04-measurement-harness.md) | DONE | Added corpus loader, recall scorer, live-regex metrics emitter, structured usage/timing/rejection audit events, and full arm orchestrator with pre-flight assertions and derived timeout polling. Dry-run/parser checks pass; full suite: 916 passed, 11 skipped. Live DB/API reproduction and end-to-end timeout assertion deferred to Backlog #8. | |
| 5 | [Baseline arm — GPT-5.4-mini](stages/05-baseline-arm.md) | BLOCKED | Run 1 corpus arm completed cleanly and was snapshotted; run 2 remained at two `doing` extraction jobs for >30 minutes with no finished events, so variance, E2E gates, and resolved thresholds are NOT MEASURED. See Backlog #9. | 89e7f95 |
| 6 | [Qwen arm — all four agents](stages/06-qwen-arm.md) | BLOCKED | Stage 5 is BLOCKED because baseline run 2 did not complete; the required baseline variance, E2E gates, and resolved thresholds are not measured. See Backlog #9. | |
| 6b | [Isolation arms (conditional)](stages/06b-isolation-arms.md) | BLOCKED | Stage 6 is BLOCKED because baseline run 2 did not complete; isolation arms cannot run until the baseline and joint Qwen arm are measured. See Backlog #9. | |

**Phase C — Gate and cutover**

| # | Stage | Status | Notes | Commit |
|---|-------|--------|-------|--------|
| 7 | [Quality gate evaluation](stages/07-quality-gate.md) | BLOCKED | Stage 5 is BLOCKED because baseline run 2 did not complete; Stages 6 and 6b therefore cannot provide the required Qwen comparison or attribution evidence. See Backlog #9. | |
| 8 | [Thinking-effort tuning](stages/08-thinking-effort-tuning.md) | BLOCKED | Stage 7 is BLOCKED because Stage 5 baseline run 2 did not complete; no agent has a validated MIGRATE verdict to tune. See Backlog #9. | 9475829 |
| 9 | [Cutover, docs, rollback](stages/09-cutover-and-docs.md) | BLOCKED | Stage 8 is BLOCKED because the baseline run 2 did not complete; no validated MIGRATE verdict exists for cutover. See Backlog #9. | |

Statuses: `PENDING` -> `IN_PROGRESS` -> `DONE` | `BLOCKED` | `SKIPPED`

**Stage 6b is conditional on Stage 6.** If the Stage 6 joint arm clears every Tier 1 and Tier 2
threshold, mark 6b SKIPPED — no attribution is needed, because the measured configuration is the
configuration that would ship. If it misses any Tier 2 metric, 6b is **required** before Stage 7 can
issue a per-agent verdict.

**Stages 8 and 9 are conditional on Stage 7.** If Stage 7 clears no agent, mark 8 and 9 SKIPPED,
record the measured evidence in the Backlog, and end the run with the plan's question answered
"no" — that is a successful outcome, not a failure.

---

## Execution Protocol

This plan is built for **autonomous, unattended execution**. The guiding principle is
**keep making progress**: resolve problems in place when you can, defer them when you
can't, and never halt the whole plan over a single fixable or deferrable issue.

For each stage:

1. **Read the progress tracker** above and pick the stage to work on. If a stage is
   **IN_PROGRESS**, a previous run was interrupted mid-stage — resume and finish that one
   (re-read its steps, inspect the working tree to see what's already done) before
   starting anything new. Otherwise, take the first **PENDING** stage.
2. **Read the stage file** -- follow the link in the tracker to the stage's .md file.
3. **Read resources** -- if the stage references shared resources, find them in `resources/`.
4. **Resolve ambiguity yourself** -- there is no user to ask during an autonomous run.
   Pick the most reasonable interpretation that fits the codebase and existing
   conventions, record it under **Decisions**, and proceed. Only defer to the Backlog
   if the ambiguity genuinely blocks any sensible implementation.
5. **Implement** -- execute the steps described in the stage.
6. **Validate** -- run the verification checks and the test suite. **If anything fails,
   do not stop — triage it via the self-healing loop below.**
7. **Update this index** -- mark the stage DONE in the progress tracker, add brief notes
   about what was done and any deviations. Log every problem you hit in **Fixed Issues**
   (if resolved) or **Backlog** (if deferred). Never silently drop a problem.
8. **Commit** -- create an atomic commit with the message specified in the stage.
   Include all changed files (code, config, docs, and this plan's index.md).

Repeat until every stage is DONE or terminally deferred. After the last stage, **sweep
the Backlog**: attempt any items that are now resolvable, and leave the rest for a
follow-up run.

### Measurement integrity rules (specific to this plan)

This plan's output is *evidence*, so the usual "make it pass" instinct is actively wrong here:

- **Never tune a prompt, threshold, or setting between the two arms.** If Stage 6 reveals a needed
  prompt fix, either re-run Stage 5 with the fix, or record the asymmetry explicitly as a
  confound in the Qwen arm's notes. Never silently compare unequal arms.
- **A measured regression is a valid result.** Record it and let Stage 7's gate decide. Do not
  soften a target to make the migration succeed.
- **Never fabricate or estimate a metric.** If a measurement could not be taken, write `NOT MEASURED`
  in the cell and add a Backlog entry. An empty cell is better than a plausible guess.
- **Snapshot both arms** (`manage.sh snapshot save <arm>`) before tearing anything down, so any
  disputed number can be re-derived from the graph after the fact.

### Self-healing loop (handling problems)

When a step fails — failing test, build/lint/type error, a bug in the new code, an
unexpected runtime error:

1. **Triage** the problem as *light* or *heavy*.
   - **Light** -- self-contained and fixable in a focused effort: a failing unit test,
     a lint/type error, a missing import, a small logic bug in code you just wrote.
   - **Heavy** -- needs an architectural decision, spans many files, depends on an
     external blocker, contradicts the plan's assumptions, or has already survived a
     fix attempt.
2. **Light → delegate the fix to a subagent.** Spawn a focused subagent (Agent/Task
   tool) with: the failing command and its full output, the relevant file paths, the
   stage goal, and a crisp deliverable (e.g. "make `<test>` pass without weakening
   assertions"). Delegating keeps the main execution context clean. Re-run verification
   when it returns. Cap at **2 attempts per issue** — if still failing, treat it as heavy.
3. **Heavy → defer to the Backlog.** Add a self-contained entry (see the Backlog table).
   Do **not** keep grinding and do **not** halt the plan.
4. **Decide the stage's disposition:**
   - If the stage's core goal is met without the deferred item → mark **DONE**, note the
     backlog reference, and continue.
   - If the deferred item is essential to this stage → mark **BLOCKED**, note the backlog
     reference, and continue to the next *independent* stage. Only stop the run when every
     remaining stage depends on blocked work.
5. **Record** the outcome: resolved problems → **Fixed Issues**; deferred problems → **Backlog**.

**Endpoint-specific triage.** If the z-spark endpoint is unreachable or returns 5xx, that is an
**external blocker**, not a light problem: do not retry in a loop. Mark the current stage BLOCKED,
record it in the Backlog with the exact error, and continue to any stage that does not need the endpoint.

Which stages those actually are, since the dependency chain is nearly linear:

- **Stages 1 and 4 are genuinely endpoint-independent** — pure code and tooling.
- **Stage 3's edits are endpoint-independent; only its verification is not.** Steps 1–8 are prompt and
  regex changes that apply to both arms regardless of what Stage 2 measured. If Stage 2 is blocked,
  apply the universal hardening (source-text framing, terminal imperatives, reordering, the duplicate-text
  removal, the regex extension), skip the exemplars that Stage 2's verdicts were meant to scope, mark
  Stage 3 DONE with a Backlog note that live re-probing is deferred, and carry on. D5 is preserved
  because **both arms still run identical prompt text** — only the empirical confirmation that hardening
  helped is deferred.
- **Stage 5 needs Stage 3 landed, not Stage 2 measured.** There is no "baseline half of 5" that can run
  before Stage 3 — running the baseline arm on unhardened prompts would void D5 permanently and force a
  re-run, which is far more expensive than waiting. Never do it.
- **Stages 6, 6b, 7, 8 and 9 all require the endpoint.** If it stays down, the run legitimately ends after
  Stage 5 with Stages 6+ BLOCKED.

### Guardrails

- Keep every commit in a working, buildable state.
- **Never weaken, skip, or delete a test to make it pass.** If a test is genuinely wrong,
  fix it correctly and note it in Fixed Issues.
- Never use `git commit --no-verify`.
- Don't expand a stage's scope to chase a heavy problem — that's what the Backlog is for.
- **Never commit the LiteLLM key.** It is read from `$VLLM_API_KEY` / the bot's `.env` at runtime.
  `.env` is gitignored; keep it that way and never paste the value into a plan file, log, or commit.

---

## Fixed Issues

Problems encountered during execution and resolved (in place or via a fix subagent).
Leave empty until execution surfaces something.

| # | Stage | Symptom | Root Cause | Resolution | Fixed By |
|---|-------|---------|-----------|------------|----------|
| 1 | 1 | Full suite failed in `test_extract_episode_calls_run_extraction` with `KeyError: 'local_endpoint'` | The test uses a minimal pre-existing fake service context without the new optional context field | Task wiring now uses `services.get("local_endpoint")`, preserving hosted behavior for older/minimal contexts while production services provide the resolved endpoint | inline |
| 2 | 1 | Pre-commit `ty` rejected `_build_model` return annotation | The annotation predated the new local `Model` return path | Annotated the delegate as `str | Model`; formatting and lint hooks also passed after re-staging | inline |
| 3 | 2 | Required `poetry run pytest` command was unavailable | This checkout uses `uv` and does not have the Poetry executable installed | Ran the repository-equivalent `uv run pytest` successfully: 911 passed, 11 skipped | inline |
| 4 | 3 | New Qwen marker tests did not raise because `<…>` was stripped first | Normalization checked `_TOOL_CALL_ARTIFACT` only after removing invalid characters | Check the raw type name before sanitization; added regression cases for all five new marker families and reran the full suite | inline |
| 5 | 3 | Pre-commit rejected two prompt lines with E501 | Added terminal contracts exceeded the repository's 120-column lint limit | Wrapped the prompt strings without changing their text; pre-commit passed on retry | inline |
| 6 | 4 | Two unit tests emitted unawaited-coroutine warnings from usage instrumentation | Minimal AsyncMock librarian results expose an async `usage()` placeholder, unlike production pydantic-ai results | Detect awaitable usage values and close coroutine placeholders before returning | inline |
| 7 | 5 | Baseline orchestrator failed its admin pre-flight with HTTP 401 | `manage.sh` advertises `admin-token`, while the harness fallback is `admin-token-neocortex` | Supplied `NEOCORTEX_ADMIN_TOKEN=admin-token` for the measured run; no key or code change | inline |
| 8 | 5 | Recall scorer returned all-zero results with HTTP 401 on MCP | Its fallback `alice-token` is absent from production `dev_tokens.json`; the corpus was loaded under the admin identity | Kept the output as non-gating diagnostic data and did not use it as a model metric | inline |
| 9 | 5 | First E2E gate could not connect after `manage.sh` reported healthy | `uv run` wrapper PID bookkeeping allowed the underlying listener to re-parent; the gate also needs a separate test-token file | Direct retry reached MCP but exposed the token-file mismatch; E2E score remains NOT MEASURED | inline |

---

## Backlog (Deferred Issues)

Problems deferred for later — too heavy to fix inline without derailing the plan.
Each entry must be **self-contained enough for a future run to pick it up cold**:
state the symptom, where it came from, and a concrete lead for resolving it.

| # | Title | Origin Stage | Severity | Why Deferred | Suggested Next Step | Status |
|---|-------|--------------|----------|--------------|---------------------|--------|
| 1 | Embeddings remain cloud-bound | scoping | med | Out of scope by decision — swapping `gemini-embedding-001` changes vector dimensionality and semantics, requiring a re-embed of every stored node | If full-local is later required, plan a separate migration: pick a local 768-dim model, add an `embedding_backend` setting, and write a backfill job over `nodes.embedding` | OPEN |
| 2 | Media description remains cloud-bound | scoping | low | Audio/video multimodal + Gemini Files API (2 GB uploads, PROCESSING polling) have no local equivalent in a text-only SGLang lane | Only actionable if a local multimodal lane is stood up on z-spark | OPEN |
| 3 | `embedding_service.py` silently returns `None` without `GOOGLE_API_KEY` | pre-existing | med | Unrelated to this migration, but it will corrupt a bake-off arm by silently degrading recall to text-only with no error | Make the embedding service fail loudly at startup when `GOOGLE_API_KEY` is absent and `mock_db` is false. Note it reads `os.environ["GOOGLE_API_KEY"]` directly and has no `settings` reference, so this needs a constructor change. Stage 4 must assert embeddings are live before either arm runs | OPEN |
| 4 | Artifact-rejected entities are silently discarded, not quarantined | pre-review | med | A product issue this plan only *measures* (Tier 1c). When `normalize_node_type` rejects a name, `get_or_create_node_type` returns `None` and `pipeline.py:448` does `continue` — the entity is dropped with a WARNING and nothing surfaces it to the caller or the graph. Any model that leaks markers loses data quietly, on any provider | Give `run_extraction` a `rejected: list[...]` in its result and surface a count on the job record, so a rejection is visible without log archaeology. Consider a retry that strips the artifact and re-normalizes rather than dropping the entity | OPEN |
| 5 | Probe tool backend is not PostgreSQL-backed | 2 | med | The completed capability sweep uses `InMemoryRepository` to avoid mutating the shared development graph. This exercises the real PydanticAI agents and tool functions but does not measure PostgreSQL query/permission behavior or production graph latency | Before any bake-off interpretation, run a small repeat of ontology/librarian probes with the production repository and isolated probe schema, or explicitly document why the mock backend is sufficient | OPEN |
| 6 | Hosted no-regression E2E not run after prompt hardening | 3 | med | The required hosted E2E needs a running hosted-configured service and the runner uses `start --fresh`, which would destroy the persisted development graph; no truthful result was available without that environment decision | Run `./scripts/run_e2e.sh scripts/e2e_extraction_pipeline_test.py` in the dedicated hosted baseline environment, snapshot first, and record the exit/output before Stage 5 | OPEN |
| 7 | Extractor open-dict schema experiment not isolated | 3 | med | The existing probe harness only runs the committed schema and has no agent-selection or temporary-schema variant; changing `properties` in place would confound the shared bake-off schema and alter stored data semantics | Add a bounded extractor-only probe mode or temporary schema variants, measure open `dict`, `dict[str, str]`, and omitted properties with latency and token counts, then retain the committed schema unless hosted validation also passes | OPEN |
| 8 | Stage 4 live harness verification not run | 4 | med | This unattended checkout has no running PostgreSQL/NeoCortex services or guaranteed embedding/API credentials, so Plan 29 snapshot reproduction, live audit-event assertion, pre-flight failure/pass matrix, and bounded poll-timeout test could not be truthfully executed | Start the dedicated hosted/local bake-off environment, run the listed Stage 4 verification commands, restore any snapshots afterward, and record the emitted metrics JSON before Stage 5 | OPEN |
| 9 | Baseline run 2 did not complete | 5 | high | Run 1 completed 102/102 jobs with 0 failures and produced `metrics-baseline-gpt54mini.json` plus snapshot `baseline-gpt54mini`; run 2 reached 103 succeeded but jobs 1 and 3 remained `doing` for over 30 minutes with only `started` events. It was stopped before the 4-hour deadline, so no truthful run-2 metrics, spread, E2E scores, or thresholds exist | Re-run Stage 5 in a stable dedicated environment. Investigate jobs 1 and 3 with `/admin/jobs/{id}` and `procrastinate_events`; add an explicit per-job HTTP/model timeout if they can hang indefinitely. Do not run Stage 6 until both runs and E2E gates are captured | OPEN |

Statuses: `OPEN` -> `IN_PROGRESS` -> `RESOLVED`. When an item is resolved, flip its
status and summarize the fix in **Fixed Issues**. Heavy items may warrant their own
follow-up plan — link it here.

---

## Decisions

Recorded during planning (D1–D8); D9–D12 added by pre-review, which also revised D6. Execution appends D13+.

**D1 — All four PydanticAI agents are in scope; embeddings and media are not.**
Owner decision. "Main model" means the reasoning surface. Embeddings are excluded because the
768-dim vectors are already persisted in `pgvector` and a swap would require re-embedding the
entire graph — a separate plan (Backlog #1).

**D2 — The gate is near-parity on objective metrics, with a hard-fail floor.**
Owner decision. Tier 1 encodes the Plan 28 ontology crisis and cannot regress at any cost;
Tier 2 is scored against the measured baseline with stated tolerances. This avoids both
"strict parity" (which would likely stall the migration on noise) and a bare "good-enough floor"
(which would let real quality loss through unexamined).

**D3 — Latency is measured but never gates.**
Owner decision. Extraction is async background work behind a job queue. This is the key
difference from bot Plan 26, which excluded `xhigh` at the type level because of a 77-second
*interactive* turn. NeoCortex has no interactive path here, so `xhigh` stays on the table and
Stage 8 evaluates it on quality alone.

**D4 — A partial pass ships.** Owner decision. Each agent is gated independently; whatever clears
migrates. This is the constraint that forces per-agent provider routing in Stage 1 — a single
global `OPENAI_BASE_URL` cannot express "librarian local, ontology hosted".

**D5 — Prompt hardening lands before both arms, not between them.**
The 2026-08-19 probe showed the model's only failure was prompt-shaped. Hardening after the
baseline would confound the comparison. Both arms therefore run identical, hardened prompts, and
any benefit to GPT-5.4-mini is a real result that stays.

**D6 — Keep the unified `ModelSettings.thinking` for local models too; add `temperature`/`top_p`/`timeout` to it.**
*Revised during pre-review — the original rationale was wrong.* Bot Plan 26 D1 warned that the unified
field maps through `OPENAI_REASONING_EFFORT_MAP` and could emit values outside the stock Qwen3.8 template
allowlist. Checked against the installed pydantic-ai 1.72.0, that map is
`{True: 'medium', False: 'none', 'minimal': 'minimal', 'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'xhigh'}`
— an **identity map for every string level** — and `OpenAIChatModel._get_reasoning_effort` falls back to
it when `openai_reasoning_effort` is unset. So `ModelSettings(thinking=X)` and
`OpenAIChatModelSettings(openai_reasoning_effort=X)` put the identical string on the wire for every value
`ThinkingLevel` permits (`bool | Literal['minimal','low','medium','high','xhigh']`, which includes `xhigh`).
Base `ModelSettings` already carries `temperature`, `top_p` and `timeout`, which were the other stated
reasons to switch types. There is therefore **no benefit** to a second settings type, and a single code
path is one fewer branch to get wrong. If a future sweep needs `reasoning_effort='none'` — which
`ThinkingLevel` cannot express but `ReasoningEffort` can — that is the one case worth reaching for
`OpenAIChatModelSettings`, and it is out of scope here.

**D7 — Extend `normalization.py`'s `_TOOL_CALL_ARTIFACT` rather than replacing it.**
It was built against Gemini Flash's leakage and Plan 29 proved its value (garbage types 9 → 0 via
two regex additions, no model change). Qwen's leakage shapes differ (`<think>`, `</think>`,
`<tool_call>`, `<function=`, `<parameter=`) and are additive.

**D8 — Reuse Plan 29's SQL and the existing e2e scripts; build only the loader, the metrics
emitter, and the orchestrator.** NeoCortex has three tiers of measurement maturity — Plan 29's
metrics are SQL (automatable today), Plan 15/17/32's are Python (already automated), Plan 18.5's
M1–M7 are prose executed by a human. Stage 4 builds only the missing connective tissue, and
Stage 4's own success criterion is that it reproduces Plan 29's already-recorded numbers — against
the **`pre-plan30-20260407-201234` snapshot**, not the live graph, which has drifted through Plans
30–32 (its `graph_registry` holds schemas created as late as 2026-07-28). Two carve-outs from
"reuse verbatim": the garbage-type regex is read live from `normalization.py` instead of the stale
copy hardcoded in Plan 29's SQL, and the instance-level-type metric is **not** in that SQL at all
(Plan 29 computed it by human review) so Stage 4 defines an explicit automatable rule for it.

---

**D9 — One joint Qwen arm decides "all four", and only a Tier 2 miss buys isolation arms.**
Added during pre-review. Every Tier 2 metric (scenario counts, type counts, unused edge %, reuse
ratio, dedup rate, episodes consolidated) is produced jointly by all four agents against one graph,
so the Stage 6 arm cannot attribute a miss to an individual agent — yet D4 promises a per-agent
verdict and Stage 7 requires one. Rather than pay for four isolation arms up front, Stage 6b runs
them **only** for the agents a Tier 2 miss could plausibly implicate, and is SKIPPED when the joint
arm passes outright. Stage 7's Tier 1 attribution heuristic is unchanged; Stage 6b is what makes its
Tier 2 counterpart possible.

**D10 — Rejected artifacts are counted, not just absent from the graph.**
Added during pre-review. Extending `_TOOL_CALL_ARTIFACT` (Stage 3 step 6) makes the artifact shapes
Qwen actually leaks *unstorable*, which would drive the "stored artifact types" and "leaked marker"
Tier 1 rows to 0 by construction while entities are silently dropped at `pipeline.py:448`. A
rejection-rate metric is therefore Tier 1 alongside them. This is a genuine tension in D7's
"extend, don't replace": the regex is both the defense and the blindfold, so the plan needs to
measure what it blocks.

**D11 — Both arms run at `worker_concurrency=2`.**
Added during pre-review. The Qwen arm needs 2 to respect SGLang's `max_running_requests=8`, and the
original plan left the baseline at the default 4. That is not a throughput-only difference: each
ontology agent is seeded with a type snapshot taken when its job starts and types are created via
`INSERT … ON CONFLICT DO NOTHING`, so concurrency changes how much of each other's ontology sibling
extractions see — moving the active type counts, unused edge %, and reuse ratio that Tier 2 gates on.
Equalising at 2 costs the baseline arm wall-clock and buys a clean comparison.

**D12 — The baseline arm runs twice; tolerances must exceed observed spread.**
Added during pre-review. Nothing pins temperature or a seed on either arm (local runs at 0.6), and
Tier 2 tolerances like "≥ baseline − 1" on a 14-point gate were chosen a priori without ever
measuring run-to-run variance. Two baseline runs give a spread; any tolerance narrower than that
spread is noise-dominated and must be widened in Stage 5 step 5, before the Qwen arm runs.

**D13 — Capability probes use bounded concurrency and record timeout caps.**
The local endpoint has a measured concurrency ceiling of eight, so the harness defaults to
six concurrent records to avoid serial runs taking hours while leaving headroom for serving
overhead. The normal per-call timeout remains 300 seconds; the completed effort sweep used
30 seconds for low/high/xhigh and 60 seconds for medium to produce bounded evidence. Those
caps are part of the findings and are not quality gates; the bake-off uses its own prescribed
timeouts and worker concurrency.

**D14 — Preserve open extractor properties until an isolated experiment exists.**
Stage 3 did not change `ExtractedEntity.properties` or `ExtractedRelation.properties`: those fields
carry real graph data, and the existing probe harness cannot compare schema variants without changing
the shared bake-off contract. The known open-dict baseline remains recorded (124.8 s / 3350 reasoning
tokens in the earlier real-schema probe); the isolated comparison is Backlog #7.

**D15 — Do not use a single completed arm as a variance baseline.**
Stage 5 run 1 is retained as valid evidence, but run 2 did not finish its two oldest extraction
jobs and the E2E helper environment had token/lifecycle mismatches. Baseline columns and Tier 2
thresholds therefore remain unresolved; Stage 6 must not proceed from these partial measurements.

## Execution Notes

Stage 3 prompt source sizes were not tokenized because the repository has no prompt-token counter.
The extractor's duplicate episode user message was removed, so its largest variable is now injected
once through instructions; the added framing and terminal contracts are short static lines. The
hosted E2E was not run against the persisted local services because the prescribed runner starts a
fresh environment; see Backlog #6.
