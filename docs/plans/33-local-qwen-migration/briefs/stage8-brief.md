---
stage: 8
implementer: no-op; orchestrator records the measured control decision
reviewer: codex/gpt-5.6-sol, effort high
tier: no implementation
tier-reason: Stage 7 has no MIGRATE verdict, so D20 requires a DONE no-op
sources: stages/08-thinking-effort-tuning.md; resources/bakeoff-comparison.md; state.json
collected: 2026-09-11
status: FROZEN
---

# Stage 8 brief: required no-op

## Decision

Read the accepted Stage 7 verdict table. If every reasoning agent has verdict `HOLD`, record Stage 8 as `DONE` with no implementation commit.

Do not run an effort sweep. Do not call a local model. Do not create tuned metrics. Do not select an effort value.

## Evidence

Create `validation/stage8-no-op.json` as a run record with these values:

- `status`: `PASS`
- `outcome`: `DONE_NO_OP`
- `stage7_verdicts`: the exact four agents, each with `HOLD`
- `migrate_count`: `0`
- `effort_sweep`: `NOT_RUN`
- `combined_tuned_arm`: `NOT_RUN`
- `reason`: Stage 7 has no validated migration path

## Gates

1. The Stage 7 comparison has exactly the four required agents, once each, with `HOLD`.
2. The Stage 7 privacy and verdict completeness gate is `PASS` in `state.json`.
3. No `resources/effort-sweep.json` or `resources/metrics-qwen-flash-next-compact-tuned.json` is created by this stage.
4. No Qwen call, effort sweep, or benchmark runs.

Run this one bounded command from the repository root. It exits nonzero before it writes the Stage 8 record if any source condition is false.

```bash
set -euo pipefail
stage8_check=$(mktemp /tmp/neocortex-stage8-XXXXXX.json)
uv run python scripts/generate_qwen_parsing_report.py privacy-scan \
  --input-manifest docs/plans/33-local-qwen-migration/resources/qwen-parsing-inputs.json \
  --report docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.json \
  --markdown docs/plans/33-local-qwen-migration/resources/qwen-parsing-report.md \
  --sample docs/plans/33-local-qwen-migration/resources/quality-sample-qwen-flash-next.json \
  --comparison docs/plans/33-local-qwen-migration/resources/bakeoff-comparison.md \
  --output "$stage8_check"
jq -e '.comparison_agent_rows == 4 and .comparison_unique_agents == 4 and .comparison_hold_rows == 4 and .comparison_duplicate_agents == 0 and .comparison_unknown_agent_rows == 0 and .comparison_missing_agents == 0 and .comparison_outside_verdict_rows == 0' "$stage8_check" >/dev/null
jq -e '.stages[] | select(.id == 7) | .status == "DONE" and .gates.privacy == "PASS" and .gates.verdict_completeness == "PASS"' docs/plans/33-local-qwen-migration/state.json >/dev/null
test ! -e docs/plans/33-local-qwen-migration/resources/effort-sweep.json
test ! -e docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact-tuned.json
jq -n '{status:"PASS",outcome:"DONE_NO_OP",stage7_verdicts:[{agent:"Ontology",verdict:"HOLD"},{agent:"Extractor",verdict:"HOLD"},{agent:"Librarian",verdict:"HOLD"},{agent:"Domain classifier",verdict:"HOLD"}],migrate_count:0,effort_sweep:"NOT_RUN",combined_tuned_arm:"NOT_RUN",reason:"Stage 7 has no validated migration path"}' > docs/plans/33-local-qwen-migration/validation/stage8-no-op.json
```

## Files

- `briefs/stage8-brief.md`
- `validation/stage8-pre-review.md`
- `validation/stage8-no-op.json`
- `state.json`
- `journal.md`

## Non-goals

- Do not tune `low`, `medium`, `high`, or `xhigh`.
- Do not change model defaults or configuration.
- Do not reinterpret a `HOLD` verdict as a migration candidate.
