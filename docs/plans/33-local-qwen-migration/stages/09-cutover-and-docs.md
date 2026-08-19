# Stage 9: Cutover, Docs, Rollback

**Goal**: Make the validated local configuration the default for every agent that cleared the gate, document it, and leave a one-command rollback.
**Dependencies**: Stage 8 DONE.

---

## Steps

1. **Flip the defaults for MIGRATE agents only.**
   - Files: `src/neocortex/mcp_settings.py` — edit these **eight named fields**, not a line range:
     `ontology_model` / `ontology_thinking_effort` (`:125-126`), `extractor_model` /
     `extractor_thinking_effort` (`:127-128`), `librarian_model` / `librarian_thinking_effort`
     (`:129-130`), `domain_classifier_model` / `domain_classifier_thinking_effort` (`:142-143`).
     **`125-143` is not a contiguous per-agent block** — `extraction_tool_calls_limit`,
     `ontology_tool_calls_limit`, `ontology_max_new_types`, `worker_concurrency`,
     `worker_polling_interval` and `domain_routing_enabled` are interleaved between the librarian and
     the classifier. Editing by range would silently touch the concurrency setting D11 depends on.
   - Details: set `*_model` to `local:qwen3.8-27b` and `*_thinking_effort` to Stage 8's chosen level
     for each agent with a MIGRATE verdict. Agents with HOLD or BLOCKED **keep**
     `openai-responses:gpt-5.4-mini` and their current effort. A mixed default is an expected,
     supported outcome (D4) — do not "tidy" it into uniformity.
   - Also update the hardcoded fallbacks so a config built without settings agrees with the
     defaults: `extraction/agents.py:30-31`, `domains/classifier.py:44`, `domains/seed_generator.py:29`.
     Those three plus the four settings fields are the **7** `openai-responses:` occurrences in
     `src/neocortex/` — verify with `grep -rn "openai-responses:" src/neocortex/` that only the
     HOLD/BLOCKED agents' entries survive.

2. **Set `local_model_base_url` safely.**
   - Details: leave the settings default `None` and document the value in `.env.example`. A
     hardcoded Tailscale hostname in `mcp_settings.py` would make the server unbootable for anyone
     off that tailnet — including CI, if it is ever added. The code must fail with a clear error
     ("local: model requires NEOCORTEX_LOCAL_MODEL_BASE_URL", from Stage 1) rather than hang.

3. **Document the local-model setup.**
   - File: `docs/configuration.md`
   - Details: a new section covering the `local:` prefix, `NEOCORTEX_LOCAL_MODEL_BASE_URL`,
     `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV`, the temperature/top_p knobs, per-agent mixing, and the
     effort allowlist finding from Stage 8. Link this plan's `resources/bakeoff-comparison.md` as
     the evidence.

4. **Fix the stale Gemini references — all of them, not just the five originally listed.**
   - Files, extraction/classifier claims: `CLAUDE.md:109`, `docs/configuration.md:213,220-222`,
     `docs/development.md:222-243`, `README.md:90`, `.claude/skills/neocortex/SKILL.md:60`, and —
     **missed by the original list** — `docs/multi-agent.md:84`
     (`NEOCORTEX_DOMAIN_CLASSIFIER_MODEL` still shown as `google-gla:gemini-3-flash-preview`),
     `docs/e2e-reproduction.md:9` ("GOOGLE_API_KEY … used for extraction agents + embeddings") and
     `:95` ("3 sequential Gemini API calls" per extraction job), and
     `.claude/skills/neocortex/PERMISSIONS.md:130` ("A classifier (Gemini model) assigns semantic
     domain labels").
   - `docs/configuration.md:191` and `:205` are about **embeddings** and **media description** — those
     are correct as they stand and must survive. Same for `CLAUDE.md:11,51`,
     `docs/architecture.md:9,86,90,92` and `docs/how-it-works.md:21`.
   - `docs/reports/00-extraction-pipeline-e2e-validation.md` is a dated historical report describing
     what ran at the time. Leave it; do not rewrite history.
   - Details: every extraction/classifier reference above still claims the pipeline runs on Gemini. It
     has not since commit `e74b441` (2026-04-07). Correct them to describe the post-migration reality,
     and state plainly that **embeddings and media description remain Gemini** so the next reader does
     not assume NeoCortex is fully local.

5. **Complete `.env.example`.**
   - File: `.env.example`
   - Details: it currently documents **neither** `GOOGLE_API_KEY` nor `OPENAI_API_KEY`, both of
     which are required. Add them plus the new local-model keys, with placeholder values only.
     `GOOGLE_API_KEY` remains **required** — `embedding_service.py` silently returns `None` without
     it and degrades recall to text-only with no error (index Backlog #3). Say so in a comment.

6. **Write the rollback.**
   - File: `docs/plans/33-local-qwen-migration/resources/rollback.md`
   - Details: a copy-pasteable env block that restores every agent to
     `openai-responses:gpt-5.4-mini` with the pre-migration effort levels (ontology `medium`,
     extractor `low`, librarian `low`, classifier `medium`), plus
     `./scripts/manage.sh snapshot load baseline-gpt54mini` to restore the pre-migration graph.
     Note that rollback is **config-only** — no code revert is needed, because Stage 1's routing
     leaves the hosted path untouched and Stage 3's prompt hardening was validated against the
     hosted model in Stage 5.

7. **Note what the migration did not cover.**
   - Details: in `docs/configuration.md` and the index, state that embeddings
     (`gemini-embedding-001`) and media description (`gemini-3-flash-preview`) are still cloud
     services, so NeoCortex is **not** fully local or fully offline after this plan. Backlog #1 and
     #2 carry the follow-up.

8. **Final sweep.**
   - Details: work the index Backlog — resolve anything now resolvable, and leave the rest with
     concrete next steps. Confirm every stage in the tracker is DONE or terminally dispositioned.

---

## Verification

- [ ] `uv run pytest tests/ -v` — all pass.
- [ ] `NEOCORTEX_MOCK_DB=true uv run python -m neocortex` boots clean.
- [ ] With `NEOCORTEX_LOCAL_MODEL_BASE_URL` **unset**, a `local:` default produces the clear
      configuration error from Stage 1 — not a hang and not a stack trace on first extraction.
- [ ] `./scripts/run_e2e.sh scripts/e2e_extraction_pipeline_test.py` passes on the shipped defaults.
- [ ] Repo-wide, not just the five files the original list named:
      ```bash
      grep -rn "[Gg]emini" README.md CLAUDE.md docs/ .claude/skills/ \
        --exclude-dir=plans --exclude-dir=reports --exclude-dir=research
      ```
      Every surviving mention must refer to embeddings or media description, never to the extraction
      pipeline or the domain classifier. (`docs/plans/`, `docs/reports/` and `docs/research/` are
      excluded as historical or unrelated.)
- [ ] Rollback rehearsed, not just written: apply `resources/rollback.md`, run the extraction smoke,
      confirm it passes on the hosted model, then restore the local config.
- [ ] `.env.example` lists every required key with placeholders and no real values.
- [ ] `git log --oneline` shows one atomic commit per stage.

---

## Commit

`feat(models): migrate cleared agents to local Qwen3.8-27B defaults`
