# Backlog (Deferred Issues)

Each entry must be self-contained enough for a future run to pick it up cold.

| # | Title | Origin | Severity | Why deferred | Next step | Status |
|---|-------|--------|----------|--------------|-----------|--------|
| 1 | No env var pins the librarian profile in the worker path | planning (research) | low | `run_extraction(librarian_profile=...)` is only reachable from `qwen_speed_probe.py --profile`; `extract_episode` in `src/neocortex/jobs/tasks.py` never passes it. Qwen models auto-select `qwen_oneshot`, which is the profile this plan measures, so no arm needs the pin. | Add `NEOCORTEX_LIBRARIAN_PROFILE` to `MCPSettings` and thread it through `extract_episode` when a non-default profile must run through services | OPEN |
| 2 | Domain-classification clamp applies to hosted models too | `.tmp/qwen-swift` B2 | low | `DomainClassification.confidence` clamp and empty defaults widened acceptance for every model; hosted prompts unchanged. Not on this plan's path. | Gate the clamp by `is_qwen_model` if strict hosted parity is required | OPEN |
| 3 | One-shot/cap accounting nits | `.tmp/qwen-swift` B3 | low | (a) relation skipped for a temporal pair counts as unchanged even if the temporal upsert later fails; (b) the Qwen entity cap is bypassed on the cached-extraction path used only by the speed probe. Stage 2 closes the uncounted cap-drop part. | Fold (a) and (b) into the next `oneshot_librarian.py` change | OPEN |
| 4 | In-memory probe does not exercise PostgreSQL permissions or latency | Plan 33 backlog 5 | medium | Level selection in Stage 6 runs on `InMemoryRepository`; the service arm in Stage 7 is the only PostgreSQL measurement. Accepted in D-4. | If Stage 7 contradicts a Stage 6 selection, repeat the affected agent's cells against an isolated PostgreSQL schema before changing the level | OPEN |
| 5 | Local `.env` carries a trailing backslash on `NEOCORTEX_EXTRACTION_ENABLED` | `.tmp/qwen-swift` B1 | low | Untracked local file; breaks a bare `MCPSettings()`. The preflight in `resources/commands.md` detects it. | Owner edits `.env`; nothing to commit | OPEN |

Statuses: `OPEN` -> `IN_PROGRESS` -> `RESOLVED`.

When an item flips to RESOLVED, **revisit its origin stage in the same commit** -- a stage may
not stay BLOCKED on a resolved item. Summarize the fix in `journal.md`. Heavy items may warrant
their own follow-up plan; link it here.
