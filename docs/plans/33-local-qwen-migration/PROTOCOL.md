# Execution protocol

Rendered by `init_run.sh` on 2026-09-11 for the run `33-local-qwen-migration`. Preset `unattended`: review placement `review-each-stage-before-and-after`, review budget `two-fix-rounds-max`, stop policy `never-stop`.

This file is the contract for this run. Do not edit it. A change of settings is a new render and a journal entry that says why. `goal.md` holds what this run must achieve. This file holds how.

## Roles

| Role | Tier | Assigned | How it runs |
|---|---|---|---|
| Orchestrator | coordinator | `codex/gpt-6-astra` | this session |
| Implementer | strong | `codex/gpt-5.6-sol` | effort `high`, started by the orchestrator's harness |
| Reviewer | strong | `codex/gpt-5.6-sol` | effort `high`, started by the orchestrator's harness |
| Helper | light | `codex/gpt-5.6-luna` | effort `medium`, started by the orchestrator's harness |
| Owner | | the person who started the run | chat |

**Orchestrator.** The strongest model in the run, and the only one that judges. Reads the plan. Writes the brief for one stage at a time. Dispatches every subagent itself. Runs the gates. Reads the full diff the way a maintainer reads a contributor's pull request. Triages every finding as fix, dismiss, or ship, with one line of reason in the journal, after trying to refute it against the code. Commits. Writes the run record. Writes no feature code, with one exception: a small change it is sure of, applied and journaled with its line count. Does not trace a defect through the code itself when a diagnosis assignment can.

**Implementer.** The only writer for its stage. Receives the brief as a file path. Implements it, writes the tests, runs the checks the brief names, and reports changed paths, check output, raw observations, and what it could not measure. Works alone: spawns no subagents and delegates nothing. A stage too large for one agent goes back to the orchestrator, who splits it into sequential assignments. Commits nothing. Never edits the run record.

**Reviewer.** Read-only. Sees the plan, the brief, the diff, the full files it needs, and the evidence under `validation/`. Never sees the implementer's transcript. Spawns no subagents. Reports in the finding contract of the `code-review` skill: decide whether it is a defect, then grade it, and name the failing input. A finding is advice from a model weaker than the orchestrator. The orchestrator's triage line is the verdict.

**Helper.** One scoped assignment at a time: a fully specified edit, a rename or move, a named command whose output it saves, an inventory, a post-mortem of a transcript or an earlier run. Stops and reports when the assignment turns out to need a decision. Spawns no subagents. Commits nothing. Never edits the run record.

**Owner.** Decides product and preference calls. Grants the allowed actions listed in `goal.md`.
Is not asked anything between the settings message and the final report.

## Models

The tier decides the model and the effort. The role table above holds the run defaults; the brief header and the stage record in `state.json` hold what a stage actually ran on.

- A stage runs on the strong tier unless its brief is a complete specification with nothing left to decide, in which case the orchestrator may assign it to the helper and writes the reason in the brief header. In doubt, strong.
- Every review, every fix round, and every diagnosis runs on the strong tier at effort `high`, or `xhigh` when the orchestrator marks it hard in the brief header.
- No subagent runs on the coordinator tier. The orchestrator never runs a subagent on its own model.
- A light agent that reports it is out of its depth gets the same assignment rerun on the strong tier. Nothing escalates to the orchestrator's model.
- The hierarchy is flat. The orchestrator dispatches every subagent; no subagent spawns another. The agent definitions and command flags enforce it where the harness allows, and every prompt says it regardless.

## The stage loop

Every stage runs these steps in order. A skipped step is a journal line with its reason. The `step` field in `state.json` records where a stage is.

