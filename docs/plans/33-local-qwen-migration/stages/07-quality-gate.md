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
5. Write `resources/bakeoff-comparison.md` with every metric, arm, delta, verdict, provenance, and
   caveat. Add a short D-entry and backlog item for every HOLD/BLOCKED result. Ask a fresh
   GPT-5.6-Luna xhigh subagent to audit provenance.
6. Leave Stage 8 eligible only when at least one agent is `MIGRATE`. If none passes, Stage 8 may be
   `SKIPPED` and Stage 9 must publish the technical report rather than force a cutover.

## Verification

- [ ] GATE verdict completeness — all four reasoning agents have one explicit verdict and each verdict traces to current raw evidence; missing or inferred evidence makes this red.
- [ ] GATE integrity disposition — every critical defect is assigned to an agent or interaction and appears in `resources/bakeoff-comparison.md` and `backlog.md`; silent drops make this red.
- [ ] REPORT quality comparison and fixed sample — record all metrics, baseline availability, the 20-node/20-edge validator output, and `NOT MEASURED` values in `journal.md`.

## Commit

`docs(plan): record Flash Next quality decision`
