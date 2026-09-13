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
Stage6 is now finalized: resources/effort-sweep.json and every resources/sweep/
raw file were reopened by validation/verify_live_sweep.py. Runnerwall3896.741s,
15new cells plus reused baseline, all4selectedoff. Do not rerun any cell.
Classifier domainagreementoff:low6/8, off:medium5/8, low:medium7/8 is setagreement,
not correctness. High0/8valid; its extractedfacts43/56 do not credit classification.
Librarianoff/low/medium reasoningmedians are observed0 in these cached-input cells,
not proof that positive levels are ignored for every agent or request shape.
Positiveontologycells contain rawfailedruns but aggregateproposalcounts unknown.
Do not describe them as unattempted cells. Ontologyoff was the only eligiblelevel.
Read the Plan33 rubric and the Stage7 parsing report.
Do not use a stage status or an agent summary as a measured rubric value.
Rubric authority: this plan's index.md Success Criteria and decisions.md D-3/D-7,
plus ../33-local-qwen-migration/stages/07-quality-gate.md. Stage7's sample follows
this plan's privacy-safe schema, not the incompatible historical sample schema.
Use all five child exits0, Plan15>=11/14 PASS, Plan17>=13/14 ACCEPTABLE and0FAIL,
20actual nodes/20actual edges with required validity booleans, skip consistency
and temporal survival, terminal stability and critical integrity as required inputs.

Create one decision row for each agent: ontology, extractor, librarian and domain classifier.
Include its selected level, five E2E exits, Plan15/17 scores, sample result and skip result.
Each result must cite its source artifact through a relative Markdown link.
State that the service arm measured the combined configuration, not isolated per-agent quality.
MIGRATE requires every specified rubric input to be measured and passing.
Any failed or NOT MEASURED input gives HOLD.
Do not convert an incomplete sample, unresolved temporal survival, or missing attribution to PASS.
A sweep cell's PASS means eligible measured evidence, not a migration verdict.
Keep that distinction explicit when a PASS cell has low fact or correction scores.

If Stage5 proves cancellation, explain the observed failure to distinguish positive effort levels.
Keep the claim limited to this endpoint, model and sample.
Do not infer cancellation from missing usage counts.
Stage5 retained all four levels because positive pairwise comparisons were
incomplete. That is not proof that all four levels are mutually distinct.
Its high-level rows expose ModelHTTPError only, not HTTP status/body or root cause.
Historical Plan33 reasoning medians came from classifier-only rows on a different
corpus. Do not present them as a controlled before/after extractor comparison.
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
Record the Stage4 operational overrun beside its measured quality:396.67s versus
configured350s. D-17 corrected later deadlines; the historical run did not pass
its budget. Keep its42/56facts and1/3supersession as observed results, not universal
success of scalar correction. Stage6 F1 preserves unknown timeout/error usage as
null; missing usage is not evidence that a request consumed zero reasoning tokens.
Proposal observations cover host validators in the sequential probe; they do
not establish complete coverage of malformed output or pre-hook rejected calls.

## Handoff

If Stage7 attribution and sample evidence pass, mark Plan33 item16 RESOLVED with source links.
Otherwise record DEFERRED to Plan34 with the measured reason.
Append the decision path to the Plan33 journal for Stage9.
Add only durable, measured lessons. Link each lesson to this plan.
Read this plan's entire append-only backlog, including later dispositions.
Items6/7/8/10/11 are resolved by Stage4 despite the historical table's OPEN text.
Report remaining items1/2/3/4/5/9/12/13/14 with their recorded next trigger/owner.
Do not imply that item5 currently reproduces or that item12 requires a Stage1 rerun.
Any new confirmed non-blocking review finding must also appear with its owner.

## Checks

Make sure that every decision link resolves to a repository artifact.
Make sure that each numeric statement matches its cited source.
Make sure that no MIGRATE row contains a failed or NOT MEASURED input.
Make sure that Plan33 state.json and historical artifacts remain unchanged.
Run the full regression suite and lint. Save fresh validation/stage8-* evidence.
Run scoped hooks for changed documents. Do not run all-files formatting.
Report exact changed paths, gate results, self-check results and remaining limitations.
Do not commit or edit run records. Work alone, with no delegation.
