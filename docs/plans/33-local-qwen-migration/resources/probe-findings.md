# Stage 2 Flash Next capability probe findings

These findings are from the corrected active local runs on 2026-09-03. They supersede the prior
Stage 2 result files and the retained historical remote-Qwen findings. The evidence is limited to
the four reasoning-agent surfaces.

## Run provenance

Every raw artifact contains a `run_metadata` object with the following measured values:

- Model route: `local:qwen3.8-flash-next`; endpoint URL `http://127.0.0.1:24000/v1`; service model id
  `qwen3.8-flash-next`.
- Authentication: `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY`; the credential value was never
  printed, logged, persisted, or committed.
- Corpus: id `plan33-local-qwen-probe-v1`, repository-relative path
  `docs/plans/33-local-qwen-migration/resources/probe-corpus.md`, SHA-256
  `5e9c2402dc87d2976d4dab0fac1a77689903843bf6d3a3ace2f6f17f062b967f`, exact episode set `[E1, E2, E3]`.
- Invocation: direct PydanticAI agent calls (`pydanticai_agent_direct`), with `job_ids: []` and an
  explicit `NOT_SUBMITTED` explanation. No ingestion jobs were enqueued.
- Each effort: 5 repeats × 3 episodes × 4 agents = 60 real attempts; concurrency 2; per-attempt
  timeout 300 seconds. The N≥5 preference was met for every agent and effort.
- Runs record source revision `920a2083846311a04fdf8bfdf9cfd1febc9f60eb`, source/worktree status,
  source diff SHA-256, probe-script SHA-256, run ID, and UTC start timestamp. The source tree was
  intentionally dirty while this correction was being measured; the hashes identify the exact
  harness used.
- Ontology and librarian used isolated `InMemoryRepository` instances. This is real PydanticAI
  agent/tool-surface evidence, not a PostgreSQL persistence or production-latency quality pass.

Raw records:

- [`probe-results-low.json`](probe-results-low.json)
- [`probe-results-medium.json`](probe-results-medium.json)
- [`probe-results-high.json`](probe-results-high.json)
- [`probe-results-xhigh.json`](probe-results-xhigh.json)

## Outcome distribution

Success counts are per episode attempt. `HTTP 400/order` is the exact local service rejection
`System message must be at the beginning.`

| Agent | low | medium | high | xhigh | Provisional surface finding |
|---|---:|---:|---:|---:|---|
| Ontology | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | NEEDS HARDENING |
| Extractor | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | NEEDS HARDENING |
| Librarian | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | 0/15; 15 HTTP 400/order | NEEDS HARDENING |
| Domain classifier | 13/15; 2 invalid structured output | 14/15; 1 invalid structured output | 14/15; 1 invalid structured output | 12/15; 3 invalid structured output | NEEDS HARDENING |

No attempt timed out. The classifier's invalid-output failures were all E3 and ended with
`UnexpectedModelBehavior: Exceeded maximum retries (1) for output validation`. No model-refusal,
empty-content, or malformed-tool-argument outcome was observed.

## Usage and timing

The values below are medians over successful records unless stated otherwise. Failed transport calls
have no model usage because the service rejected the request before generation; their artifacts say
`usage.availability: NOT_MEASURED` rather than using null. Timing is informational and does not block
migration.

| Effort | Agent | Success | Prompt tokens (median) | Completion tokens (median) | Reasoning tokens (median) | Elapsed p50 / p95 (s) |
|---|---|---:|---:|---:|---:|---:|
| low | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.078 / 0.182; 0.067 / 0.159; 0.095 / 0.152 |
| low | Domain classifier | 13/15 | 1069 | 346 | 196 | 17.123 / 64.057 |
| medium | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.085 / 0.178; 0.066 / 0.152; 0.095 / 0.151 |
| medium | Domain classifier | 14/15 | 1069 | 302 | 192 | 18.216 / 38.995 |
| high | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.074 / 0.156; 0.060 / 0.130; 0.090 / 0.144 |
| high | Domain classifier | 14/15 | 1069 | 342 | 219 | 18.299 / 48.794 |
| xhigh | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.076 / 0.132; 0.064 / 0.142; 0.091 / 0.145 |
| xhigh | Domain classifier | 12/15 | 1069 | 292 | 171 | 15.923 / 55.172 |

Successful classifier records measured one model request, zero retry prompts, and the internal
`final_result` output tool with zero function-tool calls. Ontology, extractor, and librarian emitted
no tool calls because their requests were rejected first; their `tool_calls_available` flags are false.
Completed calls have measured normalization-rejection lists (empty in this run). Rejected calls mark
normalization rejection count, retry count, raw validation output, usage, and tool-call availability as
`NOT_MEASURED`/false because no model result was returned.

## Failure classification and interpretation

The exact HTTP 400 body was recorded in every ontology, extractor, and librarian failure. It names
`code: 400` and `System message must be at the beginning.` This is a request-message ordering
compatibility failure, not a model refusal or an invalid graph result. The affected agents therefore
did not reach their ontology or librarian tools, and no tool order or persistence quality conclusion
can be drawn for them.

Classifier E3 failures are a separate structured-output class. PydanticAI reported one validation
retry budget exhaustion, but because no `RunResult` was returned the retry count, raw validation
payload, and token usage are explicitly `NOT_MEASURED` in the artifact. The generic exception text is
not used as a measured retry or token value. These failures require later compatibility/prompt
investigation before the classifier can be considered ready.

## Provisional finding

**NEEDS HARDENING.** The local service is reachable and the domain classifier can produce valid
structured classifications, but ontology, extractor, and librarian are all blocked by the same
reproducible HTTP 400 message-order contract. Classifier E3 output is not reliable at any effort.
Stage 3 owns the compatibility/prompt repair and must re-run these real-agent probes after its
changes. These findings do not claim that the model is intrinsically unable to perform the tasks.
