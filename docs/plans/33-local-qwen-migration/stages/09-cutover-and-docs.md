# Stage 9: Cutover, Docs, Rollback

**Goal**: Make the validated local configuration the default for every agent that cleared the gate, document it, and leave a one-command rollback.
**Dependencies**: Stage 8 DONE.

---

## Steps

1. **Flip the defaults for MIGRATE agents only.**
   - Files: `src/neocortex/mcp_settings.py:125-143`
   - Details: set `*_model` to `local:qwen3.8-27b` and `*_thinking_effort` to Stage 8's chosen level
     for each agent with a MIGRATE verdict. Agents with HOLD or BLOCKED **keep**
     `openai-responses:gpt-5.4-mini` and their current effort. A mixed default is an expected,
     supported outcome (D4) — do not "tidy" it into uniformity.
   - Also update the hardcoded fallbacks so a config built without settings agrees with the
     defaults: `extraction/agents.py:30-31`, `domains/classifier.py:44`, `domains/seed_generator.py:29`.

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

4. **Fix the stale Gemini references.**
   - Files: `CLAUDE.md:109`, `docs/configuration.md:191,205,213,220-222`,
     `docs/development.md:222-243`, `README.md:90`, `.claude/skills/neocortex/SKILL.md:60`
   - Details: every one of these still claims the pipeline runs on Gemini. It has not since commit
     `e74b441` (2026-04-07). Correct them to describe the post-migration reality, and state plainly
     that **embeddings and media description remain Gemini** so the next reader does not assume
     NeoCortex is fully local.

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
- [ ] `grep -rn "[Gg]emini" CLAUDE.md README.md docs/configuration.md docs/development.md .claude/skills/neocortex/SKILL.md`
      — every surviving mention refers to embeddings or media description, never to the extraction pipeline.
- [ ] Rollback rehearsed, not just written: apply `resources/rollback.md`, run the extraction smoke,
      confirm it passes on the hosted model, then restore the local config.
- [ ] `.env.example` lists every required key with placeholders and no real values.
- [ ] `git log --oneline` shows one atomic commit per stage.

---

## Commit

`feat(models): migrate cleared agents to local Qwen3.8-27B defaults`
