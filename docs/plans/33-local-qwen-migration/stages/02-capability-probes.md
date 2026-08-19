# Stage 2: Per-Agent Capability Probes

**Goal**: Exercise all four agents against `qwen3.8-27b` with their real schemas, real tools, and real prompts, so the plan knows exactly where the model breaks before investing in a full bake-off.
**Dependencies**: Stage 1 DONE (needs `local:` routing).

---

## Why this stage exists

A full bake-off arm costs a fresh database, a 28-episode ingest, and a wait on ~56 sequential
LLM calls. This stage costs about fifteen minutes and can disqualify the whole idea — or, more
usefully, tell Stage 3 precisely which prompts need hardening.

The 2026-08-19 probe already established the shape of the answer at the raw-HTTP level:
structured output works, tool calling works *only with a hardened prompt*, and the multi-turn
loop works. This stage repeats that against NeoCortex's actual `output_type` schemas and actual
tool surfaces, which are considerably heavier than the probe's toy versions:

| Agent | Real surface | Predicted risk |
|---|---|---|
| Extractor | `ExtractionResult` — 2 nested models, **2 unconstrained `dict` properties**, 2 `ge/le` floats, 4 nullable strings, a **raising** `type_name` validator; largest dynamic prompt (full ontology + episode, duplicated) | Widest schema surface. **Measured 124.8 s / 3350 reasoning tokens at `low`, and a timeout at `medium`** — no loop risk, but the pipeline's most expensive call by far |
| Ontology | `OntologyProposal` with **raising** name validators; 3 tools; explicit reject-and-retry protocol (`propose_type` returns `accepted: false` + a reason the model must act on); `tool_calls_limit=30` | Multi-turn + must recover from an in-band rejection |
| Librarian | `CurationSummary`; **9 tools**; `tool_calls_limit=150`; ~5 KB system prompt; tools return `{"error": …}` the model must self-correct from; structured output demanded *after* a long tool sequence | **Highest risk.** Local models characteristically drop the terminal structured output after a long loop |
| Domain classifier | `ClassificationResult` with a nullable nested `ProposedDomain` and calibrated confidence floats; growing domain tree in the prompt | Medium; already has a keyword fallback and a router-level try/except |

---

## Steps

1. **Write the probe script.**
   - File: `scripts/probe_local_model.py` (new)
   - Details: for each of the four agents, build it through the *real* factory
     (`build_ontology_agent`, `build_extractor_agent`, `build_librarian_agent`,
     `AgentDomainClassifier`) with `model_name='local:qwen3.8-27b'`, and run it **N=5 times**
     against a fixed 3-episode probe corpus (below). Record per attempt:
     - success / failure and the exception type (`ValidationError`, `UnexpectedModelBehavior`,
       `UsageLimitExceeded`, timeout)
     - wall-clock, prompt / completion / reasoning tokens
     - number of tool calls and their names in order
     - for failures, the raw model output that failed validation
     Emit JSON to `docs/plans/33-local-qwen-migration/resources/probe-results-<effort>.json`.
     Accept `--effort` (`low|medium|high|xhigh`) and `--model` so the same script serves Stage 8.
   - **Set an explicit per-call timeout** (`asyncio.wait_for`, default ≥ 300 s, configurable) and
     record a timeout as its own outcome class. The 2026-08-19 exploratory run of this probe was
     killed after ~25 minutes without completing because it had no timeout — without one, the
     extractor's cost profile presents as a hang rather than a measurement.
   - The librarian and ontology probes need a live DB for their tools. Run under
     `KEEP_RUNNING=1 ./scripts/run_e2e.sh` or against an already-started stack — the tools
     query real schemas and will error against a torn-down database.

2. **Use a fixed probe corpus with known-hard properties.**
   - File: `docs/plans/33-local-qwen-migration/resources/probe-corpus.md` (new)
   - Details: three short episodes, deliberately chosen to trip the known failure modes:
     - **E1 — plain factual**: entities, one clear relation. Baseline sanity.
     - **E2 — temporal correction**: states a fact, then corrects it in the same episode
       ("Correction: it actually landed on the 14th, not the 15th"). Exercises `supersedes` /
       `temporal_signal` and the SUPERSEDES/CORRECTS edge path — a documented Plan 18.5 M4 weak spot.
     - **E3 — adversarial type bait**: entity names that invite instance-level types
       (the `DishGreg` / `LocationSalCapeVerde` shapes from Plan 28) plus tech jargon that
       historically produced garbage types. Reuse the two adversarial documents already written
       in `docs/plans/29-ontology-validation/resources/test_documents.md`.

3. **Record the refusal failure mode explicitly.**
   - Details: the 2026-08-19 probe found the model refusing to use tools and instead fact-checking
     the episode — *"I have no record of 'NeoCortex,' a developer named Zbigniew…"*. The probe
     script must detect and count this specific mode: a run that returns prose, calls zero tools,
     and contains refusal markers (`I can't verify`, `I have no record`, `I don't have access`).
     It is the single most likely Qwen failure against NeoCortex's prompts and it is invisible to
     a plain exception counter because **the run succeeds** — it just does nothing useful.

4. **Sweep effort levels while here.**
   - Details: run the full probe at `low`, `medium`, `high`, and `xhigh`. This is cheap now and
     gives Stage 8 a head start. Specifically record whether `high` behaves distinctly from
     `medium` and `xhigh` — the stock template allowlist is `{low, medium, xhigh}` and unrecognised
     values clamp silently, so `high` may be an alias. Compare reasoning-token counts to tell.

5. **Verify `tool_choice=required` behaviour.**
   - Details: the 2026-08-19 probe saw `tool_choice=required` produce double-wrapped arguments
     (`{"arguments": "{}"}` instead of `{}`). pydantic-ai uses forced tool choice in some
     output-tool configurations. Determine whether any of the four agents hits that path — check
     whether pydantic-ai sends `tool_choice: required` for an agent that has both tools and an
     `output_type` — and if so, record it as a concrete risk with the observed malformation.

6. **Write the findings up.**
   - File: `docs/plans/33-local-qwen-migration/resources/probe-findings.md` (new)
   - Details: a per-agent table — pass rate at N=5 per effort level, failure modes with example
     raw output, tool-call counts vs budget, latency and token cost. End with an explicit
     **per-agent verdict**: `READY` / `NEEDS HARDENING` / `LIKELY BLOCKED`, which is the direct
     input to Stage 3's scope.

---

## Verification

- [ ] `uv run python scripts/probe_local_model.py --effort medium` completes and writes a JSON
      results file for all four agents.
- [ ] `resources/probe-findings.md` exists and contains a verdict for each of the four agents.
- [ ] Every failure in the JSON has its raw model output captured — a failure count with no
      example is not actionable by Stage 3.
- [ ] The refusal-mode counter is present and reported, even if zero.
- [ ] Effort sweep covers `low`, `medium`, `high`, `xhigh`, with reasoning-token counts recorded
      so `high`-vs-`xhigh` aliasing is answerable.

**This stage cannot fail the plan.** A catastrophic result (e.g. librarian 0/5 at every effort)
is a *finding*: record it, mark the stage DONE, and let Stage 7's gate act on it. Do not
attempt fixes here — that is Stage 3.

---

## Commit

`test(models): add local model capability probe harness and findings`
