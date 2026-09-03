# Stage 7: Quality Decision and Evidence Report

**Goal**: Issue an evidence-backed per-agent `MIGRATE`, `HOLD`, or `BLOCKED` verdict without treating incomplete baseline data as a pass.
**Dependencies**: Stage 6 DONE; Stage 6b must be DONE or explicitly SKIPPED.

## Steps

1. Read the local metrics, raw job/audit events, qualitative graph sample, and
   `resources/isolation-attribution.md`. Read the optional baseline only if it contains two complete
   same-input runs. Keep every caveat attached to the number it qualifies.
2. Apply the integrity floor first. Any artifact stored, leaked reasoning marker, invalid type name,
   unexplained normalization rejection spike, structured-output failure, auth failure, or incomplete
   job run blocks the implicated agent. A zero stored-artifact count is not enough if rejections rose.
3. Compare quality metrics to a valid baseline with a measured noise band. If no valid baseline exists,
   use absolute checks and qualitative review, record quality as `NOT MEASURED` where appropriate, and
   do not invent parity. A missing isolation arm means the implicated agent is `HOLD`, not `MIGRATE`.
4. Review about 20 local nodes and 20 edges against the corresponding corpus and baseline snapshot when
   available. Reject a superficial metric pass when types, relations, temporal corrections, or domain
   routing are visibly wrong.
5. Write `resources/bakeoff-comparison.md` with every metric, arm, delta, verdict, provenance, and
   caveat. Add a short D-entry and backlog item for every HOLD/BLOCKED result. Ask a fresh
   GPT-5.6-Luna xhigh subagent to audit provenance.
6. Leave Stage 8 eligible only when at least one agent is `MIGRATE`. If none passes, Stage 8 may be
   `SKIPPED` and Stage 9 must publish the technical report rather than force a cutover.

## Verification

- [ ] GATE verdict completeness — all four reasoning agents have one explicit verdict and each verdict traces to current raw evidence; missing or inferred evidence makes this red.
- [ ] GATE integrity disposition — every critical defect is assigned to an agent or interaction and appears in `resources/bakeoff-comparison.md` and `backlog.md`; silent drops make this red.
- [ ] REPORT quality comparison and qualitative sample — record all metrics, baseline availability, 20-node/20-edge review, and `NOT MEASURED` values in `journal.md`.

## Commit

`docs(plan): record Flash Next quality decision`