1. **Brief.** Read the stage file and the code it touches. Write the brief to `briefs/stage<n>-brief.md`: the header with the implementer and reviewer as `agent/model, effort` and the tier reason, then data shapes, files, signatures, tests with their cases, the exact gate commands as verified at baseline, the evidence paths per check and attempt, and the non-goals. Set the stage `IN_PROGRESS` and `step: BRIEFED`.
2. **Pre-review.** Send the brief, the stage file, and the code paths it names to the reviewer with the `plan-pre-review` skill. When it returns, write the complete finding set to `validation/stage<n>-pre-review.md`, numbered F1, F2, and so on, and set `preReview.used: true`. Only then triage. Each finding is a fix (edit the brief; a stage-file edit is one docs commit), a dismiss with a reason, or an accept. Append the triage as a `## Triage` section to the same file. Set the brief `status: FROZEN` and `step: PRE_REVIEWED`.
4. **Implement.** Set `step: WRITING`, `writer`, and the stage's `implementer` to the agent, model, and effort that run. Start the implementer with the brief path. It commits nothing.
5. **Gates.** Run the gates from `goal.md` yourself and read the full diff. A red gate whose cause is plain from the output goes back to the implementer as a complete assignment; one whose cause is not plain goes first to a strong read-only diagnosis whose report you turn into the assignment. Each such cycle increments the stage's `gateFixes`. This is implementation, not a review fix round. Do not send a diff you know fails to the reviewer.
6. **Commit.** Stage files by explicit path with the stage's commit message. One commit for the implementation. Files another session changed are never staged. Never `--no-verify`; a hook that fails on files this stage did not stage means the tree is contended, so stop the other writer or commit from an isolated worktree. Record the hash in `state.json`.
7. **Post-review.** Set `step: FROZEN`, `writesFrozen: true`, and the stage's `reviewer`. Send the commit, the plan, and the brief to the reviewer with the `plan-post-review` skill. When it returns, write the complete finding set to `validation/stage<n>-review.md`, numbered F1, F2, and so on, set `review.used: true` and `step: REVIEWED`, and only then triage. Refute each `BLOCKING` finding against the code before accepting it. Append the triage as a `## Triage` section to the same file.
8. **Fix rounds.** Per the review budget below. A fix is a complete assignment: the blocking ids, the paths, the checks to rerun. One commit per fix round, appended to the stage's `commit` list.
9. **Live proof.** If the stage names a check on a real system, run it and paste the observed value into the journal. A value that could not be read is written `NOT MEASURED` and blocks the stage. A check that runs more than once gets one evidence file per attempt.
10. **Record.** Append the journal entry. Update the stage's `gates`, `evidence`, `note`, `commit`, `implementer`, and `reviewer` in `state.json`. Set the stage `DONE` and `step: null`. A stage whose measurement shows nothing needs to change is `DONE` with `commit: null` and the measurement as evidence, journaled as a no-op. Advance `currentStage`.


## Review budget

Ship is the default. After triage, if no finding is above P2 or the rest is style with diminishing return, ship.

- **Fix round 1.** The complete blocking set in one assignment. The implementer reruns every affected check. Inspect the diff against every finding, including the ones with no deterministic check. Set `repair.rounds: 1`.
- **Re-review, once.** The reviewer reads only the changed lines of the fix, with the finding set as context. Append its findings to `validation/stage<n>-review.md` under a `## Re-review` heading and set `repairReview.used: true`.
- **Fix round 2** only if the re-review found a blocking item. No review follows it. Set `repair.rounds: 2` and `repair.used: true`. Accept on deterministic evidence inspected against every finding, or block the stage.

Two failed rounds block the stage. There is never a third round or a second re-review, not after a resume, not after a session change.

## Gates

A stage passes when every gate holds. Any one failing blocks the next stage.

| Gate | Evidence |
|---|---|
| Plan gates | Every gate `goal.md` names for the stage, with the command and its observed output under `validation/` |
| Review | Every review this protocol names has returned, its finding set is on disk, and every finding has a triage line |
| Live | When the stage names a check on a real system, the observed value is in the journal. `NOT MEASURED` blocks |
| Scope | The diff touches only files the brief names, or the journal says why |
| Docs | A stage that makes a durable doc stale updates it in the same commit |

A gate is green only on the real artifact. Run the feature, read the value, open the diff. A passing command, a green log line, an exit code, or an agent saying "done" is not evidence on its own. Judge the implementer's work by its diff and its check output, never by its report. When a check can be a script, write the script, run it, and keep its output under `validation/`.

Three rules about the checks themselves. Unmeasurable is not failed: a check that returns no signal says something about the instrument, and its gate is `NOT MEASURED` until someone reads the value. A check that cannot fail is not a check: if a gate would pass on an empty result, fix the gate before trusting it. Never write rows or values to satisfy a declared count; a count is evidence only when each item behind it is real.

## Stops

There are no owner gates. A blocked stage is marked `BLOCKED` with its condition in the journal, and the run continues with every stage that does not depend on it.

Actions listed under allowed actions in `goal.md` proceed without asking. An action the plan did not foresee proceeds if it is reversible, with a journal line. Five actions stop the stage instead, whatever the plan says:

1. deleting or overwriting data outside the allowed actions;
2. pushing to a shared branch, or force-pushing anywhere;
3. deploying, releasing, or tagging;
4. sending anything to a person or an external service;
5. spending money.

Nothing else stops the run.

## Rules that do not bend

- The orchestrator does not write feature code beyond the small-change exception, journaled.
- No subagent spawns a subagent. No subagent runs on the coordinator tier.
- One stage writes at a time. The next stage's implementer may start during a review of a committed stage only when the two briefs' file lists do not intersect, journaled.
- Never `git add .`. Never `--no-verify`. Never a tag. Never a push that the owner did not grant.
- No backwards compatibility unless `goal.md` asks for it. A finding that asks for a shim, an optional field for old callers, or a grandfathered path is dismissed with that reason.
- A spent ledger flag never comes back. Not on resume, not in a new session, not on another harness.
- Every deviation from this file is a journal line, not a silence.
