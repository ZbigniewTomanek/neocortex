# Capability Probes — Reproduction

Everything measured on **2026-08-19** against `http://z-spark.tail215ba1.ts.net:4000/v1`,
which serves exactly one model: `qwen3.8-27b`. These are the probes that justified writing this
plan; Stage 2 generalises them into `scripts/probe_local_model.py`.

## Setup

```bash
export VLLM_API_KEY=$(grep -E '^VLLM_API_KEY=' ~/projects/my-telegram-bot/.env | cut -d= -f2-)
export ENDPOINT=http://z-spark.tail215ba1.ts.net:4000/v1
```

Shell-sourcing that `.env` directly yields nothing for these values — use the `grep | cut` form
above or a `dotenv` loader. **Never commit the key.**

## Probe 0 — is the endpoint alive and what does it serve?

```bash
curl -s $ENDPOINT/models -H "Authorization: Bearer $VLLM_API_KEY" \
  | python3 -c "import sys,json; print('\n'.join(m['id'] for m in json.load(sys.stdin)['data']))"
```

Expected: `qwen3.8-27b`. A 401 whose message mentions *"LiteLLM Virtual Key expected … expected to
start with 'sk-'"* means the key did not resolve — the request reached LiteLLM, so the network is fine.

## Probe 1 — strict `json_schema` structured output

Sends a NeoCortex-shaped extraction schema (nodes with open `properties`, edges with a float weight)
via `response_format: {type: json_schema, strict: true}`.

| Setting | Latency | completion tok | reasoning tok | Valid JSON |
|---|---|---|---|---|
| `reasoning_effort=none`, temp 0.6 | 8.4 s | 391 | 0 | **yes** |
| `reasoning_effort=medium`, temp 0.6 | 17.6 s | 725 | 210 | **yes** |
| tools + json_schema together, `low` | 15.2 s | 654 | 198 | **yes** |

**Conclusion: strict structured output is not a risk on this deployment.** This retires the single
biggest concern about putting a 27B model behind the extractor.

## Probe 2 — tool calling, weak prompt (**the failure**)

System prompt: `"You are an ontology agent. Before proposing any type you MUST first call
list_node_types, then find_similar_nodes for each candidate. Explore first, then propose."`
Three tools attached, `tool_choice=auto`, `reasoning_effort=medium`.

Result: **40.1 s, zero tool calls**, 669 reasoning tokens, and prose output:

> I appreciate you sharing that, but I have to be upfront: I can't verify any of the specifics in
> that claim. A few things stand out to me:
> - **I have no record of "NeoCortex," a developer named Zbigniew, or a branch called
>   `upper-ontology-improvements`.** I don't have access to any repository, com…

The model treated the episode as **a claim to fact-check** rather than source text to process.
Note that the run *succeeded* — nothing threw. A failure counter based on exceptions would score
this as a pass.

## Probe 3 — tool calling, hardened prompt (**the fix**)

Same model, same endpoint, same three tools. The prompt adds an explicit framing and a terminal
mandatory-first-action line:

```
You are the ontology agent of a knowledge-graph memory system.
The user message is NOT a claim to verify. It is raw source text that has already been
accepted into the system. Your only job is to decide which node types the graph needs to store it.

MANDATORY WORKFLOW — follow in order, no exceptions:
1. Call list_node_types (no arguments) to see the existing ontology.
2. For each entity you see in the source text, call find_similar_nodes with its name.
3. Only then call propose_type for genuinely new types.

Never answer in prose. Never question whether the source text is true.
Your first action in this turn MUST be a call to list_node_types.
```

| Probe | Latency | reasoning tok | Tool calls |
|---|---|---|---|
| hardened, `medium` | **2.4–2.7 s** | 48–64 | 1 × `list_node_types` ✓ |
| hardened, `high` | 2.4 s | 48 | 1 × `list_node_types` ✓ |
| hardened, `required` | 3.6 s | 63 | 1 × `list_node_types`, **args malformed** |
| **round 2** (after feeding a tool result back) | 11.3 s | 127 | **6 parallel** `find_similar_nodes`, correct args ✓ |

**40.1 s and zero tool calls → 2.4 s and a correct call, from the prompt alone.** This is the
finding that shapes Stage 3.

### The `tool_choice=required` defect

With `tool_choice=required` the model emitted:

```json
{"function": {"name": "list_node_types", "arguments": "{\"arguments\": \"{}\"}"}}
```

The argument payload is double-wrapped — `{"arguments": "{}"}` where `{}` was required. Harmless
for a no-argument tool, potentially not for one with a real schema. Stage 2 step 5 determines
whether pydantic-ai ever puts a NeoCortex agent on that code path.

