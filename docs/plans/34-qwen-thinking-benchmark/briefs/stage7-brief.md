# Stage 7 brief — one tuned service arm

Implementer: `codex/gpt-5.6-sol`, effort high, strong tier.
Reviewer: `codex/gpt-5.6-sol`, effort high, strong tier.
Status: FROZEN for preparation; live dispatch waits Stage6 selected levels.
Authority: `stages/07-combined-compact-run.md`, `goal.md`, `PROTOCOL.md`.

Current assignment is preparation only: implement/gate harness and supervisor,
no real service starts/stops, Docker/DB writes, embeddings or inference. Live
levels and run identity are runtime inputs from finalized Stage6, not guessed.
Use off/mock values solely in tests/dry-run. Do not commit or edit run records.

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
The planned child-reset provenance event must be durable before starting the
background E2E wrapper, not only before waiting for it. Have the fake child read
and assert that planned event before its first reset/write. A final event-order
assertion alone does not prove write-ahead ordering across processes.

Read existing scripts/tests first. Run focused harness tests, `bash -n` on modified
shell, full pytest/ruff, and the documented --dry-run. Save raw outputs per attempt.
Inspect dry-run command order to prove graph capture precedes child restarts and
metric finalization precedes digest capture. The service harness has --dry-run rather
than --test-model: the plan explicitly prescribes it for this service arm; all model
paths must already have passed test-model checks in preceding stages.

## Operational documentation correction

Scope also includes resources/commands.md, now stale after D-16 and this stage's
integrated exports. Correct operational reproduction instructions only. Do not
declare validated defaults or MIGRATE. Read the complete simple-english skill
at /Users/zbigniewtomanek/.agents/skills/simple-english/SKILL.md and use its
structural rules and four self-checks for prose. Preserve identifiers exactly.
Replace the obsolete nohup launch examples with managed asynchronous-session
instructions and the current runner/supervisor commands. State that a plain
foreground shell is not the orchestrator's managed session. Keep all budgets,
no-rerun rule and five-minute polling limits. Show Stage6's finalized identity,
original baseline and live cache inputs, with no baseline or identity rerun.
For Stage7 show explicit selected-level inputs, local models, env-only credentials,
300s calls, compact profile, supervisor6600/7200 and unique status/run paths.
Remove the separate post-arm exporter procedure: tuned harness captures the
corpus graph before child resets and restoration. Do not add a duplicate external
snapshot operation. Explain the harness's automatic preservation and restoration.
Mention explicit desktop-linux Docker context on this machine without changing
global Docker configuration. Runtime selected levels remain unset until Stage6
finishes. Correcting commands is not a change to product defaults or report rules.

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

## Single review fix — F1/F2/F3/F4

Read validation/stage7-review.md complete finding set and triage. This is the only
review fix round, no re-review. Sole strong writer, no live calls/services/DB/Docker.
Own model_bakeoff.sh, run_e2e.sh, existing harness tests, stage7_arm_supervisor.py,
and resources/commands.md if corrected behavior changes its instructions.
Scope permits a small dedicated evidence finalizer under validation/ and its tests,
plus narrowly necessary e2e_manifest/compute_metrics/report-generator changes if
their existing APIs cannot represent honest partial artifacts. Prefer existing
APIs; report exact necessity for each added path. No product model code or Stage6
probe/runner/evidence edits. Do not alter historical artifacts or measured schemas
to make unknown values pass. Freeze source after checks, report paths and proof.

F1: restore must not share the signalled workload group. The bake-off must own
targeted shutdown of its active workload, with parent control signals separated
from workload signals. Latch termination once. Ignore subsequent signals during
finalization/recovery. Also cover the FIRST deadline or external signal arriving
during natural EXIT restoration and an external signal before the automatic
deadline. A one-shot supervisor latch alone does not solve these first-signal
cases. Use owned PIDs/groups only, no broad kill or Docker teardown. Stop all new
model/job launches at the work deadline; required cleanup can exceed reserve only
with actual overrun recorded. Keep restore failure3 distinct from timeout124.
Tests: repeated TERM/INT after restore starts, natural restore straddling deadline,
external-stop cleanup straddling deadline, unrelated sentinel survives, child
cleanup precedes one restore, no later fresh-start. Use harmless fakes only.

F2: tuned arm terminal summaries continue even above10% failed+cancelled. Persist
the actual validated summary and failed stability observation. Keep historical
arm behavior/tests unchanged. Prove terminal8success/1failed/1cancelled/total10
continues through safe exports/children/manifest and preserves20%, never PASS.
Malformed or unavailable summaries remain unknown, not zero failures. A producer
which wrote valid NOT_MEASURED evidence must not prevent the rest of the report.
Preserve its true reason/exit. Infrastructure failures must stop unsafe work and
produce honest partial evidence, not blindly continue fresh starts or model calls.

