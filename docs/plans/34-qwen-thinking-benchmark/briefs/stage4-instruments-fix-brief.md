# Stage 4 A1 gate correction — timeout and type observations

Implementer: codex/gpt-5.6-sol/high. Strong tier, sequential before A2.
Run contract: goal.md and PROTOCOL.md. Report final; no delegation or commits.
Scope only scripts/qwen_speed_probe.py and tests/unit/test_qwen_speed_probe.py.
Preserve all other agents' changes. No live calls or run-record edits.

The bounded diagnosis found two concrete observation defects, before live use:

1. _valid_type_name accepts DishGreg, Functiondefault and FUNCTIONDEFAULT, while
the actual public normalizers reject instance-level/tool-artifact types. Use
normalize_node_type/normalize_edge_type, require exact equality to the stored
name, and treat ValueError as invalid. Keep code-owned reasons and no source text.
Do not duplicate normalization rules. Add the rejecting and valid control cases.
2. An episode timeout produces agent_run_failed(error_type=CancelledError), which
currently yields critical_defects=[agent_run_failure]. A provider APITimeoutError
becomes error:APITimeoutError with model/agent critical defects. Stage6 permits
one timeout, so timeout alone cannot be both a timeout and a critical defect.
Normalize provider APITimeoutError to timeout in extraction and classifier paths.
Exclude timeout-caused CancelledError/TimeoutError/APITimeoutError records from
generic critical failure reasons, but preserve any independent actual validation,
unknown-tool, stored marker or invalid-type defect in the same unit.
Add delayed TestModel and provider-timeout regressions, plus a timeout with an
independent real defect so blanket suppression cannot pass. No production hooks.

Run both focused probe/fact files and scoped hooks with fresh evidence paths
validation/stage4-instruments-gatefix1-*.txt. No full suite here; A2 runs it on
the final Stage4 tree. Report direct before/after values and release write lock.
