# Stage 8: Thinking-Effort Tuning

**Goal**: For each agent that cleared the gate, find the thinking effort that maximises quality — and establish empirically what `high` actually does on this deployment.
**Dependencies**: Stage 7 DONE with at least one MIGRATE verdict.

---

## The question this stage answers

The stated intent is to run local Qwen "with high thinking". Two facts make that worth measuring
rather than assuming:

1. **The stock Qwen3.8 chat template's effort allowlist is `{low, medium, xhigh}`.** Bot
   measurement M1 found that unrecognised values **clamp rather than raise** — 13 of 13 effort
   values produced a correct tool call and none threw. So `high` is *accepted*, but may be an
   alias for a neighbouring level. Reasoning-token counts are the way to tell them apart.
2. **NeoCortex can afford levels the telegram bot could not.** Bot Plan 26 excluded `xhigh` at the
   type level because it measured a **77-second interactive turn**. NeoCortex has no interactive
   path here — extraction runs behind a job queue — and the scoping decision (D3) is that latency
   is measured and never gates. **`xhigh` is therefore genuinely on the table**, and this is the
   single biggest difference between this plan and its precedent.

Counter-pressure worth holding: bot M2 measured 1691 reasoning tokens at `xhigh` versus 81 at
`medium` on the same prompt, and the endpoint's ceiling is `max_running_requests=8` on one shared
GPU. More thinking is not free even when it is not gated, and it is not automatically better —
M2 also recorded `xhigh` at temperature 0.3 selecting only 1 of 2 required tools, *worse* than
`medium`.

---

## Steps

0. **Do not assume the effort/quality curve is monotonic.**
   - Details: the 2026-08-19 probe measured the real `ExtractionResult` schema finishing in 124.8 s
     at `low` and **failing to finish inside 150 s at `medium`**. Bot M2 separately measured `xhigh`
     at temperature 0.3 selecting only 1 of 2 required tools — *worse* than `medium`. More thinking
     is not reliably better. Sweep every level and read the results; never shortcut to "highest
     available". Set per-call timeouts of at least 300 s before sweeping the extractor.

1. **Sweep effort per agent, one agent at a time.**
   - Details: for each MIGRATE agent, run the sweep over `{low, medium, high, xhigh}` while holding
     the other three agents at their Stage 6 settings. Reuse `scripts/probe_local_model.py` from
     Stage 2 (it already accepts `--effort`) for the fast signal, at N ≥ 5 per level.
   - Record per level: pass rate, reasoning tokens, wall-clock, tool calls, and any Tier 1
     violation (a garbage type or a leaked marker at *any* effort level is disqualifying for that level).
   - **Include the Tier 1c invalid-type rejection rate per effort level.** Because Stage 3 step 6 makes
     leaked markers unstorable, a level that leaks heavily shows up as a rejection spike and silently
     dropped entities, not as stored garbage. A level whose rejection rate is materially worse than its
     neighbours is disqualified even when every stored-artifact count reads 0.

2. **Settle the `high` question explicitly.**
   - Details: compare reasoning-token distributions across `low` / `medium` / `high` / `xhigh` on an
     identical prompt. If `high` is statistically indistinguishable from a neighbour, it is an alias
     — record which one, and configure the real value rather than the alias so the setting means
     what it says. Write the finding into the index Decisions.

3. **Confirm the winners on the full corpus.**
   - Details: a probe sweep is a fast proxy, not the gate. Once per-agent winners are chosen, run
     **one** full arm (`./scripts/model_bakeoff.sh --arm qwen38-27b-tuned`) with all winners applied
     together and confirm it still clears every Tier 1 threshold and does not regress Tier 2 versus
     the Stage 6 Qwen arm. Effort levels interact through the graph — the ontology agent's proposals
     become the extractor's type list, which becomes the librarian's input — so per-agent winners
     chosen in isolation are a hypothesis until measured together.

4. **Choose on quality, report the cost.**
   - Details: pick the highest-quality level per agent. Where two levels are within noise, prefer
     the cheaper one — that is a tie-break, not a trade-off, and D3 forbids treating latency as a
     constraint. Record p50/p95 per-episode wall-clock and total tokens for the chosen configuration
     in Tier 3 so the operational cost of the migration is on the record.

5. **Guard against the `none`-level artifact.**
   - Details: bot Plan 26 D19 found `reasoning_effort=none` leaking a raw `</think>` marker into
     visible content on a full production prompt, while `low` and `medium` did not. `none` is not in
     this sweep, but if any agent's winner turns out to be a very low level, run the Tier 1 leak scan
     specifically against that configuration before accepting it.

6. **Write the chosen configuration into the index.**
   - Details: a table of agent → model → effort → the deciding measurement. This is what Stage 9
     turns into code defaults.

---

## Verification

- [ ] Sweep results for every MIGRATE agent across all four effort levels exist in
      `resources/effort-sweep.json`, with reasoning-token counts.
- [ ] The `high`-vs-`xhigh` aliasing question is answered explicitly in the index Decisions, with
      the token distributions that decided it.
- [ ] `resources/metrics-qwen38-27b-tuned.json` exists; the combined configuration clears every
      Tier 1 threshold and does not regress Tier 2 against the Stage 6 arm.
- [ ] No effort level was chosen that produced a Tier 1 violation at any point in the sweep.
- [ ] Tier 3 latency and token cost for the chosen configuration recorded in the index.
- [ ] `./scripts/manage.sh snapshot save qwen38-27b-tuned` completed.

---

## Commit

`perf(models): tune per-agent thinking effort for local Qwen`
