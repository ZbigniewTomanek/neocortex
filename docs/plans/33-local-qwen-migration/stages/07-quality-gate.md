# Stage 7: Quality Gate Evaluation

**Goal**: Decide, per agent, whether local Qwen clears the gate — and produce a written verdict with the evidence attached.
**Dependencies**: Stages 5 and 6 DONE, and Stage 6b DONE **or** SKIPPED (SKIPPED only if the joint arm cleared every threshold).

---

## This stage writes no code

It is a judgement stage. Its entire output is a decision document plus the index's Decisions
section. The temptation it must resist is obvious: the plan has by now invested six stages, and
the cheapest way to "succeed" is to soften a threshold. **Don't.** A clean "no" answered with
evidence is the successful outcome of a gate — the plan's stated goal is to *determine* whether
the model is capable, not to arrive at a migration.

---

## Steps

1. **Diff the arms.**
   - Details: produce `resources/bakeoff-comparison.md` — a side-by-side of every Tier 1, Tier 2,
     and Tier 3 metric from `metrics-baseline-gpt54mini.json` (plus `-run2` as the variance column)
     and `metrics-qwen38-27b.json`, with the delta and a PASS/FAIL against the absolute thresholds
     Stage 5 resolved. Add one column per Stage 6b isolation arm where those exist.
   - Where a Qwen delta falls inside the baseline's own two-run spread, mark it **within noise** rather
     than PASS or FAIL, and say so in the verdict. That is what the second baseline run was for.

2. **Apply Tier 1 — hard fail, absolute.**
   - Details: any miss on stored garbage types, the invalid-type **rejection rate**, instance-level
     type candidates above baseline, extraction failure rate > 10%, invalid type names, leaked
     reasoning markers, or a failing `e2e_extraction_pipeline_test.py` **blocks the responsible agent
     from migrating**, no matter what the baseline scored. These encode the Plan 28 ontology crisis.
   - **Read the rejection rate before you read the stored-artifact rows.** After Stage 3 step 6,
     leaked `<think>` / `<tool_call>` shapes in type names are rejected before storage, so "stored
     garbage types = 0" and "leaked markers = 0" are guaranteed and carry no information about Qwen's
     actual leakage. A rejection rate materially above baseline, with rejected names listed in the
     metrics JSON, is the leakage finding — and it means entities were silently dropped at
     `pipeline.py:448`, which no other metric counts. Do not sign off a MIGRATE on the strength of two
     rows that cannot fail.
   - Attribute each failure to an agent where possible. Garbage and instance-level type names come
     from the **ontology** agent (`propose_type`) and the **extractor** (`type_name`); leaked
     markers in node *content* point at the **librarian**; a failure to route points at the
     **classifier**. Where attribution is genuinely ambiguous, say so and treat it as blocking for
     every agent it could plausibly implicate.

