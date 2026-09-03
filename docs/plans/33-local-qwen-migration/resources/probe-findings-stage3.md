# Stage 3 Flash Next compatibility findings

These findings record the real-agent reruns after the local message-mapping adapter. The adapter
was measured against `http://127.0.0.1:24000/v1`, model `qwen3.8-flash-next`, with the configured
`LITELLM_API_KEY` environment variable. The credential value was not printed or persisted.

## Rerun provenance

- Medium artifact: [`stage3-probe-results-medium-after-coalescing.json`](stage3-probe-results-medium-after-coalescing.json)
  with SHA-256 `321eeeb513fc22b4bd6b5afaf59f2959640e547ccad7559c96f9d2e32315c570`.
- The complete medium JSON, including untruncated successful `raw_output`, is retained in the
  compressed sidecar [`stage3-probe-results-medium-after-coalescing.full.json.gz`](stage3-probe-results-medium-after-coalescing.full.json.gz)
  with SHA-256 `71eed69f39a790e9499de42d366e91e437ff58276ff7b6cafbbbfd9f3fa9774d`. The readable
  medium artifact truncates only oversized successful `raw_output` fields and retains all measured
  status, outcome, timing, usage, retry, tool-order, and structured-output fields.
- Low confirmation artifact: [`stage3-probe-results-low-after-coalescing.json`](stage3-probe-results-low-after-coalescing.json)
  with SHA-256 `4f129f91f6d8d83a137fdc97ce7605185040372c345e774364d584ea737b3467`.
- Both runs used corpus id `plan33-local-qwen-probe-v1`, repository-relative corpus path
  `docs/plans/33-local-qwen-migration/resources/probe-corpus.md`, corpus SHA-256
  `5e9c2402dc87d2976d4dab0fac1a77689903843bf6d3a3ace2f6f17f062b967f`, and exact episodes
  `[E1, E2, E3]`. Calls were direct PydanticAI agents with `job_ids: []` and no ingestion jobs.
- Medium settings were 5 repeats, 60 records, concurrency 2, and a 300-second per-attempt timeout.
  Low confirmation settings were 1 repeat, 12 records, concurrency 2, and the same timeout.
- The medium run source revision was `c8743fef7293b3074e7f59a61fe81787dc4df732`, with source-diff
  SHA-256 `718350b423a5dff02ea96f4ef49dc5297bc971573b8e73b8eea9d0d28502ff44`. The low run used the
  same revision and source-diff SHA-256 `77b99d4a31319492cfe1304e807027f2bc1b35e64980c9dd96c3b0124804810c`.
  These hashes identify the uncommitted adapter and focused tests used by each run.

## Compatibility delta

| Agent | Stage 2 medium before | Stage 3 medium after | Low confirmation |
|---|---:|---:|---:|
| Ontology | 0/15; 15 HTTP 400/order | 13/15; 2 timeouts | 3/3 success |
| Extractor | 0/15; 15 HTTP 400/order | 15/15 success | 3/3 success |
| Librarian | 0/15; 15 HTTP 400/order | 15/15 success | 3/3 success |
| Domain classifier | 14/15; 1 invalid structured output | 13/15; 2 invalid structured output | 3/3 success |

The former `System message must be at the beginning.` HTTP 400 was absent from all 72 Stage 3
records. Successful ontology calls reached ontology tools, extractor calls returned structured
results, and successful librarian calls reached graph mutation tools. Medium ontology timeouts at
E2 attempt 2 and E3 attempt 3 reached the explicit 300-second bound and have no inferred usage or
tool data. They are generation-time limits, not transport failures.

Medium classifier failures remained a separate `invalid_structured_output` class. Both were E3 and
ended with `Exceeded maximum retries (1) for output validation`; the probe correctly records retry,
raw validation, usage, and tool availability as `NOT_MEASURED` because no `RunResult` was returned.
Four additional direct E3 classifier diagnostics, using the same model, prompt, and medium effort,
all completed with one valid structured result and no retry. Their varied but valid classifications
did not expose a deterministic malformed marker or schema field. Therefore no classifier prompt
change is evidence-backed by this run; the residual issue is a stochastic output-quality risk for
later quality gates, not a confirmed compatibility defect.

## Tool and timing observations

Medium successful librarian calls retained their tool traces, with 13/15 requiring two validation
retries and 2/15 requiring none. Low confirmation librarian calls were 3/3 successful, with 2/3
requiring two validation retries. No normalization rejection was recorded for successful extractor
or librarian records. Low confirmation ontology, extractor, librarian, and classifier slowest
attempts were respectively 195.179 s, 81.969 s, 95.845 s, and 21.067 s. Latency is informational.

## Stage finding

**Compatibility repaired; quality remains provisional.** The local-only adapter resolves the
confirmed multi-system-message transport defect without changing hosted routing or request tool /
structured-output parameters. The medium run still has two ontology timeouts and two classifier
structured-output misses, so this stage does not certify migration quality. Stage 6/6b must measure
the full local flow and attribute any remaining failures.
