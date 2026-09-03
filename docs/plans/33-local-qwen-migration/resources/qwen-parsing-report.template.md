# Qwen Flash Next Per-Episode Parsing Report

Use this template after the Stage 6 full run attempt. Create the JSON report first. Render this Markdown report from that JSON report.

Keep one report row for each fixed episode key, from `E01` through `E28`. Do not add a row for an episode that is not in the fixed corpus.

When a source does not contain a value, write `NOT MEASURED` and record the reason beside the value. Do not infer a value from a default, a target, or another episode.

## Report control

| Field | Value |
|---|---|
| Report status | `MEASURED` or `NOT_MEASURED` |
| Schema version | `1` |
| JSON report | `resources/qwen-parsing-report.json` |
| Input manifest | `resources/qwen-parsing-inputs.json` |
| Model | observed model id or `NOT_MEASURED` |
| Effort | observed effort or `NOT_MEASURED` |
| Run id | observed run id or `NOT_MEASURED` |
| Snapshot | observed snapshot artifact path without schema names, or `NOT_MEASURED` |
| Source revision | observed commit or `NOT_MEASURED` |
| Corpus path | fixed corpus path |
| Corpus SHA-256 | observed hash or `NOT_MEASURED` |

## Input manifest

Create `resources/qwen-parsing-inputs.json` before you generate the report. Record each source path, SHA-256 value, and availability.

The manifest lists these source artifacts:

| Kind | Source | Required content |
|---|---|---|
| `corpus` | Fixed 28-episode corpus | Episode keys, source locators, and corpus hash |
| `metrics` | `metrics-qwen-flash-next.json`, or its `NOT_MEASURED` sidecar | Run id, model, effort, snapshot path, and source revision |
| `snapshot` | PostgreSQL snapshot from the local run | Actual episode, node, edge, and job records |
| `admin_jobs` | Saved admin API responses | Job ids, task names, statuses, and safe numeric arguments |
| `graph_export` | Read-only export from the named snapshot | Stable ids, types, source episode ids, and counts |
| `audit_log` | `log/agent_actions.log` path and hash | Event counts and numeric usage values |

Remove episode text, `episode_text`, `domain_hint`, dynamic domain values, and dynamic schema names from saved admin responses.
Remove prompts, model output, credentials, and authorization headers from saved admin responses.

Keep only the audit-log path and hash in the manifest. Read the audit log during generation. Do not copy its records into the report.

## Required episode row

Create one section with this field set for every episode key:

### `<episode key>`

| Field | Required value |
|---|---|
| Source | Fixed corpus path without schema names and stable episode locator |
| Jobs | Ingestion, routing, and extraction job id, status, and outcome |
| Run provenance | Model, effort, run id, snapshot path, and source revision |
| Domains | Accepted static refs, opaque domain ids, proposal status, proposal hash, and static parent ref |
| Ontology | Proposed, accepted, and rejected node and edge type counts |
| Extraction | Entity and relation counts, stable ids or `NOT MEASURED`, and safe values |
| Librarian | Created, updated, archived, and edge action counts |
| Events | Retry, timeout, and rejection values |
| Quality and integrity | Check status and source reference for each check |

Use the JSON field names from `qwen-parsing-report.schema.json`. Keep the Markdown field order from this template.

## Safe values

Use counts, opaque ids, type names, relation types, action labels, static built-in refs, and one-way hashes as safe values.

| Safe value kind | JSON value form |
|---|---|
| Opaque id | `{"kind":"opaque_id","value":42}` |
| One-way hash | `{"kind":"one_way_hash","value":"sha256:<64 lowercase hex digits>"}` |
| Type name | `{"kind":"type_name","value":"Component"}` |
| Relation type | `{"kind":"relation_type","value":"USES"}` |
| Static domain ref | `{"kind":"static_domain_ref","value":"technical_knowledge"}` |
| Librarian action | `{"kind":"action","value":"created_node"}` |

Use `domains.accepted.static_refs` for the four built-in domains only.
Use `domains.accepted.domain_ids` for accepted dynamic domains.
Use `domains.proposal.dynamic_proposal_hash` for each observed dynamic proposal value.
Use `domains.proposal.static_parent_ref` only for a built-in parent.

Use an opaque id or a one-way hash for every representative entity or relation label.
Do not include dynamic domain values, dynamic schema names, domain descriptions, or parent values.
Do not include episode text, prompts, hidden reasoning, raw model output, or secrets.
Do not include email addresses or sensitive audit fields.

## Generation contract

The report generator reads the input manifest, fixed corpus, metrics artifact, snapshot, and admin job data.
It also reads the graph export and audit log.

The generator maps each source record to one fixed episode key. It keeps source references with every measured value.
The generator maps domain data to static refs, opaque ids, one-way hashes, and proposal statuses.
The generator omits dynamic schema names and dynamic domain values.

The generator writes `resources/qwen-parsing-report.json` and then renders `resources/qwen-parsing-report.md`.

When a source record is missing, incomplete, or outside the selected run, the generator writes `NOT MEASURED`.

The generator does not copy raw source content into either report file.

## Required report checks

Validate the schema with `Draft202012Validator.check_schema`.
Validate the JSON report against `qwen-parsing-report.schema.json`.
Validate the fixed episode set for `E01` through `E28`.

Validate source links for every measured field. Validate safe-value kinds and values.
Validate that the complete episode set has no invented rows.

Scan the report for dynamic domain values and dynamic schema names.
Scan the report for hidden reasoning, raw model output, secrets, prompts, email addresses, and sensitive audit fields.
When the domain scan passes, set `checks.domain_privacy` to `PASS`.

If a required check cannot run, write `NOT MEASURED` and record the reason. Do not report `PASS` for an unavailable check.
