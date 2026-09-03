# Backlog (Deferred Issues)

Each entry is self-contained enough for a future run to pick up cold. A backlog item must not be used
as an excuse to propagate `BLOCKED` to a dependent stage.

| # | Title | Origin | Severity | Why deferred | Next step | Status |
|---|-------|--------|----------|--------------|-----------|--------|
| 1 | Embeddings remain cloud-bound | planning | medium | `gemini-embedding-001` vectors are 768-dimensional and already persisted; changing the model requires a full re-embed | Design a separate local 768-dim backend and backfill job | OPEN |
| 2 | Media description remains cloud-bound | planning | low | Audio/video description uses Gemini Files API and has no validated local multimodal equivalent | Evaluate a local multimodal service in a separate plan | OPEN |
| 3 | Embedding credentials can degrade recall silently | pre-existing | medium | `EmbeddingService` may return `None` without `GOOGLE_API_KEY`, causing text-only recall | Add a startup health check and a test; keep bake-off preflight explicit | OPEN |
| 4 | Rejected artifact entities are dropped | planning | medium | Normalization rejects bad type names, then extraction skips the entity without a quarantine record | Add rejection counts to extraction results/job records and consider safe repair | OPEN |
| 5 | Probe backend may differ from production PostgreSQL | Stage 2 | medium | In-memory tools avoid mutating the development graph but do not exercise SQL permissions or query latency | Repeat a small probe in an isolated PostgreSQL schema before interpreting backend-specific failures | OPEN |
| 6 | Hosted baseline may remain incomplete | Stage 5 | medium | Prior second run hung and cannot define variance; local execution must remain independent | Run two complete same-prompt hosted arms when credentials and an isolated environment are available; otherwise retain `NOT MEASURED` | OPEN |
| 7 | Open-dictionary extractor experiment | Stage 3 | medium | Narrowing `properties` could reduce local decode cost but would change schema semantics | Run isolated schema variants and validate the hosted arm before proposing a product change | OPEN |
| 8 | Harness live verification | Stage 4 | medium | Unit/dry-run checks cannot prove admin auth, job polling, or snapshot integrity | Run the preflight and full orchestrator in the dedicated environment; record raw JSON and timelines | OPEN |
| 9 | System-message compatibility repair | Stage 2/3 | high | Resolved by the local-only adapter in commit `1df6c2a`; strict single-system-message mapping is covered by focused tests and live reruns | Done: medium and low reruns recorded in `journal.md` and `resources/probe-findings-stage3.md`; hosted behavior remained unchanged | RESOLVED |
| 10 | Probe corpus loader symbol drift | Stage 2/4 | medium | Probe code may import `load_probe_corpus` while the loader now exports `load_corpus` | Add a compatibility alias or update all call sites; add an import test | OPEN |
| 11 | Local endpoint identity or auth failure | Stage 1 | high | ~~Exact environment `VLLM_API_KEY` returns HTTP 401 although the endpoint exposes the required model; a process-only credential alias succeeds~~ → The active endpoint credential is configured explicitly as `LITELLM_API_KEY` | Set `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY`, rerun the authenticated preflight without recording the key, and fail fast when a configured key is absent | RESOLVED |
| 12 | Flash Next residual generation reliability | Stage 3 | high | The local-only message adapter removes all 72 observed system-order 400s, but the medium rerun still had 2/15 ontology timeouts at 300 seconds and 2/15 E3 classifier structured-output failures; four additional direct E3 checks succeeded, so the classifier miss is not yet a deterministic schema defect | Stage 6/6b must measure full-flow completion and isolate ontology timeout and classifier output behavior at the selected low effort before any cutover; keep hosted semantics unchanged | OPEN |

Statuses: `OPEN` -> `IN_PROGRESS` -> `RESOLVED`. When an item is resolved, revisit its origin stage in
the same commit and record the evidence in `journal.md`. If an item remains outside this plan's scope,
close it as `DEFERRED → <successor plan>` rather than leaving an ambiguous terminal state.
