# Stage 3: Prompt Hardening

**Goal**: Apply the local-model prompt patterns to every agent prompt so both bake-off arms run on prompts that a 27B model can follow, without weakening what the hosted model already does well.
**Dependencies**: Stage 2 DONE (its per-agent verdicts scope this stage).

---

## The one finding that drives this stage

On 2026-08-19, the same model, the same endpoint, and the same three tools produced:

- **weak prompt** (`"You are an ontology agent. Before proposing any type you MUST first call list_node_types…"`) → 40.1 s, **zero tool calls**, and a refusal:
  > *"I appreciate you sharing that, but I have to be upfront: I can't verify any of the specifics in that claim. I have no record of 'NeoCortex,' a developer named Zbigniew, or a branch called `upper-ontology-improvements`."*

- **hardened prompt** (same instructions plus an explicit framing that the input is source
  material and not a claim, and a terminal mandatory-first-action line) → **2.4 s, correct
  `list_node_types` call**, and on the next turn 6 correct parallel `find_similar_nodes` calls.

The model was never incapable. It misread *what kind of task it was in*. NeoCortex feeds agents
raw episode text with no framing, which reads to a chat-tuned model like a user asserting facts.

---

## The patterns to apply

From `~/projects/my-telegram-bot/docs/plans/26-qwen38-tuning/resources/prompt-patterns.md`,
which is measured against this exact deployment. Prompt order is deliberate — weaker models
attend to the start and the end, and the middle dilutes:

