# Stage 8 brief — decision and handoff

Status: DRAFT. Finalize this brief after Stage7 evidence exists.
Implementer: codex/gpt-5.6-sol, effort high, strong tier.
Reviewer: codex/gpt-5.6-sol, effort high, one post-review.
Authority: stages/08-decision-and-handoff.md, goal.md, PROTOCOL.md.

## Scope

Create resources/decision.md and resources/report.md in this plan.
Update Plan33 backlog item16 and append its journal handoff.
Add measured lessons to docs/plans/LESSONS.md.
Do not change Plan33 state.json.
If an agent receives MIGRATE, update its documented defaults in .env.example,
docs/development.md and this plan's resources/commands.md.
Do not change defaults for HOLD agents or change MCPSettings defaults.
Do not change code, tests, source artifacts, or the evaluation rules.
The coordinator owns this plan's journal, state, backlog, briefs and review records.

## Evidence

Read the actual Stage5 identity, Stage6 sweep, and Stage7 service artifacts.
Read the Plan33 rubric and the Stage7 parsing report.
Do not use a stage status or an agent summary as a measured rubric value.

Create one decision row for each agent: ontology, extractor, librarian and domain classifier.
Include its selected level, five E2E exits, Plan15/17 scores, sample result and skip result.
Each result must cite its source artifact through a relative Markdown link.
State that the service arm measured the combined configuration, not isolated per-agent quality.
MIGRATE requires every specified rubric input to be measured and passing.
Any failed or NOT MEASURED input gives HOLD.
Do not convert an incomplete sample, unresolved temporal survival, or missing attribution to PASS.

If Stage5 proves cancellation, explain the observed failure to distinguish positive effort levels.
Keep the claim limited to this endpoint, model and sample.
Do not infer cancellation from missing usage counts.
If the sweep did not measure an agent, state that its off value is a fallback.
Do not call that value a measured winner.

## Report

Use the simple-english skill at /Users/zbigniewtomanek/.agents/skills/simple-english/SKILL.md.
Read the complete skill before drafting.
Use its strict structural rules because the plan names ASD-STE100.
Full vocabulary compliance requires the official dictionary. Do not claim certified compliance.
Use "configuration" consistently. Use "make sure that" for procedural verification.
Keep descriptive sentences within 25 words and procedural sentences within 20 words.
Keep code, commands, quoted errors, identifiers and artifact paths exact.
Perform the skill's four self-checks before delivery.

Cover scope, measured effort differences, scalar corrections, harness corrections,
per-agent decisions, limitations, and the next action.
Give each number a source. Keep synthetic TestModel results separate from live results.
Name unmeasured criteria and their causes.
Do not imply that the recall formatter was fixed unless its regression failed first.

## Handoff

If Stage7 attribution and sample evidence pass, mark Plan33 item16 RESOLVED with source links.
Otherwise record DEFERRED to Plan34 with the measured reason.
Append the decision path to the Plan33 journal for Stage9.
Add only durable, measured lessons. Link each lesson to this plan.

## Checks

Make sure that every decision link resolves to a repository artifact.
Make sure that each numeric statement matches its cited source.
Make sure that no MIGRATE row contains a failed or NOT MEASURED input.
Make sure that Plan33 state.json and historical artifacts remain unchanged.
Run the full regression suite and lint. Save fresh validation/stage8-* evidence.
Run scoped hooks for changed documents. Do not run all-files formatting.
Report exact changed paths, gate results, self-check results and remaining limitations.
Do not commit or edit run records. Work alone, with no delegation.
