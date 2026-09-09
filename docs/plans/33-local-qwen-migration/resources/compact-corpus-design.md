# Compact corpus revision 1

The user requested a smaller corpus after a local run took over 16 hours. Decision D38
selects eight original episodes for the active migration arm. This is focused migration
validation, not evidence of 28-episode endurance or complete Plan 18.5 recall coverage.

## Fixed inputs and coverage

Use [compact-corpus.md](compact-corpus.md) with `--corpus-profile compact`. Text, importance,
context, original episode numbers, and chronological order match the original corpus.

| Episodes | Coverage retained |
|----------|-------------------|
| E02 | Initial people and team roles |
| E04, E05 | Both historical dense librarian failure cases; shared normalization entities |
| E10 | Security incident and remediation; precursor to the team update |
| E18, E20, E26 | Initial concern, adopted decision, then explicit correction |
| E27 | Changed team roles and ownership, linked to E02 and E10 |

All four reasoning agents and automatic domain routing remain enabled. Actual routed jobs
and their provenance must be measured; topic variety alone does not prove routing coverage.
Eight episodes are 71% fewer submissions. Runtime reduction is NOT MEASURED. Dense cases,
routed extraction, retries, and the five separate E2E children can still dominate runtime.

## Recall interpretation

Run original queries Q2, Q3, Q6, Q7, Q8, and Q9. Q2 has narrower architecture coverage.
Exclude Q1 (blocking stop-lists), Q4 (fingerprint collisions), and Q5 (Korean UDX crash)
because their source episodes are absent. These are out-of-profile, not passing or failing.
The compact recall artifact records the selected and excluded query IDs and denominators.
M3 is measured out of 1 (Q3); M4 is measured out of 3 (Q7/Q8/Q9). M2 is over six queries,
not nine. Do not compare raw compact metrics with historical full-profile metrics.

The extraction smoke, Plan 15, Plan 17, episodic-memory, and cognitive-recall E2Es load
independent fixtures. Keep all five children and their existing acceptance thresholds.

## Evidence and gates

Keep terminal-job, failure-rate, integrity, privacy, graph-cleanliness, and provenance gates.
Keep the 20-node/20-edge sample requirement; absent actual records mean NOT MEASURED/HOLD.
Bind metrics to the selected corpus path, SHA-256, profile, and actual original episode IDs.
Use a fresh run ID and `qwen-flash-next-compact` arm. Do not reuse the unstarted full-profile
run ID or relabel historical results. No quality or migration verdict is established here.

Use [qwen-parsing-report-compact.schema.json](qwen-parsing-report-compact.schema.json)
for the active report. It requires exactly E02,E04,E05,E10,E18,E20,E26,E27 once each.
Retain the original report schema for full-profile evidence. The final output filenames
remain `qwen-parsing-report.md` and `.json`; identify the compact scope in both reports.

## Execution

Apply the model, credential, and low-effort environment from [commands.md](commands.md).
Preflight endpoint identity and authentication immediately before the real run.

```bash
./scripts/model_bakeoff.sh --arm qwen-flash-next-compact --corpus-profile compact --dry-run
./scripts/model_bakeoff.sh --arm qwen-flash-next-compact --corpus-profile compact
```

The full profile remains the harness default and is available with `--corpus-profile full`.
Use the same profile for any future hosted comparison or tuned combined arm.
