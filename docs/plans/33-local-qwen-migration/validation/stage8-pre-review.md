# Stage 8 pre-review

Reviewer: `codex/gpt-5.6-sol`, effort `high`

Verdict: needs revision. One P2 blocking finding was confirmed. One candidate was refuted.

## F1 — P2 BLOCKING — no-op evidence was not bound to its sources

The draft prescribed literal `PASS` and `DONE_NO_OP` values without an exact command that derived them from the accepted comparison and `state.json`. A changed or duplicated verdict could leave the prescribed JSON unchanged. This blocked the executable Stage 8 measurement gate.

Required fix: add a bounded fail-fast command that validates the exact four-agent `HOLD` result, the Stage 7 state gates, and tuned-artifact absence before it writes `stage8-no-op.json`.

## Gate dispositions

- Exact four Stage 7 agents with `HOLD`: PASS on the current artifact, but the draft lacked an executable Stage 8 check.
- Stage 7 privacy and verdict gates: PASS.
- Tuned artifacts absent: PASS at baseline.
- No Qwen call, sweep, or benchmark: PASS in the prescribed path.

## Refuted candidate

- The D20 branch is incorrect: refuted because all four accepted verdicts are `HOLD`. D20 requires `DONE`, no commit, and no tuning.

## Triage

- F1: FIX. The frozen brief now uses the Stage 7 structural parser, fail-fast state and absence checks, and a final evidence write.
