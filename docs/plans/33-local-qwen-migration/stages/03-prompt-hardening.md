# Stage 3: Iterative Prompt and Compatibility Hardening

**Goal**: Repair every confirmed Flash Next prompt, message-shape, tool, and structured-output failure while keeping both providers on equivalent task instructions.
**Dependencies**: Stage 2 DONE.

## Steps

1. Build a failure matrix from the Stage 2 JSON. Separate transport/template errors from model
   behavior. Start with the known 400 caused by multiple system messages before the user message.
2. Implement the smallest local-compatible fix. Prefer a local-only message coalescing adapter or
   provider request transformation that emits one system message at the beginning. Do not weaken
   ontology/extractor contracts or alter hosted requests. Cover static and dynamic instructions,
   tool definitions, and structured-output calls.
3. Apply evidence-backed prompt fixes: frame user input as source text, make the first tool action
   explicit, require terminal structured output, put dynamic context in stable order, and remove
   duplicate episode text. Add few-shot examples only for violations observed in Stage 2.
4. Extend `neocortex.normalization._TOOL_CALL_ARTIFACT` only for marker shapes observed in real
   outputs. Count every rejection because normalization can prevent stored garbage while dropping an
   entity. Do not replace existing protections.
5. If open `dict` properties appear to cause decode cost, create an isolated extractor schema
   experiment. Keep the production schema unchanged unless a hosted validation run also succeeds.
6. After each focused fix, ask a dedicated GPT-5.6-Luna xhigh subagent to inspect the failing artefact
   and propose a narrow change. Cap each issue at two attempts. Re-run the affected probes using the
   same corpus, effort, endpoint, and model; record before/after evidence in `journal.md`.
7. Stop hardening when all confirmed compatibility failures are resolved or when a heavy issue is
   isolated. Put unresolved product or serving defects in `backlog.md`; do not claim model quality.

## Verification

- [ ] GATE targeted probe rerun — every previously failing request either succeeds or has a named, reproducible backlog root cause; a silent timeout, swallowed exception, or altered fixture makes this red.
- [ ] GATE hosted-path regression tests — `uv run pytest tests/ -q` passes with no weakened assertion; a prompt fix that breaks hosted structured output/tool behavior makes this red.
- [ ] REPORT compatibility delta — record HTTP errors, valid outputs, tool order, rejected entities, and effort/timing before and after in `journal.md`.

## Commit

`fix(prompts): harden Flash Next compatibility without changing hosted semantics`
