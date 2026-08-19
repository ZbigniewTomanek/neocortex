# Stage 2 capability probe findings

The probe corpus contains E1 (factual), E2 (temporal correction), and E3 (adversarial
type bait). Each effort file contains 60 records: five attempts for each episode and
each of the four agents. The live sweep used concurrency 6 and a 30-second per-call
timeout for `low`, `high`, and `xhigh`; the `medium` sweep used a 60-second timeout
after an initial serial run showed that the 300-second default made the full sweep
impractical. A timeout is an observed outcome, not a successful response.

## Results

| Agent | low (success/5) | medium (success/5) | high (success/5) | xhigh (success/5) | Verdict |
|---|---:|---:|---:|---:|---|
| Ontology | 0/5 (15 timeouts) | 0/5 (15 timeouts at 60s) | 0/5 (15 timeouts) | 0/5 (15 timeouts) | NEEDS HARDENING |
| Extractor | 0/5 (15 timeouts) | 1/5 (12 timeouts at 60s) | 0/5 (15 timeouts) | 1/5 (14 timeouts) | NEEDS HARDENING |
| Librarian | 0/5 (15 timeouts) | 0/5 (14 timeouts at 60s) | 0/5 (15 timeouts) | 0/5 (15 timeouts) | NEEDS HARDENING |
| Domain classifier | 1/5 (11 timeouts) | 4/5 (3 timeouts at 60s) | 1/5 (13 timeouts) | 1/5 (14 timeouts) | READY WITH TIMEOUT CAVEAT |

The `success/5` column is episode-level: each agent has 15 records, three episodes
per attempt. The raw JSON remains authoritative for per-episode detail, elapsed time,
usage, and tool-call order.

The result is dominated by decode cost at these caps. The successful medium extractor
record used 3,350 reasoning tokens in the earlier real-schema probe; the present
medium sweep's successful extractor record is the same class of expensive call. No
refusal-mode records were detected in any generated file. This does not retire the
refusal risk: the detector is present, and the earlier raw probe reproduced the
zero-tool refusal against a weak prompt.

## Tool behavior

Successful librarian records emitted real `create_or_update_node` and
`create_or_update_edge` calls. Successful records preserve tool names in order. No
probe result showed an explicit forced `tool_choice=required` request; therefore the
double-wrapped-arguments defect from the raw HTTP probe was **not reproduced through
these four PydanticAI construction paths**. This is an observation, not proof that
future output-tool configurations cannot select that path.

## Per-agent interpretation for Stage 3

- **Ontology — NEEDS HARDENING.** No capped run completed. Re-probe after the
  source-text framing and mandatory-first-action prompt changes; preserve the
  explicit list/find/propose workflow.
- **Extractor — NEEDS HARDENING.** The real schema remains decode-expensive and
  higher effort is not demonstrably better. Stage 3 should remove duplicated
  episode text and evaluate narrowing the open properties dictionaries.
- **Librarian — NEEDS HARDENING.** The long tool loop did not reliably reach its
  terminal structured output under the sweep caps. Harden terminal-output
  instructions and retain the tool budget.
- **Domain classifier — READY WITH TIMEOUT CAVEAT.** It had the highest completion
  rate at medium, but the effort sweep is not a quality verdict. Keep its fallback,
  add explicit source-text framing, and verify again after shared prompt hardening.

The probe harness used `InMemoryRepository` for repeatability and to avoid mutating
the shared development graph; the service stack was started as required, but these
measurements exercise the real agent/tool surfaces rather than production PostgreSQL
latency. The bake-off stages must use the real graph and the prescribed worker
concurrency.
