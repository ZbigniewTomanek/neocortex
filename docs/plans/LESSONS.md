# Lessons

Durable, cross-plan facts. One line each, linking to the plan that learned it.

This is the file the next plan's author reads before exploring, and the one an unattended
run can reach when no memory server is running. Add a line when a fact cost someone a run
to learn -- especially one that has now been re-derived from scratch in more than one plan.

Keep it short. A fact that only matters inside one plan belongs in that plan's `journal.md`.

| Fact | Learned in | Date |
|------|-----------|------|
| Validate a live harness with a mock model (`--test-model`) before the first live call; the `.tmp/qwen-harness-tuning` run lost ~10 of 13 h to plumbing bugs found live | [33](33-local-qwen-migration/index.md) | 2026-09-10 |
| Every local-model call needs an explicit timeout; one uncapped extractor call ran 3 h 18 min. A timeout is a recorded value, not a crash | [33](33-local-qwen-migration/index.md) | 2026-09-10 |
| Cache upstream pipeline stages and iterate on one agent; never rerun the whole corpus to test one fix | [33](33-local-qwen-migration/index.md) | 2026-09-10 |
| Qwen thinking is disabled with the boolean `false` (`*_THINKING_EFFORT=false`), which maps to `openai_reasoning_effort="none"` plus `chat_template_kwargs.enable_thinking=false`; there is no `none` literal, and pydantic-ai silently drops `thinking=False` for unknown model profiles | [33](33-local-qwen-migration/index.md) | 2026-09-11 |
| asyncpg prepared-statement cache breaks across `search_path`-scoped transactions; schema-scoped pools need `statement_cache_size=0` | [33](33-local-qwen-migration/index.md) | 2026-09-11 |
| Per-event skip evidence (`edge_skipped_*`) exists in the private audit log; a quality verdict needs a privacy-safe export path, or integrity stays `NOT MEASURED` | [34](34-qwen-thinking-benchmark/index.md) | 2026-09-11 |
| Plan 15 S05/S11 and Plan 17 S07 all check that a newer scalar reaches node `content`; a terse extractor plus append-only merge fails all three regardless of model | [34](34-qwen-thinking-benchmark/index.md) | 2026-09-11 |
| Do not gate a thinking-effort sweep on a prior `MIGRATE` verdict; Plan 33 Stage 8 became a no-op and the sweep never ran | [34](34-qwen-thinking-benchmark/index.md) | 2026-09-11 |
