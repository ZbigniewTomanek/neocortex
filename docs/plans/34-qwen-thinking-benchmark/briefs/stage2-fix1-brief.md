# Stage 2 fix round 1 of 1

Implementer: codex/gpt-5.6-sol/high, strong tier. No re-review.
Read goal.md, PROTOCOL.md, stage2-brief.md and validation/stage2-review.md.

Fix confirmed F1 only. Scope: scripts/e2e_manifest.py and
tests/unit/test_e2e_manifest.py. The preceding `--- Cross-Session Isolation Check ---`
followed by `=== Stage 3: STM Boost Validation ===` must report Stage3/stage.
Preserve Plan15/17 scenario-over-PHASE precedence. Child-aware parsing or equivalent
precise banner ordering is acceptable. Preserve other existing diagnostic assertions;
if test call signatures need context, add context without weakening expectations.

Test real write_exit_result flow with the episodic script identity and the reproduced
stdout, plus existing four banner cases, exception privacy and legacy evidence.
Run focused e2e_manifest and qwen_parsing_report tests, scoped pre-commit hooks,
and full `uv run pytest tests/ -q` once. Keep outputs in new attempt files under
validation/stage2-fix1-*.txt. No live calls. No commits or edits to run records,
briefs, review files, or other stage code. Report changed paths, exact gate values
and evidence that F1's wrong attribution is fixed. Stop after this bounded set.
