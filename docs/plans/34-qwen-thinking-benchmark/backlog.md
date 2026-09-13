# Backlog (Deferred Issues)

Each entry must be self-contained enough for a future run to pick it up cold.

| # | Title | Origin | Severity | Why deferred | Next step | Status |
|---|-------|--------|----------|--------------|-----------|--------|
| 1 | No env var pins the librarian profile in the worker path | planning (research) | low | `run_extraction(librarian_profile=...)` is only reachable from `qwen_speed_probe.py --profile`; `extract_episode` in `src/neocortex/jobs/tasks.py` never passes it. Qwen models auto-select `qwen_oneshot`, which is the profile this plan measures, so no arm needs the pin. | Add `NEOCORTEX_LIBRARIAN_PROFILE` to `MCPSettings` and thread it through `extract_episode` when a non-default profile must run through services | OPEN |
| 2 | Domain-classification clamp applies to hosted models too | `.tmp/qwen-swift` B2 | low | `DomainClassification.confidence` clamp and empty defaults widened acceptance for every model; hosted prompts unchanged. Not on this plan's path. | Gate the clamp by `is_qwen_model` if strict hosted parity is required | OPEN |
| 3 | One-shot/cap accounting nits | `.tmp/qwen-swift` B3 | low | (a) relation skipped for a temporal pair counts as unchanged even if the temporal upsert later fails; (b) the Qwen entity cap is bypassed on the cached-extraction path used only by the speed probe. Stage 2 closes the uncounted cap-drop part. | Fold (a) and (b) into the next `oneshot_librarian.py` change | OPEN |
| 4 | In-memory probe does not exercise PostgreSQL permissions or latency | Plan 33 backlog 5 | medium | Level selection in Stage 6 runs on `InMemoryRepository`; the service arm in Stage 7 is the only PostgreSQL measurement. Accepted in D-4. | If Stage 7 contradicts a Stage 6 selection, repeat the affected agent's cells against an isolated PostgreSQL schema before changing the level | OPEN |
| 5 | Local `.env` carries a trailing backslash on `NEOCORTEX_EXTRACTION_ENABLED` | `.tmp/qwen-swift` B1 | low | Untracked local file; breaks a bare `MCPSettings()`. The preflight in `resources/commands.md` detects it. | Owner edits `.env`; nothing to commit | OPEN |
| 6 | Stage 6 step 2 misses the new cache key and crashes the cell | stage 1 review F1 | **high** | Verified: step 1 writes `E04-04c212aba9cf` with `--thinking off --thinking-extractor medium`; step 2 as written in `stages/06-per-agent-effort-sweep.md:31-33` computes `E04-957d37180cb3` and misses. `load_cached_extraction` (`qwen_speed_probe.py:512`) sits outside the `try` at `:547`, so the miss propagates out of `run_text`->`run_unit`->`main` and **no output file is written at all** — a traceback, not a `NOT MEASURED` row. | Before running Stage 6: (a) add `--thinking off --thinking-ontology off --thinking-extractor <L_ext>` to the step-2 command in the stage file; (b) wrap the `load_cached_extraction` call so a miss records `error:FileNotFoundError` on the cell and the run continues. Both, not either. | OPEN |
| 7 | Triplet cache key ignores the fixture text and revision | stage 1 review F5 | medium | The key uses `corpus_sha256` (hash of `compact-corpus.md`); triplet texts live in `fact-fixture.json` and contribute nothing to the preimage, so editing a triplet and bumping `revision` silently reuses the old extraction. | Fold `Fixture.revision` (or a hash of the fixture file) into the `cache_key` preimage; same change as item 6. | OPEN |
| 8 | `_node_haystack` can match a multi-word fact across two unrelated nodes | stage 1 review F6 | medium | `fact_retention.py:186-193` joins node fields with a bare space. Demonstrated: nodes `"Encoding length: 8-character"` + `"Metaphone3 for Latin-script input"` credit E26's fact `"8-character Metaphone3 for Latin-script"`, which neither states. Six of 56 facts are exposed. Can only inflate `facts_found`; Stage 6 ranks triplet passes first, which this cannot touch. | Join with a separator no fact can contain (e.g. `"\n\x00"` pre-normalization) or match per field. Fix before Stage 8 publishes the numbers. | OPEN |
| 9 | `--repo shared` cross-credits facts and counts chain edges graph-wide | stage 1 review F2, F3 | low | F2: E27's facts 0/2/3 (`Jonas Weber`, `Sarah Kim`, `Anya Kowalski`) occur verbatim in E02, which runs first, so an E02-only graph scores E27 3/6. F3: `count_temporal_edges` scans every edge, so a `SUPERSEDES` produced at E27 would make the E18->E20->E26 chain read `satisfied: true`. Latent only: every command in this plan uses `--repo fresh`, which the code records as `NOT MEASURED`. | Do not add `--repo shared` to a sweep cell without scoping the haystack to the episode under test and the chain count to the chain's own nodes. | OPEN |
| 10 | The probe's "mirrors the E2E exactly" docstring overclaims for S11 | stage 1 review F4 | low | Exact for S05 and S07. S11's child (`e2e_plan15_scenarios_test.py:699-731`) does not look at node names at all — it recalls and ranks `0.62` against `0.57` in returned content, with real embeddings, while the probe runs `embeddings=none`. Not an implementation defect; the anchor names came from the fixture spec. | Narrow the `score_supersession` docstring to say the mirror is exact for S05/S07 and approximate for S11, before Stage 8 cites the probe as an E2E mirror. | OPEN |
| 11 | `edge_types_after` writes model-proposed type names into the probe summary | stage 1 review F7 | medium | `qwen_speed_probe.py:634-638` emits `{edge_type_name: usage_count}` while the module docstring (`:10-11`) claims "model output never reaches it". Pre-existing at `8766e90`. Stage 6 commits these files under `resources/sweep/*.json`, and Stage 2 is the privacy-evidence stage. | Decide in Stage 2: either drop the names in favour of counts, or state the exemption explicitly in the docstring and the privacy scan. | OPEN |
| 12 | Stage 1's G2 artifact lives only under gitignored `.tmp/` | stage 1 review F8 | low | `stage1-testmodel-*.txt` name `.tmp/plan34/stage1-testmodel.json`, which is absent; the surviving proof is the orchestrator's re-run `.tmp/plan34/stage1-verify.json`. The gate is genuinely met (verified from that JSON and from `test_test_model_run_over_the_full_corpus_and_triplets`), but the proof is not committed. Also `run_meta["episodes"]` records the `--episodes` default even under `--corpus both`, where it is ignored. | No action for Stage 1. Future stages: copy any JSON a gate is read from into `validation/`. | OPEN |

