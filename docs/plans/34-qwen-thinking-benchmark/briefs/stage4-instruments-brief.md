# Stage 4 assignment A1 — pre-measurement instrumentation repairs

Implementer: codex/gpt-5.6-sol, effort high, strong tier.
Reviewer: codex/gpt-5.6-sol, effort high, at the single Stage 4 post-review.
Parent: stage4-brief.md. Authority: goal.md, PROTOCOL.md, backlog items 6–8, 10–11.
This assignment runs while committed Stage 2 is reviewed; the file scopes are disjoint.

## Exclusive write scope

`scripts/qwen_speed_probe.py`, `scripts/fact_retention.py`,
`tests/unit/test_qwen_speed_probe.py`, `tests/unit/test_fact_retention.py`,
new Stage4 instrumentation evidence under validation/.
Do not edit extraction agents, pipeline, one-shot librarian, report/export code,
Stage5 files, or any other test/module. No live calls. No commits or run-record edits.

## Required repairs

1. Backlog6: a librarian cache miss must become a recorded error row, not an exception
   escaping run_text/run_unit/main before output. Catch at the appropriate unit boundary,
   retain incremental output and continue remaining cells. The coordinator has already
   corrected the Stage6 CLI to pin ontology off and extractor L_ext when reading cache.
2. Backlog7: triplet cache identity must incorporate fixture content/revision, so changed
   fixture text cannot silently reuse earlier extraction. Preserve correct reuse when
   only the librarian level changes. No compatibility shim for old cached files.
3. Backlog8: a multi-word fact cannot match across unrelated nodes/fields. Use per-field
   matching or an unmatchable boundary without breaking legitimate normalization.
4. Backlog10: narrow the supersession scorer docstring: exact S05/S07 content checks,
   approximate S11 (real E2E recall ranks content with embeddings).
5. Backlog11: correct probe summary docstring: normalized ontology type names are an
   explicit structural metadata exemption, not arbitrary model text. Trace normalization
   source without modifying the repository implementation.
6. Make `--classify --test-model` exercise the actual classifier path without a live
   request. Keep the four-file scope: in probe test mode only, locally replace the
   classifier module's model factory with TestModel (scoped context manager) and deny
   live model requests. Preserve Qwen model identity/configuration so the intended
   prompt branch is exercised. No change to `src/neocortex/domains/classifier.py`.
   Prove the exact classify mock CLI completes eight compact rows and a real provider
   factory/request cannot be called. Keep live classifier construction unchanged.
7. Record per-unit `critical_defects` from actual observations before live measurement:
   invalid node/edge type names (normalization regex), leaked reasoning markers in
   stored graph text/properties, and model/validation failures or unknown-tool signals
   observable in the existing run outcome/action-log events. Emit code-owned reasons
   only; never copy graph text or exception messages. A missing/unlaunched unit cannot
   acquire an empty measured defect list by default. Use explicit NOT MEASURED/null.
   Scope raw checks to the unit; preserve classifier failures in unit validity rather
   than letting a later successful extraction hide them. For any signal that cannot
   be observed with current interfaces, report the measurement gap instead of claiming
   complete detection. Do not edit product instrumentation outside the four-file scope.
   Apply the follow-up in stage4-instruments-fix-brief.md: use actual public
   normalizers and keep expected timeouts separate from critical failures.

## Checks

Each repair needs a focused test on the concrete failing input from the backlog.
Keep existing assertions; add no skips. Run `uv run pytest tests/unit/test_qwen_speed_probe.py
tests/unit/test_fact_retention.py -q`, plus scoped black/ruff/flake8 and whole-tree ty using
the existing pre-commit hooks. Save outputs as validation/stage4-instruments-<gate>-attempt<n>.txt.
Do not run full suite during Stage2 review; coordinator runs it once after all Stage4
implementation. Report exact changed paths and measurements. This assignment is not
the complete Stage4 implementation and makes no live call.
