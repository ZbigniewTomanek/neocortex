# Stage 6b isolation and attribution

This record contains aggregate evidence only. It does not contain source text,
prompts, model output, reasoning, credentials, or model-controlled identifiers.
The local probes used a new in-memory repository for each episode. They were
diagnostic probes, not a full Stage 6 arm.

The historical full Stage 6 diagnostic agent mix is
`ontology`, `extractor`, `librarian`, and `domain_classifier`. The direct E04
and E05 isolation probes exercised only `ontology`, `extractor`, and
`librarian`; they did not exercise `domain_classifier`. Counts below do not
identify individual source records or model-controlled names.

| Failure or metric | Safe raw input paths | Reproduction | Implicated agent union | Confidence | Outcome | Fresh-run requirement |
|---|---|---|---|---|---|---|
| Librarian batch overflow | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json`; `tests/test_librarian_mutation_tools.py` | The deterministic PydanticAI 1.72.0 fixture returns a two-call batch with `tool_calls_limit=1` and `request_limit=10`. It raises `UsageLimitExceeded` before either tool executes after one model request. | librarian | High | Root cause confirmed as whole-batch tool accounting, not request-limit accounting. Local-only serial tool-call mitigation is implemented and observed in E04/E05. | Run a fresh full local arm before any stability or quality claim. |
| Possible partial mutations before a failed librarian attempt | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json`; `scripts/compute_metrics.py`; `src/neocortex/extraction/pipeline.py` | Historical diagnostics recorded successful librarian tool activity before a later limit failure. No rollback or graph-cleanliness proof exists for that attempt. The pipeline now emits a failure event with aggregate mutation count and `graph_cleanliness=NOT_MEASURED`; the metrics collector refuses certification when such an attempt is present. | librarian | High | Architectural risk remains unresolved for a failed attempt. It is fail-closed and cannot certify a graph without direct cleanliness or rollback evidence. | A fresh arm must contain no unproven librarian failures, or must provide a direct rollback/cleanliness proof. |
| Routed-job correlation collision | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json`; `src/neocortex/jobs/correlation.py`; `tests/unit/test_extraction_correlation.py`; `tests/unit/test_admin_jobs.py` | The old derived correlation scheme was not unique for routed work. The replacement generates random opaque ids at every personal, ingestion, and routed extraction enqueue; a 1,000-id collision check and retry tests verify propagation and preservation. | ontology, extractor, librarian on routed extraction | High | Repaired. IDs contain no agent, episode, schema, domain, or source data. A full arm has not yet regenerated run-scoped audit evidence. | Fresh full arm required before per-job audit attribution is accepted. |
| Timeout and retry amplification | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json`; `/tmp/neocortex-stage6b-e04.stderr`; `/tmp/neocortex-stage6b-e05.stderr` | The isolated probes used a bounded 1,200-second episode limit and no queue retry. E04 and E05 completed, but queue-level retry amplification was not exercised. | ontology, extractor, librarian | Medium | `NOT MEASURED` for queue retry amplification. Serial tool calls are genuine workload; no local probe timeout or librarian failure occurred. | Fresh arm must measure terminal queue states, attempt counts, and derived polling deadline. |
| Extractor cardinality and workload versus looping | `docs/plans/33-local-qwen-migration/resources/isolation-evidence-20260906.json`; `src/neocortex/extraction/pipeline.py` | Fresh low-effort local probes at the required endpoint used fixed E04 and E05 inputs. E04 completed with 16 nodes and 13 edges after 52 pipeline tool calls, of which 39 were librarian-phase calls. E05 completed with 26 nodes and 28 edges after 74 pipeline tool calls, of which 63 were librarian-phase calls. In each librarian phase, the maximum tool starts between model requests was 1; failures were 0. Each run emitted one safe `extractor_cardinality` event containing only entity and relation counts. | ontology, extractor, librarian | High for these isolated runs; local-only | Both probes reached terminal curation and consolidation. Counts demonstrate substantive work and do not certify the full corpus. | Fresh full arm required for corpus-level cardinality and completion evidence. |
| Local-versus-hosted attribution | `docs/plans/33-local-qwen-migration/resources/isolation-evidence-20260906.json`; `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | No complete same-input hosted pair or hosted isolation environment was available. The local probes used only the three-agent isolation mix; the four-agent mix belongs to the historical diagnostic. | isolation probe: ontology, extractor, librarian; historical diagnostic: ontology, extractor, librarian, domain_classifier | Low | `NOT MEASURED`. Local observations must not be generalized to hosted behavior. | Obtain two complete same-input hosted runs or retain `NOT MEASURED` and HOLD. |
| Certification after any failed librarian attempt | `scripts/compute_metrics.py`; `tests/unit/test_measurement_harness.py` | A run-scoped audit containing a librarian failure is counted as `unproven_librarian_failures`; the metrics CLI writes only a `NOT_MEASURED` sidecar and does not publish canonical metrics. | librarian | High | Fail-closed gate implemented. It does not hide `UsageLimitExceeded` and does not certify based on observed mutation count alone. | Fresh arm must pass the gate or attach direct cleanliness/rollback evidence. |

## Stage 6 diagnostic outcome matrix

Each diagnostic output has one explicit entry below. The diagnostic input is
the named JSON artifact, and the outcome is not inferred from missing files.
The four-role mix in this matrix is historical full-run attribution; it does
not describe the direct E04/E05 isolation probes.

| Diagnostic output | Safe raw input path | Historical diagnostic agent mix | Confidence | Outcome | Fresh-run requirement |
|---|---|---|---|---|---|
| Completion gate | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `RED`; last queue summary was non-terminal (`todo=45`, `doing=2`). | Fresh full arm must prove terminal queue state before any quality result. |
| Failure rate | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED`; non-terminal jobs prevent a valid denominator. | Fresh arm must provide a terminal summary and apply the unchanged failure-rate threshold. |
| Canonical metrics / integrity | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED`; no canonical metrics or graph-integrity certification is valid from this run. | Fresh arm must pass terminal, audit, graph-cleanliness, and integrity gates. |
| Recall | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED`; no accepted recall evaluation was run. | Fresh arm must run the defined recall checks against the accepted graph snapshot. |
| Post snapshot | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED` as a Stage 6 result; restoration metadata exists but is not a post-arm quality snapshot. | Fresh arm must create and hash the required post-run snapshot before teardown. |
| E2E results | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED`; no accepted end-to-end result exists for the blocked diagnostic. | Fresh arm must complete the defined E2E checks with terminal jobs and clean evidence. |
| Parsing report | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED`; no accepted parsing report was produced. | Fresh arm must retain a privacy-safe parsing report tied to the run id and corpus digest. |
| Quality decision | `docs/plans/33-local-qwen-migration/resources/stage6-diagnostic-20260905T014401Z-stage6fresh2.json` | ontology, extractor, librarian, domain_classifier | High | `NOT MEASURED`; certification is `INVALID` and Stage 6 is `BLOCKED`. | Fresh arm must satisfy all upstream gates before a quality decision is possible. |

## Scope and disposition

The two local probes were run with low effort and a fresh `InMemoryRepository`
per episode. They did not change the restored development graph, run a full
corpus arm, or provide PostgreSQL, queue-retry, hosted comparison, recall, or
quality evidence. The prior Stage 6 run remains invalid; a fresh Stage 6 arm is
pending and must satisfy its own terminal, integrity, and provenance gates.