3. **Apply Tier 2 — near-parity, relative.**
   - Details: score against the absolute numbers fixed in Stage 5 (which are baseline-derived and
     already widened past the two baseline runs' measured spread — do not re-derive them here).
   - **Attribute every miss using Stage 6b's `isolation-attribution.md`, never by inference.** Tier 2
     metrics are joint outputs of all four agents on one graph; the joint arm alone cannot say which
     agent caused a miss. An agent is implicated by a Tier 2 miss only when its isolation arm
     reproduced that miss. A miss no isolation arm reproduced is an **interaction** and blocks every
     agent in its implicated union. If Stage 6b was SKIPPED, the joint arm passed and there are no
     misses to attribute.
   - Note which metrics are *soft* signals, and treat a Qwen regression on them as far less
     informative than one on dedup rate or scenario pass count:
     - Plan 18.5 measured **M4 temporal evolution at 0/3** and **M5 domain routing at 0/28** on the
       old stack — a weak historical floor.
     - The three **ontology-size** rows (active node types, active edge types, unused edge %) are
       relative-only by design. Plan 29 scored the current stack against Plan 28's absolute ranges and
       recorded 6–32 / 0–22 / 46–100%, attributing the misses to corpus volume and seed-ontology size
       rather than extraction quality — and Stage 4 step 6 mandates provisioning those same seed
       schemas. Score them against the baseline only, and say so when reporting them.

4. **Write a per-agent verdict.**
   - Details: for each of ontology, extractor, librarian, and domain classifier, one of:
     - **MIGRATE** — clears Tier 1 outright, and is not implicated (per step 3's attribution) in any
       Tier 2 miss.
     - **HOLD** — clears Tier 1 but is implicated in a Tier 2 miss. Stays hosted; the specific misses
       become a Backlog entry with the measured numbers, because a targeted prompt or effort change may
       clear it later.
     - **BLOCKED** — misses Tier 1. Stays hosted; Backlog entry records the failure mode with an
       example of the bad output.
   - **When the joint arm cleared everything (Stage 6b SKIPPED), all four are MIGRATE** — the measured
     configuration is the configuration that ships, so there is nothing to attribute and no basis for
     holding an individual agent back.
   - An agent whose isolation arm could not be run is `NOT MEASURED`, which is **HOLD**, not MIGRATE.
     An unmeasured agent is not a passing agent.
   - The seed generator follows the classifier's verdict (it shares `domain_classifier_model`, with no
     setting of its own at `services.py:69-72` and `:154-157`).

5. **Sanity-check a MIGRATE verdict against the qualitative record.**
   - Details: metrics can pass while the graph is visibly worse. Before confirming any MIGRATE,
     read a sample of ~20 nodes and ~20 edges from the Qwen snapshot and compare them against the
     baseline snapshot for the same episodes. Plan 28's crisis produced types like
     `ActivityfunctiondefaultApicreateOrUpdateNodecontent`, and the E2E report before it produced
     Creatine → `ProbabilisticModel` and Serotonin → `DatabaseSystem` — failures that a
     count-based metric can miss entirely. If the sample looks wrong, downgrade the verdict and
     say why.

6. **Record the decision.**
   - File: `docs/plans/33-local-qwen-migration/index.md`
   - Details: add a Decisions entry (D9) stating the verdict for each agent with the deciding
     numbers inline. Add Backlog entries for every HOLD and BLOCKED.

7. **Set the downstream stages' disposition.**
   - Details:
     - **At least one MIGRATE** → Stages 8 and 9 proceed, scoped to the migrating agents only.
     - **No MIGRATE** → mark Stages 8 and 9 **SKIPPED**, and write a short closing summary at the
       top of the index: the question was asked and answered, with the evidence. End the run
       successfully.

---

## Verification

- [ ] `resources/bakeoff-comparison.md` exists with every metric, every arm, delta, and PASS/FAIL.
- [ ] Deltas inside the baseline's two-run spread are marked **within noise**, not PASS/FAIL.
- [ ] Every one of the four agents has an explicit MIGRATE / HOLD / BLOCKED verdict.
- [ ] Every HOLD traces to a named Tier 2 miss that agent's isolation arm reproduced, or to an
      explicitly labelled interaction, or to `NOT MEASURED` — never to inference from the joint arm.
- [ ] Tier 1 sign-off cites the rejection rate, not only the stored-artifact rows.
- [ ] Every HOLD and BLOCKED has a Backlog entry containing the measured numbers and, for BLOCKED,
      an example of the bad output.
- [ ] The qualitative 20-node / 20-edge sample review is recorded for every MIGRATE verdict.
- [ ] Index Decisions contains D9 with the deciding numbers inline.
- [ ] Stage 8 and 9 statuses in the progress tracker reflect the decision.
- [ ] **No threshold in the index was edited during this stage.** `git diff` on the Success
      Criteria tables shows only the Baseline/Qwen result columns changing, never the Target column.

---

## Commit

`docs(plans): record Plan 33 quality gate verdict per agent`