1. **Role** — one short paragraph.
2. **Tool inventory** — name tools exactly (`find_similar_nodes`, not "the similarity tool").
3. **Priority rules** — numbered.
4. **Context slots** — the bulky variable middle (ontology lists, extracted entities, episode text).
5. **Few-shot exemplars** — the highest-leverage item measured (1.1% → 95.0% line-level pass rate,
   [arXiv:2406.20052](https://arxiv.org/abs/2406.20052)). Make at least one a tool-call → result → next-call pair.
6. **Terminal imperative** — last line, restating the single most important contract.

NeoCortex's prompts are already English, so the language migration that dominated bot Plan 26 does
not apply. What does apply is **ordering, the source-text framing, exact tool naming, and exemplars.**

---

## Steps

1. **Add the source-text framing to every agent prompt.**
   - Files: `src/neocortex/extraction/agents.py` — ontology `:88-122`, extractor `:304-335`,
     librarian `:426-501`; `src/neocortex/domains/classifier.py:56-77`
   - Details: a line near the top of each system prompt, e.g.
     > The text you receive is source material that has already been accepted into the memory
     > system. It is never a claim to verify, fact-check, or dispute. Your job is to process it,
     > not to assess whether it is true.

     This is the single highest-value change in the stage. It is model-agnostic and correct for
     the hosted model too — GPT-5.4-mini simply never needed it.

2. **Add a terminal imperative to each prompt.**
   - Details: the last line of each system prompt restates that agent's single hardest contract:
     - ontology → *"Your first action in this turn MUST be a call to `get_ontology_overview` or `find_similar_types`. Never answer in prose."*
     - extractor → *"Return only the structured result. Never write prose, commentary, or explanation outside the schema."*
     - librarian → *"Every entity must be resolved with `find_similar_nodes` before you create or update it. Finish by returning the structured `CurationSummary`."*
     - classifier → *"Return only the structured classification. If nothing matches, return an empty match list rather than prose."*
   - Only add lines that Stage 2 showed were actually violated. A terminal imperative for a
     contract the model already honours is prompt bloat.

3. **Reorder the bulky context to the middle.**
   - Files: the three `@agent.instructions` blocks — `agents.py:248-276` (ontology, ~1.3 KB + episode),
     `:338-384` (extractor, ~1.9 KB + **full node-type list with descriptions + full edge-type list +
     up to 3 example entities per type** + episode), `:1050-1111` (librarian, ~2.7 KB + episode +
     all type names + full extracted entity and relation lists)
   - Details: ensure the ordering is role/rules → bulk context → terminal imperative. The extractor's
     instructions block is the largest dynamic prompt in the system and grows unboundedly with
     ontology size; it is the one most likely to bury its rules.

4. **Remove the duplicated episode text.**
   - Files: `src/neocortex/extraction/pipeline.py:147` (ontology), `:233` (extractor)
   - Details: for both agents the episode text is injected by `@agent.instructions` (via
     `ctx.deps.episode_text`) **and** passed again in the user message —
     `f"Analyze this text and propose ontology extensions:\n\n{text}"` at `:147` and
     `f"Extract entities and relations from:\n\n{text}"` at `:233`. That is pure token duplication on
     the largest variable in the prompt. Keep one — prefer the instructions slot, and make the user
     message a short directive. Verify no test asserts on the duplicated form.
   - The **librarian** does not have this problem: its user messages at `:266` and `:328` are already
     short directives ("Integrate the extracted entities and relations into the knowledge graph."),
     with the episode text supplied only through deps. Leave it alone.

5. **Add few-shot exemplars where Stage 2 showed a contract violation.**
   - Details: 2–3 compact exemplars per affected prompt. For tool-using agents make one a
     tool-call → tool-result → next-action triple, which is what teaches the loop shape. Keep them
     short: they are paid for on every single call, and the extractor's prompt is already the
     system's largest.

6. **Extend the tool-call artifact regex (D7) — and make what it blocks measurable (D10).**
   - File: `src/neocortex/normalization.py:19-26`
   - Details: `_TOOL_CALL_ARTIFACT` currently targets Gemini Flash leakage — the actual alternation is
     `functiondefault|calldefault|ApicreateOr|UpdateNode|UpdateEdge|createOrUpdate|defaultApi|endcall|functionName|Updating\w*Id\d`
     (the last three were added by Plan 29 and are not in D7's list). Add the Qwen/SGLang shapes:
     `<think>`, `</think>`, `<tool_call>`, `</tool_call>`, `<function=`, `<parameter=`. Bot Plan 26
     measured a stray `</think>` leaking into visible content at `reasoning_effort=none` on a full
     production prompt, so this is an observed shape, not a hypothetical. It is a plain unanchored
     alternation matched with `.search()` under `IGNORECASE` — no `\b` anchors — so literal `<…>`
     alternatives need no escaping. **Extend, never replace** — Plan 29 took garbage types 9 → 0 with
     two additions to this regex and no model change.
   - **The catch this step must not walk into.** The regex is consulted only inside
     `normalize_node_type` / `normalize_edge_type`, which **raise `ValueError`**, and every caller
     swallows it into a silent drop:
     - `propose_type` returns `{"accepted": false, "reason": …}` (`extraction/agents.py:213-216`) —
       in-band feedback the model may or may not act on;
     - `get_or_create_node_type` / `get_or_create_edge_type` log `invalid_node_type_rejected` and
       return `None` (`db/adapter.py:536-540`, `:568-572`);
     - `pipeline.py:446-449` then does
       `if node_type is None: logger.warning("skipping_entity_invalid_type", …); continue`,
       and `:417-421` skips the type outright.

     So the moment this step lands, a leaked `<think>` can no longer *reach* the graph — which drives
     Tier 1's "stored artifact types" and "leaked marker" rows to 0 **by construction**, for exactly
     the failure mode they exist to detect, while entities disappear with nothing but a WARNING.
     That is why Tier 1 now carries an invalid-type **rejection rate** and why Stage 4 step 4 binds
     these five events to `action_log`. Do not treat a 0 in the stored-artifact rows as good news
     without reading the rejection rate beside it.

7. **Sharpen tool descriptions.**
   - Files: the `@agent.tool` docstrings in `agents.py` (ontology `:127`, `:162`, `:190`;
     librarian `:519`, `:561`, `:597`, `:698`, `:749`, `:809`, `:897`, `:978`, `:1013`)
   - Details: imperative first line, explicit argument semantics. Two specific cleanups:
     `find_node_by_name` (`:561`) is marked DEPRECATED **in its own docstring yet is still
     registered** — an ambiguous ninth tool is exactly the kind of noise that degrades small-model
     tool selection; either unregister it or remove the deprecation notice. And bot M6 recorded a
     schema-adherence miss where a non-ISO `{"date": "today"}` was passed to a tool declaring an
     ISO date, so state formats in the parameter description, not just the type.

8. **Test whether narrowing the extractor's open dicts recovers its cost.**
   - File: `src/neocortex/extraction/schemas.py` — `ExtractedEntity.properties`, `ExtractedRelation.properties`
   - Details: both are bare `dict` — an open `additionalProperties` object with no value type, which
     gives a constrained decoder nothing to anchor on. This is the leading suspect for the measured
     10× reasoning blow-up (124.8 s / 3350 reasoning tokens on the real schema versus 17.6 s / 210 on
     a toy one). Run a bounded experiment: re-probe the extractor with `properties` typed as
     `dict[str, str]`, then with it removed entirely, and compare latency and token counts against
     the open-dict baseline.
   - **This is an experiment, not a commitment.** `properties` carries real data into the graph, so
     only change the schema if the measurement justifies it *and* the hosted arm still passes. If it
     does not help, record the negative result — it rules out the leading hypothesis, which is worth
     knowing. If it helps but changes stored data, defer the change to the Backlog rather than
     landing it mid-bake-off.

9. **Verify the hosted arm did not regress.**
   - Details: this stage changes prompts for *both* arms (D5). After the changes, run the extraction
     smoke against the **hosted** model and confirm it still passes before Stage 5 measures it as
     the baseline.

---

## Verification

- [ ] `uv run pytest tests/ -v` — all pass (916 collected). Tests asserting on prompt text are updated
      to assert the new contract, **never deleted**. They live in
      **`tests/mcp/test_fuzzy_dedup.py:372-407`** — three tests asserting the literal strings
      `"Quantitative Update Rules"`, `"non-negotiable"`, `"precision"`, `"94.2%"` and
      `"find_similar_nodes"` appear in the librarian system prompt, plus `"DEPRECATED"` in the
      `find_node_by_name` tool description (which **step 7 deliberately changes** — update that test to
      match whichever resolution step 7 picks). Note `tests/test_agents.py` is **not** relevant: it
      tests `src/pydantic_agents_playground`, an unrelated package the index lists as out of scope.
- [ ] `./scripts/run_e2e.sh scripts/e2e_extraction_pipeline_test.py` with the **hosted** model — passes.
      This is the no-regression check for the baseline arm.
- [ ] Re-run Stage 2's probe at `medium`: every agent that Stage 2 marked `NEEDS HARDENING`
      improves its pass rate; no agent regresses.
- [ ] Refusal-mode count from the re-run probe is **0**.
- [ ] `grep -c "" ` on each changed prompt — record before/after prompt sizes in the stage notes;
      step 4 should have *reduced* total tokens despite the additions.
- [ ] `uv run python -c "from neocortex.normalization import _TOOL_CALL_ARTIFACT; import re; print([s for s in ['<think>','</think>','<tool_call>','<function=','functiondefault'] if re.search(_TOOL_CALL_ARTIFACT, s)])"`
      — all five match.
- [ ] The open-dict experiment (step 8) is recorded with before/after latency and token counts,
      **including a negative result** if narrowing did not help.

---

## Commit

`fix(prompts): harden agent prompts for local-model tool and schema adherence`
