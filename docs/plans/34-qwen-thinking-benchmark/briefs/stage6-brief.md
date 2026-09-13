# Stage 6 brief — bounded per-agent sweep

Status: DRAFT; finalize against actual Stage4/5 artifacts before dispatch.
Implementer: codex/gpt-5.6-sol/high, strong tier.
Reviewer: codex/gpt-5.6-sol/high, single post-review.
Authority: stages/06-per-agent-effort-sweep.md, decisions D-8/D-10, goal.md.

## Preconditions and scope

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

Test actual selection arithmetic: higher triplet tier beats any facts count;
two-fact band selects lowest level; a critical defect or two timeouts excludes;
unmeasured cannot win as measured; classifier needs all eight; raw row mismatch
fails provenance; cached librarian uses pinned extractor cache. Test cancellation
makes no live launch. Save raw attempts under validation/stage6-*.
Run focused tests, full regression and lint, scoped hooks. Verify final resources
by reopening every raw_path and recomputing statistics, not by inspecting exit codes.
Report all measurement gaps and exact total live wall time.
