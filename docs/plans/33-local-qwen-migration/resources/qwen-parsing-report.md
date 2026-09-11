# Qwen Flash Next compact parsing report

This report covers compact corpus revision 1 only. It does not measure 28-episode endurance, hosted equivalence, or a fully offline deployment.

## Report control

| Field | Value |
|---|---|
| Report status | `NOT_MEASURED` |
| Schema version | `1` |
| Model | `qwen3.8-flash-next` |
| Effort | `false` |
| Run id | `20260911T001509Z-swift3` |
| Snapshot | `backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz` |
| Source revision | `653cbd62c962dbb8388518873fe47cd44e7fc77d` |
| Corpus path | `docs/plans/33-local-qwen-migration/resources/compact-corpus.md` |
| Corpus SHA-256 | `2394bcacfc4fcff6d8ee1f280f8642f8eaf864797cfcd4b333d57b4b9da296d3` |

## Input manifest

| Kind | Path | Availability | SHA-256 | Reason |
|---|---|---|---|---|
| corpus | `docs/plans/33-local-qwen-migration/resources/compact-corpus.md` | MEASURED | `2394bcacfc4fcff6d8ee1f280f8642f8eaf864797cfcd4b333d57b4b9da296d3` |  |
| metrics | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | MEASURED | `dbaccaeb4cb5e57fad7c3a4ec454c83a6d23dc51ab2c5e2783775df1dc01f5ff` |  |
| snapshot | `backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz` | MEASURED | `4e3dc2e6bbbbf461aa8a2a32351a82ccfc965da285304ecd33b94fc4f3bee95b` |  |
| admin_jobs | `NOT_MEASURED/admin_jobs` | NOT_MEASURED | `NOT_MEASURED` | No committed privacy-safe per-job admin response exists for this run. |
| graph_export | `NOT_MEASURED/graph_export` | NOT_MEASURED | `NOT_MEASURED` | No privacy-safe graph export with source episode and job identifiers is committed. |
| audit_log | `log/agent_actions.log` | NOT_MEASURED | `NOT_MEASURED` | The private audit log was not read; only committed aggregate counters are used. |
| e2e_manifest | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | MEASURED | `ddd35c9deb2d25adcb3a6eb82777cab30d95db3d64025d6eb082f57d50268e31` |  |
| recall | `docs/plans/33-local-qwen-migration/resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json` | MEASURED | `b80edd9c82628c88f8f1a1eaa0a37009f5a585bc50b37552303cc0c88a872b48` |  |

## E02

