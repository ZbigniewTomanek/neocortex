# Stage 9: Conditional Cutover or ASD-STE100 Technical Report

**Goal**: Cut over only validated agents, or explain the inadequate result in a clear technical report with root cause and a concrete next action. Include the per-episode parsing report.
**Dependencies**: Stage 8 DONE. Stage 8 is a control stage and records a no-op `DONE` outcome when no
agent passes, so this stage always remains reachable for the ASD-STE100 report path.

## Steps

1. For each `MIGRATE` agent, set the named `*_model` default to `local:qwen3.8-flash-next` and its
   measured effort. Keep `HOLD` and `BLOCKED` agents on their existing hosted model. Update fallback
   constants, factory settings, and tests together. Do not alter interleaved concurrency settings.
2. Keep `local_model_base_url` unset by default. Document
   `NEOCORTEX_LOCAL_MODEL_BASE_URL=http://127.0.0.1:24000/v1` and
   `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=VLLM_API_KEY` in `.env.example` using placeholders only.
3. Document per-agent mixing, explicit effort, sampling/timeout settings, the endpoint preflight,
   rollback, and the fact that embeddings and media description still use cloud services.
4. Fix active extraction/classifier documentation that still claims Gemini or remote Qwen. Preserve
   dated historical reports and historical evidence files. Remove stale remote endpoint/model values
   from operational commands used for cold execution; label retained raw remote JSON as historical.
5. Write `resources/rollback.md`: restore all hosted model/effort settings, load the baseline snapshot
   when it exists, and state that rollback is config-only. Never put an API key in the rollback file.
6. If any agent is not suitable, write `resources/technical-report.md` in ASD-STE100 technical English:
   use short active sentences, one term for one meaning, condition before command, explicit evidence,
   root cause, impact, workaround, and next action. Include `NOT MEASURED` where instrumentation did
   not produce a signal. Do not call the result a full-local migration.
7. Reference `resources/qwen-parsing-report.md` and `resources/qwen-parsing-report.json` in the
   cutover or technical report. Keep both files with the final plan evidence.
8. If a required report file is missing or incomplete, record `NOT MEASURED` and block cutover.
9. Run the final tests and a fresh local smoke. Have a dedicated GPT-5.6-Luna xhigh subagent review
   the cutover/report for secret leakage, stale active references, and evidence provenance.

## Verification

- [ ] GATE final code/documentation tests — `uv run pytest tests/ -q`, local mock boot, and configuration validation pass; a hosted-path regression or missing clear base-URL error makes this red.
- [ ] GATE cutover/report completeness — every verdict has a validated default plus rollback or an ASD-STE100 report with evidence and root cause. The per-episode report is also present. An unsupported claim makes this red.
- [ ] REPORT final model/config scan — record changed defaults, surviving hosted agents, cloud-bound services, rollback rehearsal, and unresolved backlog items in `journal.md`.

## Commit

`feat(models): cut over validated agents or publish Flash Next report`
