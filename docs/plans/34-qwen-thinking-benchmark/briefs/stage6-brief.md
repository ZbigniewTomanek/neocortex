# Stage 6 brief — bounded per-agent sweep

Status: FROZEN; finalized against actual Stage4/5 artifacts, 2026-09-13.
Implementer: codex/gpt-5.6-sol/high, strong tier.
Reviewer: codex/gpt-5.6-sol/high, single post-review.
Authority: stages/06-per-agent-effort-sweep.md, decisions D-8/D-10, goal.md.

## Preconditions and scope

Stage4 resources/sweep/off.json:11 units,42/56 compact facts,1/3 supersession,
no observed critical defects/timeouts;396.67s versus350s limit, D-17 correction
now implemented. Reuse this actual quality evidence without a baseline rerun.
Stage5 resources/effort-levels.json: finalized12 actual rows/418.004s; off gate
and request-boundary gates pass. Low3/3, medium1/3, high0/3 valid samples.
Cancellation is null, NOT true; distinct_levels retains off/low/medium/high due
missing positive comparisons. Run the declared cells once; do not repeat identity.

Read resources/sweep/off.json and resources/effort-levels.json directly. Do not
infer completed measurements from state notes. Stage4 baseline is reusable only
as the extractor off cell; other agents need their own pinned-upstream off cells.
No live command until its exact configuration has passed TestModel.

