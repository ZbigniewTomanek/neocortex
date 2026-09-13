# Stage4 fix round 1 of 1

Implementer: codex/gpt-5.6-sol/high, strong tier. Work alone, no delegation.
Run: docs/plans/34-qwen-thinking-benchmark. Report final. No re-review.
Read goal.md, PROTOCOL.md, stage4-scalars-brief.md and validation/stage4-review.md.

## Scope

Only src/neocortex/extraction/oneshot_librarian.py and
tests/test_oneshot_librarian.py. Preserve Stage3's paused uncommitted files and
Stage5 new files. No commits, run records, brief or review edits. No live calls.

## Required findings

F1: host conflict detection must not use the eight-key/256-character model-display
projection. Inspect all supported scalar keys and exact values, without truncation.
Keep bounded scalar projection for model-facing rendering. Preserve metadata filtering.
Regression: a..h existing scalar keys plus z_deadline=April15, incoming May1.
The old deadline must leave current content even though its key sorts ninth.

F2: do not globally replace a value across unrelated property facts. Regression1:
`Retry threshold 15; team size 15.`, old retry_threshold=15/team_size=15, incoming
retry_threshold=16/team_size=15. Keep team size15 and correct retry threshold16.
Regression2: `Retries 15, timeout 15.`, incoming retries16/timeout17. Correct each
property's own value without retaining its stale value. Preserve other facts.

Use property/content context for repeated values. Handle genuinely ambiguous
unlabeled repeated values conservatively rather than inventing fact attribution.
State the resulting fallback explicitly in your report. Do not drop all existing
content as a shortcut. Do not add another model request or a general text parser.
F2 fallback verification also covers one unlabeled text occurrence owned by two
properties: `The recorded value is 15.`, old retries15/timeout15, incoming16/17.
Do not assign that occurrence to retries merely because its key sorts first.
An unlabeled fallback needs unique old-value property ownership, not just a single
remaining textual occurrence. Preserve ambiguous old text and append incoming text.
Owner identity uses casefolded string values, as scalar token matching does:
integer15 and string"15" cannot be distinguished in old text. Full property labels
must distinguish retry_threshold from error_threshold; a generic "threshold"
suffix cannot authorize replacing retry15 when only error_threshold changes.
Keep label/value association direct rather than crossing arbitrary intervening facts.
Keep the existing unambiguous S05, numeric boundaries, simultaneous15->16/16->17,
newest-text truncation and repeated-target tests. Incoming descriptions stay intact.
Keep the direct rendered-property assertion and hosted paths unchanged.

## Checks

Run new regressions, the full scalar/extractor/probe/fact focused set, named hosted
tests from the parent brief, scoped hooks, full pytest and ruff. Save new raw files
under validation/stage4-fix1-*-attempt<n>.txt. Run the exact TestModel baseline again
with a new isolated mock cache and distinct JSON path (do not overwrite prior JSON).
Use env -u GOOGLE_API_KEY -u GEMINI_API_KEY. Read the actual 11-unit output.
Report direct corrected values for F1/F2, full regression counts, unchanged hosted
behavior, any unmeasured limitation, and release the write lock. No further review.
