# Journal

Append-only. Newest entries at the bottom. Never rewrite an earlier entry.

One entry per invocation, in this shape:

```
## YYYY-MM-DD HH:MM -- Stage N: [Name] -- DONE
**Did**: [1-3 lines]
**Verification**: GATE lines passed. REPORT values: [metric]=[value]
**Provenance**: [per measured GATE: the input the value was read from, and the defect that would
turn it red] - [or `NOT MEASURED` for any that could not be produced from this run's own inputs]
**Problems**: [symptom -> root cause -> resolution -> inline/subagent] or "none"
**Commit**: `abc1234`
```

---
## 2026-09-11 14:45 -- Pre-review: plan revised before execution

**Did**: Ran `/plan-pre-review` against this plan. Eleven findings confirmed, seven refuted. Fixed the one
P0 in product code and revised the plan for the rest. No stage has started; `state.json` is unchanged.

**Product fix (D-6)**: `build_model_settings` now restates every Qwen thinking level through
`openai_reasoning_effort`. Before this, `low`/`medium`/`high` reached the server as byte-identical requests,
so Stages 5-7 would have measured sampling noise. Verified at the PydanticAI boundary: each level now
resolves to its own name, `off` still resolves to `"none"` with the nothink `extra_body`, and hosted and
local-non-Qwen settings are byte-identical to before. Suite 1,288 passed / 7 skipped; `ruff check .` clean
after excluding the untracked-by-the-type-checker `test_agents/` sample tree, which had 34 pre-existing
errors and made every stage's lint GATE red at baseline.

**Plan revisions**: Stage 2 - gate command named no subcommand and could not run; graph-sample fields
cannot validate against Plan 33's `additionalProperties: false` schema, so a new schema is written instead;
`failure_step` now covers all three banner conventions; `relation_type` is not on the skip events. Stage 3 -
the compound GATE demanded a formatter reproduction that step 4 explicitly allows to fail, which would have
left Stages 7 and 8 unreachable, so it is split into a GATE and a REPORT; `wait_for_jobs` keeps the
children's baseline-scoped PostgreSQL query because `/admin/jobs/summary` cannot express "jobs after this
baseline". Stage 4 - the merge fix now names `render_oneshot_items`, the function that actually builds the
model-facing text, and requires a test that asserts the rendered prompt. Stage 5 - added the positive
control, a deterministic reduction for the non-transitive alias rule, and a cancellation rule. Stage 6 -
per-agent `off` cells (D-8) and a selection rule that ranks triplet passes first. Stage 7 - evidence lines
demoted to REPORT (D-7).

**Verification**: `uv run pytest tests/ -q` 1,288 passed / 7 skipped. `uv run ruff check .` clean.
**Provenance**: the P0 was read from `model_factory.py:104` plus PydanticAI's `prepare_request` and
`_get_reasoning_effort`, executed directly rather than inferred, and corroborated by Plan 33's committed
`probe-results-{low,medium,high,xhigh}.json`. The lint baseline was read from `ruff check .` on a clean
tree at `04e40d1`. The regression baseline 1,283 in the criteria table was stale; the tree measured 1,285
before this change.
**Problems**: none blocking. Whether the server honours `reasoning_effort` is still unmeasured by design.
**Commits**: `10dcbb5` (thinking-level relay), `b47f6ba` (ruff exclude), plus this plan revision.