## Probe 4 — through pydantic-ai (the actual integration path)

pydantic-ai **1.72.0**, `openai:qwen3.8-27b`, `OPENAI_BASE_URL` pointed at the endpoint.

```python
os.environ["OPENAI_BASE_URL"] = "http://z-spark.tail215ba1.ts.net:4000/v1"
os.environ["OPENAI_API_KEY"]  = <VLLM_API_KEY>
agent = Agent("openai:qwen3.8-27b", output_type=Out, system_prompt=...)
await agent.run(text, model_settings=ModelSettings(thinking="medium"))
```

| Case | Result |
|---|---|
| structured output, `thinking="low"` | **OK** — 6 nodes; usage 455 in / 724 out, **398 reasoning** |
| structured output, `thinking="medium"` | **OK** — 6 nodes; 455 in / 680 out, **361 reasoning** |
| tool-using agent, `thinking="medium"` | **OK** — 3 requests, **6 tool calls**, correct order |

Two things this establishes:

1. `ModelSettings(thinking=…)` reaches the server and produces real reasoning tokens, so
   LiteLLM's global `drop_params: true` is **not** eating `reasoning_effort` on the `hosted_vllm/`
   adapter. (It did eat it on the generic `openai/` adapter — z-spark Plan 14 Fixed Issue #14.)
   Checked in the installed 1.72.0, `OPENAI_REASONING_EFFORT_MAP` is
   `{True: 'medium', False: 'none', 'minimal': 'minimal', 'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'xhigh'}`
   — an identity map for every string level — and `OpenAIChatModel._get_reasoning_effort` falls back to
   it when `openai_reasoning_effort` is unset. So the unified field is not a source of value
   distortion, and there is no reason to prefer the provider-specific one. This is why D6 was revised
   to keep a single settings path.
2. The whole integration path works with no code change *for a global swap*. Per-agent routing —
   which D4 requires — is what needs Stage 1.

> Caveat worth carrying: `qwen3.8-27b` does not match pydantic-ai's `_QWEN_3_5_RE`, so it resolves
> through `openai_model_profile()`, not `profiles/qwen.py`. That means OpenAI strict-schema and
> tool-definition semantics, and `thinking_tags=('<think>','</think>')`. It worked in every probe
> above, but it is why Stage 3 extends the artifact regex with `<think>`/`</think>` shapes.

## Probe 5 — real NeoCortex schemas (**the cost finding**)

The probes above used a hand-written toy schema. Repeating with NeoCortex's actual
`ExtractionResult` — 2 nested models, **2 unconstrained `dict` properties**, 2 `ge/le` floats,
3 nullable strings, and a **raising** `type_name` validator — via pydantic-ai:

| Setting | Result |
|---|---|
| `thinking="low"` | **OK — 124.8 s**, 6 entities / 5 relations, 4436 output tokens, **3350 reasoning tokens** |
| `thinking="medium"` | **TIMEOUT at 150 s** (client-side cap) |

Compare against Probe 1's toy schema on the same endpoint: 8.4 s / 391 tokens at `none`,
17.6 s / 725 tokens at `medium`. **The real schema drives roughly a 10× blow-up in reasoning
tokens** — 3350 versus ~200–400.

The arithmetic says this is decode-bound rather than hung: at the measured p50 of 23.16 tok/s,
4436 output tokens is ~190 s of pure decode. The `medium` run had not stalled at 150 s, it was
still generating.

Three consequences the plan has to carry:

1. **The extractor is not the "easy" agent.** The Stage 2 risk table ranks it medium because it is
   single-shot with no tool loop. On latency and token cost it is the most expensive call in the
   pipeline, and it is the one whose prompt also grows unboundedly with ontology size.
2. **More thinking effort may be strictly worse here.** `medium` did not finish inside 150 s where
   `low` finished in 125 s. Stage 8 must not assume the effort/quality curve is monotonic for this
   agent, and must set generous per-call timeouts before sweeping it.
3. **Schema surface is a tunable.** The two unconstrained `dict` properties (`ExtractedEntity.properties`,
   `ExtractedRelation.properties`) are the most likely driver — an open `additionalProperties` object
   gives a constrained decoder nothing to anchor on. Narrowing or dropping them is a cheap
   experiment worth running before concluding the extractor cannot be migrated.

An earlier exploratory version of this probe (3 efforts × 3 tries, no per-call timeout) was killed
after ~25 minutes without completing. That is consistent with the numbers above and is why Stage 2
mandates an explicit per-call timeout: without one, this failure mode presents as a hang rather
than a measurement.