F3: persist the latest validated safe job summary after each poll, before waiting.
On deadline stop workloads, then finalize evidence without model, embedding or
new job/service calls. Preserve already measured artifacts.
Mandatory cleanup, including stopping the arm's service workers, is allowed and
must precede file-only finalization if those workers can otherwise issue requests.
The prohibition covers new benchmark/health/model work, not required cleanup.
Read-only diagnosis confirmed manage start--fresh backgrounds daemons in its
new session; clearing the transient helper PID loses ownership of that group.
Retain/verify that owned service PGID or an exact daemon/process-tree receipt.
Terminate and wait for those owned workers before the local finalizer. Do not
discover/kill unrelated processes by port or name. Add a harmless persistent-daemon
fake which continues request markers after startup returns, then proves no marker
can appear during finalization and restoration. Active E2E cleanup alone is not
sufficient for a deadline while polling the initial corpus jobs.
Do not use manage.sh stop as a substitute for this owned-worker shutdown: it has
a port-based fallback. A secure PGID receipt from service startup plus verified
.mcp.pid/.ingestion.pid membership before retaining and again before signalling
avoids that fallback and PGID reuse. Existing snapshot restoration remains intact.
For missing metrics, recall, child outcomes/manifest, skip-events, sample, report write explicit
NOT_MEASURED with run/arm identity, deadline reason and available source references.
Unknown numeric quantities are null/absent, never0. Unlaunched child outcomes are
NOT_MEASURED, not invented successful or failed executions. No fabricated graph
rows or empty arrays claimed as a20/20 sample. Partial artifact forms must clearly
differ from measured schemas; consumers must treat them as unavailable/HOLD.
Prefer a bounded local finalizer over live post-timeout exports. Actual finalizer
errors remain visible, and mandatory restore still runs even when persistence
fails. Recovery is more important than forcing an artifact-existence PASS.
Tests: timeout during active corpusjobs and during an E2E child, lastsummary exact,
all missing portions explicitunavailable, measured artifacts unchanged, no later
model/job launches, restored baseline once; inability to write evidence still
attempts restore and reports the failure. Keep private diagnostics on failure.

F4: explicitly check planned provenance before childcreation/launch. Do not rely
on set-e inside a function invoked by if. Inject a provenance write failure after
corpus processing and prove no E2E child/reset starts, error recorded if possible,
and existing snapshot recovery still attempted. Do not weaken failclosed semantics
when a valid prior provenance file exists but an update cannot be persisted.

Checks: focused harness/finalizer/supervisor tests, full pytest tests/ -q, ruff check .,
bash -n, exact300/domaintrue/compact dry-run, scoped hooks, documentation selfchecks
if changed. Save each attempt under validation/stage7-fix1-<check>-attempt<n>.txt.
Expose real generated fake partial JSON in validation/stage7-fix1-evidence-attempt1
for coordinator to inspect; clearly label TestModel/fake provenance, no liveclaims.
Report every finding's direct proof and every remaining limitation. No commit or
runrecord/brief/review edits. No additional review or unrelated improvements.

## Same-finding verification corrections

Coordinator inspected the frozen fix and ran fresh checks. Full1506/7 passed,
but focused41passed/1failed because the two-second startup deadline expired before
the expected job-summary write under load. Evidence: validation/stage7-fix1-
focused-coordinator-attempt1.txt and suite-coordinator-attempt1.txt.
Use deterministic readiness synchronization for the active-jobs timeout fixture,
not an assumption that startup finishes in two seconds. Keep an actual short
deadline test and make sure it proves the intended active-jobs state first.

Complete these existing F1/F2/F3 properties in the same fix, no new review:

- interrupt_bakeoff must not ignore failed owned-worker shutdown and proceed to
  local finalization while workers can issue requests. On receipt/stop/waitfailure,
  report the error, attempt mandatory protected recovery, and finalize only after
  workers are proven stopped. Missing evidence is preferable to an unsafe claim.
- The poll_jobs error branch currently finalizes before any owned daemon shutdown.
  Its own timeout and malformed/infrastructure summaries need the same stop/wait
  ordering as the external deadline, without changing the true failure reason.
- The persistent daemon fake must emit request markers after startup returns.
  Prove both daemon stops precede finalizer start, finalizer precedes restoration,
  and no request marker occurs during finalization/restoration. Cover failed
  identity verification and failed termination without killing unrelated workers.
- run_evidence_write currently turns every producer failure into a new marker
  whenever terminal stability failed. This does not distinguish a producer's
  valid NOT_MEASURED result from infrastructure/auth/malformed failure. Continue
  benchmark work only on validated current-run unavailable evidence emitted by
  that producer, or on a specifically typed expected quality outcome. For other
  failures stop unsafe work and use the shutdown/partial-report path. Preserve
  actual exits and prior measured artifacts. Do not launch later E2E resets.
- The finalizer failure status must be captured inside an else branch. After an
  if with no successful branch, `$?` can be zero. Reproduce write-unavailable I/O
  failure inside run_evidence_write and prove the true nonzero code is preserved,
  no later benchmark work starts, and restoration still runs.

Same owned paths and no live calls. Rerun all affected focused/full/lint/dry-run
checks and hooks with fresh attempt files. Regenerate the clearly fake inspection
evidence in a new attempt directory. Freeze before handoff. No commit/run edits.

## Same-F1 final fixture race correction

Strong read-only diagnosis of coordinator focusedattempt2 identifies the fake uv
readiness marker before sleep30 spawn. A groupTERM in that gap can miss the newly
forked sleep, which retains stdout/stderr pipes after parentcleanup starts.
The fake manage cleanup is only a log append; no productionchange is warranted.
Own tests/unit/test_model_bakeoff.py only for this final correction. Fake uv must
spawn sleep30 in background, capture itsPID, emit a distinct READY marker, then
wait for that child. The test waits for READY before killpg. Retain the2s
communication limit, exit143 and exactlyonecleanup assertions. Do not widen
timeouts, add retries, weaken assertions, or change run_e2e.sh.
Run the isolated test repeatedly as a regression, then focused/full/lint/hooks
with new attemptfiles on the exact finaltree. Preserve the two earlier failures.
Freeze and handoff; samefixround/no review/no livework/no commits or runrecords.