Statuses: `OPEN` -> `IN_PROGRESS` -> `RESOLVED`.

When an item flips to RESOLVED, **revisit its origin stage in the same commit** -- a stage may
not stay BLOCKED on a resolved item. Summarize the fix in `journal.md`. Heavy items may warrant
their own follow-up plan; link it here.

## 2026-09-13 — Stage4 disposition of promoted instrument items

- Items 6, 7, 8, 10 and 11: RESOLVED by Stage4 A1. Cache misses produce explicit
  error rows; source text/revision invalidate cache; fact matching stays within
  fields; S11 approximation and normalized type metadata exemption are explicit.
  Evidence: validation/stage4-instruments-gatefix1-coordinator-attempt1.txt,
  63 passed; scripts/qwen_speed_probe.py and scripts/fact_retention.py.
- Stage1 remains DONE. These items did not block its accepted gates; no spent
  review flags or Stage1 status change. Stage6 uses the corrected instrumentation.
- Item5: prior malformed-setting failure is not reproduced on this machine.
  MCPSettings construction passes without editing .env. Treat as environment-specific,
  not as a committed configuration correction.

## 13 — Recall formatter symptom does not reproduce in memory

- Origin: Stage3 read-only diagnosis, 2026-09-13, codex/gpt-5.6-sol/high.
- Existing recall-session tests pass 14/14; direct recall returns one episode
  and valid formatted JSON, not the placeholder. No demonstrated product fix.
- Non-blocking: Stage3 formatter reproduction is REPORT; Stage7 runs the actual child.
- Next trigger: a live failure with safe source_kind/count/id and placeholder
  observations tied to revision/run identity. Owner: next formatter diagnosis.

## 14 — Critical-defect observation boundaries

- Origin: Stage4 instrumentation, 2026-09-13.
- The probe inspects changed persisted graph types/text and existing failure hooks.
  Rejected proposals before persistence and unknown calls rejected before hooks
  are not observable through these interfaces. Successful structured-output tools
  are audit-redacted as unknown and cannot be counted as unknown executable calls.
- Non-blocking: the report names this limitation; no fabricated detection status.
  Next trigger: extend product audit instrumentation in a separately scoped plan.
  Owner: extraction observability follow-up.
