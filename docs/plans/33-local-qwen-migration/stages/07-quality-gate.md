# Stage 7: Quality Decision and Evidence Report

**Goal**: Issue an evidence-backed per-agent `MIGRATE`, `HOLD`, or `BLOCKED` verdict without treating incomplete baseline data as a pass.
**Dependencies**: Stage 6b DONE. Stage 6b is the ordered control stage after the Stage 6 attempt and
passes its outcome even when Stage 6 is BLOCKED. This stage must not start before that diagnosis/no-op
record exists.

## Steps

1. Read the local metrics, raw job/audit events, qualitative graph sample, and
   `resources/isolation-attribution.md`. Read the optional baseline only if it contains two complete
   same-input runs. Keep every caveat attached to the number it qualifies.
   If Stage 6 is `BLOCKED` or has no usable metrics, issue `HOLD` for every agent whose quality is not
   measured and carry the blocking root cause into `resources/bakeoff-comparison.md`; do not stop here.
2. Apply the integrity floor first. Any artifact stored, leaked reasoning marker, invalid type name,
   unexplained normalization rejection spike, structured-output failure, auth failure, or incomplete
   job run blocks the implicated agent. A zero stored-artifact count is not enough if rejections rose.
3. Compare quality metrics to a valid baseline with a measured noise band. If no valid baseline exists,
   apply the deterministic absolute rubric: the extraction smoke, episodic-memory, and cognitive-recall
   checks must exit 0; the Plan 15 score line must be at least 11/14; the Plan 17 score line must be at
   least 13/14; and all critical integrity metrics must pass. A missing or `NOT MEASURED` input means
   `HOLD`, never `MIGRATE`. A missing isolation arm means the implicated agent is also `HOLD`.
4. Create `resources/quality-sample-qwen-flash-next.json` by selecting exactly 20 actual nodes and 20
   actual edges from the named local snapshot, with their source episode/job ids. Run a deterministic
   validator: every selected record has a non-empty name, a declared existing type, valid references,
   no artifact/reasoning marker, and a source id in the fixed 28-episode corpus. An empty or fabricated
   sample is `NOT MEASURED` and forces HOLD; do not replace this check with subjective visual approval.
5. After the Stage 6 full run attempt, collect the machine-readable inputs in the report template.
6. Write `resources/qwen-parsing-inputs.json` with each input path, SHA-256 value, and availability.
7. Include the fixed corpus, metrics artifact, job responses, graph export, snapshot, and audit-log path.
8. Generate `resources/qwen-parsing-report.json` from the input manifest and the source artifacts.
9. Create one report row for each fixed episode key from `E01` through `E28`.
10. When a source value is absent, record `NOT MEASURED` and its reason.
11. Render `resources/qwen-parsing-report.md` from the JSON report.
12. Validate the schema with `Draft202012Validator.check_schema`.
13. Validate the JSON report against [qwen-parsing-report.schema.json](../resources/qwen-parsing-report.schema.json).
14. Validate that the report contains each fixed episode key once and contains no invented row.
15. Scan the report for prompts, hidden reasoning, raw model output, secrets, and sensitive audit content.
16. Scan all domain fields and safe values for dynamic domain values and schema names. Permit only
    static built-in refs, opaque domain ids, and one-way hashes for domain evidence.
17. Write `resources/bakeoff-comparison.md` with every metric, arm, delta, verdict, provenance, and
   caveat. Add a short D-entry and backlog item for every HOLD/BLOCKED result. Ask a fresh
   GPT-5.6-Luna xhigh subagent to audit provenance.
18. When at least one agent is `MIGRATE`, leave Stage 8 eligible. If none passes, Stage 8 can be
   `SKIPPED` and Stage 9 must publish the technical report rather than force a cutover.

## Per-episode report

The report has a machine-readable JSON form and a Simple English Markdown form. The JSON form is the
source for the Markdown form. The report template defines the field names, source rules, and safe values.

The input manifest references the fixed corpus, the metrics artifact, the PostgreSQL snapshot, the
admin job responses, the graph export, and the JSON-lines audit log. It stores paths and SHA-256 values.
It does not copy credentials or sensitive audit records.
The report stores source and snapshot paths without schema names. It stores job status and safe outcome
codes, not free-text errors.

Each episode row contains the episode key and source locator. It contains the ingestion and extraction
job outcomes, selected model, effort, run id, snapshot path, and source revision. It contains accepted
domains and the proposal result. Domain evidence uses static refs, opaque ids, one-way hashes, and status.
It contains proposed, accepted, and rejected ontology type counts.
It contains extraction counts, stable node and edge ids, and representative safe values. It marks missing
ids as `NOT MEASURED`.
It contains librarian action counts. It contains retry, timeout, and rejection values. It contains
quality and integrity check results with source references.

The report uses counts, opaque ids, type names, relation types, action labels, static built-in refs, and
one-way hashes as safe values. It does not contain dynamic domain values or dynamic schema names.
It does not copy episode text, prompts, hidden reasoning, raw model output, secrets, or sensitive audit
fields.

## Verification

- [ ] GATE verdict completeness — all four reasoning agents have one explicit verdict and each verdict traces to current raw evidence; missing or inferred evidence makes this red.
- [ ] GATE integrity disposition — every critical defect is assigned to an agent or interaction and appears in `resources/bakeoff-comparison.md` and `backlog.md`; silent drops make this red.
- [ ] GATE per-episode report — the JSON and Markdown reports contain `E01` through `E28` once each, with source references and safe values. Dynamic domain values or schema names make this red.
- [ ] GATE report privacy — `checks.domain_privacy` is `PASS` only after the domain and safe-value scans pass. A missing scan makes this red.
- [ ] REPORT quality comparison and fixed sample — record all metrics, baseline availability, the 20-node/20-edge validator output, and `NOT MEASURED` values in `journal.md`.

## Commit

`docs(plan): record Flash Next quality decision`
