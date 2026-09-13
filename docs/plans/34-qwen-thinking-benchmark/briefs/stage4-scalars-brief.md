# Stage 4 assignment A2 — Qwen scalar retention

Implementer: codex/gpt-5.6-sol/high, strong tier.
Reviewer: codex/gpt-5.6-sol/high, single Stage4 post-review after all assignments.
Parent contract: stage4-brief.md; stages/04-numeric-fact-preservation.md.

## Scope

`src/neocortex/extraction/agents.py` (Qwen prompt only),
`src/neocortex/extraction/oneshot_librarian.py`,
`tests/test_oneshot_librarian.py`, `tests/test_qwen_extractor.py`.
No edits to A1 probe files, Stage2 evidence code, or Stage5 identity probe.

Implement the scalar portion of stage4-brief.md. Write and run the S05 canned
regression against unchanged product code first, saving its actual failure. Then
keep scalar facts in Qwen descriptions and render incoming scalar properties into
the one-shot prompt. Hosted prompts/builders/profile branches must remain identical.

Make host-default merges aware of incoming/existing scalar properties so stale shared
key values in content are replaced and stored properties update. The S05 assertion
requires April15 absent and May1 present: a "previously April15" clause fails it.
Preserve free-text append behavior without shared scalar conflict. Truncation retains
newest text. Avoid replacing a numeric fragment within an unrelated larger value.

Current call sites are _decision_for and _chain_repeated_targets. The latter rebuilds
later content using previous content/new_fact and must not undo the scalar correction
or lose another entity's previously accepted fact when aliases resolve to one node.
Keep existing repeated-target tests and add a scalar conflict case if that path changes.
Do not weaken existing assertions. Only fix demonstrated behaviors within this contract.

## Gates

- Red S05 evidence before product fix: validation/stage4-s05-red-attempt1.txt.
- Focused scalar/extractor tests, including the rendered text assertion and all three
  canned triplets, plus hosted tests named in parent brief.
- Scoped pre-commit hooks for these four files. Do not run all-files formatting.
- `uv run pytest tests/ -q` and `uv run ruff check .`, once code is frozen.
- Parent brief's exact --test-model baseline, isolated mock cache; save raw JSON under
  validation with a new attempt name. Verify eight compact plus three triplet rows,
  now including the A1 observations. Never contaminate .tmp/plan34/cache with TestModel.
- Read diff against 8766e90 and report hosted branch identity explicitly.

No live model call. No commit or run-record/brief/review edits. Report changed paths,
red/green test evidence, real gate results and any unmeasured criterion. Coordinator
dispatches the bounded live baseline separately after these gates pass.
