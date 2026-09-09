# Stage 4: Harness, Instrumentation, and Authentication Stability

**Goal**: Make the bake-off and stability evidence reproducible, authenticated, timeout-bounded, and resistant to silent metric fabrication.
**Dependencies**: Stage 1 DONE; run after Stage 3 where possible so both arms share prompts.

## Steps

1. Inspect `scripts/corpus_loader.py`, `scripts/compute_metrics.py`, `scripts/model_bakeoff.sh`, and
   `src/neocortex/extraction/pipeline.py`. Repair missing imports, stale model defaults, and parser
   assumptions found by a dry run. A loader must parse the fixed 28-episode corpus without changing it.
   D38 adds an explicit compact profile; retain the original full default and validate both profiles.
2. Ensure every metric contains its input path and run metadata. Graph metrics must read the live
   snapshot; token and timing metrics must read structured audit events; job metrics must read the
   admin API. Never generate rows to meet a count and never copy a target into output.
3. Instrument model calls, tool calls, structured-output retries, normalization rejections, and stage
   timings in `log/agent_actions.log`. Keep secret values out of logs. Include model id, endpoint
   identity (not credentials), agent, effort, and correlation/job id.
4. Validate admin and MCP authentication with explicit environment tokens. Assert embeddings are live
   before graph-derived recall metrics because missing `GOOGLE_API_KEY` otherwise degrades recall
   silently. Preserve snapshots before any fresh run and cleanly restore them after checks.
5. Derive a completion poll timeout from configured per-call timeout, corpus size, and worker
   concurrency. Abort without writing quality metrics when jobs remain non-terminal; record the exact
   state as `NOT MEASURED` and open a backlog item instead.
6. Use a fresh GPT-5.6-Luna xhigh subagent to audit each measured GATE's provenance: it must identify
   the input file/API response and a defect that would make the check fail.

## Verification

- [x] GATE `uv run python scripts/corpus_loader.py --dry-run` and harness unit tests — the fixed corpus parses and generated metrics contain real input references; parser fabrication makes this red.
- [x] GATE auth and timeout self-check — invalid admin/MCP credentials fail clearly and a deliberately non-terminal job cannot produce a PASS metrics file.
- [x] REPORT `./scripts/model_bakeoff.sh --arm qwen-flash-next-compact --corpus-profile compact --dry-run` — record resolved model, endpoint, effort, concurrency, timeout, and output paths without exposing keys.

## Commit

`test(models): stabilize local bake-off instrumentation and auth`
