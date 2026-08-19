# Stage 6b: Isolation Arms (Conditional)

**Goal**: Attribute a Tier 2 miss in the joint Qwen arm to a specific agent, by running single-agent arms — so Stage 7's per-agent verdict rests on per-agent evidence instead of guesswork.
**Dependencies**: Stage 6 DONE **and** at least one Tier 2 threshold missed. If the joint arm cleared everything, mark this stage SKIPPED.

---

## Why this stage exists

D4 promises that "a partial pass ships" — each agent gated independently, whatever clears migrates.
Stage 7 turns that into a hard requirement: an explicit MIGRATE / HOLD / BLOCKED verdict for each of
ontology, extractor, librarian and domain classifier.

Stage 6 cannot supply the evidence for that. It swaps all four agents at once and measures **one**
graph. Every Tier 2 metric — Plan 15/17 scenario counts, active node/edge type counts, unused edge %,
type reuse ratio, entity dedup rate, episodes consolidated — is a joint product of all four agents
operating in sequence, where the ontology agent's proposals become the extractor's type list, which
becomes the librarian's input. Stage 7 step 2 has an attribution heuristic for Tier 1 type-name
failures; there is no equivalent for Tier 2, and there cannot be one derived from a single joint arm.

Left unaddressed, Stage 7 has exactly two dishonest options: HOLD all four (killing the migration
even when three agents are fine) or invent an attribution nobody measured. This stage buys the real
thing, and only when it is actually needed.

**Why not four isolation arms up front?** Because when the joint arm passes, the configuration that
was measured *is* the configuration that ships — attribution buys nothing. Isolation is only worth
its cost when something missed. That is the same "cheapest disqualifying evidence first" ordering the
rest of the plan follows.

---

## Steps

1. **Scope the stage from Stage 6's misses.**
   - Details: list every Tier 2 metric the joint arm missed, and for each, the agents that could
     plausibly have caused it:
     | Missed metric | Plausibly implicates |
     |---|---|
     | Active/unused/reuse type metrics | ontology (proposes types), extractor (assigns `type_name`) |
     | Entity dedup rate | librarian (`find_similar_nodes` resolution), extractor (entity naming) |
     | Plan 15 / Plan 17 scenario counts | all four — recall depends on the whole graph |
     | Episodes consolidated | extractor, librarian (a dropped payload leaves the episode unconsolidated) |
     | M1–M4 recall metrics | all four |
   - Only run isolation arms for agents that appear in that union. An agent implicated by nothing
     stays on the joint arm's evidence.

2. **Run one arm per implicated agent — that agent local, the other three hosted.**
   - Details: for each implicated agent A:
     ```
     NEOCORTEX_<A>_MODEL=local:qwen3.8-27b            THINKING_EFFORT=<A's Stage 6 effort>
     <the other three>=openai-responses:gpt-5.4-mini  THINKING_EFFORT=<their Stage 6 efforts>
     NEOCORTEX_WORKER_CONCURRENCY=2
     ```
     then `./scripts/model_bakeoff.sh --arm qwen38-27b-only-<agent>`.
     Everything else — corpus, prompts, seed schemas, concurrency, poll timeout — identical to
     Stages 5 and 6. **One variable changed per arm.** That is the whole point.
   - The seed generator has no model setting of its own (`services.py:69-72` and `:154-157` both pass
     `settings.domain_classifier_model`), so it necessarily follows the classifier's arm. Say so in the
     notes rather than pretending it was isolated.
   - Budget each arm like Stage 6: three of four agents are on the fast hosted path, so expect
     something between the baseline's 60–90 min and Stage 6's duration. Keep the ≥ 4 h poll timeout.

3. **Attribute each miss.**
   - Details: for each missed Tier 2 metric, compare the isolation arms against the **baseline** arm.
     An agent is responsible for a miss when its own isolation arm reproduces that miss. If no
     isolation arm reproduces it but the joint arm shows it, the cause is an **interaction** between
     agents — record that explicitly and treat it as blocking for every agent in the union, because a
     partial migration would ship exactly that interaction.
   - Where two isolation arms both reproduce a miss, both agents are responsible. Do not pick a winner.

4. **Record the attribution table.**
   - File: `docs/plans/33-local-qwen-migration/resources/isolation-attribution.md` (new)
   - Details: one row per (missed metric × implicated agent), with the baseline value, the joint-arm
     value, each isolation-arm value, and the resulting attribution. This table is Stage 7 step 3's
     direct input.

5. **Snapshot every arm.**
   - Details: `./scripts/manage.sh snapshot save qwen38-27b-only-<agent>` per arm, and archive each
     `log/agent_actions.log` to `resources/logs-qwen38-27b-only-<agent>.log` — they carry the Tier 1c
     rejection events, which are per-agent evidence in their own right (a rejection rate that spikes
     only in the ontology arm attributes leakage precisely).

---

## Verification

- [ ] Stage 6's missed Tier 2 metrics are enumerated, and the implicated-agent union is justified.
- [ ] One `resources/metrics-qwen38-27b-only-<agent>.json` exists per implicated agent, each recording
      its resolved model strings, effort levels, and `worker_concurrency=2`.
- [ ] Every isolation arm changed exactly **one** model string relative to the baseline arm.
- [ ] `resources/isolation-attribution.md` exists and covers every missed metric.
- [ ] Misses that no isolation arm reproduces are labelled **interaction** rather than silently
      dropped or assigned to an arbitrary agent.
- [ ] Each arm reached `todo+doing == 0` before metrics were computed.
- [ ] Snapshots and archived logs exist for every arm.

**This stage cannot fail the plan.** If an isolation arm is itself blocked (endpoint down, timeout),
mark the attribution for that agent `NOT MEASURED`, and Stage 7 must treat that agent as blocking for
every metric it could have caused — an unmeasured agent is not a passing agent.

---

## Commit

`test(models): record per-agent isolation arms for Tier 2 attribution`
