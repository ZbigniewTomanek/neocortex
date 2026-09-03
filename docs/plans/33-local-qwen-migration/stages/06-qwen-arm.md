# Stage 6: Full Local Stability and Quality Run

**Goal**: Drive NeoCortex's complete ingestion/extraction flow with `qwen3.8-flash-next` and produce truthful stability and quality evidence.
**Dependencies**: Stages 3 and 4 DONE. Stage 5 is optional and must not block this stage.

## Steps

1. Preflight again immediately before the arm. Set `NEOCORTEX_LOCAL_MODEL_BASE_URL` to
   `http://127.0.0.1:24000/v1`, each in-scope model to `local:qwen3.8-flash-next`, and provide
   `VLLM_API_KEY` through the environment. Confirm `/v1/models` before starting; do not print the key.
   Use the repository token map explicitly: `NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json` and
   `NEOCORTEX_ADMIN_TOKEN=admin-token`. These names are verified in the repository root:
   `dev_tokens.json` maps `admin-token` to the bootstrap `admin` identity. Do not use the test token
   file or the obsolete `admin-token-neocortex` fallback for this arm.
2. Use the fixed 28-episode corpus, identical Stage 3 prompts/schema, and a worker concurrency safe
   for this local service. Configure explicit per-call and job-poll timeouts. Long processing is
   acceptable, but a non-terminal job after the derived deadline is a stability failure, not success.
3. Run `NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json NEOCORTEX_ADMIN_TOKEN=admin-token
   ./scripts/model_bakeoff.sh --arm qwen-flash-next` (update the harness if its arm name or model
   defaults still refer to the superseded remote target). Save raw job events, metrics JSON, and a named graph
   snapshot. Include model id, endpoint, effort, seed/schema version, and commit in metadata.
4. Inspect Tier 1 integrity: stored type names, artifact markers in names/content, normalization
   rejection rate, structured-output failures, tool-order violations, auth failures, and dropped
   entities. Read rejection evidence before treating zero stored artifacts as meaningful.
5. Run the existing extraction, episodic-memory, cognitive-recall, and scenario scripts only when
   their authentication and lifecycle are configured. Parse scenario score lines rather than trusting
   scripts that always exit zero. Record missing scripts/signals as `NOT MEASURED`.
6. Have a fresh dedicated GPT-5.6-Luna xhigh subagent audit the raw artefacts and provenance. If a
   light failure appears, delegate at most two focused repairs and rerun the affected measurement;
   do not tune prompts or thresholds after seeing a local result without rerunning shared inputs.

## Verification

- [ ] GATE full local job completion — read terminal states and failure/stall rate from this run's `/admin/jobs/summary` and event records; any non-terminal job or rate above 10% makes this red.
- [ ] GATE integrity scan — read `resources/metrics-qwen-flash-next.json` and the named snapshot; any stored artifact, leaked marker, invalid type, unhandled auth/structured-output failure, or unexplained rejection makes this red.
- [ ] REPORT quality, tool, token, and timing metrics — record raw file paths, counts, and `NOT MEASURED` signals in `journal.md`; latency never blocks.

## Commit

`test(models): run full local Qwen Flash Next stability arm`
