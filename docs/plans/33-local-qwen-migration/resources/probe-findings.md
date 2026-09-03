# Stage 2 Flash Next capability probe findings

These findings are from the active local run on 2026-09-03. They replace the retained
historical remote-Qwen findings and are limited to the four reasoning-agent surfaces.

## Run provenance

- Model: `local:qwen3.8-flash-next` (the service model id is `qwen3.8-flash-next`).
- Endpoint: `http://127.0.0.1:24000/v1`.
- Authentication: the process-only `LITELLM_API_KEY` environment value, selected by
  `NEOCORTEX_LOCAL_MODEL_API_KEY_ENV=LITELLM_API_KEY`; no key value was recorded.
- Input: the fixed three-episode corpus in [`probe-corpus.md`](probe-corpus.md). Every record
  contains the source path and SHA-256 of the exact episode text.
- Four efforts: low, medium, high, and xhigh.
- Each effort: 5 attempts × 3 episodes × 4 agents = 60 real attempts; concurrency 2; per-attempt
  timeout 300 seconds. The N≥5 preference was met for every agent and effort.
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
| Domain classifier | 14/15; 1 invalid structured output | 15/15 | 12/15; 3 invalid structured output | 14/15; 1 invalid structured output | NEEDS HARDENING |

No attempt timed out. The classifier's invalid-output failures were all E3 and ended with
`UnexpectedModelBehavior: Exceeded maximum retries (1) for output validation`. No model-refusal,
empty-content, or malformed-tool-argument outcome was observed in this run.

## Usage and timing

The values below are medians over successful records unless stated otherwise. Failed transport calls
have no model usage because the service rejected the request before generation. Timing is informational
and does not block migration.

| Effort | Agent | Success | Prompt tokens (median) | Completion tokens (median) | Reasoning tokens (median) | Elapsed p50 / p95 (s) |
|---|---|---:|---:|---:|---:|---:|
| low | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.085 / 0.141; 0.060 / 0.073; 0.095 / 0.172 |
| low | Domain classifier | 14/15 | 1069 | 282 | 171 | 15.075 / 29.308 |
| medium | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.098 / 0.164; 0.068 / 0.151; 0.109 / 0.127 |
| medium | Domain classifier | 15/15 | 1069 | 370 | 256 | 20.626 / 33.819 |
| high | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.076 / 0.141; 0.068 / 0.129; 0.091 / 0.172 |
| high | Domain classifier | 12/15 | 1069 | 314 | 178 | 17.171 / 49.580 |
| xhigh | Ontology / Extractor / Librarian | 0/15 each | NOT MEASURED | NOT MEASURED | NOT MEASURED | 0.080 / 0.154; 0.067 / 0.128; 0.101 / 0.164 |
| xhigh | Domain classifier | 14/15 | 1069 | 345 | 227 | 18.436 / 48.945 |

The classifier's successful records used one request and zero retries. Internal structured-output
records identify the `final_result` output tool; the usage counter reports zero function tool calls.
Ontology, extractor, and librarian emitted no tool calls because their requests were rejected first.
Normalization rejection counts were zero on completed calls and there was no opportunity to exercise
ontology `propose_type` validation after the transport rejection.

## Failure classification and interpretation

The exact HTTP 400 body was recorded in every ontology, extractor, and librarian failure. It names
`code: 400` and `System message must be at the beginning.` This is a request-message ordering
compatibility failure, not a model refusal or an invalid graph result. The affected agents therefore
did not reach their ontology or librarian tools, and no tool order or persistence quality conclusion
can be drawn for them.

Classifier E3 failures are a separate structured-output class. They exhausted PydanticAI's one
validation retry and did not report a transport error. They require a later compatibility/prompt
investigation before the classifier can be considered ready.

## Provisional finding

**NEEDS HARDENING.** The local service is reachable and the domain classifier can produce valid
structured classifications, but ontology, extractor, and librarian are all blocked by the same
reproducible HTTP 400 message-order contract. Classifier E3 output is not reliable at every effort.
Stage 3 owns the compatibility repair and must re-run these real-agent probes before any quality or
cutover conclusion. These findings do not claim that the model is intrinsically unable to perform
the tasks.
