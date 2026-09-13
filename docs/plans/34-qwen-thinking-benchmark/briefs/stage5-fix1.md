# Stage5 single fix round

Implementer codex/gpt-5.6-sol/high, strong. One source writer, no delegation.
Read goal.md, PROTOCOL.md, stage5-brief.md and validation/stage5-review.md.
Fix F1/F2 only in scripts/effort_level_probe.py and its unit test file.
No live calls, commits, run-record/brief/review edits. Preserve other source edits.

F1: a final wall-limited request must mark budget_exhausted when that limit fires.
Finalization must not claim remaining budget when actual elapsed reaches limit.
Add deterministic fake-clock/final-timeout regression, no long sleep.

F2: present token counts alone cannot yield OK/exit0 on invalid output, markertrue
or output_tokens<=0. Persist a non-OK code-owned reason, no text leakage. Require
full declared live gates at exit: every valid usable row, expected resolved effort,
and off reasoning0 with thinking disabled. Missing required evidence fails closed.
Keep TestModel allowance for missing synthetic reasoning usage, not for invalid
output, zero output, markers, timeout or wrong boundary.
Test actual run_probe return code and persisted rows with mocked responses for
marker, zero output, invalid output, off nonzero reasoning and successful valid rows.
Existing alias/cancellation analysis remains conservative and unchanged.

Run focused tests, full suite, ruff, scoped hooks, exact 12-row TestModel CLI from
stage5 brief. Save new validation/stage5-fix1-<check>-attempt<n> evidence each time.
Report direct evidence for F1/F2, actual final JSON fields, diff and limitations.
This is one fix round with no re-review; do not broaden into a new audit.