Scope: an executable evidence/selection runner under validation/, its unit tests,
resources/effort-sweep.json, resources/effort-sweep.md, resources/sweep/*.json.
Probe instrumentation may change only when a declared measurement is impossible
through its existing fields; report the exact gap before editing. No product code.
No run-record, brief, review or historical evidence edits; no commits.

## Selection and evidence contract

Implement the stage's ascending agent sequence and pinned configurations exactly.
The librarian cache uses thinking=off, ontology=off, extractor=L_ext; changing
librarian effort does not change cache identity. Keep TestModel and live caches
separate. Copy actual raw files, never synthesize measured episode rows.

Derive every cell statistic from its raw file. Both corpus has 11 summary units
(8 compact plus 3 triplets), representing 14 source-text runs. Compact has eight.
The episodes count in a cell means raw summary row count, not number of calls.
Count timeouts by distinct source-text labels in raw stage rows, not once per
agent row; do not undercount two timeouts in the same triplet. Missing rows or
missing defect observations are NOT MEASURED, not clean zeros.
Missing/null stage status also makes timeout evidence NOT MEASURED. Validate
the exact local model against finalized identity for baseline and new cells;
another non-TestModel model is not equivalent. Refuse hosted-model launch.

Disqualify critical defects and more than one timeout. Rank eligible levels by
triplet passes, then compact facts_found, then choose the lowest effort within
two facts of the best score in the highest triplet tier. Preserve arithmetic in
the JSON and Markdown. Ontology compact-only cells have triplet tier not applicable,
not an invented three-pass score; compare their measured compact fact scores.
Classifier selection requires 8/8 valid results and chooses the lowest eligible
level; report domain agreement from actual returned domain sets, not their counts.
Never credit extraction success for a classifier failure.

Cells expose the stage's specified fields and raw paths relative to the plan.
Use null for unavailable numeric quantities. Each selected level must either
have clean measured raw evidence or be explicitly NOT MEASURED fallback off,
which is never represented as a passing selection gate.

If the measured Stage5 cancellation rule fired, write explicit unmeasured cells
with reason endpoint_ignores_effort, select off for all agents, and make zero
Stage6 live requests. Do not remeasure the endpoint identity.

## Execution bounds

Prepare the complete cell plan and TestModel run before any live launch. Use
env -u GOOGLE_API_KEY -u GEMINI_API_KEY for in-memory probes, explicitly pin
http://127.0.0.1:24000/v1, and retain LITELLM_API_KEY only in the environment.
Per-call maximum 300 seconds; stage budget 14,400 seconds total, no extension.
Launch through managed asynchronous command sessions under .tmp/plan34/ (D-16),
not shell-background nohup. Persist incremental raw and aggregate JSON,
poll no more often than every five minutes. Stop launching at the budget and
record all unlaunched cells as NOT MEASURED. A rerun requires a coordinator-recorded
root-caused code change; a timeout does not authorize a retry.

## Checks

## Preparation A — instrument gap, before runner or live work

Bounded scope: scripts/qwen_speed_probe.py and tests/unit/test_qwen_speed_probe.py.
No product code or live calls. This preparation is independent of selected levels.
Current equal counts cannot distinguish technical_knowledge from work_context.
Add sorted unique domain_keys to classifier raw stage rows via _classify/run_text:
known:<allowlisted seed slug>, proposed:sha256:<hex> of NFKC, whitespace-collapsed,
trimmed, casefolded proposal name. Do not serialize unknown model-provided slugs,
names, descriptions, reasoning or hash preimages. Hashes are pseudonymous, not
anonymous; limit their interpretation to within-run equality.
Valid empty set is []; timeout/error/unknown matched slug/unusable name is null.
Unknown/unusable keys cannot count as valid agreement evidence.
Test differing known sets with equal counts; canonicalization; empty versus absent;
unknown/empty refusal; serialization privacy; provider-timeout tuple propagation.

Aggregate exact accepted node/edge counts from ontology_agent_complete and each
ontology_proposal_rejected by kind/reason_code (before stage lookup: no stage field).
Fields are nullable; zero rejections only when completion establishes observation.
Test accepted/rejected events and timeout before completion. These are host-validator
proposal counts, not malformed outputs, budget truncations or persistence outcomes.
Collector reset per text permits attribution only in this sequential probe.
Run focused probe tests, full suite/ruff, and fresh TestModel both+classify with
all thinking off, per-call300, episode600, max-wall1200, isolated mock cache.
Save validation/stage6-instruments-<check>-attempt<n> evidence; no commits or run edits.

## Preparation B — hard deadline correction (D-17)

After PreparationA checkpoint, same probe/test scope, sequential sole writer.
Compute one monotonic deadline; cap run_unit with remaining time via wait_for.
On expiry persist launched unit TIMEOUT reason wall_budget_during_unit, null
unobserved scoring/defect values, exhaustedtrue; remaining units NOT MEASURED.
Retain actual partial stage evidence where already observed, never invent zeros.
No later text/stage/provider request may start after expiry; cancellation must
propagate through the pipeline. Persist partial JSON immediately and stop.
Use short deterministic tests to prove cancellation despite longer episode/call
timeouts; no second triplet text/later request; all planned summary units present;
valid incremental JSON; exhaustedtrue and chain NOT MEASURED; small elapsed tolerance.
The future runner caps each cell to remaining global14,400s and refuses launches
after expiry, with a managed-process termination backstop. No Stage4 rerun.

## Runner checks

Runner path: validation/effort_sweep_runner.py (committed executable evidence,
not raw stdout); tests/unit/test_effort_sweep_runner.py. Import by path in tests.
Accept --test-model, --output-dir, --identity-json, --baseline-json,
--cache-dir and --max-wall-seconds (at most14400). Refuse accidental overwrite
of existing live raw cells. Reuse completed extractor off only, never relaunch it.
Build the same level/configuration plan for TestModel; mock cells finish in seconds.
Read selected upstream levels from just-completed raw evidence before next agent.
Unknown or no eligible measured level yields explicitly unmeasured fallbackoff.
Run subprocesses without shell, environment-only credentials, no hosted keys.
Managed parent execution survives command-tool yields per D-16. Capture child
stdout privately under .tmp/plan34, not in public result JSON. Persist aggregate
after each cell; after budget exhaustion represent every remaining planned cell.
No recursive retries or remeasurement. Use a process-level timeout for each child
bounded by the remaining stage deadline; terminate only the child it created.
If termination leaves a partial raw artifact, retain it and classify incomplete
evidence honestly. Never pad raw measurements or score absent rows as zero.

Mock invocation uses identity validation/stage5-fix1-testmodel-coordinator-attempt1.json
and baseline validation/stage4-fix1-testmodel-coordinator-attempt1.json, isolated
.tmp/plan34/stage6-mock cache/output. Live uses resources/effort-levels.json and
resources/sweep/off.json only after coordinator reads final identity. Mock identity
has null usage and retains all four levels; do not invent an endpoint conclusion.
For cell p50/p95 and median reasoning use the target agent's actual stage rows;
score fact/triplet quality from summaries. Keep total cell wall as a separate field.
Classifier cells pin all selected upstream levels explicitly, with --thinking off.
Librarian uses --cache-thinking off and exact selected extractor/ontologyoff pins.
Prepare every mock cell including a distinct librarianoff/ontologyoff/classifieroff.
Do not change frozen identity/baseline artifacts, including to add new fields.
If isolated mock caches lack the baselineoff extraction entries, prepare a fresh
TestModel all-off baseline in that same isolated mock cache/output before testing
the runner and pass its new JSON as --baseline-json. This is offline setup only,
not permission to rerun the live baseline or silently populate a missing live cache.

Test actual selection arithmetic: higher triplet tier beats any facts count;
two-fact band selects lowest level; a critical defect or two timeouts excludes;
unmeasured cannot win as measured; classifier needs all eight; raw row mismatch
fails provenance; cached librarian uses pinned extractor cache. Test cancellation
makes no live launch. Save raw attempts under validation/stage6-*.
Run focused tests, full regression and lint, scoped hooks. Verify final resources
by reopening every raw_path and recomputing statistics, not by inspecting exit codes.
Report all measurement gaps and exact total live wall time.

## Single review fix — F1

Read validation/stage6-review.md complete finding set and triage. This is the
only review fix round; no re-review. Scope scripts/qwen_speed_probe.py,
tests/unit/test_qwen_speed_probe.py, tests/unit/test_effort_sweep_runner.py;
runner only if directly necessary for F1. No other source or raw evidence edits.
Incomplete ordinary timeout/error rows without agent_usage must carry null usage
counts, just like hard-wall cancellation; do not convert established zero usage
to unknown. Preserve already observed counts and completed-stage measurements.
Extend reachable episode/provider timeout tests, error-without-usage and observed
zero/nonzero regressions. Feed the timeout result through analyse_raw to prove
one allowed timeout cannot publish a reasoning median based on invented zero.
Run focused probe+runner tests, full pytest tests/ -q, ruff check ., scoped hooks.
Run the exact full16-cell TestModel sweep in fresh validation/stage6-fix1-mock-
attempt1 and isolated mock cache, preparing its baseline if needed. Save each
check separately as validation/stage6-fix1-<check>-attempt<n>.txt. No live calls.
Report full diff, observed per-finding proof and any remaining unavailable values.