| Field | Value |
|---|---|
| source | `{"locator":"episode:E02","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/0/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/0/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/0/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/0/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/0/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/0/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E04

| Field | Value |
|---|---|
| source | `{"locator":"episode:E04","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/1/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/1/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/1/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/1/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/1/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/1/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E05

| Field | Value |
|---|---|
| source | `{"locator":"episode:E05","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/2/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/2/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/2/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/2/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/2/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/2/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E10

| Field | Value |
|---|---|
| source | `{"locator":"episode:E10","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/3/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/3/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/3/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/3/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/3/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/3/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E18

| Field | Value |
|---|---|
| source | `{"locator":"episode:E18","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/4/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/4/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/4/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/4/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/4/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/4/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E20

| Field | Value |
|---|---|
| source | `{"locator":"episode:E20","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/5/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/5/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/5/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/5/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/5/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/5/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E26

| Field | Value |
|---|---|
| source | `{"locator":"episode:E26","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/6/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/6/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/6/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/6/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/6/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/6/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## E27

| Field | Value |
|---|---|
| source | `{"locator":"episode:E27","path":"docs/plans/33-local-qwen-migration/resources/compact-corpus.md"}` |
| jobs | `[{"job_id":"NOT_MEASURED","kind":"ingestion","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"routing","outcome":"NOT_MEASURED","status":"NOT_MEASURED"},{"job_id":"NOT_MEASURED","kind":"extraction","outcome":"NOT_MEASURED","status":"NOT_MEASURED"}]` |
| run_provenance | `{"effort":"false","model":"qwen3.8-flash-next","run_id":"20260911T001509Z-swift3","snapshot_path":"backups/qwen-flash-next-compact-20260911T001509Z-swift3-20260911-022540.tar.gz","source_revision":"653cbd62c962dbb8388518873fe47cd44e7fc77d"}` |
| domains | `{"accepted":"NOT_MEASURED","proposal":"NOT_MEASURED"}` |
| ontology | `{"accepted":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"proposed":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"},"rejected":{"edge":"NOT_MEASURED","node":"NOT_MEASURED"}}` |
| extraction | `{"entities":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"},"relations":{"count":"NOT_MEASURED","representative_safe_values":"NOT_MEASURED","stable_ids":"NOT_MEASURED"}}` |
| librarian | `{"actions":{"archived_nodes":"NOT_MEASURED","created_edges":"NOT_MEASURED","created_nodes":"NOT_MEASURED","removed_edges":"NOT_MEASURED","updated_nodes":"NOT_MEASURED"}}` |
| events | `{"rejections":"NOT_MEASURED","retries":"NOT_MEASURED","timeouts":"NOT_MEASURED"}` |
| quality_integrity | `{"checks":[{"name":"extraction_smoke","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan15","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"plan17","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"episodic_memory","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"},{"name":"cognitive_recall","source":"docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json","status":"NOT_MEASURED"}],"status":"NOT_MEASURED"}` |

### Evidence

| JSON Pointer | Status | Exact value | Source | Reason |
|---|---|---|---|---|
| `/episodes/7/jobs/0/kind` | MEASURED | `ingestion` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/7/jobs/0/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/0/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/0/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/1/kind` | MEASURED | `routing` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/7/jobs/1/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/1/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/1/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/2/kind` | MEASURED | `extraction` | `resources/qwen-parsing-report-compact.schema.json` |  |
| `/episodes/7/jobs/2/status` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/2/job_id` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/jobs/2/outcome` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/admin_jobs` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/domains/accepted` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/domains/proposal` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/ontology/proposed/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/ontology/proposed/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/ontology/accepted/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/ontology/accepted/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/ontology/rejected/node` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/ontology/rejected/edge` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/extraction/entities/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/extraction/entities/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/extraction/entities/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/extraction/relations/count` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/extraction/relations/stable_ids` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/extraction/relations/representative_safe_values` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/librarian/actions/created_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/librarian/actions/updated_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/librarian/actions/archived_nodes` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/librarian/actions/created_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/librarian/actions/removed_edges` | NOT_MEASURED | `NOT_MEASURED` | `NOT_MEASURED/graph_export` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/events/retries` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/events/timeouts` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/events/rejections` | NOT_MEASURED | `NOT_MEASURED` | `log/agent_actions.log` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/checks/0/name` | MEASURED | `extraction_smoke` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/0/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/checks/0/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/1/name` | MEASURED | `plan15` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/1/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/checks/1/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/2/name` | MEASURED | `plan17` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/2/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/checks/2/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/3/name` | MEASURED | `episodic_memory` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/3/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/checks/3/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/4/name` | MEASURED | `cognitive_recall` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |
| `/episodes/7/quality_integrity/checks/4/status` | NOT_MEASURED | `NOT_MEASURED` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | No committed privacy-safe per-episode attribution exists for this field. |
| `/episodes/7/quality_integrity/checks/4/source` | MEASURED | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` | `docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json` |  |

## Checks

| Check | Result |
|---|---|
| episode_set | E02,E04,E05,E10,E18,E20,E26,E27 |
| source_links | PASS |
| evidence_coverage | PASS |
| evidence_value_equality | PASS |
| no_invented_rows | PASS |
| hidden_reasoning_absent | PASS |
| raw_secrets_absent | PASS |
| sensitive_audit_absent | PASS |
| domain_privacy | PASS |
