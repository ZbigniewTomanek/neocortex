# Stage 7 brief — one tuned service arm

Implementer: `codex/gpt-5.6-sol`, effort high, strong tier.
Reviewer: `codex/gpt-5.6-sol`, effort high, strong tier.
Status: DRAFT; finalize selected levels and evidence filenames after Stages 2–6.
Authority: `stages/07-combined-compact-run.md`, `goal.md`, `PROTOCOL.md`.

## Required preparation before live launch

The stage's after-arm exporter sequence cannot run literally: `model_bakeoff.sh`
restores PRE_SNAPSHOT in its EXIT trap, and each E2E child restarts the services with
fresh data. The graph being sampled must be the measured corpus graph, not the last
child graph or restored user graph. Add scoped integration for the tuned arm in
`scripts/model_bakeoff.sh` with tests in its existing test module(s): export safe skips
and graph sample after corpus jobs finish and corpus metrics exist, before child
restarts. Update corpus metrics with consistency/survival before the E2E manifest
pins their SHA. Generate the tuned report only after final manifest/recall evidence
exists, without overwriting historical report files. Follow Stage 2's actual API.

Do not disable the recovery snapshot or EXIT restoration. Keep prior arm behavior
unchanged. Ensure a failed quality check still preserves measured/partial artifacts
and restores the user's data. Record the actual run identity on all evidence. Scope
includes the plan-authorized harness scripts and their focused tests, plus run
artifacts and Plan 33 evidence. No unrelated application change.

## Deadline and restoration correction

Read-only signal experiments proved group TERM can start parent restoration before
active E2E child cleanup finishes. Shell-only TERM can wait on foreground work;
run_e2e's combined EXIT/INT/TERM cleanup also runs twice. Correct this before live.
Scope adds scripts/run_e2e.sh and its existing fixture tests, plus a supervisor
under this plan's validation/ (committed executable evidence, not raw stdout).
Supervisor launches only the arm in a new process session via Popen/start_new_session.
It signals only that owned process group, never broad pkill/Docker/port-based cleanup.
Track the active E2E child asynchronously in model_bakeoff; explicit TERM/INT
handlers wait for its cleanup before exiting to the single existing snapshot restore.
Timeout exit124 must remain distinct from restore failure3. Retain private diagnostics.
run_e2e uses one EXIT cleanup; TERM/INT only exit143/130. No double cleanup.

Reserve600s of the7200s total budget for mandatory cleanup: stop benchmark workload
at6600s, with no new request/job launch. Measure both workload and total arm wall time.
Never forcibly kill an in-progress restore to manufacture budget compliance. If
cleanup unexpectedly exceeds the reserve, report the actual overrun and incomplete
benchmark as NOT MEASURED; preserve recovery evidence and finish required data recovery.
This is not permission to extend model work or run another arm.

Fake-service tests: short deadline terminates blocking child while unrelated
sentinel survives; child manage-stop completes before exactly one snapshot-load;
no later start--fresh; diagnostics retained; restore failure returns3 aftertimeout;
direct run_e2e TERM cleans once/exits143. Tests must not run real services or inference.

Read existing scripts/tests first. Run focused harness tests, `bash -n` on modified
shell, full pytest/ruff, and the documented --dry-run. Save raw outputs per attempt.
Inspect dry-run command order to prove graph capture precedes child restarts and
metric finalization precedes digest capture. The service harness has --dry-run rather
than --test-model: the plan explicitly prescribes it for this service arm; all model
paths must already have passed test-model checks in preceding stages.

## Live assignment, only after preparation is gated

Owner authorized the pending Gemini embedding calls with "proceed" on 2026-09-13.
The grant covers the bounded Stage7 service benchmark and its embedding API cost,
using the existing key. Keep embedding health checks intact. This does not authorize
hosted reasoning models or embeddings in the in-memory Stage4–6 probes.

Use mechanically selected levels from `resources/effort-sweep.json`; off becomes
boolean false. Preflight authenticated local model listing and settings without
printing credentials. Check Docker/PostgreSQL readiness with bounded commands. If
unavailable, report the observed blocker; do not restart Docker or unrelated services.

Before every external write, record safe provenance under validation/provenance.json:
existing snapshot identity, planned run id and local graph reset, created snapshot and
artifact ids, each write and any partial failure. Never include credentials or graph text.
The recorded owner permission authorizes local development snapshots and the fresh
graph benchmark, with restoration. Read permissions in goal.md before the reset.

Run in a managed asynchronous command session under `.tmp/plan34/` (D-16),
with 300 s maximum per model call and 2 h maximum
per arm. The launch must include a bounded supervisory mechanism that terminates only
this run's processes on deadline and lets restoration execute. Poll at least five
minutes apart. Preserve last job summary and partial artifacts on deadline; do not
wait beyond the budget. No third arm. A second arm requires a root-caused change
recorded by coordinator, never merely a failed quality score.

## Evidence and rubric

Record real corpus stability, integrity, skip consistency, temporal survival,
20/20 sample (or actual shortfall), five child exits, Plan 15/17 scores, recall,
per-agent usage/latency and wall time. Quality failures are REPORT and feed HOLD;
missing measurements stay NOT MEASURED. Do not manufacture placeholder counts or
successful rows. Keep every evidence file associated with its producing run id.

The gate is that the arm ran and its evidence artifacts exist, or the stage is BLOCKED
with the actual condition. Coordinator owns lifecycle status, decisions, commits and
final review. Implementer must not commit or edit run records/briefs/review files.
